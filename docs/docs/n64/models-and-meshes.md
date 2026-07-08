# Models & Meshes

**Audience:** LLM agents building games with Binface64. The GLTF→fast64→tiny3d pipeline, vertex budgets, material system, skinning/animation limits, and common export mistakes. Use this as the pre-flight reference before importing any 3D model.
**Last reviewed:** 2026-07-07. Sources: vendored tiny3d glTF importer source (file:line cites), vendored tiny3d docs, BF64 build pipeline source, n64brew wiki. Where sources disagree, the conservative number is picked and noted.
**Scope:** 3D models. For texture formats, see `textures.md`. For the runtime render pipeline, see `display-and-video.md`. For the tiny3d API surface, see `libdragon-tiny3d.md`.

---

## Hard limits

| Resource | Hard limit | Source |
|---|---|---|
| RSP vertex cache (per part) | 70 vertices | `vendored/tiny3d/tools/gltf_importer/src/structs.h:293` `MAX_VERTEX_COUNT`, `vendored/tiny3d/src/t3d/t3d.h:17` `T3D_VERTEX_CACHE_SIZE` |
| Per-vertex bytes (on disk, pre-interleave) | 16 (0x10) | `vendored/tiny3d/tools/gltf_importer/src/structs.h:66-89` `VertexT3D::byteSize` |
| Per-vertex-pair bytes (runtime, interleaved) | 32 (0x20) | `vendored/tiny3d/src/t3d/t3d.h:42-53` `T3DVertPacked` |
| Total vertices per model file | 65535 (u16) | `writer.cpp:133-134,456-458` |
| Total indices per model file | 65535 (u16) | `writer.cpp:133-134,456-458` |
| Bones per vertex | **1** (rigid; glTF weights read and discarded) | `vendored/tiny3d/tools/gltf_importer/src/parser.cpp:309,314-327` |
| Bones per mesh part | **1** (multi-bone chunks auto-split) | `vendored/tiny3d/tools/gltf_importer/src/converter/meshConverter.cpp:169-236` |
| Bones per model | 65535 (u16 `matrixIdx`, 0xFFFF = none); no explicit cap | `vendored/tiny3d/tools/gltf_importer/src/structs.h:197` |
| Strip slots per part | 4 | `vendored/tiny3d/tools/gltf_importer/src/structs.h:154` `stripIndices[4]` |
| Triangles per index sequence | 255 (u8 `idxSeqCount`) | `vendored/tiny3d/tools/gltf_importer/src/structs.h:156` |
| Strip indices per slot | 255 (u8 `numStripIndices`) | `vendored/tiny3d/src/t3d/t3dmodel.h:75` |
| Texture slots per material | 2 (textureA, textureB) | `vendored/tiny3d/tools/gltf_importer/src/structs.h:129-130` |
| Material placeholders per MaterialInstance | 8 | `n64/engine/include/renderer/material.h:164` `MAX_SLOTS` |
| Lights per frame | 7 directional + 7 point (shared), profile→2 | `vendored/tiny3d/rsp/rsp_tiny3d.rspl:15` `LIGHT_COUNT 7` |
| Animation sample rate (CLI) | 60 Hz | `vendored/tiny3d/tools/gltf_importer/main.cpp:54` |
| Animation time encoding | 60 ticks/sec, u16; `timeNext` < 2^15 | `animConverter.cpp:16-18`, `writer.cpp:381` |
| Animation channel targets per model | 65535 (u16 `targetIdx`) | `vendored/tiny3d/tools/gltf_importer/src/structs.h:227` |
| .t3dm format magic | `"T3M"` + version 0x04 | `vendored/tiny3d/tools/gltf_importer/src/structs.h:295`, `writer.cpp:129-130` |
| glTF material requirement | **fast64 `f3d_mat` extras required** (else throw) | `vendored/tiny3d/tools/gltf_importer/src/parser/materialParser.cpp:195-203` |
| Armature ancestor constraint | skin root must have no transformed ancestors | `vendored/tiny3d/tools/gltf_importer/src/parser.cpp:74-119` |
| Skipped node name prefix | `fast64_f3d_material_library*` | `vendored/tiny3d/tools/gltf_importer/src/parser.cpp:160-162` |

---

## 1. The BF64 model pipeline

### 1.1 Editor-side import (`src/project/assetManager.cpp:295-343`)

`AssetManager::reloadEntry` for `MODEL_3D`:
1. Calls `T3DM::parseGLTF(path, config)` (the vendored tiny3d importer).
2. Wraps in try/catch; **on failure only logs — broken glb → empty model with no editor-visible error** (`assetManager.cpp:339-341`).
3. Builds a `Renderer::N64Mesh` via `N64Mesh::fromT3DM` for viewport preview.

