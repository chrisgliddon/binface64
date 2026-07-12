# Procedural chunk meshes

`P64::Renderer::ChunkMesh` is the supported tiny3d surface for runtime-generated
geometry that changes in independent regions: terrain tiles, destructible
floors, voxel faces, paint masks, and vertex-colored lawns. It owns a canonical
CPU copy and one uncached render copy per in-flight frame buffer.

## Geometry model

A mesh has a fixed-capacity, uniform layout:

- `chunkCount` independently dirty and visible regions;
- `batchesPerChunk` tiny3d vertex-cache loads per region;
- up to 70 `verticesPerBatch`;
- `trianglesPerBatch` using one topology shared by every batch;
- normally three render buffers to match BF64's swap chain.

Uniform topology keeps the runtime data small and makes a color/position edit
copy only the changed chunk. For an 8×8 quad chunk, one useful layout is four
batches of two quad rows: 27 vertices and 32 triangles per batch, safely below
the 70-vertex tiny3d cache limit.

```cpp
#include <renderer/chunkMesh.h>

P64::Renderer::ChunkMesh lawn;
P64::Renderer::ChunkMesh::Config config{
  .chunkCount = 24,
  .batchesPerChunk = 4,
  .verticesPerBatch = 27,
  .trianglesPerBatch = 32,
  .bufferCount = 3,
};

if(lawn.init(config)) {
  lawn.setTopology(indices, 32 * 3);
  auto *vertices = lawn.editBatch(chunk, batch);
  // Fill packed tiny3d positions, colors, normals, and UVs.
  lawn.markDirty(chunk);
}
```

Direct `editBatch` access modifies the canonical copy, so call `markDirty` when
finished. `setVertexColor` performs both operations for one vertex. Dirty state
is tracked separately for every render buffer: `beginFrame(bufferIndex)` copies
only chunks that the selected buffer has not yet received, leaving all unrelated
chunk geometry untouched.

## Culling and drawing

`setVisible` provides explicit chunk culling. `setBounds` adds a world-space
AABB; when `draw` receives a `T3DFrustum`, it rejects bounds outside that
frustum. Bounds are deliberately world-space because the low-level API does not
own an object transform. A Code component that applies a model matrix should
transform its local bounds before assigning them.

The caller owns material, combiner, matrix, and tiny3d draw-state setup:

```cpp
lawn.beginFrame(frameIndex);

rdpq_mode_combiner(RDPQ_COMBINER_SHADE);
t3d_state_set_drawflags(static_cast<T3DDrawFlags>(
  T3D_FLAG_SHADED | T3D_FLAG_DEPTH | T3D_FLAG_NO_LIGHT
));
t3d_matrix_set(modelMatrix, true);

const auto draw = lawn.draw(&viewport.viewFrustum);
```

## Telemetry and verification

`metrics()` reports dynamic allocation bytes, capacity triangles, chunks copied
for the current buffer, visible/culled chunks, draw batches, and submitted
triangles. These counters can be included directly in game telemetry without
estimating from source grids.

`n64/tests/chunk_mesh_probe` is a standalone N64 example. It changes one chunk
color every 30 frames, culls another, and emits `BF64_CHUNK_MESH_JSON` with the
memory/triangle counters. The MIPS warning-policy test compiles the API, and the
Ares v148 smoke produced three visible chunks, one culled chunk, six submitted
triangles, and one copied dirty chunk.
