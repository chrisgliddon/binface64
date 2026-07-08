# Audio Assets

**Audience:** LLM agents building games with Binface64. Accepted input formats, conversion pipeline, memory/quality tradeoff tables, music strategy. Use this as the pre-flight reference before importing any audio.
**Last reviewed:** 2026-07-07. Sources: vendored libdragon source (file:line cites), BF64 build pipeline source, vendored tiny3d docs. Where sources disagree, the conservative number is picked and noted.
**Scope:** audio assets. For the mixer/runtime layer, see `audio.md`. For hardware specs, see `hardware.md`.

---

## Hard limits

| Resource | Hard limit | Source |
|---|---|---|
| Mixer channels | 32 | `vendored/libdragon/include/mixer.h:59` `MIXER_MAX_CHANNELS` |
| Stereo consumes | 2 channels per source | `mixer.h:181-185`, `mixer.c:467` |
| Max `--wav-resample` | 48000 Hz | `vendored/libdragon/tools/audioconv64/audioconv64.cpp:342` |
| Min `--wav-resample` | 1 Hz | same |
| VADPCM bits/sample | 2, 3, or 4 (default 4) | `audioconv64.cpp:327` |
| Wav64 compression levels | 0=raw, 1=VADPCM (default), 3=Opus (2 reserved) | `vendored/libdragon/include/wav64.h:46-76`, `wav64_internal.h:9-12` |
| Opus forced sample rate | 48000 Hz (regardless of `--wav-resample`) | `conv_wav64.cpp:46,795-805` |
| Wav64 paths | `rom:/` only | `vendored/libdragon/include/wav64.h:85-86` |
| Wav64 header version | 6 | `wav64_internal.h:36`, `wav64.c:139` |
| VADPCM frame | 16 samples → 9 bytes per channel | `vadpcm/codec/vadpcm.h:39,42` |
| AI buffer count | capped at 32 (`sizeof(buf_full)*8`) | `audio.c:200-204` |
| Mixer poll rate | 8×/sec (`MIXER_POLL_PER_SECOND=8`) | `mixer.c:54` |
| Loop overread | 64 bytes past loop end (RSP ucode doesn't bound-check) | `mixer.h:62-74` `MIXER_LOOP_OVERREAD` |
| XM64 channel count | must fit `first_ch + num_channels ≤ 32` | `xm64.c:198` |
| Audio2D component binary | 6 bytes per instance (`u16 id, u16 volume, u8 flags, u8 pad`) | `src/project/component/types/compAudio2d.cpp:53-76` |

---

## 1. Accepted input formats

### 1.1 audioconv64 dispatcher — `audioconv64.cpp:139-153`

| Input ext | Accepted? | Output | Handler |
|---|---|---|---|
| `.wav` | Yes | `.wav64` | `wav_convert` → `read_wav` (dr_wav) |
| `.aiff` | Yes (`.aiff` only — `.aif` NOT matched) | `.wav64` | `read_wav` (dr_wav handles AIFF metadata) |
| `.mp3` | Yes | `.wav64` | `wav_convert` → `read_mp3` (dr_mp3) — **all `--wav-*` flags apply** |
| `.xm` | Yes | `.xm64` | `xm_convert` (libxm) |
| `.ym` | Yes | `.ym64` | `ym_convert` (Arkos Tracker II / AY8910) |
| `.it`, `.s3m`, `.mod` | **NO** | — | Rejected with `"WARNING: ignoring unknown file"` |

### 1.2 BF64 asset manager — `src/project/assetManager.cpp:117-122`

BF64's editor exposes only three input extensions:

```cpp
} else if (ext == ".wav" || ext == ".mp3") {
  type = Project::FileType::AUDIO;
  outPath = changeExt(outPath, ".wav64");
} else if (ext == ".xm") {
  type = Project::FileType::MUSIC_XM;
  outPath = changeExt(outPath, ".xm64");
```

`.ym` and `.aiff` work only if you invoke audioconv64 manually — the BF64 editor doesn't classify them.

### 1.3 Usage banner — `audioconv64.cpp:68-72`

```
Supported conversions:
   * WAV/MP3 => WAV64 (Waveforms)
   * XM  => XM64  (MilkyTracker, OpenMPT)
   * YM  => YM64  (Arkos Tracker II)
```

---

## 2. audioconv64 CLI — every flag

### 2.1 Global flags — `audioconv64.cpp:73-79,228-244`

| Flag | Arg | Effect |
|---|---|---|
| `-o` / `--output` | `<dir>` | Output directory |
| `-v` / `--verbose` | — | Verbose stderr logging |
| `-d` / `--debug` | — | Dump uncompressed `.vadpcm.wav` / `.opus.wav` next to output for A/B comparison |
| `-h` / `--help` | — | Print usage |
| `--help-compress` | — | Print compression sub-options help |

### 2.2 WAV/MP3 flags — `audioconv64.cpp:80-91,246-358`

| Flag | Arg | Default | Effect |
|---|---|---|---|
| `--wav-mono` | — | `false` | Force stereo→mono by averaging L+R |
| `--wav-resample` | `<N>` Hz, 1–48000 | `0` (original) | Resample via libsamplerate (SRC_SINC_BEST_QUALITY) |
| `--wav-compress` | `0\|1\|3`[,opts] | `1` (VADPCM) | 0=none, 1=vadpcm, 3=opus. Level 2 does NOT exist. Sub-opts: `huffman=true\|false`, `bits=2\|3\|4` (vadpcm only). Opus rejected for XM. |
| `--wav-loop` | `true\|false` | `false` | Activate default playback loop |
| `--wav-loop-offset` | `<N>` samples | `0` | Set loop start; implicitly enables looping |
| `--wav-seek` | `<SEC>` float OR `<FILE>` | none | Generate seek points: periodic every SEC seconds, or read explicit list (sample offsets or `[hh:]mm:ss[.mmm]`) from a file. WAV `cue` chunks auto-become seek points; WAV `smpl` chunks auto-become loop points. |

### 2.3 XM flags — `audioconv64.cpp:92-97,359-377`

| Flag | Arg | Default | Effect |
|---|---|---|---|
| `--xm-8bit` | — | `false` | Downconvert 16-bit samples to 8-bit |
| `--xm-ext-samples` | `<dir>` | (internal) | Export instrument samples as separate `<hash>.wav64` files instead of embedding |
| `--xm-compress` | `0\|1`[,opts] | `1` (vadpcm) | Per-sample compression. **Opus (3) explicitly rejected** with `"opus compression not supported for XM64"`. Same `huffman`/`bits` sub-opts as wav. |
| `--xm-compress-data` | `0..3` | `DEFAULT_COMPRESSION` | RLE compression of pattern + metadata blobs |

### 2.4 YM flags — `audioconv64.cpp:98-99,378-390`

| Flag | Arg | Default | Effect |
|---|---|---|---|
| `--ym-compress` | `true\|false` | `false` | LZH5-compress the YM64 output |

### 2.5 Flags BF64 exposes — `src/build/audioBuilder.cpp:31-46`

```cpp
if(asset.type == Project::FileType::AUDIO) {
  if(asset.conf.wavForceMono.value) cmd += " --wav-mono";
  if(asset.conf.wavResampleRate.value != 0)
    cmd += " --wav-resample " + std::to_string(asset.conf.wavResampleRate.value);
  cmd += " --wav-compress " + std::to_string(asset.conf.wavCompression.value);
}
```

BF64 exposes only:
- `wavForceMono` → `--wav-mono`
- `wavResampleRate` → `--wav-resample`
- `wavCompression` → `--wav-compress`

**NOT exposed:** `--wav-loop`, `--wav-loop-offset`, `--wav-seek`, `--xm-8bit`, `--xm-ext-samples`, `--xm-compress`, `--xm-compress-data`, `--ym-compress`, the `vadpcm,bits=` / `huffman=` sub-opts. To use these, invoke audioconv64 manually.

**Engine-enforced:** `--wav-compress` is ALWAYS passed for AUDIO (even if 0 or 1), but NOT for MUSIC_XM — XM uses converter defaults (vadpcm samples, no huffman).

---

## 3. The MP3 open question — DEFINITIVELY ANSWERED

**YES — MP3 input accepts and honors ALL `--wav-*` flags.** MP3 is decoded into the same in-memory `wav_data_t` structure and routed through the identical post-processing pipeline as WAV.

Evidence chain (`conv_wav64.cpp:706-739`):
```c
if (strcasestr(infn, ".mp3"))
    loaded = read_mp3(infn, &wav);    // drmp3_read_pcm_frames_s16
else
    loaded = read_wav(infn, &wav);
// ... after this single branch, mono downmix, seek-point loading,
//     resampling, compression, wav64_write all run identically
```

`read_mp3` (`conv_wav64.cpp:132-153`) populates the same `wav_data_t` (`samples`, `cnt`, `channels`, `bitsPerSample=16`, `sampleRate`, `looping`, `loopOffset`, `skipPoints`). MP3 has no native loop/cue metadata, so `looping=false` and `skipPoints` are empty unless `--wav-loop*` / `--wav-seek` are passed.

**Caveats specific to MP3:**
- `--wav-compress 3` (opus) on an MP3 forces resample to **48000 Hz** regardless of `--wav-resample` (`conv_wav64.cpp:795-805`, `OPUS_SAMPLE_RATE=48000`). If the MP3 is 44100 Hz (typical), it WILL be upsampled. The original `--wav-resample` value is repurposed as a bitrate tuning hint.
- MP3s have no loop metadata; pass `--wav-loop` / `--wav-loop-offset` explicitly if you want looping.
- `--wav-seek` is fully functional on MP3.
- `flag_wav_compress` default is `1` (vadpcm) for ALL inputs including MP3.

**Verdict:** Treat MP3 as a first-class WAV-equivalent input. The only asymmetry is metadata discovery (no smpl/cue chunks) and the opus forced-48kHz behavior.

---

## 4. Sample rates

### 4.1 Options

- **CLI:** `--wav-resample <N>`, N clamped to `[1, 48000]` (`audioconv64.cpp:342`).
- **BF64 editor preset values** (`assetInspector.cpp:82-91`): `0 (Original)`, 8000, 11025, 16000, 22050, 32000, 44100. **48000 is NOT offered in the BF64 UI** but is accepted by audioconv64 and is mandatory for opus.
- **Resampler:** libsamplerate (`SRC_SINC_BEST_QUALITY` normally; `SRC_SINC_MEDIUM_QUALITY` for files > 15 s to save time, `conv_wav64.cpp:822-828`).

### 4.2 Size effect (uncompressed / raw)

Output bytes scale linearly with sample rate. Raw 16-bit mono per second = `sampleRate × 2` bytes:

| Rate | Mono 16-bit | Stereo 16-bit |
|---|---|---|
| 8000 Hz | 16 KiB/s | 32 KiB/s |
| 22050 Hz | 44.1 KiB/s | 88.2 KiB/s |
| 32000 Hz | 64 KiB/s | 128 KiB/s |
| 44100 Hz | 88.2 KiB/s | 176.4 KiB/s |
| 48000 Hz | 96 KiB/s | 192 KiB/s |

### 4.3 Size effect (VADPCM)

VADPCM frame = 16 samples → 9 bytes per channel (`vadpcm/codec/vadpcm.h:39,42`). Compressed size ≈ `sampleRate × 9/16 × channels` B/s ≈ **0.5625 × sampleRate × channels** B/s. With 4-bit default + optional Huffman (on by default for wav64):

| Rate | Mono VADPCM | Stereo VADPCM |
|---|---|---|
| 22050 Hz | ~12.4 KiB/s | ~24.8 KiB/s |
| 32000 Hz | ~18 KiB/s | ~36 KiB/s |
| 44100 Hz | ~24.8 KiB/s | ~49.6 KiB/s |
| 48000 Hz | ~27 KiB/s | ~54 KiB/s |

### 4.4 Size effect (Opus)

Bitrate = `60 × FRAMES_PER_SECOND + resampleRate × channels` bps = `3000 + resampleRate × channels` bps (`conv_wav64.cpp:526,505`). VBR, complexity 10.

| Rate | Mono Opus | Stereo Opus |
|---|---|---|
| 32000 Hz | ~51 kbps = 6.4 KiB/s | ~99 kbps = 12.4 KiB/s |
| 48000 Hz | ~51 kbps = 6.4 KiB/s | ~99 kbps = 12.4 KiB/s |

### 4.5 Opus special case

`conv_wav64.cpp:795-805`:
```c
if (flag_wav_compress == 3) {
    wavResampleTo = OPUS_SAMPLE_RATE;  // 48000
    if (!flag_wav_resample)
        flag_wav_resample = wav.sampleRate;  // used for bitrate calc
}
```

Opus output is ALWAYS 48000 Hz internally. The `freq` written to the wav64 header is 48000. Setting `--wav-resample 32000` with opus does NOT downsample the audio — it only lowers the bitrate budget.

### 4.6 BF64 canonical rate

jam25 (a complete 3D platformer) uses **32000 Hz** as the canonical SFX rate. All jam25 SFX confs set `"wavResampleRate": 32000`. The mixer/audio_init runs at 32000 Hz (`audioManagerPrivate.h:10`, `scene.cpp:74`, jam25 `scene.json:audioFreq: 32000`).

| Layer | Default | Source |
|---|---|---|
| `P64::AudioManager::init(freq)` | 32000 | `audioManagerPrivate.h:10` |
| BF64 `SceneConf::audioFreq` | 32000 | `scene.h` |
| Editor dropdown options | 32000, 44100, 48000 | `sceneInspector.cpp:93-96` |
| Asset resample dropdown | 0, 8000, 11025, 16000, 22050, 32000, 44100 (no 48000) | `assetInspector.cpp:82-91` |
| Opus internal | 48000 (forced) | `conv_wav64.cpp:46,795-805` |

---

## 5. Mono vs stereo

### 5.1 Default

Channel count preserved from input. Stereo in → stereo wav64 out.

### 5.2 `--wav-mono` — `conv_wav64.cpp:741-763`

Only acts if `wav.channels == 2`. Averages L+R into a single 16-bit sample `(L+R)/2`. Allocates new buffer, frees old, sets `wav.channels = 1`.

### 5.3 Stereo playback cost

A stereo wav64 consumes **two consecutive mixer channels** (`mixer.h:181-185` doc; `mixer.c:467` asserts `ch != num_channels-1`):

```c
assertf(ch != Mixer.num_channels-1, "cannot configure last channel (%d) as stereo", ch);
```

Channel `ch` = left, `ch+1` = right (auto-marked `CH_FLAGS_STEREO_SUB`, `mixer.c:467-470`). You cannot independently address `ch+1` while stereo is playing.

### 5.4 BF64 default for SFX

jam25 sets `wavForceMono: true` on every SFX. Music (MP3) keeps stereo: `wavForceMono: false`. **This is the recommended pattern** — SFX want mono to halve channel pressure and ROM size; music wants stereo.

### 5.5 Runtime

BF64 `AudioManager::play2D` reserves `audio->wave.channels` consecutive free slots (`audioManager.cpp:142-146`), so a stereo clip blocks 2 of the 32 slots.

---

## 6. Compression modes

### 6.1 Format IDs — `wav64_internal.h:9-12`

```c
#define WAV64_FORMAT_RAW    0
#define WAV64_FORMAT_VADPCM 1
#define WAV64_FORMAT_OPUS   3
#define WAV64_NUM_FORMATS   4   // level 2 reserved/unused
```

### 6.2 Raw (0)

- **ROM cost:** full PCM. 8-bit or 16-bit signed, big-endian byte-swapped (`conv_wav64.cpp:264-275`).
- **Runtime state:** 0 bytes.
- **Quality:** lossless.
- **Init:** none.
- **Best for:** very short SFX where decode overhead matters; assets needing sample-accurate seeking.

### 6.3 VADPCM (1) — DEFAULT

- **Codec:** RSP-optimized Variable ADPCM. Frame = 16 samples → 9 bytes per channel. 4-bit default residuals, 4 predictors, order-2 filter. `kPREDICTORS=4`, `kVADPCMEncodeOrder=2`.
- **Bits-per-sample option:** `--wav-compress 1,bits=2|3|4`. Lower = smaller but lower quality. For bits<4, Huffman should be enabled.
- **Huffman:** `--wav-compress 1,huffman=true|false`. **Default ON for wav64, OFF for xm64** (`conv_wav64.cpp:712-714`, `conv_xm64.cpp:417-418`). Extra ~5-15% reduction.
- **Loop alignment:** loop point forced to 32-sample boundary (forward-padded, `conv_wav64.cpp:223-236`).
- **Runtime state:** 48 bytes per channel (`wav64_state_vadpcm_t` = 2 × 8-sample vector (32 B) + int bitpos (4 B), aligned 16 → 48).
- **Quality:** ~4-bit ADPCM quality. Good for SFX, acceptable for music at 32-48 kHz. Audible quantization on quiet material.
- **Seeking:** sample-accurate only at precomputed skip points (16-sample frame boundaries).
- **Init:** none required.

### 6.4 Opus (3)

- **Codec:** Opus custom mode, RSP-decoded (`libopus_rsp.c`). Frame size = `sampleRate/50` samples (960 @ 48 kHz, 640 @ 32 kHz). 20 ms frames.
- **Mandatory resample to 48000 Hz** regardless of `--wav-resample`.
- **Bitrate:** `3000 + resampleRate*channels` bps. VBR, complexity 10, AUTO bandwidth, no FEC, no DTX.
- **Preroll:** 2 frames decoded-and-discarded after seeking (`PREROLL_FRAMES=2`, `conv_wav64.cpp:499,540`).
- **Runtime state:** `16 + opus_custom_decoder_get_size(mode, channels)` bytes — several KiB per channel (much larger than vadpcm).
- **Quality:** best of the three. Transparent for music at typical bitrates.
- **Seeking:** only to precomputed seek points (frame-aligned + preroll).
- **Init:** **MUST call `wav64_init_compression(3)` before opening any opus wav64** (`wav64.h:54-76`, asserts at `wav64.c:141-143`). BF64 auto-injects this — see §8.
- **NOT supported for XM** (`audioconv64.cpp:285-288` hard error).

### 6.5 Comparison table

| Mode | ROM size vs raw 16-bit | Runtime state/channel | Quality | Init needed | Seek |
|---|---|---|---|---|---|
| 0 raw | 100% (or 50% if 8-bit) | 0 B | Lossless | No | Sample-accurate |
| 1 vadpcm (4-bit+huff) | ~30-40% | 48 B | Good (SFX) | No | Skip points only |
| 3 opus | ~10-20% | several KiB | Excellent (music) | **Yes** | Skip points only |

---

## 7. XM music format

### 7.1 Based on libxm

`vendored/libdragon/src/audio/xm64.c`, header `xm64.h:14-35`. FastTracker II / MilkyTracker / OpenMPT modules.

XM64 version: 11 (`conv_xm64.cpp:207`).

### 7.2 Supported XM features

Effects 0x0 (arpeggio), 0x1 (portamento up), 0x2 (portamento down), 0x3 (tone portamento), 0x4 (vibrato), 0x5 (tone portamento + volume slide), 0x6 (vibrato + volume slide), 0x7 (tremolo), 0x8 (panning), 0x9 (sample offset — also recorded as a skip point for VADPCM seeking), 0xA (volume slide), 0xB (position jump), 0xC (set volume), 0xD (pattern break), 0xE (extended, sub-effects for fine portamento, vibrato waveform, panning fine, pattern loop, tremolo waveform), 0x10+ (volume column). Volume envelopes, panning envelopes, sustain/loop points, vibrato (sweep/depth/rate), fadeout — all serialized.

### 7.3 Unsupported / adapted

- **Ping-pong loops: UNSUPPORTED at runtime.** Converter unrolls them into forward loops (`conv_xm64.cpp:507-521`, `xm64.h:23`). RSP mixer only does forward loops.
- **Sample preloading: NO.** Samples stream from ROM via mixer callbacks (`xm64.h:28-29`).
- **Unknown effects** forwarded to a user callback (`xm64player_set_effect_callback`, `xm64.h:165-182`) — intended for game sync cues, not playback.

### 7.4 XM64 preprocessing — `conv_xm64.cpp:11-29`

1. Ping-pong loops unrolled to forward loops (RSP limitation).
2. Patterns recompressed with custom RLE (`asset_compress_mem`). Decompressed on-the-fly per pattern; only current pattern in RAM.
3. Module analyzed to compute minimum per-channel sample buffer size (dry-run playback). Stored as `ctx_size_stream_sample_buf[32]`.
4. Short odd-length 8-bit loops (<1024 B) duplicated to even length to avoid DMA phase issues.
5. Empty (length=0) samples removed and remapped.
6. Unused trailing samples freed.
7. Duplicate samples deduplicated by CRC32.
8. `MIXER_LOOP_OVERREAD` (64 B) of repeated loop-start data appended after loop-end for safe RSP overread.

### 7.5 XM sample compression

- Default `flag_xm_compress_samples = 1` (vadpcm) (`conv_xm64.cpp:47`).
- **Huffman OFF by default for XM** (`conv_xm64.cpp:417-418`) — unlike wav64.
- Each sample encoded as embedded/external wav64, always treated as mono 44100 Hz nominal (actual playback frequency comes from note pitches).
- `--xm-8bit` converts 16-bit samples to 8-bit.
- `--xm-ext-samples <dir>` externalizes samples as `<crc32hex>.wav64` files; xm64 stores CRC32 as a placeholder offset and `xm64_set_extsampledir` (`xm64.h:198`) configures the runtime search dir.

### 7.6 XM runtime RAM cost

Computed per-channel at convert time. Verbose output (`conv_xm64.cpp:686-700`):
```
* ROM size: <N> KiB (samples:<N>)
* RAM size: <N> KiB (ctx:<N>, patterns:<N>, samples:<N>)
* Samples RAM per channel: [n,n,n,...]
```

Each channel's buffer is `ch_buf[i] * 1.05` (5% margin), 8-byte aligned. VADPCM channels get +64-byte quantum rounding.

### 7.7 XM channel count

XM modules declare `num_channels`. Runtime requires `first_ch + num_channels ≤ MIXER_MAX_CHANNELS` (32) (`xm64.c:198`):
```c
assert(first_ch + xm_get_number_of_channels(player->ctx) <= MIXER_MAX_CHANNELS);
```

An XM with >32 channels, or insufficient free channels, aborts.

### 7.8 XM playback model

- `xm64player_play(player, first_ch)` (`xm64.h:116`) grabs N consecutive mixer channels.
- Tempo/BPM from module.
- Seeking is "broken by design" — moves cursor but doesn't reconstruct active samples/effects (`xm64.h:142-153`).
- `setSpeed` (per-waveform pitch) is **NOT supported for XM** — BF64 explicitly warns (`audioManager.cpp:218-222`).

---

## 8. The BF64 audio layer

### 8.1 Audio2D component — `src/project/component/types/compAudio2d.cpp:20-26`

```cpp
struct Data {
  PROP_U64(audioUUID);    // reference to an AUDIO or MUSIC_XM asset
  PROP_FLOAT(volume);     // default 1.0f
  PROP_BOOL(loop);
  PROP_BOOL(autoPlay);
};
```

### 8.2 Binary build output — `compAudio2d.cpp:53-76`

```cpp
uint16_t id;        // asset index, 0xDEAD if UUID missing
uint16_t volume;    // (float)volume * 0xFFFF
uint8_t  flags;
uint8_t  padding;
```

**Flags byte:**
- bit 0: `loop`
- bit 1: `autoPlay`
- bit 2: `isXM` (set when `asset->type == FileType::MUSIC_XM`)

**Total: 6 bytes per Audio2D component instance** in the scene file.

### 8.3 Opus init injection — `scriptBuilder.cpp:144-157`

```cpp
sceneCtx.needsOpus = false;
for(auto &asset : project.getAssets().getTypeEntries(Project::FileType::AUDIO)) {
  if(asset.conf.wavCompression.value == 3) sceneCtx.needsOpus = true;
}
if(sceneCtx.needsOpus) {
  nameMap["onGameInit"] += " wav64_init_compression(3); \n";
}
```

If ANY AUDIO asset has `wavCompression == 3`, the generated `onGameInit` script gets `wav64_init_compression(3);` injected automatically. **Required** — opening an opus wav64 without it triggers the assert at `wav64.c:141-143`. Only AUDIO assets are scanned; MUSIC_XM cannot be opus anyway.

### 8.4 AssetConf audio fields — `assetManager.h:49-70`

```cpp
struct AssetConf {
  PROP_BOOL(wavForceMono);      // → --wav-mono
  PROP_U32(wavResampleRate);    // → --wav-resample
  PROP_S32(wavCompression);     // → --wav-compress  (0/1/3)
};
```

These only apply to `FileType::AUDIO`. `MUSIC_XM` assets get no `--wav-*` flags but DO get `--xm-*` defaults (vadpcm samples, no huffman).

### 8.5 Runtime — `n64/engine/include/audio/audioManager.h`

- 32 mixer channels (`CHANNEL_COUNT=32`, `audioManager.cpp:14`).
- `init(freq)` — only re-initializes if freq changed. Frequency from `SceneConf::audioFreq`.
- Slot model: `std::array<Slot,32>`, each a union of `wav64_t*`/`xm64player_t*`.
- `play2D(wav64_t*)` / `play2D(xm64player_t*)` / `play2D(assetId)`.
- `Audio::Handle` (4 bytes): `stop`, `setVolume`, `setSpeed` (WAV only; warns for XM), `isDone`. UUID guards against stale handles.
- `setMasterVolume`, `stopAll`, `Metrics` (bitmasks of allocated/playing channels).
- Component: `Comp::Audio2D` (ID 6) auto-plays wav/xm with LOOP/AUTO_PLAY flags.

**GOTCHA:** `AudioManager::destroy()` exists in the `.cpp` (line 122) but is NOT declared in the public header. No public teardown; audio is torn down implicitly on `mixer_close` frequency change.

**GOTCHA:** All asset pointers are invalidated on every scene change (`Scene::~Scene` → `AssetManager::freeAll`). Audio handles become stale across scene transitions.

**GOTCHA:** No 3D audio — the component is `Audio2D`. The mixer supports Dolby Pro Logic II and per-channel L/R volume (panning), but BF64 does not wire these up. `audioManager.cpp:105` has a TODO: `// @TODO: implement and handle 3D sound / panning`.

---

## 9. Memory cost

### 9.1 Per-channel mixer buffer — `mixer.c:206-228` `mixer_calc_buffer_size`

```c
nsamples = max_frequency;                 // Hz, default = output sample rate
nsamples *= max_bits / 8;                 // 1 or 2 bytes
nsamples *= nchannels;                    // 1 mono, 2 stereo
size = ROUND_UP(ceilf(nsamples / MIXER_POLL_PER_SECOND), 8);
```

`MIXER_POLL_PER_SECOND = 8`. Mixer expects to be polled 8× per second; each channel's buffer holds 1/8 s of audio.

| Output rate | Mono bytes/channel | Stereo bytes/channel |
|---|---|---|
| 32000 Hz | 8000 B | 16000 B |
| 44100 Hz | 11032 B | 22064 B |
| 48000 Hz | 12000 B | 24000 B |

**Total for 32 channels @ 32000 Hz, mono, 16-bit:** 32 × 8000 = **256 KiB** of uncached sample buffers. Stereo everywhere doubles this to ~512 KiB.

### 9.2 AI output buffers — `audio.c:178,244`

`audio_init(freq, numbuffers)`. Buffer size = `CALC_BUFFER(freq) = ((freq/25)>>3)<<3` (`audio.c:44,53`) — `freq/25` stereo samples, 8-byte aligned. Each buffer is `2*short*_buf_size + 8` bytes uncached.

- 32000 Hz: 1280 stereo samples × 4 B = ~5120 B per buffer.
- BF64 calls `audio_init(freq, 3)` — 3 buffers. ~15 KiB of AI buffers at 32 kHz.

### 9.3 RSP mixer ucode state

`MIXER_STATE_SIZE = 128` bytes (`mixer.c:62`), allocated via rspq overlay state.

### 9.4 Per-waveform runtime state

- Raw: 0 B.
- VADPCM: 48 B/channel.
- Opus: `16 + opus_custom_decoder_get_size(...)` — several KiB/channel.

---

## 10. Real-world asset sizes (jam25)

jam25 audio runs at `audioFreq: 32000`. All SFX confs: `wavCompression: 1` (vadpcm), `wavForceMono: true`, `wavResampleRate: 32000`. Music confs: `wavCompression: 1` (vadpcm), `wavForceMono: false`, `wavResampleRate: 32000`.

### 10.1 SFX (WAV)

| File | Input size | Duration | Est. 32k mono vadpcm |
|---|---|---|---|
| `sfx/StepDef.wav` | 19,968 B | 0.156 s | ~2.8 KiB |
| `sfx/BoxBreak.wav` | 41,618 B | 0.650 s | ~11.7 KiB |
| `sfx/CoinHit.wav` | 52,440 B | 0.409 s | ~7.4 KiB |
| `sfx/UiOk.wav` | 56,144 B | 0.438 s | ~7.9 KiB |
| `sfx/StepStone00..02.wav` | 55–67 KB | 0.38–0.46 s | ~6.8–8.2 KiB |
| `sfx/FadeOut.wav` | 78,032 B | 0.884 s | ~15.9 KiB |
| `sfx/PlayerJump00.wav` | 83,496 B | 0.472 s | ~8.5 KiB |
| `sfx/PlayerLand.wav` | 84,288 B | 0.580 s | ~10.4 KiB |
| `sfx/CoinGet.wav` | 129,088 B | 0.732 s | ~13.2 KiB |
| `sfx/VoidDisable.wav` | 149,664 B | 1.169 s | ~21 KiB |
| `sfx/PotBreak.wav` | 160,324 B | 1.252 s | ~22.5 KiB |

### 10.2 Music (MP3)

| File | Input size | Duration | Est. 32k stereo vadpcm |
|---|---|---|---|
| `Main.mp3` | 2,303,906 B (44.1k/2ch, 199 kbps) | 92.6 s | ~3.25 MiB |
| `sea_of_symbols.mp3` | 2,196,451 B (44.1k/2ch, 170 kbps) | 103.4 s | ~3.63 MiB |
| `proto_spokehul.mp3` | 3,277,191 B (44.1k/2ch, 187 kbps) | 140.5 s | ~4.93 MiB |
| `discovery_fragment.mp3` | 3,369,283 B (44.1k/2ch, 170 kbps) | 158.9 s | ~5.57 MiB |

**Key finding:** MP3s decode to PCM and are re-compressed as VADPCM. The resulting wav64 files are **LARGER than the source MP3s** (MP3 @ 170 kbps = ~21 KiB/s; vadpcm stereo @ 32k = ~36 KiB/s). MP3 here is being used purely as a convenient input container, NOT for its compression efficiency.

### 10.3 Total jam25 audio ROM budget (rough)

17 SFX ≈ 175 KiB vadpcm + 4 music tracks ≈ 17.4 MiB vadpcm → **~17.6 MiB of audio in ROM**. Significant fraction of a typical 32-64 MiB ROM. For long music, opus (`wavCompression: 3`) would yield ~12 KiB/s stereo at 48k — but BF64 ships jam25 with vadpcm, likely because opus requires the `wav64_init_compression(3)` init and larger runtime state.

---

## 11. Music strategy

| Approach | Pros | Cons | When to use |
|---|---|---|---|
| XM64 (sequenced) | <3% CPU, <10% RSP for 10-channel XM; tiny ROM; interactive (can change tempo/mute channels) | limited to XM format (FastTracker/MilkyTracker/OpenMPT) | interactive music, adaptive scores |
| WAV64 streaming (VADPCM) | any audio source; simple | ~36 KiB/s ROM at 32k stereo 4-bit; non-interactive | linear music, recorded tracks |
| WAV64 streaming (Opus) | smallest ROM (~12 KiB/s stereo) | slower runtime; requires init; 48 kHz forced; several KiB state/channel | very long music, voiceover |
| WAV64 streaming (PCM) | fastest decode | largest ROM (192 KiB/s stereo 48k) | short SFX only, never music |

**Rule of thumb:** XM64 for interactive music, VADPCM WAV64 for recorded music/SFX, Opus only for very long audio (voiceover, cutscenes).

**MP3 as music input is wasteful** — it's decoded then re-encoded as vadpcm, which is larger than the source MP3. For long music, opus (`wavCompression: 3`) is the size-efficient choice. Tradeoff: opus needs init + larger runtime state + 48 kHz forced.

---

## Implications for BF64 agents

1. **32000 Hz is the BF64 canonical rate.** Good quality, half the ROM cost of 44100. Use 22050 for SFX if you need ROM space. Use 44100 only for high-quality music. 48000 is NOT offered in the BF64 UI dropdown but is accepted by audioconv64 and is mandatory for opus.
2. **VADPCM 4-bit is the default for a reason.** ~30-40% of raw size with good quality. 2-bit for SFX where you need ROM space and can tolerate quality loss. Opus only for very long audio.
3. **MP3 is a first-class input.** All `--wav-*` flags apply. The only asymmetry is metadata discovery (no smpl/cue chunks) and opus forced-48kHz. Treat MP3 as WAV-equivalent.
4. **Mono SFX, stereo music.** jam25 sets `wavForceMono: true` on every SFX. Stereo doubles channel pressure, ROM size, and mixer buffer. Music keeps stereo.
5. **32 channels is the hard ceiling.** Stereo clips take 2; XM modules take `num_channels` (often 8-16). Budget: 1 XM (16 ch) + 16 stereo SFX = maxed. Or 32 mono SFX.
6. **XM ping-pong loops are unrolled at convert time.** RSP mixer only does forward loops. Don't use ping-pong loops in your XM modules.
7. **Opus requires init.** If any asset uses compression level 3, `wav64_init_compression(3)` must be called before opening. BF64 auto-injects this into `onGameInit` (`scriptBuilder.cpp:144-157`), but if you're building outside BF64, do it yourself. Opus is forbidden for XM.
8. **`setSpeed` only works for WAV, not XM.** Calling `setSpeed` on an XM handle logs a warning (`audioManager.cpp:220`). Use pattern tempo changes for XM speed.
9. **Audio handles are stale across scene changes.** `AudioManager::freeAll` is called in `Scene::~Scene`. Don't hold `Audio::Handle` across scene loads. Re-play on scene enter.
10. **Looping waveforms need 64 bytes of overread.** The RSP ucode doesn't bound-check; `audioconv64` handles this automatically for wav64 loops. For manual loops, repeat loop-start data past loop-end (`mixer.h:62-74`).
11. **`rom:/` only for wav64.** `wav64_open` only accepts `rom:/` paths, not `sd:/`. For SD card audio, use `asset_fopen` + manual feeding.
12. **No 3D audio.** The component is `Audio2D`. The mixer supports Dolby Pro Logic II and panning, but BF64 doesn't wire them up. `audioManager.cpp:105` has a TODO.