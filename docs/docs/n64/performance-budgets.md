# N64 Performance Budgets

**Audience:** LLM agents building games with Binface64. Numbers are practical budgets, not hard limits (those are in `hardware.md`).
**Last reviewed:** 2026-07-06. Sources cited inline. Where sources disagree, the conservative number is picked and noted.
**Scope:** triangle counts, fill rate, RSP/RDP time, RDRAM bandwidth contention. For hardware specs, see `hardware.md`. For the tiny3d/libdragon API surface, see `libdragon-tiny3d.md`.

---

## Hard limits (quick reference)

| Resource | Hard limit | Source |
|---|---|---|
| Frame time @ 60fps NTSC | 16.67 ms | NTSC VI/AI clock 48.68 MHz, 525 lines, 60 Hz |
| Frame time @ 30fps NTSC | 33.33 ms | |
| Frame time @ 50fps PAL | 20 ms | PAL 625 lines, 50 Hz |
| RSP vertex cache | 70 vertices per load | `vendored/tiny3d/src/t3d/t3d.h:17` `T3D_VERTEX_CACHE_SIZE` |
| RSP output vertex size | 36 bytes | `vendored/tiny3d/src/t3d/t3d.c:37` `VERT_OUTPUT_SIZE`; `rsp_tiny3d.rspl:45` `TRI_SIZE` |
| RSP DMEM vertex buffer | 70 × 36 = 2520 bytes | `vendored/tiny3d/rsp/rsp_tiny3d.rspl:171-172` `VERT_BUFFER[70][36]` |
| Lights (multiplicative) | 7 directional + 7 point (shared pool), ambient always on | `vendored/tiny3d/rsp/rsp_tiny3d.rspl:15` `LIGHT_COUNT 7`; with `RSPQ_PROFILE` clamped to 2 |
| Particles per batch (S8) | 344 | `vendored/tiny3d/src/tpx/tpx.c:19` `MAX_PARTICLES_S8` |
| Particles per batch (S16) | 228 | `vendored/tiny3d/src/tpx/tpx.c:20` `MAX_PARTICLES_S16` |
| TMEM | 4 KB (2 KB for RGBA32/CI4/CI8/YUV16) | `vendored/libdragon/src/rdpq/rdpq_tex.c:188` |
| RDP tiles | 8 (TILE0–7) | `vendored/libdragon/include/rdpq.h:254-263` |
| Mixer channels | 32 | `vendored/libdragon/include/mixer.h:59` |
| RDRAM | 4 MiB base, 8 MiB Expansion Pak | `vendored/libdragon/include/n64sys.h:511,526` |

---

## 1. Frame budget breakdown

At 30fps (the common 3D target), you have **33.33 ms** per frame. A typical budget split for a tiny3d game:

| Phase | Budget (30fps) | Notes |
|---|---|---|
| CPU game logic + script callbacks | ~5–8 ms | user `update`/`fixedUpdate`/`onEvent`/`onCollision`; depends on script complexity |
| RSP T&L (vertex transform, lighting, clipping) | ~8–12 ms | the dominant 3D cost; ~8.8 ms measured for a 3642-vert model (see §2) |
| RDP rasterization (fill rate) | ~5–10 ms | depends on triangle count, texture size, blend mode, overdraw |
| Audio mixer (RSP, highpri) | ~0.5–1 ms | preemptively slices between RSP commands; <3% CPU for 10-ch XM (`vendored/libdragon/README.md`) |
| VI/scaler + framebuffer writeback | ~1–2 ms | VI runs concurrently with RDP for the *previous* frame (triple-buffered) |
| Overhead (queue, sync, cache flush) | ~1–2 ms | rspq syncpoints, autosync, RDP→RDRAM writeback |
| **Slack** | ~2–5 ms | absorb spikes; if negative, frame dropped |

