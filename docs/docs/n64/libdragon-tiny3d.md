# libdragon & tiny3d Reference

**Audience:** LLM agents building games with Binface64. What the vendored SDK actually provides, version pins, idioms, and footguns.
**Last reviewed:** 2026-07-06. Sources: vendored submodule source (file:line cites), libdragon README, tiny3d README/docs.
**Scope:** the software stack BF64 sits on. For hardware limits, see `hardware.md`. For display/audio specifics, see those docs.

---

## Version pins (BF64)

| Submodule | Path | Commit | Upstream | Notes |
|---|---|---|---|---|
| libdragon | `vendored/libdragon/` | `b1011fe31` | DragonMinded/libdragon | "preview" branch; describes as `toolchain-continuous-prerelease-4493-gb1011fe31` |
| tiny3d | `vendored/tiny3d/` | `bdcd946` | HailToDodongo/tiny3d | "chg: add additive light option"; no tags |
| SDL | `vendored/SDL/` | (SDL3) | libsdl-org/SDL | editor only |
| ImGui | `vendored/imgui/` | `913a3c6` | ocornut/imgui | docking branch, SDL3 GPU backend; editor only |
| quickjs-ng | `vendored/quickjs-ng/` | `fd0a021` | quickjs-ng/quickjs | editor only (node-graph specs) |

**GOTCHA:** The engine runtime (`n64/engine/`) is *not* the same as libdragon+tiny3d — Pyrite64 is a higher-level engine on top of both. When an agent reads "libdragon API" vs "engine API," they're different layers:
- **libdragon**: low-level SDK (rdpq, video, audio, mixer, filesystem, DMA).
- **tiny3d**: 3D library + RSP ucode on top of libdragon (t3d_* functions, T3DModel, T3DViewport).
- **Pyrite64 engine** (`n64/engine/include/`): scene management, object/component model, collision, asset management, scripts — on top of tiny3d + libdragon. See `ARCHITECTURE.md` §2.

---

## 1. libdragon API surface

### 1.1 Display / VI

- **Headers:** `include/display.h`, `include/vi.h`, `include/surface.h`, `include/graphics.h`. **GOTCHA:** `include/video.h` is FMV/MPEG1/H264 playback, NOT the display API.
- **Resolutions:** predefined `RESOLUTION_256x240`, `RESOLUTION_320x240`, `RESOLUTION_512x240`, `RESOLUTION_640x240`, `RESOLUTION_512x480`, `RESOLUTION_640x480` (`display.h:164-174`). Max 800×720 (`display.c:363-364`).
- **Bit depths:** `DEPTH_16_BPP` (RGBA5551), `DEPTH_32_BPP` (RGBA8888) (`display.h:179-185`).
- **VI modes:** NTSC, PAL, MPAL (`tv_type_t`, `n64sys.h:621-625`), plus non-standard PAL60 (`vi.c:65-75`, unsupported by some upscalers — `vi.h:446-464`).
- **Interlace:** `INTERLACE_OFF`, `INTERLACE_HALF` (swap on odd/even fields), `INTERLACE_FULL` (`display.h:96-103`). `RESOLUTION_*x480` uses `INTERLACE_HALF`.
- **AA / filters:** `FILTERS_DISABLED`, `FILTERS_RESAMPLE` (bilinear), `FILTERS_DEDITHER`, `FILTERS_RESAMPLE_ANTIALIAS`, `FILTERS_RESAMPLE_ANTIALIAS_DEDITHER` (`display.h:218-238`). See `display-and-video.md` for details.
- **Gamma:** `GAMMA_NONE`, `GAMMA_CORRECT`, `GAMMA_CORRECT_DITHER` (`display.h:188-206`).
- **`surface_t`:** `{flags, width, height, stride, buffer}` (`surface.h:139-146`). Flags pack pixel format + OWNEDBUFFER + texindex.

See `display-and-video.md` for the full display reference.

### 1.2 RDP / rdpq

