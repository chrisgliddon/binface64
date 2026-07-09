# Textures

**Audience:** LLM agents building games with Binface64. Every N64 texture format, TMEM fitting math, palette rules, mipmaps, and the big-texture streaming technique. Use this as the pre-flight reference before importing any image.
**Last reviewed:** 2026-07-07. Sources: vendored libdragon source (file:line cites), vendored tiny3d source, BF64 build pipeline source, n64brew wiki. Where sources disagree, the conservative number is picked and noted.
**Scope:** textures. For the full RDP/rdpq API surface, see `libdragon-tiny3d.md`. For display formats, see `display-and-video.md`. For the model format that consumes these textures, see `models-and-meshes.md`.

---

## Hard limits

| Resource | Hard limit | Source |
|---|---|---|
| TMEM (texture memory) | 4 KB (4096 B); 2 KB usable for RGBA32/CI4/CI8/YUV16 | `vendored/libdragon/src/rdpq/rdpq_tex.c:188,365,381,410` |
| RDP tile descriptors | 8 (TILE0–TILE7) | `vendored/libdragon/include/rdpq.h:254-263` |
| Max texture coord | 1023 px (10.2 fixed-point) | `vendored/libdragon/include/rdpq.h:468-469` |
| Palette address | 0x800 (2048) in TMEM | `vendored/libdragon/src/rdpq/rdpq_tex.c:32-33` |
| Palette colors | 256 max (×4 replication = 2048 B = half TMEM) | `vendored/libdragon/include/rdpq.h:604-607` |
| Max texels per `rdpq_load_block` | 2048 | `vendored/libdragon/include/rdpq.h:734-737` |
| Max TLUT load per call | 256 colors | `vendored/libdragon/include/rdpq.h:625-634` |
| Material texture slots | 2 per material (TILE0, TILE1) | `vendored/tiny3d/include/t3d/t3dmodel.h:63-64`, `n64/engine/include/renderer/material.h` |
| Material placeholders | 8 per MaterialInstance | `n64/engine/include/renderer/material.h:164` `MAX_SLOTS` |
| Max WxH that fits in TMEM | format-dependent — see §3 | `rdpq_tex.c:371-384` `rdpq_tex_can_upload` |
| mksprite input format | PNG only | `vendored/libdragon/tools/mksprite/mksprite.c:27-28,292-313` |
| mksprite LOD levels | up to 7 (+ 1 detail) | `vendored/libdragon/src/sprite_internal.h:26` `lods[7]` |
| BigTex pool size | 18 textures × 256×256 | `n64/engine/include/renderer/pipelineBigTex.h:20`, `n64/engine/src/renderer/bigtex/textures.cpp:11-13` |
| BigTex base RDRAM | 0x80400000 (1 MiB-aligned; Expansion Pak required) | `n64/engine/src/renderer/bigtex/bigtex.h:10-11`, `memory.cpp:59` |
| BCI block size | 4×4 pixels → 16 bytes on disk | `src/build/tools/bci.cpp:184-194` |

---

## 1. The BF64 texture pipeline

BF64 textures flow through three layers. Every claim below is engine-enforced unless tagged (hardware) or (best-practice).

### 1.1 Editor preview (no N64 conversion)

`Renderer::Texture` (`src/renderer/texture.cpp:14-107`) loads the source PNG via **SDL_image** (`IMG_Load`), converts to `SDL_PIXELFORMAT_BGRA32`, supports mono I4/I8 mode (R → alpha copy, `texture.cpp:29-45`), uploads to a host GPU texture. The editor shows the **source PNG**, not the converted N64 output. This is editor-only and does not affect what ships in the ROM.

### 1.2 Asset manager entry (`src/project/assetManager.cpp:101-185`)

The asset type is decided by file extension:

| Extension | FileType | Output ext | Converter |
|---|---|---|---|
| `.png` | IMAGE | `.sprite` | libdragon `mksprite` |
| `.bci.png` | IMAGE | `.bci` | internal `BCI::convertPNG` (`src/build/tools/bci.cpp`) |
| `.glb` / `.gltf` | MODEL_3D | `.t3dm` | tiny3d glTF importer (see `models-and-meshes.md`) |

**Auto-format hint:** if a `.png` filename contains a format token (e.g. `foo.i8.png`, `bar.rgba16.png`, `baz.ci4.png`) mksprite's AUTO mode parses the token out of the filename (`mksprite.c:317-333`). BF64 does not parse this itself — it just passes the filename to mksprite, which extracts the token.

**BCI auto-assignment:** `assetManager.cpp:165-168` — any PNG whose filename ends with `.bci.png` is force-assigned `format: 13` (BCI_256). The user does not need to set this manually.

### 1.3 Build path (`src/build/textureBuilder.cpp:17-54`)

