#include <cstdint>
#include <libdragon.h>
#include <t3d/t3d.h>

#include "renderer/chunkMesh.h"

namespace
{
  constexpr std::uint8_t BUFFER_COUNT = 3;
  constexpr std::uint16_t CHUNK_COUNT = 4;

  void setVertex(
    T3DVertPacked *vertices,
    std::uint16_t index,
    std::int16_t x,
    std::int16_t y,
    std::int16_t z,
    std::uint32_t color,
    std::uint16_t normal
  )
  {
    auto *position = t3d_vertbuffer_get_pos(vertices, index);
    position[0] = x;
    position[1] = y;
    position[2] = z;
    *t3d_vertbuffer_get_color(vertices, index) = color;
    *t3d_vertbuffer_get_norm(vertices, index) = normal;
    auto *uv = t3d_vertbuffer_get_uv(vertices, index);
    uv[0] = 0;
    uv[1] = 0;
  }
}

int main()
{
  debug_init_isviewer();
  debug_init_usblog();
  display_init(RESOLUTION_320x240, DEPTH_16_BPP, BUFFER_COUNT, GAMMA_NONE, FILTERS_RESAMPLE_ANTIALIAS);
  rdpq_init();
  t3d_init({});

  T3DViewport viewport = t3d_viewport_create_buffered(BUFFER_COUNT);
  auto *matrices = static_cast<T3DMat4FP*>(malloc_uncached(sizeof(T3DMat4FP) * BUFFER_COUNT));
  for(std::uint8_t index = 0; index < BUFFER_COUNT; ++index)t3d_mat4fp_identity(&matrices[index]);

  P64::Renderer::ChunkMesh mesh{};
  P64::Renderer::ChunkMesh::Config config{};
  config.chunkCount = CHUNK_COUNT;
  config.batchesPerChunk = 1;
  config.verticesPerBatch = 4;
  config.trianglesPerBatch = 2;
  config.bufferCount = BUFFER_COUNT;
  assert(mesh.init(config));
  constexpr std::uint8_t topology[]{0, 2, 1, 0, 3, 2};
  assert(mesh.setTopology(topology, sizeof(topology)));

  const T3DVec3 up{{0.0f, 1.0f, 0.0f}};
  const std::uint16_t normal = t3d_vert_pack_normal(&up);
  for(std::uint16_t chunk = 0; chunk < CHUNK_COUNT; ++chunk) {
    const std::int16_t x0 = static_cast<std::int16_t>(-36 + chunk * 24);
    const std::int16_t x1 = static_cast<std::int16_t>(x0 + 20);
    auto *vertices = mesh.editBatch(chunk, 0);
    const std::uint32_t color = 0x228844FFU + (static_cast<std::uint32_t>(chunk) << 24U);
    setVertex(vertices, 0, x0, 0, -10, color, normal);
    setVertex(vertices, 1, x1, 0, -10, color, normal);
    setVertex(vertices, 2, x1, 0,  10, color, normal);
    setVertex(vertices, 3, x0, 0,  10, color, normal);
    mesh.markDirty(chunk);
    mesh.setBounds(
      chunk,
      T3DVec3{{static_cast<float>(x0), -1.0f, -10.0f}},
      T3DVec3{{static_cast<float>(x1),  1.0f,  10.0f}}
    );
  }
  // Exercise the explicit visibility culling path alongside frustum culling.
  mesh.setVisible(CHUNK_COUNT - 1, false);

  const T3DVec3 cameraPosition{{0.0f, 70.0f, 75.0f}};
  const T3DVec3 cameraTarget{{0.0f, 0.0f, 0.0f}};
  const T3DVec3 cameraUp{{0.0f, 1.0f, 0.0f}};
  std::uint32_t frame = 0;
  for(;;) {
    const std::uint8_t buffer = static_cast<std::uint8_t>(frame % BUFFER_COUNT);
    if(frame != 0 && frame % 30U == 0) {
      const std::uint16_t chunk = static_cast<std::uint16_t>((frame / 30U) % (CHUNK_COUNT - 1));
      mesh.setVertexColor(chunk, 0, 0, 0xE8B030FFU);
    }
    mesh.beginFrame(buffer);

    t3d_viewport_set_projection(&viewport, T3D_DEG_TO_RAD(65.0f), 5.0f, 300.0f);
    t3d_viewport_look_at(&viewport, &cameraPosition, &cameraTarget, &cameraUp);
    rdpq_attach(display_get(), display_get_zbuf());
    t3d_frame_start();
    t3d_viewport_attach(&viewport);
    t3d_screen_clear_color(RGBA32(20, 28, 36, 0xFF));
    t3d_screen_clear_depth();
    rdpq_mode_combiner(RDPQ_COMBINER_SHADE);
    rdpq_mode_blender(0);
    t3d_state_set_drawflags(static_cast<T3DDrawFlags>(T3D_FLAG_SHADED | T3D_FLAG_DEPTH | T3D_FLAG_NO_LIGHT));
    t3d_matrix_set(&matrices[buffer], true);
    const auto draw = mesh.draw(&viewport.viewFrustum);
    rdpq_detach_show();

    if(frame == 90U) {
      const auto metrics = mesh.metrics();
      debugf(
        "BF64_CHUNK_MESH_JSON:{\"allocated_bytes\":%u,\"capacity_triangles\":%u,"
        "\"submitted_triangles\":%u,\"visible_chunks\":%u,\"culled_chunks\":%u,"
        "\"copied_chunks\":%u,\"draw_batches\":%u}\n",
        static_cast<unsigned>(metrics.allocatedBytes),
        static_cast<unsigned>(metrics.capacityTriangles),
        static_cast<unsigned>(draw.submittedTriangles),
        static_cast<unsigned>(draw.visibleChunks),
        static_cast<unsigned>(draw.culledChunks),
        static_cast<unsigned>(metrics.copiedChunks),
        static_cast<unsigned>(draw.drawBatches)
      );
    }
    ++frame;
  }
}
