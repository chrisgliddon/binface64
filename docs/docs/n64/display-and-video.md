# Display & Video

**Audience:** LLM agents building games with Binface64. Resolutions, framebuffer formats, VI filtering, NTSC/PAL, and Pyrite64's HDR+Bloom and BigTex pipelines.
**Last reviewed:** 2026-07-06. Sources: vendored libdragon source (file:line cites), Pyrite64 ARCHITECTURE.md.
**Scope:** the display/video subsystem. For hardware specs, see `hardware.md`. For the RDP/rdpq API, see `libdragon-tiny3d.md`.

---

## Hard limits

| Resource | Hard limit | Source |
|---|---|---|
| Max framebuffer | 800×720 px | `vendored/libdragon/src/display.c:363-364` |
| 16bpp width alignment | `%4==0` | `display.c:366` |
| 32bpp width alignment | `%2==0` | `display.c:368` |
| NTSC visible lines | 525 (V_TOTAL 526) | `vendored/libdragon/src/vi.c:32` |
| PAL visible lines | 625 (V_TOTAL 626) | `vendored/libdragon/src/vi.c:44` |
| NTSC output area (default) | (108,35)–(748,515) → 640×480 | `vi.c:35-38` |
| PAL output area (default) | (128,45)–(768,621) → 640×576 | `vi.c:47-50` |
| Framebuffer bit depths | 16bpp (RGBA5551), 32bpp (RGBA8888) | `display.h:179-185` |
| Valid RDP render target formats | FMT_RGBA16, FMT_RGBA32, FMT_I8, FMT_CI8 | `rdpq.h:1129-1131,1200-1202` |
| Z-buffer format | FMT_RGBA16 (16-bit) | `display.c:606` |

---

## 1. Resolutions

**Predefined** (`vendored/libdragon/include/display.h:164-174`):
- `RESOLUTION_256x240` — 4:3, non-interlaced.
- `RESOLUTION_320x240` — 4:3, non-interlaced. **The most common N64 resolution.** Pyrite64's Default, HDR+Bloom, and BigTex pipelines all use this.
- `RESOLUTION_512x240` — 4:3, non-interlaced.
- `RESOLUTION_640x240` — 4:3, non-interlaced.
- `RESOLUTION_512x480` — 4:3, `INTERLACE_HALF`.
- `RESOLUTION_640x480` — 4:3, `INTERLACE_HALF`.

**Custom:** `display_init(res, bitdepth, buffers, gamma, aa, filter_options)` (`display.h`). Width 2–800, height 1–720. 16bpp width must be `%4==0`, 32bpp `%2==0`.

**Interlace modes** (`display.h:96-103`):
- `INTERLACE_OFF` — progressive scan (240p).
- `INTERLACE_HALF` — swap on odd & even fields (480i).
- `INTERLACE_FULL` — swap only on even fields.

**GOTCHA:** `vi_v_total % 2 == 1` is asserted for progressive scan (`vi.c:852`).

---

## 2. Framebuffer formats

| Format | bpp | RDP fmt/size | Valid render target? | Notes |
|---|---|---|---|---|
| `FMT_RGBA16` | 16 | (0,2) | ✅ | RGBA5551; the default; VI `VI_CTRL_TYPE_16_BPP` |
| `FMT_RGBA32` | 32 | (0,3) | ✅ | RGBA8888; VI `VI_CTRL_TYPE_32_BPP`; uses 2 KB TMEM for textures |
| `FMT_I8` | 8 | (4,1) | ✅ | intensity-only; used for some 2D |
| `FMT_CI8` | 8 | (2,1) | ✅ | 8-bit paletted; accepted by `rdpq_set_color_image_raw` (`rdpq.h:1200-1202`) |
| `FMT_YUV16` | 16 | (1,2) | ❌ | YUYV 4:2:2 interleaved; for YUV blit mode |
| `FMT_CI4` | 4 | (2,0) | ❌ | 4-bit paletted |
| `FMT_IA4` | 4 | (3,0) | ❌ | 3-bit I + 1-bit A |
| `FMT_IA8` | 8 | (3,1) | ❌ | 4-bit I + 4-bit A |
| `FMT_IA16` | 16 | (3,2) | ❌ | 8-bit I + 8-bit A |
| `FMT_I4` | 4 | (4,0) | ❌ | 4-bit intensity |

**`surface_t`** (`surface.h:139-146`): `{flags, width, height, stride, buffer}`. `surface_alloc` gives 64-byte alignment for RDP framebuffer use (`surface.h:211`).

---

## 3. VI modes & filtering

**TV types** (`tv_type_t`, `n64sys.h:621-625`): `TV_PAL=0`, `TV_NTSC=1`, `TV_MPAL=2`. Plus non-standard `VI_TIMING_PAL60` (`vi.c:65-75`) — 60 Hz PAL, unsupported by some upscalers/grabbers (`vi.h:446-464`).

