/**
 * @copyright 2026 - BF64 contributors
 * @license MIT
 *
 * Fixed-capacity, independently dirty procedural mesh chunks for tiny3d.
 */
#pragma once

#include <cstddef>
#include <cstdint>
#include <t3d/t3d.h>

namespace P64::Renderer
{
  class ChunkMesh
  {
  public:
    static constexpr std::uint16_t MAX_VERTICES_PER_BATCH = 70;

    struct Config
    {
      std::uint16_t chunkCount{};
      std::uint16_t batchesPerChunk{1};
      /** tiny3d accepts at most 70 vertices in one cache load. */
      std::uint16_t verticesPerBatch{};
      std::uint16_t trianglesPerBatch{};
      /** Match the number of render buffers that can be in flight. */
      std::uint8_t bufferCount{3};
    };

    struct Metrics
    {
      std::uint32_t allocatedBytes{};
      std::uint32_t capacityTriangles{};
      std::uint32_t copiedChunks{};
      std::uint32_t visibleChunks{};
      std::uint32_t culledChunks{};
      std::uint32_t drawBatches{};
      std::uint32_t submittedTriangles{};
    };

    ChunkMesh() = default;
    ~ChunkMesh();
    ChunkMesh(const ChunkMesh&) = delete;
    ChunkMesh& operator=(const ChunkMesh&) = delete;

    /** Allocate canonical geometry plus one uncached copy per render buffer. */
    bool init(const Config &config);
    void close();
    [[nodiscard]] bool initialized() const { return initialized_; }
    [[nodiscard]] const Config &config() const { return config_; }

    /**
     * Set the triangle list shared by every batch. Indices are local to a
     * batch, and count must equal trianglesPerBatch * 3.
     */
    bool setTopology(const std::uint8_t *indices, std::size_t count);

    /** Edit canonical packed vertices; call markDirty after direct edits. */
    [[nodiscard]] T3DVertPacked *editBatch(std::uint16_t chunk, std::uint16_t batch);
    /** Inspect the current render-buffer copy. */
    [[nodiscard]] const T3DVertPacked *frameBatch(std::uint16_t chunk, std::uint16_t batch) const;
    void markDirty(std::uint16_t chunk);
    bool setVertexColor(
      std::uint16_t chunk,
      std::uint16_t batch,
      std::uint16_t vertex,
      std::uint32_t rgba
    );

    /** Bounds are compared with a world-space frustum when one is supplied. */
    bool setBounds(std::uint16_t chunk, const T3DVec3 &minimum, const T3DVec3 &maximum);
    bool setVisible(std::uint16_t chunk, bool visible);

    /** Copy only dirty chunks into the selected render buffer. */
    void beginFrame(std::uint8_t bufferIndex);
    /** Draw visible batches; caller owns material, matrix, and draw-state setup. */
    Metrics draw(const T3DFrustum *frustum = nullptr);
    [[nodiscard]] const Metrics &metrics() const { return metrics_; }

  private:
    [[nodiscard]] std::size_t packedPerBatch() const;
    [[nodiscard]] std::size_t packedPerChunk() const;
    [[nodiscard]] std::size_t batchOffset(std::uint16_t chunk, std::uint16_t batch) const;

    Config config_{};
    Metrics metrics_{};
    T3DVertPacked *canonical_{};
    T3DVertPacked *frameVertices_{};
    std::uint8_t *topology_{};
    T3DVec3 *boundsMinimum_{};
    T3DVec3 *boundsMaximum_{};
    std::uint32_t *dirtyWords_{};
    std::uint8_t *boundsValid_{};
    std::uint8_t *visible_{};
    std::size_t dirtyWordCount_{};
    std::uint8_t currentBuffer_{};
    bool topologyReady_{};
    bool initialized_{};
  };
}