At 60fps, halve everything: **16.67 ms** total, ~2.5–4 ms for CPU logic, ~4–6 ms RSP, ~2.5–5 ms RDP. Much tighter; only feasible with low-poly scenes and few lights.

**GOTCHA:** Pyrite64's `VI::SwapChain` is triple-buffered (`FB_COUNT=3`, `vi/swapChain.h:13`) and runs the VI concurrently with RDP for the previous frame. This means the VI chases the RDP — you don't pay VI time inside the frame budget, but a stalled RDP delays *two* frames downstream. There's a 200 ms RSP-timeout escape hatch that forces a free buffer if the RSP hangs (`swapChain.cpp:132-137`) — if it fires, you see a torn frame.

---

## 2. Triangle counts

tiny3d does not publish a headline "X tris at 30fps" figure. The closest measured data point is from the tiny3d model optimization doc:

**Test model** (`vendored/tiny3d/docs/modelOpt.md:195-253`):
- Input: 3642 vertices, 6978 indices (2326 draw commands).
- After optimization: 3698 vertices (+54 dupes for cache defrag), 4674 indices (-33%), 127 draw commands (-94.5%).
- RSP time: **8807 µs** (~8.8 ms) with strips saving 1650 µs.
- Memory bandwidth: 10142 B vs 18608 B (-45.5%).

This is a single-model measurement, not a full-scene budget. Deriving practical scene budgets:

| Scene complexity | Tris/frame | Verts/frame | Notes |
|---|---|---|---|
| Minimal (one model, 1-2 lights) | ~500–1,000 | ~300–700 | headroom for heavy CPU logic; 60fps viable |
| Light (small level, 2-3 lights) | ~1,000–3,000 | ~700–2,000 | 30fps comfortable, 60fps tight |
| Medium (SM64-ish level, 3-5 lights) | ~3,000–6,000 | ~2,000–4,500 | 30fps target; fill rate becomes a factor |
| Heavy (OoT-ish scene, 5-7 lights, fog) | ~6,000–10,000 | ~4,500–7,500 | 30fps only, expect dropped frames on real hardware |
| Extreme (max out RSP) | ~10,000–15,000 | ~7,000–10,000 | 20-30fps; experimental, not shippable |

**Derivation:** the test model is ~3.6K verts at 8.8 ms RSP. RSP is ~62.5% of a 30fps budget if you want to leave room for CPU+RDP. At ~70 verts per RSP load and ~0.24 ms per load (8.8ms / 37 parts ≈ 0.24ms each), ~36 loads fit in 8.6 ms = 2520 verts ≈ ~1700 tris (at 1.5 verts/tri average with stripping). Double it for two-pass lighting or heavy clipping. These are rough — actual cost varies with lighting count, clipping frequency, strip efficiency.

**GOTCHA:** these numbers are for *tiny3d's custom ucode*, which is written from scratch and not based on proprietary code (`vendored/tiny3d/README.md:12`). The author compared it against F3DEX3 in a separate repo (https://github.com/HailToDodongo/gl_test_scene, referenced in `vendored/tiny3d/examples/99_testscene/Readme.md:3-4`) but no published comparison numbers are in the repo. Treat these as "what tiny3d achieves," not "what the N64 can do in general."

**GOTCHA:** `t3d_metrics_fetch` is a deprecated no-op stub (`vendored/tiny3d/src/t3d/t3d.h:162-169`, `t3d.c:119-125`). You cannot query RSP metrics at runtime; you must profile offline with `RSPQ_PROFILE=1`.

---

## 3. RSP microcode limits

