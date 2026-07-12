/**
 * @copyright 2026 - BF64 contributors
 * @license MIT
 */
#include "renderer/chunkMesh.h"

#include <cstdlib>
#include <cstring>
#include <limits>
#include <libdragon.h>

namespace
{
  bool multiplyFits(std::size_t lhs, std::size_t rhs, std::size_t &result)
  {
    if(lhs != 0 && rhs > std::numeric_limits<std::size_t>::max() / lhs)return false;
    result = lhs * rhs;
    return true;
  }
}

namespace P64::Renderer
{
  ChunkMesh::~ChunkMesh()
  {
    close();
  }

  std::size_t ChunkMesh::packedPerBatch() const
  {
    return (static_cast<std::size_t>(config_.verticesPerBatch) + 1U) / 2U;
  }

  std::size_t ChunkMesh::packedPerChunk() const
  {
    return packedPerBatch() * config_.batchesPerChunk;
  }

  std::size_t ChunkMesh::batchOffset(std::uint16_t chunk, std::uint16_t batch) const
  {
    return static_cast<std::size_t>(chunk) * packedPerChunk() +
      static_cast<std::size_t>(batch) * packedPerBatch();
  }

  bool ChunkMesh::init(const Config &value)
  {
    close();
    if(
      value.chunkCount == 0 ||
      value.batchesPerChunk == 0 ||
      value.verticesPerBatch == 0 ||
      value.verticesPerBatch > MAX_VERTICES_PER_BATCH ||
      value.trianglesPerBatch == 0 ||
      value.bufferCount == 0
    )return false;

    config_ = value;
    std::size_t packedCount = 0;
    std::size_t framePackedCount = 0;
    std::size_t topologyBytes = 0;
    if(
      !multiplyFits(packedPerChunk(), config_.chunkCount, packedCount) ||
      !multiplyFits(packedCount, config_.bufferCount, framePackedCount) ||
      !multiplyFits(config_.trianglesPerBatch, 3U, topologyBytes)
    ) {
      close();
      return false;
    }

    dirtyWordCount_ = (static_cast<std::size_t>(config_.chunkCount) + 31U) / 32U;
    const std::size_t canonicalBytes = packedCount * sizeof(T3DVertPacked);
    const std::size_t frameBytes = framePackedCount * sizeof(T3DVertPacked);
    const std::size_t boundsBytes = static_cast<std::size_t>(config_.chunkCount) * sizeof(T3DVec3);
    const std::size_t flagsBytes = config_.chunkCount;
    const std::size_t dirtyBytes = dirtyWordCount_ * config_.bufferCount * sizeof(std::uint32_t);

    canonical_ = static_cast<T3DVertPacked*>(std::calloc(packedCount, sizeof(T3DVertPacked)));
    frameVertices_ = static_cast<T3DVertPacked*>(malloc_uncached(frameBytes));
    topology_ = static_cast<std::uint8_t*>(std::malloc(topologyBytes));
    boundsMinimum_ = static_cast<T3DVec3*>(std::calloc(config_.chunkCount, sizeof(T3DVec3)));
    boundsMaximum_ = static_cast<T3DVec3*>(std::calloc(config_.chunkCount, sizeof(T3DVec3)));
    boundsValid_ = static_cast<std::uint8_t*>(std::calloc(config_.chunkCount, 1));
    visible_ = static_cast<std::uint8_t*>(std::malloc(flagsBytes));
    dirtyWords_ = static_cast<std::uint32_t*>(std::calloc(dirtyWordCount_ * config_.bufferCount, sizeof(std::uint32_t)));
    if(
      canonical_ == nullptr || frameVertices_ == nullptr || topology_ == nullptr ||
      boundsMinimum_ == nullptr || boundsMaximum_ == nullptr || boundsValid_ == nullptr ||
      visible_ == nullptr || dirtyWords_ == nullptr
    ) {
      close();
      return false;
    }

    for(std::size_t index = 0; index < framePackedCount; ++index)frameVertices_[index] = {};
    std::memset(visible_, 1, flagsBytes);
    initialized_ = true;
    metrics_.allocatedBytes = static_cast<std::uint32_t>(
      canonicalBytes + frameBytes + topologyBytes + boundsBytes * 2U +
      flagsBytes * 2U + dirtyBytes
    );
    metrics_.capacityTriangles = static_cast<std::uint32_t>(config_.chunkCount) *
      config_.batchesPerChunk * config_.trianglesPerBatch;
    for(std::uint16_t chunk = 0; chunk < config_.chunkCount; ++chunk)markDirty(chunk);
    return true;
  }

  void ChunkMesh::close()
  {
    std::free(canonical_);
    if(frameVertices_ != nullptr)free_uncached(frameVertices_);
    std::free(topology_);
    std::free(boundsMinimum_);
    std::free(boundsMaximum_);
    std::free(dirtyWords_);
    std::free(boundsValid_);
    std::free(visible_);
    config_ = {};
    metrics_ = {};
    canonical_ = nullptr;
    frameVertices_ = nullptr;
    topology_ = nullptr;
    boundsMinimum_ = nullptr;
    boundsMaximum_ = nullptr;
    dirtyWords_ = nullptr;
    boundsValid_ = nullptr;
    visible_ = nullptr;
    dirtyWordCount_ = 0;
    currentBuffer_ = 0;
    topologyReady_ = false;
    initialized_ = false;
  }