For each IMAGE asset (non-excluded):
1. `compr = compression - 1; if compr < 0 compr = 1` — `ComprTypes::DEFAULT` (0) becomes level 1, not "default-aware" (`textureBuilder.cpp:34-35`, TODO comment).
2. If `format == BCI_256` → `BCI::convertPNG(path, outPath)` (internal, NOT mksprite).
3. Otherwise → `mksprite -c <compr> [-f <format>] -o <dir> <png>`.

**Engine-enforced GOTCHA:** the `compression` conf field is shifted by 1 before passing to mksprite's `-c`, so the editor's "Default" (0) becomes mksprite level 1. There is no way to ask mksprite for its actual default (`-1`) from the BF64 UI (`textureBuilder.cpp:34-35`).

**Engine-enforced GOTCHA:** BCI output is **non-deterministic** — `bci.cpp:46` uses `rand()` for k-means palette init with no `srand()` call. Two builds of the same `.bci.png` may produce byte-different `.bci` files, breaking content-addressable caching (`ARCHITECTURE.md` §3.4).

### 1.4 Runtime binding

The engine runtime material (`n64/engine/include/renderer/material.h`) holds up to two `Tile` slots (TILE0, TILE1). Each `Tile` references an asset index and stores UV wrap/clamp/mirror/scale. At draw time `Material::begin` (`material.cpp:172-208`) uploads via `rdpq_sprite_upload`, or runs a pre-recorded `rspq_block_t` for placeholders. See §6 below.

---

## 2. Every N64 texture format

### 2.1 Format enum — `vendored/libdragon/include/surface.h:105-118`

```c
typedef enum {
    FMT_NONE, FMT_RGBA16, FMT_RGBA32, FMT_YUV16,
    FMT_CI4, FMT_CI8, FMT_IA4, FMT_IA8, FMT_IA16,
    FMT_I4, FMT_I8,
} tex_format_t;
```

Encoded as `(rdp_fmt<<2)|rdp_size`; low 2 bits = size code (0→4bpp, 1→8bpp, 2→16bpp, 3→32bpp).

### 2.2 BF64 conf `format` integers — `src/utils/textureFormats.h:9-24`

BF64's `AssetConf.format` uses a separate 0-based enum that serializes into the `.conf`:

| Int | Name | libdragon equivalent |
|---|---|---|
| 0 | AUTO | (mksprite autodetects from PNG color type + filename token) |
| 1 | RGBA32 | FMT_RGBA32 |
| 2 | RGBA16 | FMT_RGBA16 |
| 3 | CI8 | FMT_CI8 |
| 4 | CI4 | FMT_CI4 |
| 5 | I8 | FMT_I8 |
| 6 | I4 | FMT_I4 |
| 7 | IA16 | FMT_IA16 |
| 8 | IA8 | FMT_IA8 |
| 9 | IA4 | FMT_IA4 |
| 10 | IHQ | mksprite-extended (I4 detail + RGBA16 main, subtractive blend) |
| 11 | SHQ | mksprite-extended (I4 mipmap + RGBA16, subtractive) |
| 12 | ZBUF | (encoded as IA16 on disk; for depth buffers, not color textures) |
| 13 | BCI_256 | BF64-specific 4×4-block 4-color compressed format (BigTex pipeline) |

### 2.3 Format reference

| Format | bpp | Bytes/texel | Palette | Color depth | Alpha | When to use |
|---|---|---|---|---|---|---|
| RGBA32 | 32 | 4 | — | 8-bit RGB | 8-bit | Avoid on N64 — uses 2 KB TMEM only; rare |
| RGBA16 | 16 | 2 | — | 5-bit RGB | 1-bit | Default for color textures needing alpha |
| YUV16 | 16 | 2 | — | YUYV 4:2:2 | none | Video / YUV blit mode only; not for game textures |
| CI8 | 8 | 1 | 256-color TLUT (2048 B in TMEM) | 5-bit RGB in output palette | treated opaque by BF64/mksprite | Best for photographic color textures |
| CI4 | 4 | ½ | 16-color TLUT (per-tile palette 0–15) | 5-bit RGB in output palette | treated opaque by BF64/mksprite | Best for small color palettes (16 colors) |
| IA16 | 16 | 2 | — | 8-bit intensity | 8-bit alpha | Gradients, smooth-height maps, font glyphs |
| IA8 | 8 | 1 | — | 4-bit intensity | 4-bit alpha | UI with low-bit alpha |
| IA4 | 4 | ½ | — | 3-bit intensity | 1-bit alpha | Tiny UI / bitmask |
| I8 | 8 | 1 | — | 8-bit intensity | (alpha = intensity) | Greyscale, lightmaps |
| I4 | 4 | ½ | — | 4-bit intensity | (alpha = intensity) | Tiny greyscale / lightmap |
| IHQ | — | — | — | I4 detail + RGBA16 main | mixed | "Fakes doubling TMEM" via subtractive detail blend (`mksprite.c:967-972`) |
| SHQ | — | — | — | I4 mipmap + RGBA16 | mixed | High-quality mipmap variant; very rare |
| BCI_256 | 1 ROM byte/pixel | — | 4 colors per 4×4 block | 5-bit RGB (RGBA5551) | 1-bit | BigTex streaming pipeline only — see §7 |