**DMEM is 4 KB.** tiny3d is at **100% DMEM usage** (`vendored/tiny3d/docs/modelOpt.md:108`). The layout (`rsp_tiny3d.rspl:69-186`):
- `MATRIX_PROJ/MVP/MV/NORMAL` — 4 matrices.
- `FOG_SCALE_OFFSET`, `SCREEN_SCALE_OFFSET`, `NORMAL_MASK_SHIFT`, `CLIPPING_PLANES`, `NORM_SCALE_W`, `SEGMENT_TABLE[8]`, `COLOR_AMBIENT`, `LIGHT_DIR_COLOR[16][7]`.
- `VERT_BUFFER[70][36]` = 2520 bytes — the vertex cache.
- `CLIP_BUFFER_TMP[7][36]` + `CLIP_BUFFER_RESULT[8][36]` — clipping scratch.

**Vertex cache = 70.** Models are split into parts of ≤70 verts at import (`vendored/tiny3d/tools/gltf_importer/src/structs.h:293` `MAX_VERTEX_COUNT = 70`). The optimizer (`docs/modelOpt.md`) partitions triangles into parts preferring 0-new-vertex then 1 then 2-new-vertex triangles, de-fragmenting by duplicating vertices from earlier parts so each part needs exactly one vertex load.

**Triangle stripping:** tiny3d uses TriStripper (not meshoptimizer, because meshoptimizer forces degenerate triangles — `docs/modelOpt.md:155-162`). **Degenerate triangles are NOT supported** (`t3d.h:691`, `docs/modelOpt.md:147-154`); restart is via MSB of first index of a new strip (`t3d.h:691-695`). Max 4 strip commands per part (`t3dmodel.h:75` `numStripIndices[4]`); overflow falls back to `t3d_tri_draw`.

**Index buffer DMEM reuse:** index buffers are DMA'd into freed vertex-cache slots (1 vert slot = 36 bytes = 18 indices = 6 triangles, `docs/modelOpt.md:122`). Drawing higher-index triangles first maximizes free space. **GOTCHA:** the index buffer DMEM target overlaps the vertex cache — free vertex slots are required or vertices corrupt (`t3d.h:390-396`).

**Clipping overlay:** the clipping code lives in a **separate RSP overlay** (`rsp_tiny3d_clipping`) DMA'd into IMEM on demand (`rsp_tiny3d.rspl:258-278`, `t3d.c:61-69`). Triggered only when a triangle actually needs clipping (`rsp_tiny3d.rspl:749-763`). `t3d_tri_sync` restores the original code. The two overlays must keep data/code layouts in sync — enforced by static_asserts (`t3d.c:12-23`).

**Profile builds (RSPQ_PROFILE=1):** the ucode no longer fits in DMEM. **Lights reduced 7→2**, and any vertex effect (uvgen) becomes UB (`t3d.c:188-190, 212-213, 240-241`; `examples/99_testscene/Readme.md:22-23`). **GOTCHA:** "Even if you don't use profiling in your code, running with a libdragon version that has it enabled will reduce RSP performance" (`examples/99_testscene/Readme.md:25`).

---

## 4. Fill rate / RDP

The RDP's fill rate depends heavily on mode:

| Mode | Relative speed | Notes |
|---|---|---|
| Fill | 4× | `rdpq_set_mode_fill` — fill rect, no blend |
| Copy | 4× | `rdpq_set_mode_copy` — 16bpp only, CI4/CI8/RGBA16, Y-scale only, no rotation/mirror, transparency via color-0 only |
| 1-cycle (1cyc) | 1× (baseline) | standard textured/shaded triangles |
| 2-cycle (2cyc) | ~0.5× | required for fog, two-pass blender, 2nd combiner |

**RDRAM bandwidth contention:** the RDP, VI, CPU, and RSP all share RDRAM. The VI fetches the framebuffer for display every scanline. The RDP writes the framebuffer. The CPU reads code/data. The RSP reads commands + matrices + vertices from RDRAM via DMA. Heavy RDP fill (large transparent sprites, post-process passes, full-screen fog) saturates RDRAM bandwidth and can stall the CPU.

