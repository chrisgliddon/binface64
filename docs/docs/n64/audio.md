# Audio

**Audience:** LLM agents building games with Binface64. Mixer channels, sample rates, memory cost, formats.
**Last reviewed:** 2026-07-06. Sources: vendored libdragon source (file:line cites), Pyrite64 ARCHITECTURE.md.
**Scope:** the audio subsystem. For hardware specs, see `hardware.md`. For the libdragon API surface, see `libdragon-tiny3d.md`.

---

## Hard limits

| Resource | Hard limit | Source |
|---|---|---|
| Mixer channels | 32 | `vendored/libdragon/include/mixer.h:59` `MIXER_MAX_CHANNELS` |
| Audio output buffers | 4 (default `NUM_BUFFERS`) | `vendored/libdragon/src/audio.c:42` |
| Buffer size | `((frequency/25)>>3)<<3` (8-byte aligned, 25 buffers/sec) | `audio.c:43-53` |
| Stereo consumes | 2 channels per source | `mixer.h:181-185` |
| Wav64 paths | `rom:/` only | `wav64.h:85-86` |
| Wav64 compression levels | 0=none, 1=VADPCM (default), 3=Opus | `wav64.h:46-76` |
| VADPCM bits/sample | 2, 3, or 4 (default 4) | `audioconv64.cpp:118` |
| Mixer poll rate | 8×/sec (`MIXER_POLL_PER_SECOND=8`) | `mixer.c:54` |
| Loop overread | 64 bytes past loop end (RSP ucode doesn't bound-check) | `mixer.h:62-74` `MIXER_LOOP_OVERREAD` |
| Bitrate register cap | 16 | `audio.c:220` |

---

## 1. Sample rates

`audio_init(frequency, numbuffers)` (`include/audio.h:79`, impl `src/audio.c:178-266`). The actual frequency differs from requested due to DAC divider rounding: `actual = 2*clockrate / ((2*clockrate/frequency)+1)` (`audio.c:227`). Query with `audio_get_frequency()` (`audio.h:136`).

**DAC clocks** (same as VI clocks, `audio.c:24-28`):
- NTSC: 48,681,818 Hz
- PAL: 49,656,530 Hz
- MPAL: 48,628,322 Hz

**Common choices:** 32000, 44100, 22050, 48000. Pyrite64's `SceneConf::audioFreq` defaults to 32000 (`scene.h`), and each scene can set its own mix rate (`scene.cpp:74`).

**Per-channel resampling:** `mixer_ch_set_freq` (`mixer.h:210`) — the mixer can play samples at different rates per channel. 8-bit and 16-bit signed samples supported.

**GOTCHA:** AI DMA hardware bug workaround — if a buffer ends exactly on a 0x2000 boundary, the pointer is bumped by 4 samples (8 bytes) (`audio.c:247-254`).

---

## 2. Formats

### 2.1 WAV64 (sound effects)

`wav64_open(wav64_t*, const char *fn)` (`wav64.h:87`). `rom:/` only (`wav64.h:85-86`).

**Streaming modes** (`wav64.h:90-111`):
- `WAV64_STREAMING_FULL` (default) — stream from ROM, low memory.
- `WAV64_STREAMING_NONE` — preload + decompress into RAM.

**Compression** (`wav64.h:46-76`):
| Level | Format | Notes |
|---|---|---|
| 0 | Uncompressed PCM | fastest decode, largest ROM |
| 1 | VADPCM (default) | RSP-optimized ADPCM; configurable bits/sample (2/3/4, default 4); optional Huffman (default on for wav64) |
| 2 | (does not exist yet) | |
| 3 | Opus | RSP-optimized; smallest ROM; slower runtime; requires `wav64_init_compression(3)` before any level-3 wav64 is opened |

**GOTCHA:** Opus init must happen before any wav64 with level-3 compression is opened (`wav64.h:55-62`). Pyrite64's `buildGlobalScripts` injects `wav64_init_compression(3)` into the game-init hook when any asset uses opus (`scriptBuilder.cpp:145-156`).

### 2.2 XM64 (music)

FastTracker II .XM → .XM64 via `audioconv64` (`xm64.h`, `src/audio/xm64.c`). Based on libxm (`xm64.h:15`). Uses one mixer channel per XM channel. Patterns loaded on-the-fly, samples streamed. RLE recompression for patterns (`xm64.h:25`).

**GOTCHA:** Opus not supported for xm64 (`audioconv64.cpp:111-112`).

### 2.3 YM64

Arkos Tracker II .YM → .YM64 (`audioconv64.cpp:71`, `src/audio/ym64.c`).

### 2.4 Conversion tool

`audioconv64` (`vendored/libdragon/tools/audioconv64/audioconv64.cpp`):
- WAV/MP3/AIFF → WAV64: `--wav-mono`, `--wav-resample <N>`, `--wav-compress <0|1|3>`, `--wav-loop <true|false>`, `--wav-loop-offset <N>`, `--wav-seek <SEC|FILE>`.
- XM → XM64: `--xm-8bit`, `--xm-ext-samples <dir>`, `--xm-compress <0|1>`, `--xm-compress-data <0..3>`.
- YM → YM64: `--ym-compress <true|false>`.
- VADPCM detail: `vadpcm,bits=<2|3|4>` (default 4), `vadpcm,huffman=true|false` (default true for wav64, false for xm64).

**GOTCHA:** `audioconv64` is invoked with the same flags for both AUDIO types but the wav-* flags are only added when `asset.type == AUDIO` (`audioBuilder.cpp:33-43`); an `.mp3` typed as AUDIO will pass `--wav-*` flags to `audioconv64` which may or may not accept them for mp3 input — undocumented.

---

## 3. Mixer

`mixer_init(int num_channels)` (`mixer.h:93`). Default 32 channels. RSP-accelerated (`rsp_mixer.S`).

**Per-channel sample buffer size:** `ceil(max_frequency * max_bits/8 * nchannels / MIXER_POLL_PER_SECOND)` rounded to 8 (`mixer.c:206-228`). At 44100 Hz, 16-bit stereo: ~22 KiB per channel.

**Features:**
- 8-bit and 16-bit signed samples.
- Mono and stereo (stereo = 2 channels, `mixer.h:181-185`).
- Per-channel resampling (`mixer_ch_set_freq`, `mixer.h:210`).
- Per-channel volume (`mixer_ch_set_vol`).
- Dolby Pro Logic II surround (`mixer_ch_set_vol_dolby(fl,fr,c,sl,sr)`, `mixer.h:168-169`).
- `mixer_throttle` for video-sync (`mixer.h:325`).

**GOTCHA:** `MIXER_LOOP_OVERREAD = 64` — the RSP ucode doesn't bound-check sample buffer accesses; looping waveforms need up to 64 bytes of repeated loop-start past the loop-end (`mixer.h:62-74`).

---

## 4. Memory cost

### 4.1 Per second of audio (storage in ROM)

| Format | Rate | Channels | Bytes/sec | Notes |
|---|---|---|---|---|
| PCM 16-bit | 44100 | stereo | ~176 KB/s | uncompressed |
| PCM 16-bit | 32000 | stereo | ~128 KB/s | |
| PCM 16-bit | 22050 | stereo | ~88 KB/s | |
| VADPCM 4-bit | 44100 | stereo | ~44 KB/s | 4× compression |
| VADPCM 2-bit | 44100 | stereo | ~22 KB/s | 8× compression, lower quality |
| VADPCM 3-bit | 44100 | stereo | ~33 KB/s | 6× compression |
| Opus | 44100 | stereo | ~10-20 KB/s | variable bitrate, depends on content |

### 4.2 Runtime RAM (per channel, streaming)

~22 KiB per channel at 44100 Hz 16-bit stereo (`mixer.c:218`). 32 channels max = ~704 KiB if all used (rare). Streaming from ROM means no per-second RAM cost — only the per-channel buffer.

### 4.3 AI output buffers

`NUM_BUFFERS=4` × `frequency/25` stereo samples × 4 B (`audio.c:42,53,244`). At 44100 Hz: ~7 KB/buffer × 4 ≈ 28 KB uncached.

---

## 5. Pyrite64 audio layer

`P64::AudioManager` (`n64/engine/include/audio/audioManager.h`, see `ARCHITECTURE.md` §2.6):
- 32 mixer channels (`CHANNEL_COUNT=32`, `audioManager.cpp:84-85`).
- `init(freq)` — only re-initializes if freq changed. Frequency from `SceneConf::audioFreq` (`scene.cpp:74`).
- Slot model: `std::array<Slot,32>`, each a union of `wav64_t*`/`xm64player_t*`.
- `play2D(wav64_t*)` / `play2D(xm64player_t*)` / `play2D(assetId)`.
- `Audio::Handle` (4 bytes): `stop`, `setVolume`, `setSpeed` (WAV only; warns for XM), `isDone`. UUID guards against stale handles.
- `setMasterVolume`, `stopAll`, `Metrics` (bitmasks of allocated/playing channels).
- Component: `Comp::Audio2D` (ID 6) auto-plays wav/xm with LOOP/AUTO_PLAY flags.

**GOTCHA:** `AudioManager::destroy()` exists in the `.cpp` (line 122) but is NOT declared in the public header. No public teardown; audio is torn down implicitly on `mixer_close` frequency change.

**GOTCHA:** All asset pointers are invalidated on every scene change (`Scene::~Scene` → `AssetManager::freeAll`). Audio handles become stale across scene transitions.

---

## 6. Music strategy

| Approach | Pros | Cons | When to use |
|---|---|---|---|
| XM64 (sequenced) | <3% CPU, <10% RSP for 10-channel XM; tiny ROM; interactive (can change tempo/mute channels) | limited to XM format (FastTracker/MilkyTracker/OpenMPT) | interactive music, adaptive scores |
| WAV64 streaming (VADPCM) | any audio source; simple | ~44 KB/s ROM at 44100 stereo 4-bit; non-interactive | linear music, recorded tracks |
| WAV64 streaming (Opus) | smallest ROM (~10-20 KB/s) | slower runtime; requires init | very long music, voiceover |
| WAV64 streaming (PCM) | fastest decode | largest ROM (176 KB/s stereo 44100) | short SFX only, never music |

**Rule of thumb:** XM64 for interactive music, VADPCM WAV64 for recorded music/SFX, Opus only for very long audio (voiceover, cutscenes).

---

## Implications for BF64 agents

1. **32000 Hz is the Pyrite64 default.** Good quality, half the ROM cost of 44100. Use 22050 for SFX if you need ROM space. Use 44100 only for high-quality music.
2. **VADPCM 4-bit is the default for a reason.** 4× compression with good quality. 2-bit for SFX where you need ROM space and can tolerate quality loss. Opus only for very long audio.
3. **XM64 is the cheapest music.** A 10-channel XM costs <3% CPU and <10% RSP (`README.md`). Use MilkyTracker/OpenMPT to author. Patterns and samples stream from ROM.
4. **Stereo = 2 channels.** A stereo WAV64 consumes 2 of your 32 mixer channels. Budget accordingly: 16 stereo sources = 32 channels = maxed out.
5. **Looping waveforms need 64 bytes of overread.** The RSP ucode doesn't bound-check; repeat loop-start data past loop-end (`mixer.h:62-74`). `audioconv64` handles this automatically for wav64 loops.
6. **Audio handles are stale across scene changes.** `AudioManager::freeAll` is called in `Scene::~Scene`. Don't hold `Audio::Handle` across scene loads. Re-play on scene enter.
7. **`setSpeed` only works for WAV, not XM.** Calling `setSpeed` on an XM handle logs a warning (`audioManager.cpp:220`). Use pattern tempo changes for XM speed.
8. **Opus requires init.** If any asset uses compression level 3, `wav64_init_compression(3)` must be called before opening. Pyrite64's build system auto-injects this into the game-init hook (`scriptBuilder.cpp:145-156`), but if you're building outside Pyrite64, do it yourself.
9. **`rom:/` only for wav64.** `wav64_open` only accepts `rom:/` paths, not `sd:/` (`wav64.h:85-86`). For SD card audio, use `asset_fopen` + manual feeding.
10. **The actual sample rate differs from requested.** DAC divider rounding means `audio_init(44100)` might give you 44056 or similar. Query with `audio_get_frequency()`. For precise timing, derive from the actual rate, not the requested.