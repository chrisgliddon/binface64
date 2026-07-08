# Emulation & Hardware Testing

**Audience:** LLM agents building games with Binface64. Why accuracy matters, which emulators to use, flashcarts, and a test matrix.
**Last reviewed:** 2026-07-06. Sources: Pyrite64 README/FAQ, libdragon README, n64brew wiki.
**Scope:** how to test N64 ROMs — emulators, flashcarts, and the test matrix an agent should run.

---

## Hard limits

| Resource | Hard limit | Source |
|---|---|---|
| Required emulator accuracy | cycle-accurate or near-cycle-accurate | Pyrite64 FAQ; libdragon README |
| Recommended emulators | Ares (v147+), gopher64 | Pyrite64 README:34; FAQ |
| NOT recommended | Project64, Android emulators | Pyrite64 FAQ |
| Flashcart CIC | 6102 (libdragon requirement) | Pyrite64 FAQ |
| Flashcarts supported by libdragon | 64drive, EverDrive64, SummerCart64 | libdragon README |
| SD card access | via flashcart hardware (libcart) | libdragon README |

---

## 1. Why accuracy matters

The N64 is a tightly-coupled system: CPU, RCP (RSP + RDP), RDRAM, VI, AI, PI all share RDRAM bandwidth and interact via DMA and interrupts. Inaccurate emulators:
- Don't model RDRAM bandwidth contention correctly → games that work in emulation fail on hardware.
- Don't model RDP pipeline hazards → rendering glitches that don't appear on hardware.
- Don't model RSP timing correctly → audio glitches or dropped frames.
- Don't model VI timing correctly → wrong frame timing, audio desync.
- Don't model PI DMA correctly → asset loading races.

Pyrite64's FAQ is explicit (see `docs/docs/faq.md`):
> Games made with Pyrite64 require *accurate* emulation.
> Recommended emulators are: Ares (v147 or newer) or gopher64.
> **No**, you cannot emulate games in Project64 / Android.

libdragon's README confirms: "Can be developed with newer-generation emulators (Ares, Gopher64) and development cartridges (64drive, EverDrive64, SummerCart64)."

---

## 2. Emulators

### 2.1 Ares (recommended)

- **Required version:** v147 or newer.
- **Accuracy:** cycle-accurate (near-cycle-accurate). Models RDRAM bandwidth, RDP pipeline, RSP timing, VI/AI timing.
- **Platform:** cross-platform (Windows, macOS, Linux).
- **URL:** https://ares-emu.net/
- **Use for:** primary development testing. Pyrite64's `Build & Run` launches Ares by default (`pathEmu` default "ares", `globalActions.cpp:189`).

### 2.2 gopher64 (recommended)

- **Accuracy:** high-accuracy, high-performance. Not as cycle-accurate as Ares but sufficient for libdragon/Pyrite64.
- **Platform:** cross-platform.
- **URL:** https://github.com/gopher64/gopher64
- **Use for:** fast iteration. Pyrite64 supports it as an alternative emulator target (`bf64 run --emu gopher64` is planned in Phase 5).

### 2.3 NOT recommended

- **Project64** — not accurate enough. Pyrite64 FAQ explicitly says no.
- **Android emulators** — same.
- **Other low-accuracy emulators** — if it's not Ares or gopher64, assume it's wrong.

**GOTCHA:** A ROM that works in Project64 but not Ares is a ROM that will fail on real hardware. The reverse is not true — Ares is the stricter test.

---

## 3. Flashcarts (real hardware)

libdragon supports three flashcart families (libdragon README, `vendored/libdragon/include/dma.h:215-221`):

| Flashcart | Notes |
|---|---|
| **64drive** | USB upload, SD card |
| **EverDrive64** | SD card, ROM loading via menu |
| **SummerCart64** | SD card, USB upload, real-time clock support |

**CIC requirement:** libdragon requires a **CIC 6102** (Pyrite64 FAQ). The IPL3 is open source and NOT taken from a game — libdragon ships its own.

**SD card access:** `sd:/` prefix via FAT (ChaN FatFS). SD access through flashcart hardware (libcart). `asset_load` works with both `rom:/` and `sd:/`.

**ROM format:** `.z64` (big-endian). libdragon's `n64.mk` produces `.z64`; a `.v64` rule exists (`objcopy --reverse-bytes=2`, `n64.mk:156-158`) for byte-swapped format if needed.

**ROM header:** 4096-byte IPL3 + TOC at 0x1000 + ELF + DFS + sym. Region default 'E' (North America), region-free by default (`N64_ROM_REGIONFREE=1`, `n64.mk:11-12`). Save types: none/eeprom4k/eeprom16k/sram256k/sram768k/sram1m/flashram (`n64.mk:7-19`).

---

## 4. Test matrix

An agent shipping an N64 game should test on this matrix before declaring done:

| Platform | Config | What it catches | Priority |
|---|---|---|---|
| **Ares (latest)** | NTSC mode, 4 MiB (no Expansion Pak) | RDP/RSP/RDRAM timing bugs; the strictest test | **required** |
| **Ares (latest)** | NTSC mode, 8 MiB (Expansion Pak) | memory-related crashes, expansion-only code paths | **required** |
| **Ares (latest)** | PAL mode | 50fps timing, PAL-specific VI issues | recommended |
| **gopher64** | NTSC, 4 MiB | cross-emulator differences; if it works in Ares but not gopher64, you're relying on ares-specific timing | recommended |
| **Real N64 + flashcart** | NTSC, 4 MiB | the ground truth; catches anything emulators miss | **required for release** |
| **Real N64 + flashcart** | NTSC, 8 MiB (Expansion Pak) | expansion-specific code paths | recommended for release |
| **iQue Player** | (if available) | iQue-specific differences (CPU/RCP clock, `sys_hw_memset` fallback, memory detection) | optional |