**GOTCHA (hardware):** RGBA32, CI4, CI8, YUV16 only get **2 KB of usable TMEM** because their data lives in TMEM's upper half / split / palette-aliased. The 2 KB restriction is hard-coded in four places in `rdpq_tex.c:188,365,381,410-411`. RGBA16, IA16, IA8, IA4, I8, I4 get the full 4 KB.

**GOTCHA (hardware):** CI4/CI8 have no real alpha — `mksprite.c:796-871` calls `exq_no_transparency()` because the RDP palette format doesn't support per-pixel alpha. Use RGBA16 or IA* for alpha-bearing textures.

### 2.4 AUTO autodetection (`mksprite.c:344-369`)

When the conf `format` is 0 (AUTO), mksprite picks the format from the PNG color type:

| PNG color type | AUTO → | Additional downgrade after color counting |
|---|---|---|
| `LCT_GREY` | I8 (if bitdepth > 4) else I4 | I4 if used_colors ≤ 16 |
| `LCT_GREY_ALPHA` | IA16 (bitdepth 8+) / IA8 (4) / IA4 (<4) | — |
| `LCT_PALETTE` | CI8 | CI4 if used_colors ≤ 16 |
| `LCT_RGB` / `LCT_RGBA` | RGBA16 | CI8 if used_colors ≤ 256; CI4 if ≤ 16 |

Filename tokens (e.g. `foo.i8.png`) are parsed as a fallback when no `-f` is given (`mksprite.c:317-333`). So `texture.i8.png` becomes I8 even if the PNG itself is RGBA.

---

## 3. TMEM fitting math (the lookup table)

### 3.1 The math — `rdpq_tex.c:371-384` `rdpq_tex_can_upload`

```c
bool rdpq_tex_can_upload(const surface_t *tex) {
    tex_format_t fmt = surface_get_format(tex);
    int width = tex->width;
    if (TEX_FORMAT_BITDEPTH(fmt) == 4) width = (width + 1) & ~1;            // 4bpp must be even width
    int pitch_shift = (fmt == FMT_RGBA32 || fmt == FMT_YUV16) ? 1 : 0;       // halve pitch for split formats
    int tmem_pitch = ROUND_UP(TEX_FORMAT_PIX2BYTES(fmt, width) >> pitch_shift, 8);  // 8-byte align
    int tmem_size = (fmt == FMT_RGBA32 || fmt == FMT_CI4 || fmt == FMT_CI8 || fmt == FMT_YUV16) ? 2048 : 4096;
    return tex->height * tmem_pitch <= tmem_size;
}
```

The assert in `texload_set_rect` (`rdpq_tex.c:189-190`) triggers if `height * tmem_pitch > tmem_size`. There is no graceful fallback at runtime — your ROM asserts.

### 3.2 TMEM fitting lookup table (max square WxH per format)

Computed using the exact libdragon math (8-byte pitch alignment, 2 KB split for restricted formats, even-width for 4bpp):

| Format | bpp | Image TMEM | **Max square WxH** | Max texels (byte budget ÷ bpp) | Notes |
|---|---|---|---|---|---|
| RGBA32 | 32 | 2048 B (split) | **32 × 32** | 1024 | Pitch halved; rare on N64 |
| RGBA16 | 16 | 4096 B | **44 × 44** | 2048 | The default |
| YUV16 | 16 | 2048 B (split) | **42 × 42** | 1024 | Video only |
| CI8 | 8 | 2048 B (+2 KB palette) | **42 × 42** | 2048 | Palette eats the other 2 KB |
| CI4 | 4 | 2048 B (+2 KB palette) | **64 × 64** | 4096 | Palette eats the other 2 KB |
| IA16 | 16 | 4096 B | **44 × 44** | 2048 | Same as RGBA16 |
| IA8 | 8 | 4096 B | **64 × 64** | 4096 | — |
| IA4 | 4 | 4096 B | **85 × 85** | 8192 | — |
| I8 | 8 | 4096 B | **64 × 64** | 4096 | — |
| I4 | 4 | 4096 B | **85 × 85** | 8192 | — |

**Engine-enforced:** the runtime `rdpq_tex_can_upload` check is the source of truth — exceeding these dimensions asserts at draw time. The editor does NOT pre-validate this; the agent must.