- **Header:** `include/rdpq.h` (the main API), `include/rdpq_macros.h` (combiner/blender macros), `include/rdpq_mode.h` (high-level mode presets).
- **TMEM:** 4 KB (4096 B), 2 KB usable for RGBA32/CI4/CI8/YUV16 (`rdpq_tex.c:188`). 8 tile descriptors (`rdpq.h:254-263`).
- **Texture loading:** `rdpq_load_tile` (sub-rect), `rdpq_load_block` (contiguous, max 2048 texels, faster), `rdpq_load_tlut_raw` (max 256 colors, `rdpq.h:625-634`). **GOTCHA:** after `rdpq_load_block`, the tile descriptor can't be reused for drawing — reconfigure via `rdpq_set_tile` (`rdpq.h:730-732`).
- **Auto-TMEM:** `rdpq_set_tile_autotmem(int16_t tmem_bytes)` (`rdpq.h:848`) — rdpq manages TMEM fitting transparently. **GOTCHA:** overflow is a runtime RSP assert, not compile-time (`rdpq.c:574-575`).
- **Color combiner:** `RDPQ_COMBINER1(rgb, alpha)` (1cyc), `RDPQ_COMBINER2(rgb0, alpha0, rgb1, alpha1)` (2cyc) (`rdpq_macros.h:466-492`). rdpq auto-promotes 1cyc→2cyc when needed (fog, two-pass blender, 2nd combiner, `rdpq.c:94-131`).
- **Blender:** `RDPQ_BLENDER((...))` macro (`rdpq_macros.h:615-711`). Presets: `RDPQ_BLENDER_MULTIPLY`/`_MULTIPLY_CONST`/`_ADDITIVE` (`rdpq_mode.h:515-547`).
- **Z-buffer:** 16-bit (`FMT_RGBA16`), Z-modes `SOM_ZMODE_OPAQUE`/`_INTERPENETRATING`/`_TRANSPARENT`/`_DECAL` (`rdpq_macros.h:629-632`). Z-source per-pixel or fixed PRIM.
- **Render targets:** only `FMT_RGBA16`, `FMT_RGBA32`, `FMT_I8` valid as color images (`rdpq.h:1129-1131`). `FMT_CI8` also accepted (`rdpq.h:1200-1202`).
- **Modes:** `rdpq_set_mode_standard`, `rdpq_set_mode_copy` (4× fast, limited), `rdpq_set_mode_fill` (4×, fill rect), `rdpq_set_mode_yuv` (`rdpq_mode.h:27-46`).
- **Autosync:** `RDPQ_CFG_AUTOSYNCPIPE/AUTOSYNCLOAD/AUTOSYNCTILE/AUTOSCISSOR` (`rdpq.h:229-233`). Default `RDPQ_CFG_DEFAULT = 0xFFFF` (all on). Internal `AUTOSYNC_TILE(n)`/`AUTOSYNC_TMEM(n)`/`AUTOSYNC_PIPE` (`rdpq.h:237-241`).

### 1.3 RSP / rspq

- **Header:** `include/rspq.h`, `include/rspq_constants.h`.
- **Architecture:** lockless ring buffer, CPU writes / RSP reads concurrently (`rspq.h:16-23`).
- **Commands:** up to 62 32-bit words (`rspq.h:200`). Short form `rspq_write` max 16 words (`rspq.h:207`). Command ID = top 8 bits = 4-bit overlay ID + 4-bit command index (`rspq.h:36-39`).
- **Overlays:** max 16 (`rspq_constants.h:18-21`). Register with `rspq_overlay_register(rsp_ucode_t*)` (`rspq.h:337`).
- **Blocks:** pre-recorded command sequences, max 8 nesting levels (`rspq_constants.h:37`). Up to 7 placeholders (`rspq.h:255-283`).
- **Syncpoints:** interrupt-based, "tens per frame OK, not hundreds/thousands" (`rspq.h:243-245`).
- **High-priority queue:** preempts normal between commands (`rspq.h:131-159`); used for audio. **GOTCHA:** cannot create syncpoints or blocks from highpri (`rspq.h:1076-1080`).

### 1.4 Audio