### 4.1 What to check on each platform

For each test config, verify:
1. **Boot:** ROM loads and reaches the first scene without crashing.
2. **Video:** correct resolution, no tearing, no flicker, AA looks right, colors are correct.
3. **Audio:** no glitches, no dropouts, correct sample rate, stereo pan correct.
4. **Input:** controller responds, all 4 controller ports work if used.
5. **Frame rate:** stable target (30fps or 60fps), no sustained drops.
6. **Scene transitions:** no crashes, no asset leaks, audio restarts correctly.
7. **Save data:** if used, EEPROM/SRAM/FlashRAM writes and reads correctly across power cycles.
8. **Memory:** no heap leaks (Pyrite64's `Mem::getHeapDiff` logs warnings on non-zero diff every main-loop iteration, `main.cpp:108-111`).

### 4.2 Automated testing

Pyrite64's test ROM (`n64/tests/test_obj_states/`, see `ARCHITECTURE.md` §2.9) runs on-device and self-reports via `debugf`/onscreen text. **GOTCHA:** there is no host-side test runner that aggregates results — a human or external harness must read the ISViewer log / screen.

For agent-driven testing (Phase 5+), the `bf64 run` command (planned) should:
1. Build the ROM (`bf64 build`).
2. Launch in Ares headless mode (if supported) or gopher64 with screenshot capture.
3. Capture the ISViewer log for `debugf` output.
4. Screenshot the first frame and compare against a reference.
5. Report pass/fail.

---

## 5. Common hardware-only bugs

These are bugs that appear on real N64 but NOT in most emulators (even Ares, occasionally):

1. **RDRAM bandwidth saturation:** too many concurrent RDP + VI + CPU + RSP accesses → torn frames, audio glitches. Emulators often model bandwidth loosely.
2. **RDP pipeline hazards:** invalid render mode combinations crash the RDP (see [n64brew RDP Hazards](https://n64brew.dev/wiki/Reality_Display_Processor/Hazards)). Requires hard reset.
3. **TMEM overflow:** the RSP assert (`rdpq.c:574-575`) fires at runtime, not compile-time. Emulators may not assert.
4. **Cache coherency:** DMA targets must be uncached. Cached memory corrupts via DMA. Emulators with simplified cache models may not catch this.
5. **VI AA FETCH_ALWAYS in 32bpp:** broken on hardware, falls back to FETCH_NEEDED. Some emulators don't model this.
6. **PI DMA address mangling:** `dma_read`/`dma_write` mangle addresses into ROM range. Non-ROM PI space needs `dma_read_async`. Emulators may not enforce.
7. **AI DMA 0x2000 boundary bug:** buffers ending on 0x2000 boundaries are bumped by 8 bytes (`audio.c:247-254`). Emulators may not model.
8. **Mixer loop overread:** RSP ucode overreads up to 64 bytes past loop end. Emulators may not fault; hardware RSP will read garbage.
9. **iQue differences:** CPU/RCP clocks differ (144/96 vs 93.75/62.5 MHz), `sys_hw_memset` falls back to CPU, memory detection differs. Test only if iQue is a target.

---

## Implications for BF64 agents

1. **Test in Ares first, always.** It's the strictest widely-available test. If it works in Ares, it probably works on hardware. If it fails in Ares, it will fail on hardware.
2. **Test in gopher64 second.** If it works in Ares but not gopher64, you're relying on Ares-specific timing quirks — fix the underlying issue.
3. **Test on real hardware before release.** Emulators miss things. A flashcart (64drive/EverDrive64/SummerCart64) is required for release. CIC 6102.
4. **Never use Project64 or Android emulators.** They are not accurate enough. A ROM that works only in Project64 is broken.
5. **Test with 4 MiB, not just 8 MiB.** The base N64 has 4 MiB. If your game requires the Expansion Pak, detect it (`is_memory_expanded()`) and warn the user — or design to fit in 4 MiB.
6. **Check for heap leaks.** Pyrite64's `Mem::getHeapDiff` runs every main-loop iteration and logs warnings on non-zero diff. If you see these in the ISViewer log, you have a leak.
7. **Capture the ISViewer log.** `debugf` output goes to ISViewer (a debug interface on real hardware via flashcart, or emulated in Ares/gopher64). This is the primary debugging channel for N64 homebrew. The `bf64 run` command (Phase 5) should capture this.
8. **Don't assume emulator = hardware.** The common hardware-only bugs list (§5) is the things emulators miss. If you're doing anything bandwidth-sensitive (heavy RDP fill, concurrent audio + 3D, DMA-heavy asset loading), test on hardware early.
9. **PAL is not just NTSC at 50fps.** Different VI clock (49.66 vs 48.68 MHz), different visible lines (625 vs 525), different output area (640×576 vs 640×480). Test PAL if you target it. PAL60 is non-standard and unsupported by some upscalers.
10. **Save types are hardware-specific.** EEPROM 4K/16K, SRAM 256K/768K/1M, FlashRAM — the flashcart and console must support the type you use. Set `N64_ROM_SAVETYPE` in the Makefile/`.p64proj`. Pyrite64's `romMeta.h` exposes this (`romMeta.h:17-56`).