The source `.glb`/`.gltf` is **kept as-is** in `assets/`. Conversion happens at build time.

### 1.2 Build path (`src/build/t3dmBuilder.cpp:205-275`)

`Build::buildT3DMAssets`:
1. For each MODEL_3D asset, calls `T3DM::writeT3DM(config, t3dm, t3dmPath)` → `.t3dm` in `filesystem/`.
2. Then runs `mkasset -c <compr>` to compress the `.t3dm`.
3. Animation `.sdata` sidecars are collected separately (`t3dmBuilder.cpp:258-272`).

### 1.3 Config — `vendored/tiny3d/tools/gltf_importer/src/structs.h:263-291`

```cpp
struct Config {
  float globalScale{64.0f};
  uint32_t animSampleRate{30};      // struct default; CLI overrides to 60 (main.cpp:54)
  bool ignoreMaterials{false};
  bool createBVH{false};
  bool verbose{false};
  bool ignoreTransforms{false};
  std::string assetPath{};
  std::string assetPathFull{};
  std::filesystem::path projectPath{};
  struct MatInfo { float texSizeX, texSizeY; bool pointFilter; };
  std::function<bool(const std::string &matName, MatInfo &matInfo)> getMaterialInfo{};
  std::function<bool(std::shared_ptr<BinaryFile> f, const Material &material, uint32_t matIdx)> materialWriter{};
};
```

BF64 fills `globalScale` from the conf's `baseScale` (default 16 — `assetManager.cpp:152`), `createBVH` from `gltfBVH` conf flag, `assetPath` = `"assets/"`, `getMaterialInfo` callback reads per-material tex sizes/filter from conf, `materialWriter` callback is the build-time custom serializer (`t3dmBuilder.cpp:234-241`).

### 1.4 Runtime loading

`AssetManager::init` (`n64/engine/src/assets/assetManager.cpp:101`) loads the `.t3dm` via `t3d_model_load` into the global asset table. `Comp::Model::draw` draws mesh indices with an embedded `MaterialInstance`. Animation data is streamed from separate `.sdata` files via `asset_fopen`.

---

## 2. Vertex format

### 2.1 Importer-side intermediate — `structs.h:58-64`

```cpp
struct VertexNorm {
  Vec3 pos{};
  Vec3 norm{};
  float color[4]{};   // init {1,1,1,1}
  Vec2 uv{};
  int32_t boneIndex{-1};
};
```

### 2.2 Final on-disk vertex — `structs.h:66-89`

```cpp
struct VertexT3D {
  /* 0x00 */ int16_t pos[3]{};   // 16.0 fixed point (scaled by globalScale at import)
  /* 0x06 */ uint16_t norm{};   // 5.6.5 packed normal
  /* 0x08 */ uint32_t rgba{};   // RGBA8 color
  /* 0x0C */ int16_t s{};       // 10.6 fixed point (pixel coords)
  /* 0x0E */ int16_t t{};       // 10.6 fixed point (pixel coords)
  uint64_t hash{};              // for dedup
  int32_t boneIndex{};
  uint32_t originalIndex{};
  constexpr static uint32_t byteSize() { return sizeof(VertexT3D) - sizeof(hash) - sizeof(boneIndex) - sizeof(originalIndex); }
};
static_assert(VertexT3D::byteSize() == 0x10, "VertexT3D has wrong size");
```

**Per-vertex byte size = 16 (0x10)** on disk. Runtime packed form interleaves pairs = 32 (0x20) bytes (`T3DVertPacked`, `t3d.h:42-53`).

### 2.3 Components present

| Component | Format | Notes |
|---|---|---|
| Position | `int16[3]` 16.0 fixed point | Pre-multiplied by `globalScale` (default 64); skinned verts pre-transformed by inverse bind pose (`meshConverter.cpp:76-82,87-91`) |
| Normal | `uint16` 5.6.5 packed (X:5, Y:6, Z:5 bits signed) | `meshConverter.cpp:93-102` |
| Color | `uint32` RGBA8 | Clamped 0..1 × 255, packed `(A) \| (B<<8) \| (G<<16) \| (R<<24)` (`meshConverter.cpp:104-108`) |
| UV | `int16[2]` 10.6 fixed point **pixel coords** | `uv * texSize * 32.0` → int16; `-16` adjustment if non-point filter (`meshConverter.cpp:120-126`) |

**NOT supported:** tangent, bitangent, second UV channel (UV1). No normal mapping, no lightmap UVs.

### 2.4 Position range

`int16_t[3]` → ±32767 in 16.0 fixed point → **±32767/globalScale Blender units**. At default `baseScale=64`: ±511.99 Blender units. At `baseScale=16`: ±2047.99. Choose `baseScale` to fit your model's bounding box.