- **Headers:** `include/audio.h`, `include/mixer.h`, `include/wav64.h`, `include/xm64.h`.
- **Mixer:** 32 channels (`mixer.h:59`), RSP-accelerated (`rsp_mixer.S`). Per-channel resampling (`mixer_ch_set_freq`, `mixer.h:210`). 8-bit and 16-bit signed samples, mono and stereo (stereo = 2 channels). Dolby Pro Logic II surround (`mixer_ch_set_vol_dolby`, `mixer.h:168-169`).
- **WAV64:** `wav64_open` (`wav64.h:87`), `rom:/` only (`wav64.h:85-86`). Compression: 0=none, 1=VADPCM (default), 3=Opus (requires `wav64_init_compression(3)`).
- **XM64:** FastTracker II .XM → .XM64, one mixer channel per XM channel (`xm64.h`). Patterns loaded on-the-fly, samples streamed. RLE recompression for patterns (`xm64.h:25`).
- **YM64:** Arkos Tracker II .YM → .YM64 (`audioconv64.cpp:71`, `src/audio/ym64.c`).
- **GOTCHA:** `MIXER_LOOP_OVERREAD = 64` — RSP ucode doesn't bound-check; looping waveforms need up to 64 bytes of repeated loop-start past the loop-end (`mixer.h:62-74`).

See `audio.md` for the full audio reference.

### 1.5 Filesystem / ROM

- **rompak:** TOC-based file bundle inside the ROM, created by `n64tool -T` (`n64tool.c:141`). TOC at PI offset 0x1000 (after 4096-byte IPL3 header), 1024 B, 16-byte aligned, max 15 entries (`n64tool.c:82-85`).
- **DFS (DragonFS):** read-only FAT-like FS packed into a rompak file, registered under `rom:/` (`dragonfs.h:37-40`). Max 256 MiB per file, 4 simultaneous open files, max 100 directory depth, 243-char name limit (`dragonfs.h:33-42,69,74`).
- **SD card:** `sd:/` via FAT (ChaN FatFS, `src/fatfs/ff.c`).
- **Asset API (compression):** `asset_load`/`asset_fopen`/`asset_loadf` (`asset.h:129,154,222`). Three compression levels (LZ4/APLib/Shrinkler). **GOTCHA:** header docs say "two levels" and "Level 2 = LZH5" but code uses APLib for level 2 and Shrinkler for level 3 (`asset.c:47-92`). LZMA/YAPKI/RNC are NOT present.
- **`asset_fopen` streaming:** window 2–256 KiB (default 4 KiB, `assetcomp.h:21`). **GOTCHA:** asserts on seek even for uncompressed files (`asset.h:41-43,216-218`).

### 1.6 Memory

- **RDRAM:** 4 MiB base, 8 MiB Expansion Pak. `get_memory_size()` (`n64sys.h:511`), `is_memory_expanded()` (`n64sys.h:526`), `assert_memory_expanded()` (`n64sys.h:542`).
- **Heap:** starts at `__bss_end`, stats via `sys_get_heap_stats` (`n64sys.h:555`).
- **Uncached:** `malloc_uncached`/`malloc_uncached_aligned`/`free_uncached`/`realloc_uncached` (`n64sys.h:575-617`) — returns `0xA0000000`-segment pointers, no cacheline sharing. Required for DMA targets.
- **Hardware memset:** `sys_hw_memset*` (`n64sys.h:722-767`), ~6× 64-bit / ~12× 32-bit. **GOTCHA:** unsupported on iQue (`n64sys.h:710-712`).
- **Cache line:** 16 bytes. `data_cache_hit_invalidate` requires 16-byte alignment (`n64sys.h:404-407`).

### 1.7 Tools

| Tool | Purpose | Flags |
|---|---|---|
| `mksprite` | PNG → `.sprite` | `-f <format>`, `-c <compress>`, `-D <dither>`, `-m <mipmap>`, `-g <gamma>`, `--texparms`, `--detail`, `-L <lossy>` |
| `audioconv64` | WAV/MP3/AIFF → WAV64, XM → XM64, YM → YM64 | `--wav-mono`, `--wav-resample <N>`, `--wav-compress <0\|1\|3>`, `--xm-8bit`, `--xm-compress <0\|1>` |
| `mkfont` | TTF/OTF/BMFont → `.font64` | `-s <size>`, `--format <RGBA16\|RGBA32\|CI4\|CI8>`, `-r <range>`, `--outline <w>`, `-c <compress>` |
| `mkasset` | compress/decompress arbitrary assets | `-c <0..3>`, `-w <winsize KiB>` |
| `mkdfs` | pack directory into DFS file | root dir argument |
| `n64tool` | pack ELF + DFS + sym into ROM | `--toc`, `--title`, `--header`, `--align`, `--size`, `--padding` |
| `n64metadata` | ROM metadata INI | INI file argument |
| `n64elfcompress` | compress in-ROM ELF | `-c <level>` |