**VI clocks:** NTSC 48,681,818 Hz, PAL 49,656,530 Hz, MPAL 48,628,322 Hz (`vi.c:24-28`). Same clocks drive the audio DAC.

**AA / filter options** (`display.h:218-238`, `vi.h:340-402`):
- `FILTERS_DISABLED` — raw, no resampling.
- `FILTERS_RESAMPLE` — bilinear resampling.
- `FILTERS_DEDITHER` — 16→32 reconstruct.
- `FILTERS_RESAMPLE_ANTIALIAS` — bilinear + AA + divot.
- `FILTERS_RESAMPLE_ANTIALIAS_DEDITHER` — all on.

**VI AA modes** (`vi.h:340-402`):
- `VI_AA_MODE_NONE` — resampling OFF.
- `VI_AA_MODE_RESAMPLE` — bilinear.
- `VI_AA_MODE_RESAMPLE_FETCH_NEEDED` — AA filter, fetch on demand.
- `VI_AA_MODE_RESAMPLE_FETCH_ALWAYS` — AA filter, always fetch. **GOTCHA:** broken in 32bpp — 32bpp AA falls back to `FETCH_NEEDED`, more corruption-prone (`display.c:314-321`).

**Divot filter** (`vi.h:955-967`), **dedither** (`vi.h:969-983`, incompatible with `RESAMPLE`).

**GOTCHA:** `FILTERS_DISABLED` + 16bpp + width ≤ 320 hits a hardware bug on NTSC. libdragon applies a workaround by forcing `VI_X_SCALE = 0x201` instead of `0x200` (`display.c:343-353`). The canonical 320px mode is silently patched at runtime.

**GOTCHA:** `FILTERS_DEDITHER` requires `width > 320` (`display.c:298`).

**Gamma** (`display.h:188-206`): `GAMMA_NONE=0`, `GAMMA_CORRECT=VI_GAMMA_ENABLE=(1<<2)`, `GAMMA_CORRECT_DITHER=(1<<2)|(1<<3)`. Recommended with 32bpp + linear-space assets (`graphics.h:99-136` `LINEAR16`/`LINEAR32`).

---

## 4. Pyrite64 render pipelines

Pyrite64's `SceneConf::Pipeline` enum (`n64/engine/include/scene/scene.h:36-41`, see `ARCHITECTURE.md` §2.4):

| Value | Pipeline | Resolution | Format | Notes |
|---|---|---|---|---|
| 0 | **Default** | configurable (320×240 default) | RGBA16 or RGBA32 (`FLAG_SCR_32BIT`) | per-frame depth buffer via `Mem::allocDepthBuffer` |
| 1 | **HDR+Bloom** | **320×240 fixed** (asserts, `pipelineHDRBloom.cpp:34-36`) | **RGBA16 fixed** | custom RSP ucode `RspHDR` + `PostProcess`; ping-pongs `frameIdx` across 3 buffers; config: `blurSteps=4, hdrFactor=2.0, bloomThreshold=0.2` |
| 2 | **BigTex-256** | **320×240 fixed** | **RGBA16 fixed** | custom RSP ucode for large-texture streaming; 18-texture pool; **cannot clear color** (asserts `FLAG_CLR_COLOR` NOT set, `pipelineBigTex.cpp:76`) |

**GOTCHA:** HDR+Bloom and BigTex are **hard-locked to 320×240 RGBA16** by their custom RSP ucodes. The editor must enforce these or the ROM asserts at runtime. Pyrite64's `sceneInspector.cpp:41-49` forces 320×240 RGBA16 when pipeline 1 or 2 is selected.

### 4.1 HDR+Bloom pipeline

`n64/engine/src/renderer/hdr/` (`pipelineHDRBloom.cpp`, `rspHDR.cpp`, `rsp_hdr.S`/`rsp_hdr.rspl`, `postProcess.cpp`):
- Renders the scene into an HDR color buffer.
- `PostProcess` keeps HDR + blur A/B surfaces; `beginFrame`/`endFrame`/`applyEffects`.
- Ping-pongs `frameIdx` across `BUFF_COUNT=3` so post-processing of frame N-1 happens concurrently with rendering frame N.
- Bloom composite: `applyEffects(*fb)` blends HDR + blur into the final framebuffer.
- Config: `blurSteps=4, hdrFactor=2.0, bloomThreshold=0.2` (`pipelineHDRBloom.cpp:20-26`).

### 4.2 BigTex-256 pipeline