### 3.3 Useful non-square shapes that fit

For shapes that aren't square (the TMEM budget is `height × pitch ≤ budget`):

| Format | Max shapes |
|---|---|
| RGBA16 | 64 × 32, 128 × 16, 256 × 8 (max 2048 texels, 8B-aligned rows) |
| RGBA32 | 64 × 16, 32 × 32 (max 1024 texels) |
| CI8 | 128 × 16, 64 × 32, 256 × 8 (max 2048 texels) |
| CI4 | 128 × 16, 256 × 8, 64 × 32 (max 4096 texels) |
| I4 / IA4 | 256 × 32, 128 × 64, 64 × 128 (max 8192 texels) |
| I8 / IA8 | 256 × 16, 128 × 32, 64 × 64 (max 4096 texels) |

**Rule of thumb:** a 64×64 RGBA16 texture (8 KB raw) does NOT fit in 4 KB TMEM. Either switch to CI8/CI4, or use the BigTex pipeline (§7). This is the single most common N64 asset mistake.

### 3.4 The simplified "Max. Pixels" table (from `docs/manual/assets/images.md:27-37`)

The existing user-facing docs give a simplified theoretical max (byte budget only, no pitch-alignment):

| Format | Max. Pixels | Color-Depth | Alpha-Depth |
|---|---|---|---|
| RGBA32 | 1024 | 8 bit | 8 bit |
| RGBA16 | 2048 | 5 bit | 1 bit |
| CI8 | 2048 | 5 or 8 bit | 1 or 8 bit |
| CI4 | 4096 | 5 or 8 bit | 1 or 8 bit |
| IA8 | 4096 | 4 bit | 4 bit |
| I8 | 4096 | 8 bit | (alpha = color) |
| IA4 | 8192 | 3 bit | 1 bit |
| I4 | 8192 | 4 bit | (alpha = color) |
| YUV | 2048 | — | none |

The actual max square is smaller (see §3.2) because of 8-byte pitch alignment. Use §3.2 for validation; use this table only for quick mental math.

### 3.5 IHQ special case (`mksprite.c:967-972`)

IHQ "fakes doubling TMEM" by combining an I4 (or IA4) detail plane with a halved RGBA16 main plane, totaling ~8 KB of source data squeezed into 4 KB TMEM via subtractive blending. The check is:

```c
if (calc_tmem_usage(FMT_RGBA16, spr->images[0].width, spr->images[0].height) > 8192) {
    fprintf(stderr, "ERROR: image too big for IHQ mode (max is 64x64, or 128x32, or similar)\n");
}
```

IHQ requires dimensions that are multiples of 2, and at least one of W/H multiple of 4 (`mksprite.c:974-983`). Rarely used; consider it advanced.

---

## 4. mksprite CLI — the complete flag list

Source: `vendored/libdragon/tools/mksprite/mksprite.c:132-163` (usage), parser at `mksprite.c:1965-2267`.

### 4.1 Flags BF64 exposes

BF64 invokes mksprite as `mksprite -c <compr> [-f <format>] -o <dir> <png>` (`textureBuilder.cpp:41-46`). Only `-c` and `-f` are passed; everything below is BF64-inaccessible unless you bypass the editor.

| Flag | BF64 conf field | Values |
|---|---|---|
| `-f` / `--format` | `format` (int) | AUTO, RGBA32, RGBA16, YUV16, IA16, CI8, I8, IA8, CI4, I4, IA4, ZBUF, IHQ, SHQ |
| `-c` / `--compress` | `compression` (int, shifted by 1) | 0..3 |

### 4.2 Flags BF64 does NOT expose (advanced)

These require direct mksprite invocation or extending the editor:

| Flag | Effect |
|---|---|
| `-m` / `--mipmap <algo>` | `NONE` (default) or `BOX` — generate mipmaps |
| `-D` / `--dither <algo>` | `NONE` (default), `RANDOM`, `ORDERED` — Bayer 4×4 ordered or random dithering |
| `-g` / `--gamma` | Linear-space conversion; use with runtime VI `GAMMA_CORRECT` |
| `--texparms <x,s,r,m>` | Runtime sampling params (translate, scale, repeats, mirror) per S/T |
| `--detail [<img>[,<fmt>]][,<factor>]` | Detail texture (subtractive blend, default factor 0.5) |
| `--detail-texparms <...>` | Sampling params for the detail texture |
| `-L` / `--lossy <0..100>` | Lossy H.264 intra mode (Q100→CRF14, Q0→CRF36) |
| `-t` / `--tiles <w,h>` | Tile slicing (deprecated for rdpq) |
| `-d` / `--debug` | Dump each LOD as PNG |