### 2.5 UV range

`int16_t` 10.6 → ±512.0 pixels (with `*32` scaling, effective ±1023.99 texels). UVs are in **pixel coordinates**, not normalized — because t3d doesn't know texture dimensions at draw time (see `libdragon-tiny3d.md`).

### 2.6 Vertex dedup — `meshConverter.cpp:49-65`

FNV-style hash over pos/normal/rgba/s/t + boneIndex. Vertices with identical hash are deduped via `vertIdxMap`. This is the engine-enforced dedup — don't pre-dedup in Blender, the importer does it.

---

## 3. Skinning

### 3.1 One bone per vertex, rigid (NOT smooth skinning)

This is the single most important N64 model constraint. From `parser.cpp:298-312`:

```cpp
if(attr->type == cgltf_attribute_type_joints) {
  assert(attr->data->type == cgltf_type_vec4);
  for(int l = 0; l < acc->count; l++) {
    auto &v = vertices[l];
    u32 joins[4];
    for(int c=0; c<4; ++c) joins[c] = Gltf::readAsU32(...);
    v.boneIndex = joins[0];          // ONLY the first joint is used
    if(v.boneIndex >= boneCount || v.boneIndex < 0) v.boneIndex = -1;
  }
}
if(attr->type == cgltf_attribute_type_weights) {
  // weights are READ but DISCARDED — no smooth skinning
}
```

Despite glTF providing VEC4 joints/weights (up to 4 influences), the importer keeps **only `joins[0]`** and **discards all weights**. Each vertex is rigidly assigned to exactly one bone (or `-1` = neutral/unbound).

This is "fake-blending" — the "up to 3 bones per triangle" in tiny3d docs means a triangle's 3 verts can belong to 3 different bones (handled by splitting the part), NOT that a single vertex blends 3 bones.

### 3.2 Armature ancestor constraint — `parser.cpp:74-119`

The importer **rejects** armatures whose ancestor nodes have non-identity translation/rotation/scale (epsilon `0.0001`):

```cpp
throw std::runtime_error("At least one ancestor of armature/skin root bone has significant transforms!");
```

The skin root must be at the top of any transform chain. If your armature is parented to anything with a transform, the importer throws.

### 3.3 `neutral_bone` handling

Vertices not assigned to any bone are assigned to an artificial bone named `"neutral_bone"` — `parser.cpp:68-72` skips counting it as a real bone.

### 3.4 Multi-bone chunk auto-split — `meshConverter.cpp:169-236`

If a chunk's new vertices span >1 bone, it splits into N sub-chunks (one per bone). All but the last sub-chunk only load vertices (no draw); the last one draws with remapped indices. The optimizer then **skips strip optimization for any chunk with `boneCount > 0`** (`meshOptimizer.cpp:156-157`) — skinned parts use plain triangle lists, not strips.

---

## 4. Mesh optimization (the 70-vertex split)

### 4.1 Three stages, all gated by `MAX_VERTEX_COUNT = 70`

**Stage A — cache optimization** (`parser.cpp:355`):
```cpp
meshopt_optimizeVertexCache(indices.data(), indices.data(), indices.size(), vertices.size());
```
Uses vendored `meshopt` to reorder indices for vertex-cache locality. `meshopt_optimizeOverdraw` is commented out (`:356`).

**Stage B — chunking** (`meshConverter.cpp:132-391` `chunkUpModel`):
- Reserve: `chunks.reserve(triangles * 3 / 70)`.
- Per-part vertex budget = 70. Two closures:
  - `checkAndEmitChunk(forceEmit)`: if `emittedVerts >= 70 || forceEmit`, finalize. **Throws `runtime_error("Too many vertices!")`** if `emittedVerts > 70` (`meshConverter.cpp:163`). Throws `"Not a multiple of 2!"` if vertex count is odd and not forced (`:155`) — required for 2-vertex interleaved DMA.
  - `emitTriangle(tri, onlyExisting)`: tries to find existing indices; if a triangle needs `emittedVerts + needsEmit.size() >= 70` new verts, skips it.
- Triangle ordering: greedy "most-connected-first" partitioner. For each unemitted triangle, emit it, then sweep all subsequent triangles and emit any needing 0 new verts (`onlyExisting=true`). Then a connection-count pass: emit any unemitted triangle whose `connCount >= maxCount` (3, 2, 1) that fits.

