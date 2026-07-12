# BF64 procedural chunk-mesh probe

This N64 example exercises `P64::Renderer::ChunkMesh` with four independently
dirty, triple-buffered vertex-color chunks. Three are rendered and one is
explicitly culled; the same API can cull authored world-space AABBs against the
active tiny3d frustum.

Build and run it with:

```sh
N64_INST="$HOME/Documents/libdragon-sdk" make -C n64/tests/chunk_mesh_probe
ares n64/tests/chunk_mesh_probe/chunk_mesh_probe.z64
```

After 90 frames it emits a `BF64_CHUNK_MESH_JSON:` debug record containing
dynamic allocation bytes, triangle capacity/submission, visible/culled chunk
counts, copied dirty chunks, and draw batches. Every 30 frames only one chunk's
color is changed; after the selected render buffer catches up,
`copied_chunks` is one rather than rebuilding the whole mesh.