**Best-practice:** BF64 agents should default to mksprite defaults. If you need mipmaps, dithering, or detail textures, you must either (a) extend the editor, or (b) run mksprite manually and place the resulting `.sprite` in `filesystem/`.

### 4.3 AUTO format downgrade rules

After the initial PNG-color-type pick (§2.4), mksprite counts unique colors and may downgrade (`mksprite.c:547-567`):
- LCT_PALETTE with `used_colors ≤ 16` → CI4 (saves 50%)
- LCT_GREY with `used_colors ≤ 16` → I4 (saves 50%)
- LCT_RGBA with `used_colors ≤ 256` → CI8; `≤ 16` → CI4 (huge savings — 4× or 8×)
- Lossy mode forces RGBA16

**Best-practice:** prefer AUTO and let mksprite pick. Manually forcing RGBA16 on a 16-color texture wastes 4× the ROM and TMEM.

---

## 5. Palette generation for CI4/CI8

### 5.1 Source PNG already palettized (`mksprite.c:494-517`)

Palette copied verbatim from the PNG's PLTE chunk. `used_colors` is the max index+1 actually referenced by pixels. If the requested color count (16 for CI4, 256 for CI8) is smaller than `used_colors`, the image is re-quantized via exoquant.

### 5.2 Source PNG is RGBA / non-palettized → exoquant (`mksprite.c:796-871`)

mksprite bundles the **exoquant** library (`exoquant.c`/`exoquant.h`):
- `exq_no_transparency` (CI4/CI8 have no real alpha)
- `numBitsPerChannel = 5` (forces RGB555 computation, matches RGBA16 channels)
- All LOD images are fed to `exq_feed` together so the **single palette covers every mipmap level**
- `exq_quantize_hq` — high-quality k-means quantizer
- Remap with optional dithering (NONE / RANDOM / ORDERED)

### 5.3 Palette storage on disk

The palette is written as `num_colors × uint16 RGB5551` (`mksprite.c:1654-1668`), 8-byte aligned. The `pal_used_colors` byte goes into `sprite_ext_t` (0 means 256, `sprite.c:182`).

### 5.4 Runtime palette load — `vendored/libdragon/src/rdpq/rdpq_sprite.c:17-37`

`sprite_upload_palette` calls `rdpq_tex_upload_tlut(pal, palidx*16, num_colors)`. The palette is stored in TMEM at `TMEM_PALETTE_ADDR = 0x800`, with **4× replication** (256 colors × 16-bit × 4 = 2048 B = half of TMEM, `rdpq.h:604-607`). CI4 can select one of 16 palettes (palidx 0–15) per tile via `rdpq_texparms_t.palette` (`rdpq_tex.h:42`).

**GOTCHA (hardware):** the 4× replication is wasteful — half of TMEM is always consumed by the palette for CI4/CI8, leaving only 2 KB for image data. This is why CI8 maxes at 42×42 not 64×64.

---

## 6. Runtime material/texture binding

### 6.1 The `Material::Tile` struct — `n64/engine/include/renderer/material.h:31-69`

```cpp
struct TileAxis {
    uint16_t offset;   // fx6.3 (stored × 64)
    uint16_t repeat;   // fx4.4 (stored × 16)
    int8_t  scale;     // raw scale_log (power-of-2, range [-5..10])
    int8_t  mirror;    // 0 / 1
    void setOffset(float offs) { offset = static_cast<uint16_t>(offs * 64.0f); }
    void setRepeat(float rep)  { repeat = static_cast<uint16_t>(rep * 16.0f); }
};

struct Tile {
    enum class PlaceholderType : uint8_t { NONE = 0, TILE = 1, FULL = 2 };
    uint16_t texAssetIdx;
    PlaceholderType phType;
    uint8_t  phIndex;
    TileAxis s, t;
};
```

### 6.2 Per-tile rdpq params — `material.cpp:25-38` `unpackTile`

```cpp
params.s.translate = tile.s.offset * (1.0f / 64.0f);
params.s.scale_log  = tile.s.scale;
params.s.repeats    = tile.s.repeat * (1.0f / 16.0f);
params.s.mirror     = tile.s.mirror;
```

UV wrap/clamp/mirror is set per-tile:
- `repeats > 1` → wrap/mirror enabled (`rdpq_tex.c:61-66`)
- `repeats × width < 1024` → clamp on (`rdpq_tex.c:76-79`)

### 6.3 Two texture slots, shared TMEM

`Material::begin` (`material.cpp:172-208`): if both FLAG_TEX0 and FLAG_TEX1 are set, wraps the upload in `rdpq_tex_multi_begin/end` so they share TMEM allocation. If TEX1 references the same asset as TEX0, calls `rdpq_tex_reuse` (0 extra TMEM bytes, `rdpq_tex.h:270`).

### 6.4 Placeholders (runtime-swappable textures)