---

## 2. tiny3d API surface

### 2.1 Lifecycle & frame

```c
t3d_init((T3DInitParams){.matrixStackSize = 8});  // once
// per frame:
t3d_frame_start();                                  // set default rdpq state
t3d_screen_clear_color(color);                      // optional
t3d_screen_clear_depth();                           // clears to 0xFFFC
T3DViewport vp = t3d_viewport_create();
t3d_viewport_attach(&vp);
t3d_viewport_set_perspective(&vp, fov, near, far);  // far >= 40
t3d_viewport_look_at(&vp, eye, target, up);
t3d_light_set_ambient(color);
t3d_light_set_directional(0, color, dir);
t3d_matrix_push(&modelMat);
t3d_model_draw(model);                              // high-level
// or manual: t3d_vert_load(...) + t3d_tri_draw(...)
t3d_tri_sync();                                     // before RDPQ overlay use
t3d_matrix_pop(1);
```

### 2.2 Vertex format

**16 bytes/vertex** (`T3DVertPacked`, `t3d.h:42-51`, `docs/modelFormat.md:47-59`):
- Position: `int16[3]` — s16.0 fixed point (integer, model-space, scaled at import).
- Normal: `uint16` — 5.6.5 packed (x:5, y:6, z:5 bits signed).
- Color: `uint32` RGBA8.
- UV: `int16[2]` — 10.5 fixed point **pixel coordinates** (NOT normalized — `README.md:129`, `t3d.h:49-50`).

**RSP output vertex:** 36 bytes (`t3d.c:37`, `rsp_tiny3d.rspl:45`): PosXY, Depth, ClipCode, RejCode, Color, UV, ClipPos, W, ClipPosf, Wf, InvW.

**Skinned vertices:** 1 bone per vertex, up to 3 bones per triangle (`README.md:23-24`). Each vertex has a single `boneIndex`; the converter pre-transforms into bone-space at import using the inverse-bind matrix, then splits parts by bone index. This is "fake-blending" — vertices are rigidly assigned, not smooth-skinned.

### 2.3 Materials

**Two texture slots per material** (`t3dmodel.h:63-64`). Material struct (`t3dmodel.h:46-65`): `colorCombiner` (u64), `otherModeValue`/`otherModeMask` (u64), `blendMode` (u32), `renderFlags` (T3DDrawFlags), `fogMode`, `setColorFlags`, `vertexFxFunc`, `primColor`/`envColor`/`blendColor`, `textureA`/`textureB`.

**Alpha modes:** `T3D_ALPHA_MODE_DEFAULT=0`, `OPAQUE=1`, `CUTOUT=2`, `TRANSP=3` (`t3dmodel.h:16-19`).

**Fog modes:** `T3D_FOG_MODE_DEFAULT=0`, `DISABLED=1`, `ACTIVE=2` (`t3dmodel.h:21-23`).

**fast64 → t3d mapping:** see `vendored/tiny3d/docs/fast64Settings.md`. Supported: Color-Combiner, Draw Layer, Primitive/Environment color + use-flags, Texture-Reference (offscreen), Texture Size/Path, Clamp/Mirror/Mask/Shift/Low/High per S&T, Shade-Alpha=Fog, Cull Front/Back, Texture UV Generate, Cycle Type (1/2), Texture filter, Render Mode (Blend, Z-Mode), Blend Color.

**GOTCHA:** README warns vanilla GLTF exports after 4.0 may be broken; fast64 newest recommended (`README.md:71-72`). Only fast64 materials supported (`README.md:74`).

### 2.4 Lighting

- **Ambient:** always on, global. `t3d_light_set_ambient(color)` (`t3d.h:481`). Black = effectively disabled.
- **Directional:** up to 7. `t3d_light_set_directional(index, color, dir)` (`t3d.h:492`).
- **Point:** up to 7 (shared pool with directional). `t3d_light_set_point(index, color, pos, size, ignoreNormals)` (`t3d.h:511`).
- **Count:** `t3d_light_set_count(count)` (`t3d.h:518`) — 0-6 per docstring, but ucode reserves 7 (`LIGHT_COUNT=7`, `rsp_tiny3d.rspl:15`). **GOTCHA:** with `RSPQ_PROFILE`, clamped to 2 (`t3d.c:188-190`).
- **Exposure:** `t3d_light_set_exposure(float)` (`t3d.h:530`) — scales final color, >1.0 clamped, negative allowed.
- **Mode:** `t3d_state_set_lighting_mode(MUL|ADD)` (`t3d.h:644`) — patches RSP IMEM. **GOTCHA:** only takes effect on next ucode switch; not for per-material use (`t3d.h:636-640`).
- **GOTCHA:** directional lights depend on the view matrix — re-apply when switching viewports (`t3d.h:232-234`).