**Stage C — index/strip optimization** (`meshOptimizer.cpp:151-296` `optimizeModelChunk`):
- Runs per-chunk **after** chunking. **Skips skinned chunks** (`boneCount > 0`).
- Triangle sequence extraction: detects runs of consecutive indices; if ≥3 triangles AND cuts remaining tris below half, emits as `idxSeqBase`/`idxSeqCount` (RSP `T3D_CMD_TRI_SEQ` command). Max 255 triangles per sequence.
- Triangle stripping: vendored **TriStripper** library (`src/lib/tristrip/`), configured `SetMinStripSize(2)`, `SetCacheSize(0)`, `SetBackwardSearch(false)`. Output strips sorted by max index descending (`:91-95`) to free high-index vertex slots first.
- Free-vertex-slot computation: counts unused vertex slots at end of 70-slot buffer; `calcUsableIndices(freeVerts) = freeVerts * CACHE_VERTEX_SIZE / 2 = freeVerts * 18` indices. Strip index DMA targets freed vertex-cache slots.
- Strip emission: up to 4 strip slots per chunk (`stripIndices[4]`). Strips chained via MSB reset-index (`| (1<<15)`), NOT degenerate triangles. Leftover strips destripified back to individual triangles.

### 4.2 Degenerate triangles — NOT generated

Explicit design decision. `destripify` skips degenerate implicit triangles (`if(strip[i] == strip[i+2])continue;`, `meshOptimizer.cpp:104-105`). Strip continuation uses MSB reset-index instead. The glTF importer uses TriStripper (not meshopt) specifically because meshopt forces degenerates.

### 4.3 De-fragmentation

A triangle needing a vertex from an earlier part re-emits it in the current part rather than issuing a second load. Test scene: 3642 input verts → 3696 output (+54 dupes, +1.5%).

### 4.4 Per-part limits

- **Max vertices per part: 70** (hard, throws on overflow).
- **Max triangles per part**: bounded by index storage. 4 strip slots × 255 indices = ~85 tris/slot. `numIndices` is u16 → 65535 tris max, but bounded by 70-vertex reuse in practice.

---

## 5. Material system

### 5.1 The T3DM::Material struct — `structs.h:127-150`

```cpp
struct Material {
  uint32_t index{};
  MaterialTexture texA, texB;            // TWO texture slots
  std::string name{};

  uint64_t colorCombiner{};              // packed CC (1cyc or 2cyc, MSB = 2PASS flag)
  uint64_t otherModeValue{};
  uint64_t otherModeMask{};
  uint32_t blendMode{};
  uint32_t drawFlags{};

  uint8_t fogMode{};
  uint8_t vertexFxFunc{};

  uint8_t primColor[4]{};
  uint8_t envColor[4]{};
  uint8_t blendColor[4]{};

  bool setPrimColor{false}, setEnvColor{false}, setBlendColor{false};
  bool uvFilterAdjust{false};
};
```

### 5.2 fast64 requirement — `materialParser.cpp:195-203`

**Every material must carry fast64's `f3d_mat` extras blob.** If absent, the importer throws:

```
Material has no fast64 data! (@TODO: implement fallback)
If you are using fast64, make sure to enable 'Include -> Custom Properties' during GLTF export
```

There is NO fallback for vanilla glTF materials. **fast64 is mandatory.**

### 5.3 Color combiner — `structs.h:32-42`

```cpp
namespace CC {
  constexpr uint32_t COMBINED = 0, TEX0 = 1, TEX1 = 2, PRIM = 3, SHADE = 4, ENV = 5, NOISE = 6;
  constexpr uint32_t TEX0_ALPHA = 8, TEX1_ALPHA = 9;
}
```

Parsed from fast64 JSON `f3d_mat.combiner1` / `combiner2`, each with `A,B,C,D,A_alpha,B_alpha,C_alpha,D_alpha` (`materialParser.cpp:119-135`). Supports **both 1-cycle and 2-cycle** modes (selected by `rdp_settings.g_mdsft_cycletype`, `materialParser.cpp:244`). The packed 64-bit `colorCombiner` is built with `rdpq_1cyc_comb_*` / `rdpq_2cyc_comb2*_rgb/alpha` macros. 2-cycle sets the `RDPQ_COMBINER_2PASS` bit (bit 63).

### 5.4 Textures — `structs.h:116-125`

```cpp
struct MaterialTexture {
  std::string texPath{}, texPathRom{};
  uint32_t texWidth{}, texHeight{}, texReference{};
  TileParam s{}, t{};
};
```

Both slots (`texA`, `texB`) are filled only if the color combiner actually uses a texture AND fast64 JSON has `tex0`/`tex1` (`materialParser.cpp:328-333`). `modelFormat.md:71-74` confirms: "Objects can have two materials assigned (with two textures), only the first material's CC and draw flags are used."

### 5.5 TileParam (per-axis UV wrap/clamp/mirror) — `structs.h:96-103`

