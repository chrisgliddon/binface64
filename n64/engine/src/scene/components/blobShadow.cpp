/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "scene/components/blobShadow.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <libdragon.h>

#include "debug/profiler.h"
#include "renderer/drawLayer.h"
#include "scene/object.h"

namespace
{
  struct InitData
  {
    float radius{};
    float yOffset{};
    std::uint32_t color{};
    std::uint8_t layer{};
    std::uint8_t padding[3]{};
  };

  void setVertex(T3DVertPacked *vertices, std::uint8_t index, std::int16_t x, std::int16_t z, std::uint32_t color)
  {
    auto &packed = vertices[index / 2];
    const T3DVec3 up{{0.0f, 1.0f, 0.0f}};
    const auto normal = t3d_vert_pack_normal(&up);
    if((index & 1u) == 0) {
      packed.posA[0] = x; packed.posA[1] = 0; packed.posA[2] = z;
      packed.normA = normal; packed.rgbaA = color; packed.stA[0] = packed.stA[1] = 0;
    } else {
      packed.posB[0] = x; packed.posB[1] = 0; packed.posB[2] = z;
      packed.normB = normal; packed.rgbaB = color; packed.stB[0] = packed.stB[1] = 0;
    }
  }
}

void P64::Comp::BlobShadow::initDelete(Object&, BlobShadow *data, void *initData_)
{
  if(initData_ == nullptr) {
    if(data->vertices)free_uncached(data->vertices);
    data->~BlobShadow();
    return;
  }
  new(data) BlobShadow();
  const auto &init = *static_cast<InitData*>(initData_);
  data->radius = std::max(1.0f, init.radius);
  data->yOffset = init.yOffset;
  data->color = init.color;
  data->layer = init.layer;
  data->vertices = static_cast<T3DVertPacked*>(malloc_uncached(sizeof(T3DVertPacked) * 5));
  assert(data->vertices);
  for(std::uint8_t index=0; index<5; ++index)data->vertices[index] = {};
  setVertex(data->vertices, 0, 0, 0, data->color);
  constexpr float PI = 3.14159265358979323846f;
  for(std::uint8_t segment=0; segment<SEGMENTS; ++segment) {
    const float angle = static_cast<float>(segment) * (2.0f * PI / SEGMENTS);
    setVertex(
      data->vertices,
      static_cast<std::uint8_t>(segment + 1),
      static_cast<std::int16_t>(std::lround(std::cos(angle) * 256.0f)),
      static_cast<std::int16_t>(std::lround(std::sin(angle) * 256.0f)),
      data->color
    );
  }
}

void P64::Comp::BlobShadow::draw(Object &object, BlobShadow *data, [[maybe_unused]] float deltaTime)
{
  if(!data->vertices)return;
  if(data->layer)DrawLayer::use3D(data->layer);
  rdpq_sync_pipe();
  rdpq_mode_combiner(RDPQ_COMBINER_SHADE);
  t3d_state_set_drawflags(static_cast<T3DDrawFlags>(T3D_FLAG_SHADED | T3D_FLAG_DEPTH | T3D_FLAG_NO_LIGHT));
  auto *matrix = data->matrix.getNext();
  const fm_vec3_t scale{
    object.scale.x * data->radius / 256.0f,
    1.0f,
    object.scale.z * data->radius / 256.0f
  };
  const fm_quat_t rotation{0.0f, 0.0f, 0.0f, 1.0f};
  const fm_vec3_t position{object.pos.x, object.pos.y + data->yOffset, object.pos.z};
  t3d_mat4fp_from_srt(matrix, scale, rotation, position);
  t3d_matrix_set(matrix, true);
  t3d_vert_load(data->vertices, 0, 9);
  for(std::uint8_t segment=0; segment<SEGMENTS; ++segment) {
    t3d_tri_draw(0, segment + 1, static_cast<std::uint8_t>((segment + 1) % SEGMENTS + 1));
  }
  t3d_tri_sync();
  Profiler::recordProcedural(SEGMENTS, 1, 1);
  if(data->layer)DrawLayer::useDefault();
}