### 2.5 Animation / skeleton

- **No hard bone-count limit** (`uint16_t boneCount`). Bone count stored as u16 in `.t3dm`.
- **1 bone/vertex, up to 3 bones/triangle.** Fake-blending, not smooth-skin.
- **Animation streaming:** `.t3dm` references separate `.t3ds` streaming files (can be compressed, `README.md:25`). `t3d_anim_create` opens via `asset_fopen`, `fread`s keyframes one at a time.
- **Interpolation:** nlerp for quats (slerp commented out, `t3danim.c:202-203`), lerp for scalars.
- **Keyframe packing:** 3 components × 10-bit, largest-component reconstruction (48 bits, `t3danim.c:116-131`). Time tick = 1/60s (`t3danim.c:10`).
- **Non-skeletal attachment:** `t3d_anim_attach_pos`/`_rot`/`_scale` (`t3danim.h:80-102`) — attach a channel to an arbitrary `T3DVec3*`/`T3DQuat*`.
- **GOTCHA:** reverse playback unsupported (negative speed clamped to 0, `t3danim.h:142-146`).

### 2.6 Culling / BVH

- **Frustum:** `T3DFrustum` (6 planes, `t3dmath.h:38-40`), built from cam-proj matrix. Tests: `t3d_frustum_vs_aabb`/`_aabb_s16`/`_sphere` — "may return false positives in favor of speed" (`t3dmath.h:472,483,494`).
- **BVH:** optional, generated with `--bvh` at import. `T3DBvhNode` (s16 AABBs, `t3dmodel.h:99-103`). `t3d_model_bvh_query_frustum(bvh, frustum)` marks `obj->isVisible=true` for intersecting leaves. **GOTCHA:** reset all to false first (`t3dmodel.h:484-485`).
- **No occlusion culling.**

### 2.7 Particles (tinyPX / TPX)

- **Separate RSP overlay** (`rsp_tinypx`).
- **S8 format:** 8 B/particle, max 344/batch. Color-only.
- **S16 format:** 12 B/particle, max 228/batch. Textured.
- **Screen-aligned rectangular billboards only.** Depth from center.
- **State:** `tpx_state_from_t3d` (copies screen size, MVP, W-norm from t3d), `tpx_state_set_scale` (down only 0-1.0), `tpx_state_set_base_size` (default 128).
- **GOTCHA:** buffers must be `malloc_uncached`, count must be even (`tpx.c:85,102`).

### 2.8 Textures / TMEM

- tiny3d **does not abstract textures** (`README.md:126-130`). Uses libdragon rdpq (`rdpq_sprite_upload`, `sprite_load`).
- **2 texture slots per material** (`textureA`, `textureB`). Slot B reuses slot A's TMEM load if hashes match (`t3dmodel.c:155-159`).
- **UVs in pixel coords** (10.5 fp), not normalized — because t3d doesn't know texture dimensions; RDPQ tile settings handle wrapping.
- **`t3d_state_set_alpha_to_tile(true)`:** 3 MSBs of vertex alpha select the base TILE for that triangle (free, no RSP cost). **GOTCHA:** all vertices of a triangle must share the same tile value (`t3d.h:585-589`).
- **Big texture streaming:** example `22_bigtex` demonstrates a custom technique (not a core t3d feature) — preloads 256×256 I8 textures into a contiguous RDRAM buffer at a fixed base address, uses `texReference=0xFF` placeholders and a custom 2-cycle combiner. Requires custom RSP overlay. Pyrite64 wraps this as its BigTex-256 scene pipeline (see `display-and-video.md`).

### 2.9 Model format (.t3dm)