```cpp
struct TileParam {
  float low{}, high{};
  uint8_t clamp{}, mirror{};
  int8_t mask{}, shift{};
};
```

Read from fast64 JSON `tex0.S` / `tex0.T` / `tex1.S` / `tex1.T` (`materialParser.cpp:30-44`). Per `fast64Settings.md:19-24`: Clamp S/T, Mirror S/T, Mask S/T, Shift S/T, Low S/T, High S/T are all parsed.

### 5.6 DrawFlags — `structs.h:24-30`

```cpp
namespace DrawFlags {
  constexpr uint32_t DEPTH      = 1 << 0;
  constexpr uint32_t TEXTURED   = 1 << 1;
  constexpr uint32_t SHADED     = 1 << 2;
  constexpr uint32_t CULL_FRONT = 1 << 3;
  constexpr uint32_t CULL_BACK  = 1 << 4;
}
```

`DEPTH` always set; `CULL_FRONT`/`CULL_BACK` from `rdp_settings.g_cull_front`/`g_cull_back`; `SHADED` if fog active or CC uses shade; `TEXTURED` if CC references a texture.

### 5.7 Fog modes — `structs.h:44-50`

```cpp
namespace FogMode { constexpr uint8_t DEFAULT=0, DISABLED=1, ACTIVE=2, INVALID=0xFF; }
```

Parsed from `rdp_settings.g_fog` with `+1` offset: fast64 `g_fog=0` → `DISABLED(1)`, `g_fog=1` → `ACTIVE(2)`.

### 5.8 VertexFx — `structs.h:52-55`

```cpp
namespace UvGenFunc { constexpr uint8_t NONE=0, SPHERE=1; }
```

Set from `rdp_settings.g_tex_gen`: non-zero → SPHERE, else NONE. **The importer only emits NONE or SPHERE.** The runtime enum `T3DVertexFX` has more modes (`CELSHADE_COLOR`, `CELSHADE_ALPHA`, `OUTLINE`, `UV_OFFSET`) but the importer never sets them — they're runtime-only.

### 5.9 Blend modes — `tools/gltf_importer/src/parser/rdp.h:30-34`

```cpp
namespace RDP::BLEND {
  NONE      = 0x00000000;
  MULTIPLY  = 0x00500040;   // standard alpha blend
  MUL_CONST = 0x05500040;
  ADDITIVE  = 0x005A0040;
}
```

Selected from fast64 `rendermode_preset_cycle_1/2` indices (20 presets each: Background, Opaque, Opaque Decal, Opaque Intersecting, Cutout, Transparent, Transparent Decal, Transparent Intersecting, Fog Shade, Fog Primitive, Pass, Add, No Op, various No-AA variants, Cloud, Terrain). Fallback: `draw_layer.oot` (3 layers: 0 Opaque→NONE, 1 Transparent→MULTIPLY, 2 Overlay→NONE+ALPHA_COMPARE) or `draw_layer.sm64` (≤1 NONE, ≤4 NONE+ALPHA_COMPARE, else MULTIPLY).

### 5.10 Z-modes — `rdp.h:12-16`

`OPAQUE`, `INTERPEN`, `TRANSP`, `DECAL`.

### 5.11 Texture filters — `rdp.h:19-22`

`POINT`, `MEDIAN`, `BILINEAR`. Mapped from `g_mdsft_text_filt & 0b11`. Non-point filter triggers `uvFilterAdjust=true` → `-16` half-texel UV adjustment in `meshConverter.cpp:123-126`.

### 5.12 Colors

`primColor`/`envColor`/`blendColor` (RGBA8, linear→gamma converted via `powf(c, 0.4545f)`, `materialParser.cpp:159-179`). `blendColor[3]` defaults to **128** for cutout alpha (`:223`).

### 5.13 What is NOT parsed

- **No tangent / bitangent** (no normal mapping).
- **No PBR metallic/roughness** — fast64 CC only.
- **No KHR_materials_* extension handling** — everything flows through `prim->material->extras.data` (the fast64 `f3d_mat` JSON blob).
- **No morph target weights** (animation `weights` path throws `"Unknown animation target"`).

---

## 6. Animation

### 6.1 Channel targets — `animParser.cpp:11-21`

```cpp
cgltf_animation_path_type_translation -> TRANSLATION
cgltf_animation_path_type_rotation    -> ROTATION
cgltf_animation_path_type_scale       -> SCALE
default -> throws "Unknown animation target"
```

**Morph target weights NOT supported** (no case, throws).

### 6.2 Channel expansion — `animParser.cpp:88-97`

Each rotation channel → 1 channel mapping. Each translation/scale channel → **3 channel mappings** (one per axis X/Y/Z, `attributeIdx = 0/1/2`). Channels sorted so **rotations come first**.

