# Asset Checklist

**Audience:** LLM agents building games with Binface64. A single-page pre-flight checklist with PASS/FAIL rules. Apply this to any asset before importing. Every rule is mechanical and checkable (numbers, not vibes).
**Last reviewed:** 2026-07-07. Sources: the other n64/ docs (textures, models-and-meshes, audio-assets, rom-budgets). Cross-reference those for the "why".

---

## How to use this checklist

For each asset, run the rules in its section. If ANY rule fails, fix the asset before importing. The rules cite the source doc and section for the rationale.

**Rule format:** `PASS if <condition>; FAIL otherwise. Source: <doc> §<section>.`

---

## Textures (.png)

| # | Rule | Source |
|---|---|---|
| T1 | PASS if file extension is `.png` (the only image format BF64's editor accepts). FAIL on `.jpg`, `.bmp`, `.tga`, `.webp`, etc. | `textures.md` §1.2 |
| T2 | PASS if pixel dimensions are power-of-two OR the format is non-CI (rdpq handles non-POT for RGBA/IA, but POT is safest). FAIL if non-POT and CI4/CI8. | `textures.md` §3 |
| T3 | PASS if dimensions fit TMEM for the chosen format (see table below). FAIL otherwise — the ROM will assert at draw time. | `textures.md` §3.2 |
| T4 | PASS if the conf `format` is 0 (AUTO) OR explicitly matches the texture's color count. FAIL if RGBA16 forced on a ≤256-color texture (wastes 4× ROM/TMEM). | `textures.md` §2.4, §4.3 |
| T5 | PASS if `.bci.png` extension is used ONLY for BigTex-pipeline 256×256 textures. FAIL if `.bci.png` on a non-256×256 texture (BCI requires 4×4 block alignment → W and H must be multiples of 4). | `textures.md` §7, §1.2 |
| T6 | PASS if `.bci.png` and the scene uses `renderPipeline: 2` (BigTex). FAIL if `.bci.png` but the scene uses Default or HDR+Bloom pipeline (BCI_256 textures only work in BigTex). | `textures.md` §7.3 |
| T7 | PASS if palette color count ≤ 16 for CI4, ≤ 256 for CI8. FAIL otherwise (mksprite will re-quantize, which is fine, but you should have used the bigger format). | `textures.md` §4.3 |
| T8 | PASS if `compression` conf is 0 (DEFAULT), 1, 2, or 3. FAIL on other values. Note: DEFAULT (0) becomes mksprite level 1 internally. | `textures.md` §1.3 |
| T9 | PASS if the texture is not larger than 256×256 (unless using BigTex). FAIL if >256×256 and not `.bci.png` — it cannot fit TMEM in any format. | `textures.md` §3 |
| T10 | PASS if mipmaps are NOT requested for a multi-texture material (2 texture slots + mipmaps = 8+ tiles, exceeds TILE0-TILE7). FAIL if mipmaps on a 2-slot material. | `textures.md` §8, §6.3 |

### TMEM max-square lookup (for rule T3)

| Format | Max square WxH | Max texels |
|---|---|---|
| RGBA32 | 32 × 32 | 1024 |
| RGBA16 | 44 × 44 | 2048 |
| CI8 | 42 × 42 | 2048 |
| CI4 | 64 × 64 | 4096 |
| IA16 | 44 × 44 | 2048 |
| IA8 | 64 × 64 | 4096 |
| IA4 | 85 × 85 | 8192 |
| I8 | 64 × 64 | 4096 |
| I4 | 85 × 85 | 8192 |

---

## Models (.glb / .gltf)

| # | Rule | Source |
|---|---|---|
| M1 | PASS if file extension is `.glb` or `.gltf`. FAIL on `.blend`, `.fbx`, `.obj`, `.dae`, etc. (BF64 does not import these — export to glb from Blender via fast64 first). | `models-and-meshes.md` §1 |
| M2 | PASS if the glTF was exported with fast64 AND "Include → Custom Properties" was checked. FAIL if exported with vanilla glTF (no `f3d_mat` extras → importer throws). | `models-and-meshes.md` §5.2, §9.1 |
| M3 | PASS if every material has fast64 CC/blender/zmode settings. FAIL if any material is PBR metallic/roughness only (no `f3d_mat` → throws). | `models-and-meshes.md` §5.2, §9.5 |
| M4 | PASS if total vertices ≤ 65535 AND total indices ≤ 65535 (per model file). FAIL otherwise (u16 cap — split into multiple glb files). | `models-and-meshes.md` Hard limits |
| M5 | PASS if every vertex has at most 1 bone influence (rigid skinning). WARN if vertices have >1 bone influence (glTF weights are read and discarded — only `joints[0]` is used). | `models-and-meshes.md` §3.1, §9.3 |
| M6 | PASS if the armature root has no transformed ancestors (translation/rotation/scale all identity within epsilon 0.0001). FAIL if armature is parented to a transformed node (importer throws). | `models-and-meshes.md` §3.2, §9.2 |
| M7 | PASS if animations use only translation, rotation, or scale channels. FAIL if any animation uses `weights` morph targets (importer throws "Unknown animation target"). | `models-and-meshes.md` §6.1, §9.4 |
| M8 | PASS if animation duration ≤ 18.2 minutes (65535 ticks @ 60 Hz). FAIL otherwise (u16 time cap, writer asserts `timeNext < 2^15`). | `models-and-meshes.md` §6.4 |
| M9 | PASS if `baseScale` conf is set such that the model's bounding box fits in ±32767/globalScale Blender units. FAIL if any vertex position would exceed int16 range. | `models-and-meshes.md` §2.4 |
| M10 | PASS if textures referenced by glTF materials are already imported as PNG assets in the project. WARN if missing — `getByPath` fails silently and the material loses its texture binding. | `models-and-meshes.md` §9.6, `ARCHITECTURE.md` §3.3 |
| M11 | PASS if `gltfBVH` conf is true only if you want frustum culling. WARN if false on a large scene (no culling, but smaller .t3dm). | `models-and-meshes.md` §7.7 |
| M12 | PASS if no material instance uses >8 placeholders. FAIL otherwise (9th+ placeholder silently dropped). | `models-and-meshes.md` Hard limits, `textures.md` §6.4 |
| M13 | PASS if the model does not use normal-mapped materials (no tangent/bitangent support). WARN if normal maps are present (silently ignored). | `models-and-meshes.md` §2.3, §5.13 |
| M14 | PASS if UVs are 0-1 normalized (standard glTF). WARN if UVs are outside 0-1 (will be scaled by texSize*32 — verify the conf texture size matches the actual texture). | `models-and-meshes.md` §2.5, §9.8 |

---

## Audio (.wav / .mp3 / .xm)

| # | Rule | Source |
|---|---|---|
| A1 | PASS if file extension is `.wav`, `.mp3`, or `.xm`. FAIL on `.aiff` (editor doesn't classify — invoke audioconv64 manually), `.it`, `.s3m`, `.mod`, `.ym` (not exposed by BF64 editor). | `audio-assets.md` §1.2 |
| A2 | PASS if `wavCompression` conf is 0, 1, or 3. FAIL on 2 (does not exist — reserved). | `audio-assets.md` §6.1 |
| A3 | PASS if `wavResampleRate` is 0, 8000, 11025, 16000, 22050, 32000, or 44100. WARN if 48000 (not in BF64 UI dropdown but accepted by audioconv64; mandatory for opus). | `audio-assets.md` §4.1 |
| A4 | PASS if `wavCompression: 3` (opus) AND `wavResampleRate: 0` or 48000. WARN if opus + a non-48000 resample rate (audioconv64 forces 48000 internally anyway; the resample value becomes a bitrate hint). | `audio-assets.md` §4.5 |
| A5 | PASS if `wavForceMono: true` for SFX. WARN if `wavForceMono: false` on a SFX (stereo SFX doubles ROM and channel pressure). | `audio-assets.md` §5.4, Implications #4 |
| A6 | PASS if the asset is `.xm` and `wavCompression` is NOT 3 (opus forbidden for XM64 — audioconv64 hard errors). FAIL if `.xm` + `wavCompression: 3`. | `audio-assets.md` §6.4, Hard limits |
| A7 | PASS if estimated playback channels fit the 32-channel mixer. Compute: sum of (channels per source) for all simultaneously-playing sources ≤ 32. WARN if approaching 32. FAIL if >32 (runtime assert for XM, error log for WAV). | `audio-assets.md` §5.3, §7.7, Implications #5 |
| A8 | PASS if `.xm` module has ≤32 channels (the runtime assert `first_ch + num_channels ≤ 32`). FAIL if >32 channels. | `audio-assets.md` §7.7 |
| A9 | PASS if `.xm` module does not use ping-pong loops (unrolled to forward at convert time; RSP only does forward loops). WARN if ping-pong loops present (will be unrolled, increasing ROM size). | `audio-assets.md` §7.3, Implications #6 |
| A10 | PASS if estimated ROM size fits the target cart. Compute: duration × bytes/sec (see `audio-assets.md` §4.2-4.4 for the formula per format). WARN if a single audio asset exceeds 10% of the ROM budget. | `audio-assets.md` §10, `rom-budgets.md` §7.3 |
| A11 | PASS if `wavCompression: 3` (opus) is used only for long audio (music, voiceover). WARN if opus on a short SFX (<1 s) — the runtime state cost (several KiB/channel) outweighs the ROM savings. | `audio-assets.md` §6.4, Implications #7 |
| A12 | PASS if the Audio2D component does not need 3D positional audio. FAIL if 3D audio is required (BF64's Audio2D has no 3D — `audioManager.cpp:105` has a TODO). | `audio-assets.md` §8.5, Implications #12 |

---

## Fonts (.ttf)

| # | Rule | Source |
|---|---|---|
| F1 | PASS if file extension is `.ttf` or `.otf`. FAIL on other font formats. | `libdragon-tiny3d.md` §1.7 |
| F2 | PASS if `mkfont` is available in the toolchain (`<N64_INST>/bin/mkfont`). FAIL if not (build will fail). | `libdragon-tiny3d.md` §1.7 |
| F3 | PASS if the font's glyph coverage matches `fontCharset` conf. WARN if `fontCharset` is empty (default charset used — may not cover your game's text). | `assetManager.cpp` AssetConf `fontCharset` |

---

## Scenes & prefabs (project-internal assets)

| # | Rule | Source |
|---|---|---|
| S1 | PASS if scene `fbWidth` and `fbHeight` match the render pipeline constraints: Default = any; HDR+Bloom = 320×240; BigTex = 320×240. FAIL otherwise (runtime asserts). | `display-and-video.md` §4, `models-and-meshes.md` |
| S2 | PASS if scene `fbFormat` is 0 (RGBA16) or 1 (RGBA32) for Default; 0 for HDR+Bloom; 0 for BigTex. FAIL otherwise. | `display-and-video.md` §4 |
| S3 | PASS if scene `renderPipeline: 2` (BigTex) AND `doClearColor` is false. FAIL if BigTex + `doClearColor: true` (asserts "Clearing screen not supported in BigTex pipeline"). | `display-and-video.md` §4.2, `textures.md` §7.3 |
| S4 | PASS if scene `audioFreq` is 32000 (default), 44100, or 48000. WARN if other (DAC divider rounding means actual freq differs from requested). | `audio-assets.md` §4.6, `audio.md` §1 |
| S5 | PASS if prefab child transforms are relative to their parent (BF64 rebases on creation — runtime has no transform hierarchy). WARN if prefab creation was done outside the editor (transforms may not be rebased). | `ARCHITECTURE.md` §3.2 |
| S6 | PASS if the scene has <65535 objects (runtime id cap is u16, assigned in `Scene::assignRuntimeIds`). FAIL otherwise. | `ARCHITECTURE.md` §3.2 |
| S7 | PASS if BigTex scene uses ≤18 unique large textures (pool size). FAIL if >18 (assert "Texture buffer full"). | `textures.md` §7.1, Hard limits |
| S8 | PASS if BigTex scene is targeting an Expansion Pak system. FAIL if not (asserts "Expansion-Pack required!"). | `textures.md` §7.3, `rom-budgets.md` §6.3 |

---

## Scripts (.cpp in src/user/)

| # | Rule | Source |
|---|---|---|
| C1 | PASS if namespace is `P64::Script::C<16-hex-chars>` (object script) or `P64::GlobalScript::C<16-hex-chars>` (global script). FAIL if namespace is malformed (UUID extracted by string offset — fragile). | `ARCHITECTURE.md` §3.8 |
| C2 | PASS if the first hex char of the UUID is `C` (forced to avoid leading digits in C++ namespace names). FAIL if it starts with a digit. | `ARCHITECTURE.md` §3.8 |
| C3 | PASS if `P64_DATA(...)` struct fields use only supported types: `uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/float/char[]/AssetRef<sprite_t>/ObjectRef/PrefabRef`. FAIL on other types (codeParser won't expose them in the inspector). | `ARCHITECTURE.md` §3.8 |
| C4 | PASS if `sizeof(P64_DATA struct) < 0xFFFF` (65535 bytes per-instance cap, static_assert). FAIL otherwise. | `ARCHITECTURE.md` §0, Open questions #3 |
| C5 | PASS if no `//` appears inside string literals in the script (codeParser strips comments with two regex passes — misparses `//` in strings). WARN if present. | `ARCHITECTURE.md` §3.8, §5 |
| C6 | PASS if lifecycle function return types are simple (`void`, `bool`, etc.). WARN if return type is `const void*` or `std::*` (hasFunction string-match won't detect them). | `ARCHITECTURE.md` §3.8, §5 |
| C7 | PASS if the script does not hold asset pointers across scene changes. FAIL if it does (`AssetManager::freeAll` in `Scene::~Scene` → use-after-free). | `ARCHITECTURE.md` §5, `audio-assets.md` §8.5 |

---

## ROM budget (whole-project check)

| # | Rule | Source |
|---|---|---|
| R1 | PASS if total estimated ROM size ≤ target cart size. FAIL otherwise. Target 8 MiB small / 16 MiB medium / 32 MiB large / 64 MiB rare. | `rom-budgets.md` §1, Implications #1 |
| R2 | PASS if total estimated RDRAM usage ≤ 4 MiB (base N64) OR ≤ 8 MiB (Expansion Pak, with `is_memory_expanded()` check). FAIL if >4 MiB and no Expansion Pak detection. | `rom-budgets.md` §6, `hardware.md` §3 |
| R3 | PASS if music ROM ≤ 50% of total ROM budget. WARN if >50% (switch to XM64 or Opus). FAIL if a single music track >25% of total ROM. | `rom-budgets.md` §5.3, Implications #2 |
| R4 | PASS if no single asset >10% of total ROM (except one music track). WARN if any non-music asset >10%. | `rom-budgets.md` §5 |
| R5 | PASS if the scene count is reasonable for the ROM target. A scene binary is ~1-100 KiB; 100 scenes = ~1-10 MiB. WARN if >50 scenes. | `rom-budgets.md` §7.4 |
| R6 | PASS if BigTex is used ONLY when needed (large textures, Expansion Pak target). WARN if BigTex on a 4 MiB target (pool alone = 1.125 MiB). | `rom-budgets.md` §6.3, `textures.md` §7.3 |
| R7 | PASS if `--size` is declared to n64tool (pads to target cart size). WARN if unset (no padding — ROM may be smaller than standard cart size, which some flashcarts dislike). | `rom-budgets.md` §2.3, Implications #11 |
| R8 | PASS if the ROM size is a multiple of 512 bytes (64drive compat). FAIL if not a multiple of 4 (n64tool error). | `rom-budgets.md` §2.3, Hard limits |

---

## Quick size estimation helpers

### Texture ROM cost

```
RGBA32:  W × H × 4
RGBA16, IA16: W × H × 2
CI8, IA8, I8:  W × H × 1 + 512 (palette, CI only)
CI4, IA4, I4:  W × H × 0.5 + 32 (palette, CI only)
BCI_256: (W/4) × (H/4) × 16
Mipmap chain: × 1.333
LZ4 compression (mkasset -c 1): × 0.5-0.7
APLib (mkasset -c 2): × 0.4-0.6
Shrinkler (mkasset -c 3): × 0.3-0.5
```

### Audio ROM cost per second

```
Raw 16-bit mono @ 32000 Hz:      64 KiB/s
Raw 16-bit stereo @ 32000 Hz:   128 KiB/s
VADPCM 4-bit mono @ 32000 Hz:  ~18 KiB/s
VADPCM 4-bit stereo @ 32000 Hz:~36 KiB/s
VADPCM 2-bit mono @ 32000 Hz:  ~9 KiB/s
Opus mono @ 48000 Hz:           ~6.4 KiB/s
Opus stereo @ 48000 Hz:        ~12.4 KiB/s
XM64 module:                    <100 KiB total (typical)
```

### Model ROM cost

```
Vertex: 16 B (pos s16[3] + norm u16 + rgba u32 + uv s16[2])
Index: 1 B (local int8, 0..69)
Skeleton bone: ~52 B
Animation channel mapping: ~12 B
Rotation keyframe: 6 B (u16 timeNext + u16 chanelIdx + 2×u16)
Scalar keyframe: 4 B (u16 timeNext + u16 chanelIdx + 1×u16)
LZ4 compression (mkasset -c 1): × 0.5-0.7
```

### RDRAM static cost

```
Code (ELF):           ~512 KiB
Stack:                 64 KiB
3× framebuffer (320×240 RGBA16): 461 KiB
Z-buffer:             154 KiB
32-channel mixer @ 32k mono: 256 KiB
AI buffers (3× @ 32k):  15 KiB
Total static:         ~1.4 MiB
Heap (4 MiB system):  ~3.5 MiB
Heap (8 MiB system):  ~7.5 MiB
BigTex pool (if used): +1.125 MiB
```