`n64/engine/src/renderer/bigtex/` (`pipelineBigTex.cpp`, `bigtex.cpp`, `textures.cpp`, `uvTexture.cpp`, `memory.cpp`, `applyTexture.S`, `rsp_bigtex.S`):
- A **scene-level render pipeline option**, not a per-texture flag. Enables streaming of textures > 4 KB TMEM.
- 18-texture pool (`BigTex::Textures textures{18}`, `bigtex/textures.h:13-33`) for high-res textures too large for TMEM.
- Renders geometry into a UV-index buffer (`fbs.uv[frameIdx]`) + shade buffer, then `draw()` blends slices (`SHADE_BLEND_SLICES=16`) back into the color fb via custom RSP + CPU code (`BigTex_applyTexture`, `extern "C"` at `pipelineBigTex.cpp:16-19`).
- 3 draw modes: DEF/UV/MAT.
- Triple-buffers UV/shade/color (`frameIdx = (frameIdx+1)%3`).
- **GOTCHA:** asserts `FLAG_CLR_COLOR` is NOT set — BigTex can't clear color.

**How it differs from BCI_256:** BCI_256 is a *compressed still-image texture format* (4×4-block 4-color palette, `bci.cpp`). BigTex is a *render pipeline mode* that streams large textures through RDRAM by indexing rather than reloading TMEM. They're orthogonal.

---

## 5. VI swapchain (Pyrite64 runtime)

`n64/engine/src/vi/swapChain.cpp` (see `ARCHITECTURE.md` §2.4):
- **Triple-buffered** (`FB_COUNT=3`, `swapChain.h:13`).
- VI chases the RDP: VBlank handler pops next finished buffer from FIFO and calls `vi_show`.
- `nextFrame()` blocks until a framebuffer is free, picks the free index, computes smoothed delta-time from 6-sample RingBuffer (clamped to 1/5 s), calls `drawTask`.
- **GOTCHA:** 200 ms RSP-timeout escape hatch forces a free buffer (`swapChain.cpp:132-137`) — fallback for RSP hangs; if hit, may show a torn frame.

---

## Practical budgets

| Configuration | Framebuffer RAM (×3 triple-buf) | Z-buffer | Notes |
|---|---|---|---|
| 320×240 RGBA16 | 153.6 KiB × 3 = 461 KiB | 153.6 KiB | the default; fits comfortably in 4 MiB |
| 320×240 RGBA32 | 307.2 KiB × 3 = 922 KiB | 153.6 KiB | uses 2 KB TMEM for textures; AA falls back to FETCH_NEEDED |
| 640×480 RGBA16 | 614.4 KiB × 3 = 1.8 MiB | 614.4 KiB | interlaced; tight on 4 MiB |
| 640×480 RGBA32 | 1.2 MiB × 3 = 3.7 MiB | 614.4 KiB | does NOT fit in 4 MiB with any assets |

**Rule of thumb:** use 320×240 RGBA16 for 3D games. It's the only mode the HDR+Bloom and BigTex pipelines support, and it leaves the most RAM for assets.

---

## Implications for BF64 agents

1. **320×240 RGBA16 is the default for a reason.** It's the only resolution HDR+Bloom and BigTex support, and it leaves the most RDRAM for assets. Don't use 640×480 unless you're doing 2D-only or have very few assets.
2. **HDR+Bloom and BigTex are 320×240 RGBA16 only.** The editor enforces this (`sceneInspector.cpp:41-49`), but an agent generating scene JSON must set `fbWidth=320, fbHeight=240, fbFormat=0` when `renderPipeline` is 1 or 2.
3. **BigTex can't clear color.** If you use `renderPipeline=2`, do NOT set `doClearColor=true` in SceneConf — the ROM will assert.
4. **32bpp AA is more corruption-prone.** `FETCH_ALWAYS` is broken in 32bpp; falls back to `FETCH_NEEDED`. If you need 32bpp for color precision, accept some AA degradation or use gamma correction instead.
5. **The 320px + FILTERS_DISABLED + 16bpp combo is silently patched.** libdragon forces `VI_X_SCALE = 0x201` (`display.c:343-353`). You don't need to do anything, but it's why this common mode works.
6. **Triple-buffering means a stall delays two frames.** A stalled RDP shows up two frames later. The 200ms RSP-timeout escape hatch is a fallback, not normal flow — if it fires, you have a bug.
7. **Z-buffer is 16-bit.** Z-precision is limited; Pyrite64's `t3d_viewport_set_perspective` docs say far plane "should be >=40 to avoid depth-precision issues" (`t3d.h:268,281,294`). Use near=1-4, far=100-1000 typical.
8. **Gamma is a hardware unit.** `GAMMA_CORRECT` enables the VI gamma unit for linear-space assets. `GAMMA_CORRECT_DITHER` adds dither. No CPU cost. Use with 32bpp + linear assets for best quality.
9. **PAL60 is non-standard.** Some upscalers/grabbers don't support it (`vi.h:446-464`). Default to NTSC or PAL unless you know the target display.
10. **The VI runs concurrently with the RDP.** You don't pay VI time inside the frame budget, but the VI is fetching the framebuffer every scanline — that's RDRAM bandwidth the RDP and CPU can't use. Higher resolutions = more VI bandwidth = less for everything else.