### 6.3 Interpolation — effectively LINEAR only (with resampling)

The importer does **not branch on `cgltf_interpolation_type`**. It **resamples every channel at a fixed rate** (`config.animSampleRate`, 60 Hz from `main.cpp:54`) and **linearly interpolates** (or slerps for quaternions) between source keyframes:

```cpp
float sampleStep = 1.0f / sampleRate;
for(t=timeStart; t<=(timeEnd+sampleStep); t += sampleStep) {
  float sampleInterpol = (t - time) / (nextTime - time);
  if(rotation) Quat value = valueCurr.slerp(valueNext, sampleInterpol);
  else        Vec3 value = valueCurr.mix(valueNext, sampleInterpol);
}
```

Step and CubicSpline glTF inputs are silently treated as linear. There is no cubic interpolation.

### 6.4 Time encoding

- Sample rate = **60 Hz** (CLI override of struct default 30).
- Times converted to N64 ticks via `time_to_ticks(t) = (uint16_t)roundf(t * 60.0f)` — 60 ticks/sec.
- `assert(timeNext < (1 << 15))` in `writer.cpp:381` — **15-bit cap on `timeNextInChannelTicks`**; MSB (bit 15) repurposed to encode next keyframe's data size (scalar=0, rotation=1).
- Max time = 65535 ticks ≈ **18.2 minutes** at 60 Hz.

### 6.5 Keyframe quantization — `animConverter.cpp:162-171`, `quantizer.h`

- **Rotation**: 32-bit packed quaternion via `Quantizer::quatTo32Bit`: smallest-3 encoding, 10 bits each, 2 MSB = index of largest omitted component. Range [-1/√2, 1/√2]. `valQuantSize = 2` (two u16). Throws if quantized value is exactly 0.
- **Scalar** (translation/scale per-axis): 16-bit, `floatToU16(value, valueMin, valueMax-valueMin)` per-channel. `valQuantSize = 1`.

### 6.6 Keyframe optimization — `animConverter.cpp:36-83`

MSE-gated keyframe removal. Thresholds: global `0.000001f`, local `0.0000001f`. Initial MSE must be ~0 (`assert(mse < 0.00001f)`). `isEmptyChannel` drops channels that are constant AND equal to identity (translation≈0, rotation=identity, scale=1).

### 6.7 Streaming layout

Animations are split: the `T3DChunkAnim` header + `ChannelMapping[]` go in the main `.t3dm` (`writer.cpp:361-405`), but the actual keyframe bytes go into a **separate `.sdata` streaming file** (`writer.cpp:359,463-466`), path `<base>.<idx>.sdata` mapped to `rom:/`. Each keyframe in the stream: `u16 timeNext` (MSB=size flag) + `u16 chanelIdx` + 1 or 2 × `u16` data. First keyframe forced to 4 bytes (rotation size) for known initial state.

### 6.8 Limits

- **No explicit MAX_KEYFRAMES or MAX_CLIPS.** `t3dm.animations` is unbounded `vector<Anim>`. Empty animations (duration < 0.0001) are dropped.
- **No explicit bone-count limit.** `targetIdx` is `uint16_t` → up to 65535 bones.
- **Max clips per model file**: unbounded (vector), but bounded by the 65535-vertex/65535-index total file cap.

---

## 7. The `.t3dm` binary format

### 7.1 Header (0x00–0x2B) — `writer.cpp:127-165`, `t3dmodel.h:150-169`

| Offset | Type | Field |
|---|---|---|
| 0x00 | `char[3]` | Magic `"T3M"` |
| 0x03 | `u8` | Version (`0x04`) |
| 0x04 | `u32` | chunkCount |
| 0x08 | `u16` | totalVertCount (patched) |
| 0x0A | `u16` | totalIndexCount (patched) |
| 0x0C | `u32` | chunkIdxVertices (first 'V') |
| 0x10 | `u32` | chunkIdxIndices (first 'I') |
| 0x14 | `u32` | chunkIdxMaterials (first 'M'/'m') |
| 0x18 | `u32` | stringTableOffset |
| 0x1C | `void*`/`u32` | userBlock (runtime, set by user) |
| 0x20 | `s16[3]` | aabbMin (model space) |
| 0x26 | `s16[3]` | aabbMax (model space) |
| 0x2C | `ChunkOffset[]` | chunk offset table |

### 7.2 Chunk types — `t3dmodel.h:186-194`