Three types (`material.h:36-39`):
- `NONE` — direct asset upload via `rdpq_sprite_upload`.
- `TILE` — upload the asset, then run a pre-recorded block that adjusts tile size/coords (UV rect changes without re-uploading).
- `FULL` — skip asset upload; run a pre-recorded block that does the full upload. Built by `MaterialInstance::Placeholder::update()` (`material.cpp:52-84`), triple-buffered (`block[3]`) so a new block can record while the old one is in flight.

**Engine-enforced:** `MAX_SLOTS = 8` placeholders per MaterialInstance (`material.h:164`). The builder drops placeholders past index 7 and logs an error (`t3dmBuilder.cpp:36-44`). Exceeding 8 does NOT crash, but the texture binding silently goes missing.

---

## 7. The big-texture streaming technique (BigTex-256)

The BigTex pipeline (see `display-and-video.md` §4.2) lets you use textures far larger than 4 KB TMEM by storing them in RDRAM and decoding per-pixel via a custom RSP ucode. **It is a scene-level render pipeline option, NOT a per-texture flag.**

### 7.1 How it works

1. **Geometry pass** renders into a UV-index buffer (`fbs.uv[frameIdx]`, RGBA32) instead of a color buffer. Each pixel stores `(tex_index, U, V, coverage)` — packed as 24-bit address into the RDRAM texture pool + 8-bit coverage. The "color" rendered IS the UV coordinates via a 2-cycle combiner `(1, 0, TEX0, TEX1)` with PRIM as the texture-base high byte.
2. **Post pass** (`pipelineBigTex.cpp:108-144`) reads the UV-index buffer and writes the actual color framebuffer by looking up each pixel's texture in the RDRAM pool. Done in 16 slices (`SHADE_BLEND_SLICES=16`); every 4th slice uses the RSP ucode (`rsp_bigtex.S` `FX_ApplyTex`), the other 3 use CPU MIPS (`applyTexture.S` `BigTex_applyTexture`).
3. **Texture pool** is 18 textures × 256×256, stored at fixed RDRAM base `0x80400000` (1 MiB-aligned). Each 256×256 BCI-encoded texture = 64 KiB; 18 of them = 1.125 MiB. **Expansion Pak required** (`memory.cpp:59`).
4. **Triple-buffered** UV/shade/color (`frameIdx = (frameIdx+1)%3`) so post-processing of frame N-1 runs concurrently with the RDP geometry pass of frame N.

### 7.2 The BCI_256 format — `src/build/tools/bci.cpp`

A 4×4 pixel block is encoded as **4 RGBA5551 colors + 16 × 2-bit indices** = 8 + 4 = 12 bytes of payload, but written as 16 bytes on disk (8 palette + 8 index word, upper 33 bits of the index word unused) — `bci.cpp:184-194`.

**Algorithm:** k-means clustering with 4 random initial centroids (`bci.cpp:87-102`). Up to 100 iterations. **Non-deterministic** — uses `rand()` with no `srand()` (`bci.cpp:46`); the same PNG can produce different BCI outputs across builds.

**First-index constraint** (`bci.cpp:171-182`): the runtime decoder requires index 0 to be at pixel 15 (or 0b00/0b01). If `indices[15] != 0`, the colors and indices are swapped.

**Total disk size:** `(W/4) × (H/4) × 16 bytes`. For 256×256: 64 × 64 × 16 = **65536 B = 64 KiB** per texture.

### 7.3 When to use BigTex

- Textures larger than 4 KB TMEM (e.g. 256×256 RGBA — impossible normally)
- High-res lightmaps, skyboxes, baked AO
- Up to 18 unique large textures per scene
- **Requires Expansion Pak** (1.125 MiB pool + framebuffers above 0x80500000)
- **Hard-locked to 320×240 RGBA16** (`pipelineBigTex.cpp:33-35`)
- **Cannot clear color** (`pipelineBigTex.cpp:75-77`)
- Set `renderPipeline: 2` (HiRes-Tex 256x) in `SceneConf`; editor forces 320×240 RGBA16 (`sceneInspector.cpp:41-49`)

### 7.4 How textures get into the pool

`bigtex.cpp:15-56` `patchT3DM`: iterates model objects; for each material tile, if `isPlaceholder()` calls `reserveTexture()` (slot filled at runtime), else `addTexture(path)` (loads BCI file from ROM into pool). The texture index is encoded into the prim color's R channel (high byte of RDRAM address), so the 2-cycle combiner in the geometry pass produces `(texBaseHiByte << 16) | UV` = full 24-bit pool address.

**Engine-enforced:** `.bci.png` extension auto-assigns `format: 13` (BCI_256) in the asset manager. You don't need to set it manually.

---

## 8. Mipmap cost

### 8.1 Algorithm — `mksprite.c:654-759` `spritemaker_calc_lods`