  bool ChunkMesh::setTopology(const std::uint8_t *indices, std::size_t count)
  {
    const std::size_t expected = static_cast<std::size_t>(config_.trianglesPerBatch) * 3U;
    if(!initialized_ || indices == nullptr || count != expected)return false;
    for(std::size_t index = 0; index < count; ++index) {
      if(indices[index] >= config_.verticesPerBatch)return false;
    }
    std::memcpy(topology_, indices, count);
    topologyReady_ = true;
    return true;
  }

  T3DVertPacked *ChunkMesh::editBatch(std::uint16_t chunk, std::uint16_t batch)
  {
    if(!initialized_ || chunk >= config_.chunkCount || batch >= config_.batchesPerChunk)return nullptr;
    return canonical_ + batchOffset(chunk, batch);
  }

  const T3DVertPacked *ChunkMesh::frameBatch(std::uint16_t chunk, std::uint16_t batch) const
  {
    if(!initialized_ || chunk >= config_.chunkCount || batch >= config_.batchesPerChunk)return nullptr;
    const std::size_t frameOffset = static_cast<std::size_t>(currentBuffer_) *
      config_.chunkCount * packedPerChunk();
    return frameVertices_ + frameOffset + batchOffset(chunk, batch);
  }

  void ChunkMesh::markDirty(std::uint16_t chunk)
  {
    if(!initialized_ || chunk >= config_.chunkCount)return;
    const std::size_t word = chunk / 32U;
    const std::uint32_t bit = 1U << (chunk % 32U);
    for(std::uint8_t buffer = 0; buffer < config_.bufferCount; ++buffer) {
      dirtyWords_[static_cast<std::size_t>(buffer) * dirtyWordCount_ + word] |= bit;
    }
  }

  bool ChunkMesh::setVertexColor(
    std::uint16_t chunk,
    std::uint16_t batch,
    std::uint16_t vertex,
    std::uint32_t rgba
  )
  {
    auto *vertices = editBatch(chunk, batch);
    if(vertices == nullptr || vertex >= config_.verticesPerBatch)return false;
    *t3d_vertbuffer_get_color(vertices, vertex) = rgba;
    markDirty(chunk);
    return true;
  }

  bool ChunkMesh::setBounds(
    std::uint16_t chunk,
    const T3DVec3 &minimum,
    const T3DVec3 &maximum
  )
  {
    if(!initialized_ || chunk >= config_.chunkCount)return false;
    boundsMinimum_[chunk] = minimum;
    boundsMaximum_[chunk] = maximum;
    boundsValid_[chunk] = 1;
    return true;
  }

  bool ChunkMesh::setVisible(std::uint16_t chunk, bool value)
  {
    if(!initialized_ || chunk >= config_.chunkCount)return false;
    visible_[chunk] = value ? 1 : 0;
    return true;
  }

  void ChunkMesh::beginFrame(std::uint8_t bufferIndex)
  {
    if(!initialized_)return;
    currentBuffer_ = bufferIndex % config_.bufferCount;
    metrics_.copiedChunks = 0;
    const std::size_t chunkBytes = packedPerChunk() * sizeof(T3DVertPacked);
    const std::size_t frameOffset = static_cast<std::size_t>(currentBuffer_) *
      config_.chunkCount * packedPerChunk();
    auto *dirty = dirtyWords_ + static_cast<std::size_t>(currentBuffer_) * dirtyWordCount_;
    for(std::uint16_t chunk = 0; chunk < config_.chunkCount; ++chunk) {
      const std::size_t word = chunk / 32U;
      const std::uint32_t bit = 1U << (chunk % 32U);
      if((dirty[word] & bit) == 0)continue;
      std::memcpy(
        frameVertices_ + frameOffset + static_cast<std::size_t>(chunk) * packedPerChunk(),
        canonical_ + static_cast<std::size_t>(chunk) * packedPerChunk(),
        chunkBytes
      );
      dirty[word] &= ~bit;
      ++metrics_.copiedChunks;
    }
  }

  ChunkMesh::Metrics ChunkMesh::draw(const T3DFrustum *frustum)
  {
    metrics_.visibleChunks = 0;
    metrics_.culledChunks = 0;
    metrics_.drawBatches = 0;
    metrics_.submittedTriangles = 0;
    if(!initialized_ || !topologyReady_)return metrics_;

    for(std::uint16_t chunk = 0; chunk < config_.chunkCount; ++chunk) {
      const bool inFrustum = frustum == nullptr || boundsValid_[chunk] == 0 ||
        t3d_frustum_vs_aabb(frustum, &boundsMinimum_[chunk], &boundsMaximum_[chunk]);
      if(visible_[chunk] == 0 || !inFrustum) {
        ++metrics_.culledChunks;
        continue;
      }
      ++metrics_.visibleChunks;
      for(std::uint16_t batch = 0; batch < config_.batchesPerChunk; ++batch) {
        t3d_vert_load(frameBatch(chunk, batch), 0, config_.verticesPerBatch);
        for(std::uint16_t triangle = 0; triangle < config_.trianglesPerBatch; ++triangle) {
          const auto *indices = topology_ + static_cast<std::size_t>(triangle) * 3U;
          t3d_tri_draw(indices[0], indices[1], indices[2]);
        }
        t3d_tri_sync();
        ++metrics_.drawBatches;
        metrics_.submittedTriangles += config_.trianglesPerBatch;
      }
    }
    return metrics_;
  }
}