```c
enum T3DModelChunkType {
  T3D_CHUNK_TYPE_VERTICES = 'V',
  T3D_CHUNK_TYPE_INDICES  = 'I',
  T3D_CHUNK_TYPE_MATERIAL = 'M',   // 'm' if custom materialWriter
  T3D_CHUNK_TYPE_OBJECT   = 'O',
  T3D_CHUNK_TYPE_SKELETON = 'S',
  T3D_CHUNK_TYPE_ANIM     = 'A',
  T3D_CHUNK_TYPE_BVH      = 'B'
};
```

### 7.3 Chunk write order

1. Objects (`O`) — written inline first, interleaved with vertex/index accumulation.
2. BVH (`B`) if enabled.
3. Vertices (`V`) — global interleaved vertex buffer, aligned 16.
4. Indices (`I`) — global index buffer, aligned 4.
5. Materials (`M`/`m`), aligned 8 each.
6. Skeleton (`S`), aligned 8.
7. Custom chunks.
8. String table at the end, aligned 4.

### 7.4 Skeleton chunk — `writer.cpp:180-192`, `modelFormat.md:164-184`

```
u16 boneCount
u16 _reserved
T3DBone[]:
  u32 name (strOff)
  u16 parentIdx
  u16 depth/level
  f32[3] scale
  f32[4] rotation (XYZW)
  f32[3] position (scaled by globalScale)
```

### 7.5 Material chunk — `writer.cpp:213-269`, `modelFormat.md:70-118`

```
u64 colorCombiner
u64 otherModeValue
u64 otherModeMask
u32 blendMode
u32 drawFlags
u8  _unused
u8  fogMode
u8  setColorFlags (setPrimColor | setEnvColor<<1 | setBlendColor<<2)
u8  vertexFxFunc
u8[4] primColor
u8[4] envColor
u8[4] blendColor
u32 name (strOff)
T3DMaterialTexture texA (44 B: ref, pathOff, hash, runtimePtr=0, w16, h16, S{f32,f32,s8,s8,u8,u8}, T{...})
T3DMaterialTexture texB
```

### 7.6 Animation chunk — `writer.cpp:358-408`, `modelFormat.md:186-234`

```
u32 name (strOff)
f32 duration
u32 keyframeCount
u16 channelsQuat
u16 channelsScalar
u32 filePath (strOff to rom:/ path of .sdata)
ChannelMapping[]:
  u16 targetIdx
  u8  targetType
  u8  attributeIdx
  f32 quantScale = (valueMax - valueMin) / 65535
  f32 quantOffset = valueMin
```

Keyframe data lives in the separate `.sdata` stream file.

### 7.7 BVH chunk — `writer.cpp:194-197,412-416`, `meshBVH.cpp`

Built only if `config.createBVH`. Built from per-`ModelChunked` AABBs using `bvh::v2::DefaultBuilder` with `Quality::High`. Serialized as:

```
u16 nodeCount
u16 dataCount (prim_ids count)
BVHNode[]:
  s16[3] aabbMin
  s16[3] aabbMax
  u16 packed: 12-MSB index, 4-LSB dataCount (0 = inner node; >0 = leaf)
u16[] data (object indices)
```

Inner nodes store `(indexDiff << 4)` where `indexDiff = dataOffset - nodeIndex`. Used for frustum culling — `t3d_model_bvh_query_frustum` marks `obj->isVisible=true` for intersecting leaves. **Reset all to false first** (`t3dmodel.h:484-485`). Frustum tests may return false positives.

---

## 8. Real-world model usage (jam25 example)

| File | Size | Notes |
|---|---|---|
| `head.glb` | 514 KB | Player head model |
| `mapEnd/stoneBci.glb` | 282 KB | BigTex stone map |
| `skybox.glb` | 217 KB | Skybox |
| `tutorial/mapTutorial.glb` | 149 KB | Tutorial level |
| `mapPaper/mapParts.glb` | 136 KB | Paper map parts |
| `mapPaper/skybox.glb` | 109 KB | Alternate skybox |
| `tutorial/block.glb` | 91 KB | Block |
| `envBlock.glb` | 73 KB | Environment |
| `model3.glb` | 64 KB | Misc model |
| `map00.glb` | 56 KB | Map 00 |

jam25 total GLB source: 1.94 MiB across 10 files. The conf `baseScale` is 16 for all (so position range ±2047.99 Blender units). `gltfBVH: false` and `gltfCollision: true` for the head, false for environment.

---

## 9. Common Blender/fast64 export mistakes

### 9.1 Forgetting "Custom Properties" export

The fast64 `f3d_mat` extras blob lives in the material's custom properties. If "Include → Custom Properties" is unchecked during GLTF export, the blob is dropped and the importer throws `"Material has no fast64 data!"`. **This is the #1 most common export mistake.**

### 9.2 Armature parented to a transformed node