Only `MIPMAP_ALGO_BOX` is implemented (asserted at `mksprite.c:656`). Box filter: 2×2 average per format (RGBA / GREY / GREY_ALPHA, `mksprite.c:681-740`).

Generates half-W × half-H images, up to `MAX_IMAGES=8` levels (one fewer if detail is enabled). Stops when `mw<4 || mh<4` (`mksprite.c:672`).

**Per-LOD TMEM budget check** (`mksprite.c:673-678`): accumulates `tmem_usage` per level; stops if it exceeds 4096 B. The palette (2048 B flat for CI4/CI8) is counted once at the start via `spritemaker_fit_tmem` (`mksprite.c:602-621`).

### 8.2 Cost formula

Each LOD has ¼ the pixels of the previous (½ W × ½ H). Full chain cost = `B × Σ(1/4ⁿ) = B × 4/3 ≈ 1.333 × B` (geometric series). In practice the chain truncates when `tmem_usage > 4096`.

| Base texture | Full mip chain (raw bytes) |
|---|---|
| 32×32 RGBA16 (2 KB) | 2048 + 512 + 128 + 32 + 8 ≈ 2728 B |
| 44×44 RGBA16 (3.8 KB) | ~3872 + 968 + 242 ≈ 5082 B → truncated at 4096 |
| 64×64 I4 (2 KB) | 2048 + 512 + 128 + 32 + 8 + 2 + 0.5 ≈ 2730 B |

### 8.3 Runtime mipmap upload — `rdpq_sprite.c:88-114`

LODs occupy consecutive tiles (TILE0=base, TILE1=LOD1, …). Each level's `scale_log` increments by 1 (texture appears 2× smaller). Up to 7 LODs (8 tiles total, fits in TILE0–TILE7). Render mode set via `rdpq_mode_mipmap(MIPMAP_INTERPOLATE, num_mipmaps)`.

**GOTCHA:** mipmaps cost 8× the tile descriptors of a single texture. With 8 tile descriptors total (TILE0–TILE7), a single fully-mipmapped texture consumes all of them. Multi-texture materials (2 slots) and mipmaps compete for tile descriptors.

---

## 9. The `.sprite` file format

### 9.1 Base header — `vendored/libdragon/include/sprite.h:40-61`

```c
typedef struct sprite_s {
    uint16_t width;
    uint16_t height;
    uint8_t  bitdepth  __attribute__((deprecated));
    union { uint8_t format; uint8_t flags; };  // low 5 bits = tex_format_t
    uint8_t  hslices;
    uint8_t  vslices;
    uint32_t data[0];
} sprite_t;
```

8 bytes header, immediately followed by image 0 pixel data. Flag bits (`sprite.h:87-90`):
- `SPRITE_FLAGS_TEXFORMAT 0x1F` — low 5 bits = tex_format_t
- `SPRITE_FLAGS_OWNEDBUFFER 0x20` — buffer must be freed
- `SPRITE_FLAGS_NODATA 0x40` — no data in base section
- `SPRITE_FLAGS_EXT 0x80` — sprite contains extended info (new format)

mksprite always sets `SPRITE_FLAGS_EXT`.

### 9.2 Extended header — `vendored/libdragon/src/sprite_internal.h:11-64`

128 bytes, written immediately after image 0's pixel data (8-byte aligned):

```c
#define SPRITE_EXT_VERSION 6
typedef struct sprite_ext_s {
    uint16_t size;              // 128 (for forward compat)
    uint16_t version;            // 6
    uint32_t pal_file_pos;       // palette offset in file
    struct sprite_lod_s { uint16_t width, height; uint32_t fmt_file_pos; } lods[7];
    struct { uint16_t flags; uint8_t pal_used_colors; uint8_t padding; };
    struct texparms_s { struct { float translate, repeats; int16_t scale_log; bool mirror; int8_t padding; } s, t; } texparms;
    struct detail_s { struct texparms_s texparms; float blend_factor; bool use_main_texture; uint8_t padding[3]; } detail;
    uint32_t data_ptr;
} sprite_ext_t;
_Static_assert(sizeof(sprite_ext_t) == 128, "invalid sizeof(sprite_ext_t)");
```

### 9.3 On-disk layout

```
0    : sprite_t header (8 B)
8    : image 0 pixel data (format-specific; CI4 packed 2/byte, RGBA16 as RGB5551, etc.)
8+N  : 8-align
     : sprite_ext_t (128 B, version 6)
     : 8-align
     : [image 1..7 pixel data, each 8-aligned, fmt from lods[i-1].fmt_file_pos>>24]
     : 8-align
     : [palette: num_colors × uint16 RGB5551, 8-aligned]  (only if CI4/CI8)
```