**VI AA `FETCH_ALWAYS`** is broken in 32bpp — 32bpp AA falls back to `FETCH_NEEDED`, more corruption-prone (`vendored/libdragon/src/display.c:314-321`). This is why Pyrite64's HDR+Bloom and BigTex pipelines are hard-locked to 320×240 RGBA16 (see `display-and-video.md`).

**Z-buffer:** 16-bit, stored as `FMT_RGBA16` surface, placed in the last RDRAM bank for bandwidth (`display.c:596-611`). Z-modes: `SOM_ZMODE_OPAQUE`/`_INTERPENETRATING`/`_TRANSPARENT`/`_DECAL` (`rdpq_macros.h:629-632`).

---

## 5. Lighting cost

**Hard limit: 7 directional + 7 point lights (shared pool) + ambient.** With `RSPQ_PROFILE` clamped to 2.

| Lights active | RSP cost (relative) | Notes |
|---|---|---|
| 0 (ambient only) | 1× | `NO_LIGHT` flag jumps to end with `lightColor=1.0` |
| 1–3 | ~1.2–1.6× | typical for a sunlit outdoor scene |
| 4–7 | ~1.8–2.5× | heavy; pair with lower tri counts |
| 7 + point lights | ~2.5–3.5× | point lights are more expensive (eye-space transform + distance falloff per vertex) |

Point lights compute squared distance + `invert_half_sqrt` falloff per vertex (`rsp_tiny3d.rspl:547-609`); directional is a dot product (`rsp_tiny3d.rspl:420-424`). Prefer directional for performance.

**Additive lighting mode** (`t3d_state_set_lighting_mode(ADD)`, commit bdcd946): patches RSP IMEM, swapping `VMULF` ↔ `VADD`. Use case: bake lighting into vertex colors and add dynamic light on top. **GOTCHA:** the patch only takes effect on the next ucode switch — force one (any RDPQ call) before the next vertex load (`t3d.h:636-640`). Not for per-material use (`t3d.h:636-637`).

**Exposure:** `t3d_light_set_exposure(float)` scales final (light+vertex) color; >1.0 clamped; negative allowed (inverts color). Allows simple HDR (`t3d.h:530`, `t3d.c:194-198`).

---

## 6. Memory budget (RDRAM)

| Component | Typical cost | Notes |
|---|---|---|
| Code (ELF, compressed in ROM) | ~256 KiB – 2 MiB | uncompressed in RDRAM; `n64elfcompress` compresses the in-ROM ELF |
| Stack | 64 KiB | `n64.ld:197` |
| Framebuffer (320×240 RGBA16) | 153.6 KiB per buffer × 3 (triple-buffered) = ~461 KiB | `surface_t` 2 B/pixel |
| Z-buffer (320×240 RGBA16) | 153.6 KiB | single, in last RDRAM bank |
| Audio output buffers (44100 Hz) | ~28 KiB (4 × 7 KB uncached) | `audio.c:42,53,244` |
| Audio mixer per-channel buffer (44100 Hz, 16-bit stereo) | ~22 KiB per channel | `mixer.c:218`; 32 channels max = ~704 KiB if all used (rare) |
| Heap (assets, scene data, scripts) | remainder | ~3.5 MiB on 4MB system, ~7.5 MiB on 8MB |

**GOTCHA:** All asset pointers are invalidated on every scene change in Pyrite64 (`Scene::~Scene` → `AssetManager::freeAll`, see `ARCHITECTURE.md` §2.7). Keeping an asset pointer across a scene load is a use-after-free. Use `AssetRef<T>` for lazy re-resolution.

---

## 7. Particle budget

**tinyPX (TPX)** is a separate RSP overlay from tiny3d.

| Format | Bytes/particle | Max per batch | Notes |
|---|---|---|---|
| S8 (color-only) | 8 | 344 | `TPXParticleS8`, pos int8, size int8, RGBA |
| S16 (textured) | 12 | 228 | `TPXParticleS16`, pos int16, size int8, texOffset u8, RGBA |