If the armature's parent (or any ancestor) has non-identity translation/rotation/scale, the importer throws `"At least one ancestor of armature/skin root bone has significant transforms!"`. The armature must be at the top of any transform chain.

### 9.3 Smooth skinning with >1 bone influence

glTF allows up to 4 bone influences per vertex. The importer keeps only `joints[0]` and discards weights. A vertex you painted to blend 50% BoneA / 50% BoneB will be 100% BoneA in the ROM. **Either use rigid skinning (one bone per vertex) or accept the loss.**

### 9.4 Morph target animations

`weights` morph target animation path is unsupported — the importer throws `"Unknown animation target"`. Don't use shape keys / blend shapes / morph targets.

### 9.5 Materials without fast64 settings

A vanilla glTF PBR material (metallic/roughness) has no `f3d_mat` extras. The importer throws. Every material must be authored in fast64 with explicit CC/blender/zmode settings.

### 9.6 Textures not pre-imported as PNG assets

glTF materials reference texture *paths*; `Material::fromT3D` calls `assets.getByPath(mat.texPath)` to bind the texture to its PNG asset UUID. **If `getByPath` fails (texture not in `assets/`), `tex.set.value` stays false — the material silently loses its texture binding with no warning** (`material.cpp:174-181`). Import textures into the project BEFORE importing the glb.

### 9.7 Cubic spline / step interpolation

glTF step and CubicSpline interpolation are silently treated as linear. Don't expect per-keyframe interpolation fidelity — the importer resamples everything at 60 Hz linear/slerp.

### 9.8 UVs not in pixel coordinates

UVs are multiplied by `texSize * 32.0` and stored as 10.6 fixed point. If your UVs are 0-1 normalized (standard glTF), they become 0-(texSize*32) in the ROM — this is correct. But if you set `texSize` wrong (e.g. the texture is 32×32 but the conf says 64×64), UVs will be wrong. The conf's texture size must match the actual texture.

### 9.9 Non-even vertex counts in a chunk

The 2-vertex interleaved DMA layout requires even vertex counts. The importer handles this by duplicating the last vertex when forced (`meshConverter.cpp:157-158`), but it's a sign of suboptimal mesh topology. Triangulate cleanly in Blender.

---

## Implications for BF64 agents

1. **fast64 is mandatory.** Every material must carry the `f3d_mat` extras blob. Enable "Custom Properties" during GLTF export. Vanilla glTF materials throw — there is no fallback.
2. **1 bone per vertex, rigid.** glTF weights are read and discarded. Design your rig for rigid skinning (one bone per vertex) or accept that painted weights will be lost. A triangle's 3 verts can belong to 3 different bones (auto-split into sub-parts).
3. **Armature must be at the top of the transform chain.** No transformed parents. If your armature is parented to anything, the importer throws.
4. **70 vertices per RSP load.** The importer auto-splits with a greedy most-connected-first partitioner. Don't fight it — keep individual mesh parts under ~70 verts if you can, but the importer handles arbitrary sizes by splitting.
5. **65535 vertices / 65535 indices per model file.** Above that, split your model into multiple `.glb` files. The 70-vertex split happens per-part, but the file total caps at u16.
6. **No morph targets.** `weights` animation path throws. Use skeletal animation only.
7. **Animations are resampled at 60 Hz linear/slerp.** Step and CubicSpline are silently treated as linear. Don't rely on per-keyframe interpolation. Max 18.2 minutes per clip.
8. **Two texture slots per material.** TEX0 + TEX1 share TMEM via `rdpq_tex_multi_begin`. If TEX1 references the same asset as TEX0, it reuses the TMEM load (0 extra bytes). Both must be pre-imported as PNG assets or the binding is silently lost.
9. **8 material placeholders per MaterialInstance.** Exceeding 8 silently drops the binding. The builder logs an error but does not crash (`t3dmBuilder.cpp:36-44`).
10. **UVs are pixel coordinates, not normalized.** 0-1 normalized glTF UVs become 0-(texSize*32) in the ROM (10.6 fixed point). This is correct — but the conf's texture size must match the actual texture or UVs will be wrong.
11. **Import textures BEFORE the glb.** `getByPath` failing silently loses texture bindings. The order matters.
12. **BVH is optional (`gltfBVH` conf flag).** When enabled, the importer builds a BVH for frustum culling. Reset `isVisible=false` before each query; frustum tests may return false positives (culling only, not collision).
13. **No tangent / bitangent / second UV.** No normal mapping, no lightmap UVs. Lightmaps go on a second mesh with a separate material, or use the BigTex pipeline.
14. **`baseScale` controls position precision.** Default 16 → ±2047.99 Blender units. At 64 → ±511.99. Choose `baseScale` to fit your model's bounding box without exceeding int16 range.