- **Magic:** `"T3M"` + version 0x04 (`t3dmodel.c:8` `T3DM_VERSION 0x04`).
- **Chunks:** `O` (object, first), `V` (vertices, shared), `I` (indices, shared), `M` (material), `S` (skeleton), `A` (animation), `B` (BVH). See `docs/modelFormat.md`.
- **Streaming:** `.t3ds` companion files for animation keyframes (can be compressed).
- **Optimization:** vertex cache (70, meshopt), triangle stripping (TriStripper, no degenerate tris), de-fragmentation (duplicate verts for exactly one load per part), index buffer DMEM reuse. See `vendored/tiny3d/docs/modelOpt.md` for full details.

---

## 3. Pyrite64 engine layer (on top of tiny3d + libdragon)

See `ARCHITECTURE.md` §2 for the full runtime architecture. Key points:
- **Scene management:** `P64::Scene` (`n64/engine/include/scene/scene.h`). Scenes loaded from `rom:/p64/sNNNN_` binary.
- **Object/component model:** 13 components (Code, Model static/anim, Light, Camera, CollMesh, Collider, Audio2D, Constraint, Culling, NodeGraph, RigidBody, CharBody). See `ARCHITECTURE.md` §2.2.
- **Render pipelines:** Default, HDR+Bloom, BigTex-256. See `display-and-video.md`.
- **Collision:** AABB-tree broadphase, GJK/EPA narrowphase, 6 shapes, RigidBody + MeshCollider + CharacterBody. See `ARCHITECTURE.md` §2.5.
- **Asset management:** global `P64::AssetManager`, tagged-pointer trick (type+flags in high bits, assumes pointers fit in 24 bits). All assets freed on scene change. See `ARCHITECTURE.md` §2.7.
- **Scripts:** per-object C++ (`P64_DATA` macro, `ScriptEntry` table) + global hooks + node graphs (`.p64graph` → C++ coroutines). See `ARCHITECTURE.md` §2.8 and §1.7.

---

## Implications for BF64 agents

1. **Three layers: libdragon → tiny3d → Pyrite64 engine.** Know which layer you're calling. `rdpq_*` is libdragon (lowest). `t3d_*` is tiny3d (3D). `P64::*` is the engine (scene/component/script). The engine wraps tiny3d wraps libdragon.
2. **UVs are pixel coordinates, not normalized.** A 64×64 texture has UVs 0-64, not 0-1. This is a tiny3d convention because t3d doesn't know texture dimensions at draw time.
3. **Only fast64 materials are supported.** Vanilla glTF exports after 4.0 may be broken. Use the newest fast64. Custom properties export must be enabled. See `docs/fast64Settings.md`.
4. **1 bone per vertex, up to 3 bones per triangle.** This is fake-blending, not smooth-skinning. Vertices are rigidly assigned; the "3 bones per triangle" just means a triangle's 3 verts can belong to 3 different bones (handled by splitting parts).
5. **`RSPQ_PROFILE=1` reduces lights 7→2 and breaks vertex FX.** Profile offline only. Don't ship with it.
6. **`t3d_metrics_fetch` is a deprecated stub.** Use `RSPQ_PROFILE=1` + `get_ticks()` or the debug overlay.
7. **DFS doesn't compress.** Use `asset_load`/`asset_fopen` with `mkasset -c <level>` for LZ4/APLib/Shrinkler. The header docs are stale (say "LZH5" for level 2, actually APLib; say "two levels", actually three).
8. **Animation keyframes stream from ROM.** `.t3ds` files are opened with `asset_fopen` and `fread`'d one keyframe at a time. Reverse playback is unsupported.
9. **BVH is optional and must be reset before query.** `t3d_model_bvh_query_frustum` only sets `isVisible=true`; you must set all to false first. Frustum tests may return false positives — culling only, not collision.
10. **Buffers for RSP/RDP/audio must be uncached.** Use `malloc_uncached`/`malloc_uncached_aligned`. Cached memory will corrupt via DMA. The RSP reads DMEM via DMA from RDRAM; the RDP reads TMEM via DMA from RDRAM; audio writes via DMA.
11. **`t3d_tri_sync` before RDPQ overlay use.** After triangle draws, before any RDPQ-generating overlay (audio, video), call `t3d_tri_sync` (`t3d.h:419-421`).
12. **Degenerate triangles are NOT supported in strips.** Use the MSB restart flag instead (`t3d.h:691`). The glTF importer uses TriStripper (not meshoptimizer) specifically because meshoptimizer forces degenerates.