Larger counts auto-batch (`tpx.c:87-98, 100-115`). Buffers must be `malloc_uncached` and count must be **even** (`tpx.c:85, 102`). Example `18_particles` allocates up to 100,000 particles (`examples/18_particles/main.c:66`), drawn in batches.

Particle types: screen-aligned rectangular billboards only (`examples/18_particles/main.c:15-19`). Color or textured variants. Depth sampled from center.

---

## 8. Practical budgets summary

| What | 30fps budget | 60fps budget | Hard limit | Notes |
|---|---|---|---|---|
| Triangles | 2,000–5,000 | 1,000–2,500 | RSP time (no hard tri limit) | depends on lights, clipping, strips |
| Vertices per model part | ≤70 | ≤70 | 70 | `T3D_VERTEX_CACHE_SIZE` |
| Directional lights | 1–4 | 1–2 | 7 | point lights cost more |
| Point lights | 0–2 | 0–1 | 7 | eye-space distance per vertex |
| Textures in TMEM simultaneously | 1–2 per material | 1–2 per material | 2 per material, 4 KB total | see `textures.md` (Phase 2) |
| Particles per frame | 500–2,000 | 250–1,000 | 344/228 per batch | auto-batched |
| Audio channels | 8–16 | 8–16 | 32 | each stereo = 2 channels |
| RDRAM for assets | ~3.5 MiB (4MB) / ~7.5 MiB (8MB) | same | 4/8 MiB total | minus code/fb/z/audio |

---

## Implications for BF64 agents

1. **Target 30fps for 3D games.** 60fps is viable only for minimal scenes (one model, 1-2 lights). The frame budget at 30fps is 33.33 ms — plan RSP ~8-12 ms, RDP ~5-10 ms, CPU ~5-8 ms, slack ~2-5 ms.
2. **Budget 70 vertices per model part.** The glTF importer auto-splits; don't fight it. Optimize meshes in Blender with vertex cache in mind (use the tiny3d model optimizer, `docs/modelOpt.md`).
3. **Prefer directional over point lights.** Point lights are ~2× the RSP cost (eye-space transform + distance falloff per vertex). 1-2 directional + ambient is the sweet spot; 7+ lights will crater performance.
4. **Don't use `RSPQ_PROFILE` in production.** It reduces lights 7→2 and breaks vertex FX. Profile offline, ship without it.
5. **Fill rate kills frames faster than triangle count.** Full-screen transparent passes, heavy fog, and post-process are RDP-bound. Pyrite64's HDR+Bloom and BigTex pipelines are 320×240 RGBA16 only — they exist to work within fill-rate limits.
6. **Every texture switch costs TMEM reload time.** Batch draws by material/texture; the tiny3d model optimizer sorts objects by draw-layer then material (`docs/modelOpt.md:285`). Don't scatter texture switches across the frame.
7. **Triple-buffering means a stall delays two frames.** Pyrite64's `VI::SwapChain` runs the VI concurrently with RDP. If the RDP stalls, you don't see it for two frames. The 200ms RSP-timeout escape hatch (`swapChain.cpp:132-137`) is a fallback, not normal flow.
8. **Audio is cheap but channel-limited.** 32 mixer channels hard limit; a 10-channel XM costs <3% CPU and <10% RSP (`vendored/libdragon/README.md`). Stereo consumes 2 channels per source.
9. **Memory is tight on 4 MiB.** After code (~256KB-2MB), 3 framebuffers (~461KB), Z (~154KB), audio (~28KB + per-channel), you have ~3.5 MiB for assets. Streaming from ROM (wav64, animation `.t3ds`) avoids loading everything into RAM — prefer streaming for music and long audio.
10. **Profile by measuring, not guessing.** `t3d_metrics_fetch` is a deprecated stub. Use `RSPQ_PROFILE=1` + `get_ticks()` around sections, or the debug overlay's FPS markers (`examples/99_testscene/debug_overlay.h:256-257`).