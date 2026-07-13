import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeChunkMeshTests(unittest.TestCase):
    def test_dirty_updates_copy_only_the_changed_chunk_and_draw_culls_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "t3d").mkdir()
            (root / "libdragon.h").write_text(
                "#pragma once\n"
                "#include <cstdlib>\n"
                "inline void *malloc_uncached(std::size_t size) { return std::malloc(size); }\n"
                "inline void free_uncached(void *value) { std::free(value); }\n",
                encoding="utf-8",
            )
            (root / "t3d" / "t3d.h").write_text(
                r'''#pragma once
#include <cstdint>
#include <libdragon.h>

struct T3DVec3 { float v[3]{}; };
struct T3DFrustum {};
struct T3DVertPacked {
  std::int16_t posA[3]{}; std::uint16_t normA{};
  std::int16_t posB[3]{}; std::uint16_t normB{};
  std::uint32_t rgbaA{}, rgbaB{};
  std::int16_t stA[2]{}, stB[2]{};
};

extern "C" bool t3d_frustum_vs_aabb(const T3DFrustum*, const T3DVec3*, const T3DVec3*);
extern "C" void t3d_vert_load(const T3DVertPacked*, std::uint32_t, std::uint32_t);
extern "C" void t3d_tri_draw(std::uint32_t, std::uint32_t, std::uint32_t);
extern "C" void t3d_tri_sync();

inline std::uint32_t *t3d_vertbuffer_get_color(T3DVertPacked vertices[], int index) {
  return (index & 1) ? &vertices[index / 2].rgbaB : &vertices[index / 2].rgbaA;
}
''',
                encoding="utf-8",
            )
            harness = root / "chunk_mesh_test.cpp"
            harness.write_text(
                r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include "renderer/chunkMesh.h"

namespace {
std::array<const T3DVertPacked*, 8> loaded{};
std::uint32_t loadCount{};
std::uint32_t triangleCount{};
std::uint32_t profiledTriangles{};
std::uint32_t profiledBatches{};
}

namespace P64::Profiler {
void recordChunk(std::uint32_t triangles, std::uint32_t batches) {
  profiledTriangles += triangles;
  profiledBatches += batches;
}
}

extern "C" bool t3d_frustum_vs_aabb(
    const T3DFrustum*, const T3DVec3 *minimum, const T3DVec3*) {
  return minimum->v[0] >= 0.0f;
}
extern "C" void t3d_vert_load(
    const T3DVertPacked *vertices, std::uint32_t offset, std::uint32_t count) {
  assert(offset == 0 && count == 4);
  loaded[loadCount++] = vertices;
}
extern "C" void t3d_tri_draw(std::uint32_t, std::uint32_t, std::uint32_t) {
  ++triangleCount;
}
extern "C" void t3d_tri_sync() {}

int main() {
  using P64::Renderer::ChunkMesh;
  ChunkMesh mesh;
  ChunkMesh::Config config{};
  config.chunkCount = 3;
  config.batchesPerChunk = 1;
  config.verticesPerBatch = 4;
  config.trianglesPerBatch = 2;
  config.bufferCount = 3;
  assert(mesh.init(config));

  constexpr std::uint8_t topology[]{0, 2, 1, 0, 3, 2};
  assert(mesh.setTopology(topology, sizeof(topology)));
  for(std::uint16_t chunk = 0; chunk < 3; ++chunk) {
    auto *vertices = mesh.editBatch(chunk, 0);
    assert(vertices != nullptr);
    *t3d_vertbuffer_get_color(vertices, 0) = 0x101010FFU + chunk;
    mesh.markDirty(chunk);
  }
  mesh.setBounds(0, T3DVec3{{-2.0f, 0.0f, 0.0f}}, T3DVec3{{-1.0f, 1.0f, 1.0f}});
  mesh.setBounds(1, T3DVec3{{1.0f, 0.0f, 0.0f}}, T3DVec3{{2.0f, 1.0f, 1.0f}});
  mesh.setBounds(2, T3DVec3{{3.0f, 0.0f, 0.0f}}, T3DVec3{{4.0f, 1.0f, 1.0f}});

  mesh.beginFrame(0);
  assert(mesh.metrics().copiedChunks == 3);
  const auto *chunk0Before = mesh.frameBatch(0, 0);
  const auto *chunk2Before = mesh.frameBatch(2, 0);
  const std::uint32_t chunk0Color = *t3d_vertbuffer_get_color(
      const_cast<T3DVertPacked*>(chunk0Before), 0);
  const std::uint32_t chunk2Color = *t3d_vertbuffer_get_color(
      const_cast<T3DVertPacked*>(chunk2Before), 0);

  assert(mesh.setVertexColor(1, 0, 0, 0xAABBCCFFU));
  mesh.beginFrame(0);
  assert(mesh.metrics().copiedChunks == 1);
  assert(*t3d_vertbuffer_get_color(const_cast<T3DVertPacked*>(mesh.frameBatch(0, 0)), 0) == chunk0Color);
  assert(*t3d_vertbuffer_get_color(const_cast<T3DVertPacked*>(mesh.frameBatch(2, 0)), 0) == chunk2Color);
  assert(*t3d_vertbuffer_get_color(const_cast<T3DVertPacked*>(mesh.frameBatch(1, 0)), 0) == 0xAABBCCFFU);

  T3DFrustum frustum{};
  const auto draw = mesh.draw(&frustum);
  assert(draw.visibleChunks == 2 && draw.culledChunks == 1);
  assert(draw.submittedTriangles == 4 && draw.drawBatches == 2);
  assert(loadCount == 2 && triangleCount == 4);
  assert(profiledTriangles == 4 && profiledBatches == 2);
  assert(mesh.metrics().allocatedBytes > sizeof(T3DVertPacked) * 3);
  mesh.close();
  assert(!mesh.initialized());
  return 0;
}
''',
                encoding="utf-8",
            )
            binary = root / "chunk_mesh_test"
            compile_proc = subprocess.run(
                [
                    "g++",
                    "-std=c++20",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(root),
                    "-I",
                    str(ROOT / "n64" / "engine" / "include"),
                    str(ROOT / "n64" / "engine" / "src" / "renderer" / "chunkMesh.cpp"),
                    str(harness),
                    "-o",
                    str(binary),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compile_proc.returncode, 0, compile_proc.stdout + compile_proc.stderr)
            run_proc = subprocess.run(
                [str(binary)], cwd=ROOT, text=True, capture_output=True, check=False
            )

        self.assertEqual(run_proc.returncode, 0, run_proc.stdout + run_proc.stderr)


if __name__ == "__main__":
    unittest.main()