LOD offsets and palette offset are back-patched after subsequent sections are written (`mksprite.c:1440-1671`).

### 9.4 Lossy sprites — NOT loadable at runtime

`sprite_load_buf` (`sprite.c:67-76`) rejects the `"LSPR"` magic with `"lossy sprite support not implemented"`. Lossy mksprite output (via `-L`) cannot be used in a shipping ROM. Stick to lossless.

---

## 10. Real-world texture usage (jam25 example)

jam25 (a complete 3D platformer) uses these texture formats in its `.conf` files:

| Conf `format` value | Format | Use case | Example files |
|---|---|---|---|
| 13 (BCI_256) | BCI_256 | BigTex pipeline (planets, skybox faces, lightmaps) | `planet00..04.bci.png`, `nx/ny/nz/px/py/pz.bci.png`, `lightmap00..03.bci.png` |
| 8 (IA8) | IA8 | UI elements with alpha | `titlescreen_text.rgba16.png` (misleading name), `tree.png`, `ptx/coinPart.png` |
| 6 (I4) | I4 | Retro tilesets, particles | `retro/tileset00.png`, `ptx/swirl.png`, `ptx/coin.png` |
| 5 (I8) | I8 | Greyscale / colored textures without alpha | `ui/logoTiny3d.png`, `objects/goal.png`, `noiseClouds.png`, `lab/tileWall.png` |
| 4 (CI4) | CI4 | 16-color textures | `mapPaper/card03.ci4.png` |
| 2 (RGBA16) | RGBA16 | Color textures with alpha | `titlescreen_text_2.png`, `testMap/grass02_1_128_32.png` |

jam25 BCI texture sizes: ~78–167 KB each (256×256 RGBA5551 source PNGs), 17 files totaling 1.95 MiB of source PNG.

jam25 total asset footprint (source PNGs): 19.25 MiB across 143 files. The converted `.sprite`/`.bci`/`.t3dm`/`.wav64`/`.xm64` in `filesystem/` is smaller after mksprite/audioconv64 compression.

---

## Implications for BF64 agents

1. **TMEM is 4 KB. This is the single most important N64 constraint.** A 64×64 RGBA16 texture (8 KB raw) does NOT fit. Use the §3.2 lookup table before importing any texture. Exceeding the max square asserts at runtime — the editor does not pre-validate.
2. **Prefer AUTO format.** mksprite autodetects from PNG color type and downgrades aggressively (RGBA → CI8 if ≤256 colors, CI8 → CI4 if ≤16 colors). Manual format forcing usually wastes ROM/TMEM.
3. **Use CI8 for color textures.** 256-color palette covers most game art; 1 byte/texel + 2 KB palette = 42×42 max square (vs 32×32 RGBA16). For 16-color art, CI4 doubles that to 64×64.
4. **Use I8/I4 for greyscale.** Lightmaps, heightmaps, fonts: I8 (8-bit) or I4 (4-bit). No palette cost, 64×64 / 85×85 max square.
5. **Use RGBA16 only when you need per-pixel alpha AND >256 colors.** Max 44×44. For UI with alpha but limited colors, IA8 (64×64) or IA4 (85×85) is better.
6. **Never use RGBA32 for game textures.** 32-bit color uses 2 KB TMEM (split halves), maxes at 32×32, and the AA path is more corruption-prone (`display-and-video.md`). Reserve for framebuffer format only.
7. **Mipmaps cost +33% but cost 8× the tile descriptors.** A fully-mipmapped texture uses TILE0–TILE7 (all 8). With 2 texture slots per material, mipmaps + multi-texture can't coexist. Use mipmaps only on the primary texture slot.
8. **BigTex is the escape hatch for large textures.** Up to 18 × 256×256 BCI textures in RDRAM. Requires Expansion Pak, hard-locked to 320×240 RGBA16, can't clear color. Set `renderPipeline: 2`. Use `.bci.png` extension for auto-BCI_256 assignment.
9. **BCI_256 output is non-deterministic.** `bci.cpp:46` uses `rand()` with no seed. Same input → different output across builds. Don't content-hash `.bci` files; don't rely on byte-identical rebuilds.
10. **Two texture slots per material, 8 placeholders per instance.** TEX0 + TEX1 share TMEM via `rdpq_tex_multi_begin`. Placeholders (runtime-swappable textures) are capped at 8 per MaterialInstance — exceeding silently drops the binding.
11. **Filename tokens override format.** `foo.i8.png` forces I8 even if the PNG is RGBA. Use this to lock formats that AUTO would get wrong. The token is parsed by mksprite, not BF64.
12. **UVs are pixel coordinates, not normalized.** A 64×64 texture has UVs 0-64, not 0-1. This is a tiny3d convention because t3d doesn't know texture dimensions at draw time (see `libdragon-tiny3d.md`).
