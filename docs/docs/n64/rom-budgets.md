# ROM Budgets

**Audience:** LLM agents building games with Binface64. Cart sizes, compression, asset packing in BF64, and a worked example budget for a small 3D game. Use this before estimating any game's ROM footprint.
**Last reviewed:** 2026-07-07. Sources: vendored libdragon source (file:line cites), BF64 build pipeline source, n64brew wiki. Where sources disagree, the conservative number is picked and noted.
**Scope:** ROM/cart budgets. For texture formats, see `textures.md`. For model formats, see `models-and-meshes.md`. For audio, see `audio-assets.md`. For the filesystem, see `libdragon-tiny3d.md` §1.5.

---

## Hard limits

| Resource | Hard limit | Source |
|---|---|---|
| Standard cart sizes (real hardware) | 4, 8, 12, 16, 32, 64 MiB | [n64brew Game Pak](https://n64brew.dev/wiki/Game_Pak) |
| Max DFS file size | 256 MiB | `vendored/libdragon/include/dragonfs.h:33` |
| Max DFS simultaneous open files | 4 | `dragonfs.h:35` |
| Max DFS directory depth | 100 | `dragonfs.h:42` |
| Max DFS filename length | 243 chars | `dragonfs.h:69,74` |
| DFS file data alignment | 2-byte (NOT 4-byte) | `dragonfs.h:258-259` |
| rompak TOC max entries | 15 (16-byte aligned, 1024 B TOC at PI offset 0x1000) | `vendored/libdragon/tools/n64tool.c:82-85` |
| ROM size multiple of 4 (n64tool) | enforced | `vendored/libdragon/tools/n64tool.c:440-444` |
| ROM size multiple of 512 (recommended) | 64drive warning | `n64tool.c:446-448` |
| DFS compression | **NONE** — use `asset_load`/`asset_fopen` with `mkasset -c <level>` | `dragonfs.h:44-45` |
| Asset compression levels | 0=none, 1=LZ4 (default), 2=APLib, 3=Shrinkler | `vendored/libdragon/src/asset.c:47-92` |
| `asset_fopen` streaming window | 2–256 KiB (default 4 KiB) | `assetcomp.h:21` |
| Linker ELF cap | 8 MiB − 64 KiB stack − 1 KiB low mem | `vendored/libdragon/n64.ld:197` |

---

## 1. Cart sizes (real hardware)

The N64 Game Pak uses mask ROM or flash. Standard production sizes ([n64brew Game Pak](https://n64brew.dev/wiki/Game_Pak)):

| Size | Common games |
|---|---|
| 4 MiB | Early titles (Super Mario 64, Wave Race 64) |
| 8 MiB | Most early-mid titles |
| 12 MiB | Mid-era titles |
| 16 MiB | Common late-era |
| 32 MiB | Late-era (Resident Evil 2, Conker's Bad Fur Day) |
| 64 MiB | Theoretical max; very few titles |

**Best-practice:** target 8 MiB for a small game, 16 MiB for a medium game, 32 MiB for a large game. 64 MiB is rare and may not be flashcart-friendly on older hardware. Most BF64 games will fit comfortably in 8–16 MiB.

**GOTCHA (hardware):** flashcarts (64drive, EverDrive64, SummerCart64) have their own max ROM sizes — typically 64 MiB for 64drive, 64 MiB for EverDrive64 X7, 128 MiB for SummerCart64. Real cart ROM is the binding constraint for retail.

---

## 2. What the packer does

### 2.1 Build flow — `src/build/projectBuilder.cpp:56-262` `Build::buildProject`

1. Load project; resolve `N64_INST` from conf or env.
2. Create `filesystem/p64/` dir. Register every non-excluded asset in `sceneCtx.assetList` + `assetFileMap` (`projectBuilder.cpp:99-111`).
3. Detect asset-list changes vs `filesystem/p64/fileList.txt`; if changed, wipe `.t3dm`/`.pf` + `filesystem/p64/` + code build.
4. Build node graphs → `src/p64/<uuid>.cpp` + `filesystem/.../<name>.pg`.
5. Build scripts → `src/p64/scriptTable.cpp`, `src/p64/globalScriptTable.cpp`.
6. Build scenes → binary scene/object files; generate `src/p64/sceneTable.h` + `.cpp`.
7. Build assets in order: 3D Model (`t3dmBuilder`), Font, Texture, Audio, **Prefab last** (`projectBuilder.cpp:29-36,191-197`). Each writes into `filesystem/`.
8. Generate `src/p64/assetTable.h` from `assetFileMap`.
9. Write asset table binary `filesystem/p64/a` (`projectBuilder.cpp:206-218`): u32 count, then per-asset (offset, type+flags packed), then concatenated `romPath` strings.
10. Generate `Makefile` from `data/build/baseMakefile.mk`.
11. Write `filesystem/p64/conf` (u32 sceneIdOnBoot, u32 sceneIdOnReset, u16 autoLoadFontUUIDs[16]).
12. Run `make -C "<path>" -j8`.

### 2.2 The Makefile — `data/build/baseMakefile.mk`

The generated Makefile:
1. Includes `$(N64_INST)/include/n64.mk` (libdragon) and `t3d.mk` (tiny3d).
2. Compiles `src/*.cpp` + `src/p64/*.cpp` + `src/user/*.cpp` + `USER_CODE_DIRS` into `.o`.
3. Builds `engine/build/engine.a` (sub-make).
4. Links into `.elf`.
5. `mkdfs` packs `filesystem/` into a DFS file (`build/<romName>.dfs`).
6. `n64tool` packs the ELF + DFS + TOC + header into `<romName>.z64`.

### 2.3 n64tool — `vendored/libdragon/tools/n64tool.c`

Flags (`n64.mk:87-141`):
- `--toc` — insert a rompak TOC at PI offset 0x1000 (after 4096-byte IPL3 header).
- `--title <name>` — ROM title.
- `--header <file>` — custom IPL3 header (else default_ipl3, `n64tool.c:645-649,667`).
- `--category / --region` — ROM header category/region.
- `--size <N>` — declare ROM size; pads with zeros if larger than content. If unset, no padding (`n64tool.c:757-763`). Must be a multiple of 4 (else error, `n64tool.c:440-444`); warning if not a multiple of 512 (64drive compat, `n64tool.c:446-448`).
- `--padding <N>` — bytes of padding after content (default 0 if metadata used, else a computed amount).
- `--align <N>` — alignment for subsequent files.
- `--offset <N>` — reserve space before next file.
- `--byteswap` — swap bytes (for different ROM endianness).

**GOTCHA:** `n64tool` does NOT compress. It only packs. Compression is the asset's responsibility (via `mkasset -c <level>` per-asset, NOT DFS-wide).

### 2.4 The final ROM

`<romName>.z64` in the project root (cleaned before build, `globalActions.cpp:157-158`; removed on `clean`, `projectBuilder.cpp:269`). Standard N64 `.z64` (big-endian, libdragon-generated via `n64.mk`).

ROM header flags come from `buildRomHeaderFlags` (`romMetaBuilder.cpp:85-117`): `N64_ROM_CATEGORY`, `N64_ROM_REGION`, `N64_ROM_SAVETYPE`, `N64_ROM_REGIONFREE`, `N64_ROM_RTC`, `N64_ROM_CONTROLLER1..4`, and `N64_ROM_METADATA` pointing at `metadata/metadata.ini`.

---

## 3. Compression

### 3.1 DFS does NOT compress

`dragonfs.h:44-45` is explicit: "DFS does NOT support compression — use the asset API (`asset_load`/`asset_fopen`) for compression." DFS files are stored as-is in the ROM filesystem.

### 3.2 Asset API compression — `src/asset.c:47-92`

Three levels (`vendored/libdragon/src/asset.c:47-92`):
- Level 0: none.
- Level 1 (default): **LZ4** (Yann Collet) — always linked, decompression faster than loading uncompressed.
- Level 2: **APLib** (header docs say "LZH5" but code uses APLib — stale docs).
- Level 3: **Shrinkler** (also a minishrinkler compress-side variant).

**GOTCHA:** LZMA / YAPKI / RNC are NOT present in this libdragon commit. If an agent sees those names in old docs, they're wrong.

`asset_init_compression(level)` must be called for levels 2 and 3 before loading (`asset.c:228-233`).

### 3.3 Per-asset compression via `mkasset`

`mkasset -c <level> -w <winsize KiB>` compresses an individual asset file. BF64's build pipeline invokes `mkasset -c <compr>` on `.t3dm` files after the tiny3d importer writes them (`t3dmBuilder.cpp`). The compression level comes from the asset's `compression` conf field (shifted by 1 — see `textures.md` §1.3 for the same shift on mksprite).

### 3.4 `asset_fopen` streaming — `assetcomp.h:21`

Streaming window 2–256 KiB (default 4 KiB). The asset is decompressed on-the-fly in chunks. **GOTCHA:** asserts on seek even for uncompressed files (`asset.h:41-43,216-218`).

### 3.5 Audio compression (separate axis)

Audio uses its own compression (VADPCM/Opus via audioconv64), NOT the asset API. See `audio-assets.md` §6. The `.wav64`/`.xm64` files are stored in DFS as-is after audioconv64 conversion; they're not re-compressed by `mkasset`.

### 3.6 Texture compression (separate axis)

Textures use sprite format + mksprite's `-c` compression (which is the asset API level, applied to the `.sprite` file). See `textures.md` §1.3. BCI_256 is its own block-compressed format.

---

## 4. The BF64 filesystem layout

### 4.1 What goes where

| Path | Contents | Format |
|---|---|---|
| `filesystem/` | converted ROM assets | binary |
| `filesystem/p64/a` | asset table binary | u32 count + per-asset (offset, type+flags) + romPath strings |
| `filesystem/p64/conf` | runtime boot config | u32 sceneIdOnBoot, u32 sceneIdOnReset, u16 autoLoadFontUUIDs[16] |
| `filesystem/p64/fileList.txt` | asset-list cache for change detection | text |
| `filesystem/p64/<bins>` | runtime bins (a, conf, fileList.txt) | binary |
| `filesystem/*.sprite` | converted textures | binary (mksprite output) |
| `filesystem/*.bci` | BCI_256 textures | binary (BCI output) |
| `filesystem/*.t3dm` | converted models | binary (tiny3d output) |
| `filesystem/*.sdata` | animation keyframe streams | binary (tiny3d output) |
| `filesystem/*.wav64` | converted audio | binary (audioconv64 output) |
| `filesystem/*.xm64` | converted XM music | binary (audioconv64 output) |
| `filesystem/*.font64` | converted fonts | binary (mkfont output) |
| `filesystem/*.pf` | converted prefabs | binary (prefabBuilder output) |
| `filesystem/*.pg` | converted node graphs | binary (nodeGraphBuilder output) |

### 4.2 The asset table — `filesystem/p64/a`

`projectBuilder.cpp:206-218`: u32 count, then per-asset (offset, type+flags packed into pointer high bits), then concatenated `romPath` strings.

**Engine-enforced GOTCHA:** `AssetEntry` packs type+flags into pointer high bits — assumes asset pointers fit in 24 bits (`ARCHITECTURE.md` §2.7). Hard N64-RAM assumption; don't violate.

### 4.3 Scene files — `rom:/p64/sNNNN_` (config) + `_o` (objects)

`sceneBuilder.cpp` writes binary scene/object files packed into the ROM. The `_` suffix is the config, `_o` is the object blob. Loaded by `sceneLoader.cpp:67` `loadObject`.

### 4.4 DFS packing — `mkdfs`

`mkdfs <output.dfs> filesystem/` walks the `filesystem/` directory and packs it into a DFS file. The DFS file is then packed into the ROM by n64tool.

**GOTCHA:** DFS file data is only 2-byte aligned, not 4-byte (`dragonfs.h:258-259`). DMA operations requiring 8-byte alignment must `memcpy` to an aligned buffer first.

---

## 5. Worked example: a small 3D game (8 MiB target)

A small 3D game targeting 8 MiB (the smallest practical cart for a 3D game). Based on jam25 ratios.

### 5.1 Budget breakdown

| Category | Budget | Notes |
|---|---|---|
| Engine + code (ELF) | ~512 KiB | libdragon + tiny3d + Pyrite64 engine + user scripts; `-Os` stripped |
| Framebuffers (3× RGBA16 320×240) | 461 KiB | runtime RAM, not ROM — but counts against the 8 MiB RDRAM cap if not Expansion Pak |
| Z-buffer | 154 KiB | runtime RAM |
| Audio mixer buffers (32 ch @ 32k mono) | 256 KiB | runtime RAM |
| AI buffers (3 @ 32k) | 15 KiB | runtime RAM |
| **ROM budget (assets + code)** | **~7 MiB** | the actual ROM content |

### 5.2 Asset budget (7 MiB)

| Category | Budget | Notes |
|---|---|---|
| Textures | 2.5 MiB | ~80 textures at 32×32 CI8 average (1 KiB each) + a few 64×64 CI4 (2 KiB each) |
| Models | 1.5 MiB | ~10 models at 150 KiB average (compressed .t3dm) |
| Audio (SFX) | 256 KiB | ~30 SFX at 8 KiB average (vadpcm mono 32k) |
| Audio (music) | 2 MiB | ~60 seconds of stereo vadpcm 32k = 2.2 MiB, OR 1 XM64 module at <100 KiB |
| Fonts | 64 KiB | 1-2 font64 files |
| Scenes + prefabs + node graphs | 64 KiB | binary scene files, small |
| Padding + DFS overhead | 256 KiB | n64tool alignment, DFS TOC, rompak |
| **Total** | **~6.6 MiB** | fits in 8 MiB with headroom |

### 5.3 If you need more

| Move | Savings |
|---|---|
| Switch music from VADPCM to Opus | ~3× smaller (12 KiB/s vs 36 KiB/s stereo 32k) |
| Use XM64 instead of streamed music | ~20× smaller (<100 KiB vs 2 MiB for equivalent) |
| Drop SFX sample rate to 22050 | 31% smaller |
| Drop SFX to mono (if stereo) | 50% smaller + halves channel pressure |
| Switch RGBA16 textures to CI8 | 50% smaller (if ≤256 colors) |
| Switch CI8 to CI4 | 50% smaller (if ≤16 colors) |
| Use I8/I4 for greyscale | 50-75% smaller than RGBA16 |
| Use BCI_256 + BigTex for large textures | 0.75 B/pixel effective vs 2 B/texel RGBA16 (but requires Expansion Pak + 320×240 RGBA16 lock) |
| Compress .t3dm with mkasset -c 2 (APLib) | ~10-20% smaller than LZ4 |
| Compress .t3dm with mkasset -c 3 (Shrinkler) | ~20-40% smaller than LZ4 (slower decompress) |

### 5.4 Worked example: jam25 (real)

jam25 is a complete 3D platformer. Its asset footprint (source files):

| Category | Source bytes | Source MiB |
|---|---|---|
| BCI_256 textures (17 files) | 2,044,916 | 1.95 |
| GLB models (10 files) | 2,029,004 | 1.94 |
| MP3 music (4 files) | 11,146,831 | 10.63 |
| Non-BCI PNG textures | 856,209 | 0.82 |
| WAV SFX (17 files) | 1,346,604 | 1.28 |
| TTF fonts (1 file) | 2,761,016 | 2.63 |
| **Total source** | **20,184,580** | **19.25** |

The converted `filesystem/` is smaller after compression (BCI 0.75 B/px vs PNG, vadpcm 4-bit vs WAV, mkasset LZ4 on .t3dm). The TTF converts to a much smaller `.font64` (only the glyphs used). The MP3s decode to larger vadpcm wav64s.

**Estimated converted ROM size:** ~22-28 MiB (the music dominates — 4 tracks × ~4 MiB vadpcm each). jam25 would target a 32 MiB cart.

**Lesson:** music is the dominant ROM cost for non-XM games. Switching jam25's 4 MP3s to XM64 would cut ~17 MiB down to <1 MiB, fitting in 8 MiB total.

---

## 6. RDRAM budget (runtime, separate from ROM)

The N64 has 4 MiB RDRAM base, 8 MiB with Expansion Pak. ROM size and RDRAM size are independent — a 64 MiB ROM still only has 4-8 MiB RDRAM to load into.

### 6.1 Static allocations (always present)

| Allocation | Size | Notes |
|---|---|---|
| Code (ELF) | ~512 KiB | the engine + user code |
| Stack | 64 KiB | `n64.ld:197` |
| Framebuffers (3× RGBA16 320×240) | 461 KiB | triple-buffered VI swapchain |
| Z-buffer | 154 KiB | per-frame depth buffer |
| Audio mixer (32 ch @ 32k mono) | 256 KiB | uncached sample buffers |
| AI buffers (3 @ 32k) | 15 KiB | uncached |
| RSP mixer ucode state | 128 B | rspq overlay state |
| **Total static** | **~1.4 MiB** | |

### 6.2 Heap available

- 4 MiB system: ~3.5 MiB heap (4 MiB − 1.4 MiB static − low mem)
- 8 MiB system: ~7.5 MiB heap (8 MiB − 1.4 MiB static − low mem)

The heap holds: loaded `.t3dm` models, animation `.sdata` streams, audio `wav64_t`/`xm64player_t` state, particle systems, collision meshes, the BigTex pool (1.125 MiB if BigTex pipeline), debug overlays, etc.

### 6.3 BigTex RDRAM cost

BigTex pool = 18 × 256×256 BCI textures = 1.125 MiB at fixed address `0x80400000`. **Expansion Pak required** (`memory.cpp:59`). Framebuffers placed above (`0x80500000+`). UV buffers heap-allocated (3 × 307 KB = 900 KiB).

---

## 7. Per-asset ROM cost cheat sheet

Quick reference for estimating an asset's ROM footprint:

### 7.1 Textures

| Format | Size formula | Example (32×32) | Example (64×64) |
|---|---|---|---|
| RGBA32 | W×H×4 | 4 KiB | 16 KiB |
| RGBA16 | W×H×2 | 2 KiB | 8 KiB |
| CI8 | W×H×1 + 512 B palette | 1.5 KiB | 4.5 KiB |
| CI4 | W×H×0.5 + 32 B palette | 0.5 KiB | 2 KiB |
| IA16 / RGBA16 | W×H×2 | 2 KiB | 8 KiB |
| IA8 / I8 | W×H×1 | 1 KiB | 4 KiB |
| IA4 / I4 | W×H×0.5 | 0.5 KiB | 2 KiB |
| BCI_256 | (W/4)×(H/4)×16 | 2 KiB (32×32) | 16 KiB (64×64) / 64 KiB (256×256) |
| Mipmap chain | base × 1.333 | +0.67 KiB | +2.67 KiB |
| LZ4 compression (asset API) | ~50-70% of raw | | |
| APLib | ~40-60% of raw | | |
| Shrinkler | ~30-50% of raw | | |

### 7.2 Models

| Component | Size | Notes |
|---|---|---|
| Vertex | 16 B | pos s16[3] + norm u16 + rgba u32 + uv s16[2] |
| Index | 1 B (local, int8) | 0..69 within a part |
| Strip slot | up to 255 indices | |
| Skeleton bone | ~52 B | name u32 + parent u16 + depth u16 + scale f32[3] + rot f32[4] + pos f32[3] |
| Animation channel mapping | ~12 B | targetIdx u16 + targetType u8 + attributeIdx u8 + quantScale f32 + quantOffset f32 |
| Keyframe (rotation) | 6 B | u16 timeNext + u16 chanelIdx + 2×u16 data |
| Keyframe (scalar) | 4 B | u16 timeNext + u16 chanelIdx + 1×u16 data |
| LZ4 compression | ~50-70% of raw | via mkasset |

### 7.3 Audio

| Format | Size/sec | Notes |
|---|---|---|
| Raw 16-bit mono @ 32k | 64 KiB/s | lossless |
| Raw 16-bit stereo @ 32k | 128 KiB/s | |
| VADPCM 4-bit mono @ 32k | ~18 KiB/s | default |
| VADPCM 4-bit stereo @ 32k | ~36 KiB/s | |
| VADPCM 2-bit mono @ 32k | ~9 KiB/s | lower quality |
| Opus mono @ 48k | ~6.4 KiB/s | best quality |
| Opus stereo @ 48k | ~12.4 KiB/s | |
| XM64 module | <100 KiB typical | depends on module complexity + sample count |

### 7.4 Other

| Asset | Size | Notes |
|---|---|---|
| Font64 | ~10-100 KiB | depends on glyph count + format (RGBA16 vs CI8) |
| Prefab | ~100 B - 10 KiB | depends on object tree depth |
| Node graph binary | ~1-10 KiB | the .pg file |
| Scene binary | ~1-100 KiB | the sNNNN_ config + sNNNN_o objects |

---

## Implications for BF64 agents

1. **Target 8 MiB for a small game, 16 MiB for a medium game, 32 MiB for a large game.** 64 MiB is rare and may not be flashcart-friendly. Most BF64 games fit in 8-16 MiB.
2. **Music is the dominant ROM cost.** 4 minutes of stereo VADPCM @ 32k = ~8.6 MiB. Switch to XM64 for interactive music (<100 KiB) or Opus for long recorded music (~12 KiB/s stereo). MP3 input is wasteful — it decodes to larger VADPCM.
3. **DFS does not compress.** Use `mkasset -c <level>` per-asset (LZ4 default, APLib/Shrinkler for tighter). The BF64 build pipeline already does this for `.t3dm`; you must opt in for other asset types.
4. **LZ4 is the default for a reason.** Decompression faster than loading uncompressed. APLib (level 2) ~10-20% tighter but slower. Shrinkler (level 3) ~20-40% tighter but much slower decompress — use only for one-shot load-to-RAM assets, not streaming.
5. **RDRAM is independent of ROM size.** A 64 MiB ROM still only has 4-8 MiB RDRAM. Static allocations (framebuffers + audio + code) eat ~1.4 MiB, leaving ~3.5 MiB heap on 4 MiB systems. Detect `is_memory_expanded()` before assuming 8 MiB.
6. **BigTex costs 1.125 MiB RDRAM** (18 × 256×256 BCI textures at fixed 0x80400000). Expansion Pak required. Framebuffers placed above 0x80500000.
7. **Texture format choice dominates ROM cost.** RGBA16 = 2 B/texel; CI8 = 1 B/texel + 512 B palette; CI4 = 0.5 B/texel + 32 B palette. A 64×64 RGBA16 = 8 KiB; the same as CI4 = 2 KiB (4× savings). Use AUTO format and let mksprite downgrade.
8. **BCI_256 is 0.75 B/pixel effective** (16 B per 4×4 block). Better than RGBA16 (2 B/px) for the BigTex pipeline; worse than CI4 (0.5 B/px) but supports 4 colors per block vs 16 global.
9. **Audio sample rate halves ROM.** 22050 Hz = 31% smaller than 32000; 32000 = 27% smaller than 44100. Use 22050 for SFX if you need space. 32000 is the BF64 canonical rate.
10. **Mono SFX halves ROM and channel pressure.** jam25 sets `wavForceMono: true` on every SFX. Stereo music is fine; stereo SFX is wasteful.
11. **`n64tool --size` pads to a declared size.** Use it to declare a target cart size (e.g. `--size 8M`). If unset, no padding. The 64drive warns if size is not a multiple of 512 bytes.
12. **rompak TOC max 15 entries.** The rompak (TOC at PI offset 0x1000) holds max 15 file entries. This is the rompak layer, NOT DFS — DFS is a single rompak entry containing the whole filesystem.