# N64 Hardware Reference

**Audience:** LLM agents building games with Binface64. Optimize for precision — numbers, not prose.
**Last reviewed:** 2026-07-06. Sources cited inline. Where sources disagree, the conservative number is picked and noted.
**Scope:** the N64 console hardware — CPU, RCP (RSP + RDP), RDRAM, TMEM, cart bus, DMA. For the software stack on top (libdragon/tiny3d), see `libdragon-tiny3d.md`. For display specifics, see `display-and-video.md`. For audio, see `audio.md`.

---

## Hard limits

| Resource | Hard limit | Source |
|---|---|---|
| CPU clock (real N64) | 93.75 MHz | `vendored/libdragon/include/n64sys.h:53` `CPU_FREQUENCY = __boot_consoletype ? 144000000 : 93750000`; [n64brew VR4300](https://n64brew.dev/wiki/VR4300) |
| CPU clock (iQue) | 144 MHz | same |
| RCP clock (real N64) | 62.5 MHz | `vendored/libdragon/include/n64sys.h:48` `RCP_FREQUENCY = __boot_consoletype ? 96000000 : 62500000` |
| RCP clock (iQue) | 96 MHz | same |
| Count register tick rate | CPU_FREQUENCY/2 (46.875 MHz real / 72 MHz iQue) | `vendored/libdragon/include/n64sys.h:232` `TICKS_PER_SECOND` |
| Count register overflow | ~91.625 s | `vendored/libdragon/include/n64sys.h:212` |
| RDRAM (base) | 4 MiB (4,194,304 bytes) | `vendored/libdragon/include/n64sys.h:511` `get_memory_size()`; [n64brew RDRAM](https://n64brew.dev/wiki/RDRAM) |
| RDRAM (Expansion Pak) | 8 MiB | `vendored/libdragon/include/n64sys.h:526` `is_memory_expanded()` |
| RDRAM extra bit | 1 extra bit per byte, usable only by RDP/VI (AA coverage) | [n64brew RDRAM](https://n64brew.dev/wiki/RDRAM) |
| Linker ELF cap | 8 MiB − 64 KiB stack − 1 KiB low mem | `vendored/libdragon/n64.ld:197` |
| TMEM (texture memory) | 4 KB (4096 B), but only 2 KB usable for RGBA32/CI4/CI8/YUV16 | `vendored/libdragon/src/rdpq/rdpq_tex.c:188` (`tmem_size = ... ? 2048 : 4096`); [n64brew RDP](https://n64brew.dev/wiki/Reality_Display_Processor) |
| RDP tile descriptors | 8 (TILE0–TILE7) | `vendored/libdragon/include/rdpq.h:254-263` |
| Max texture coord | 1023 px (10.2 fixed-point 0xFFF) | `vendored/libdragon/include/rdpq.h:468-469,557,684` |
| Max framebuffer | 800×720 px | `vendored/libdragon/src/display.c:363-364` |
| RSPQ max command size | 62 32-bit words (248 B) | `vendored/libdragon/include/rspq.h:200` |
| RSPQ max overlays | 16 | `vendored/libdragon/include/rspq_constants.h:18-21` |
| RSPQ block nesting | 8 | `vendored/libdragon/include/rspq_constants.h:37` |
| Mixer channels | 32 | `vendored/libdragon/include/mixer.h:59` `MIXER_MAX_CHANNELS` |
| DFS max file size | 256 MiB | `vendored/libdragon/include/dragonfs.h:33` |
| DFS open files | 4 simultaneous | `vendored/libdragon/include/dragonfs.h:35` |
| Cache line size | 16 bytes | `vendored/libdragon/include/n64sys.h:399,404-407` |
| Stack reservation | 64 KiB (linker assert) | `vendored/libdragon/n64.ld:197` |
| NTSC V_TOTAL | 526 (525 visible lines) | `vendored/libdragon/src/vi.c:32` |
| PAL V_TOTAL | 626 (625 visible lines) | `vendored/libdragon/src/vi.c:44` |
| VI/AI clock (NTSC) | 48,681,818 Hz | `vendored/libdragon/src/vi.c:24`, `src/audio.c:24` |
| VI/AI clock (PAL) | 49,656,530 Hz | `vendored/libdragon/src/vi.c:25`, `src/audio.c:26` |
| VI/AI clock (MPAL) | 48,628,322 Hz | `vendored/libdragon/src/vi.c:26`, `src/audio.c:28` |
| VI registers | 14 × 32-bit at 0xA4400000 | `vendored/libdragon/include/vi.h:171,175` |
| PI registers | 5 × 32-bit at 0xA4600000 | `vendored/libdragon/include/dma.h:44-48` |

---

## 1. CPU — VR4300

The N64's CPU is a **NEC VR4300** (modified MIPS R4300i derivative), running at **93.75 MHz** on real hardware, 144 MHz on iQue. It's a 64-bit MIPS III CPU with an integrated FPU (exposed as CP1) and a system control coprocessor (CP0) containing an MMU and TLB. ([n64brew VR4300](https://n64brew.dev/wiki/VR4300))

**ABI:** libdragon uses the **o64 ABI** (`-march=vr4300 -mtune=vr4300 -mabi=o64`, `vendored/libdragon/n64.mk:74,82`), so the full 64-bit register file and 64-bit integer ops are available. This is a notable difference from libultra (Nintendo's official SDK), which used a 32-bit ABI and could not use 64-bit registers/opcodes.

**FPU (CP1):** 32-bit and 64-bit floating point. libdragon compiles with `-ffast-math -ftrapping-math -fno-associative-math` (`n64.mk:74`) — fast but not IEEE-compliant; do not assume strict FP behavior.

**Known CPU bugs** ([n64brew VR4300 §5](https://n64brew.dev/wiki/VR4300)):
- **Multiplication bug** (early units NUS-01/02/03): incorrect FP mul results under certain circumstances. GCC has `-mfix4300` (inserts 2 nops after every `mul.s`/`mul.d`/`mult`). Not enabled by libdragon by default.
- **32-bit `sra`/`srav` bug**: fills MSBs with upper-32-bit state instead of the sign bit, leaking 64-bit state into 32-bit operations. Rare to hit in practice because most 32-bit instructions sign-extend.
- **Sign-extension bugs in `mult`/`div`**: inputs not properly sign-extended; `mult` acts as 64×35-bit, `div` as 32×35-bit. Counter-intuitive; avoid relying on 32-bit mult/div with non-sign-extended inputs.

**Count register:** ticks at CPU_FREQUENCY/2 = 46.875 MHz, overflows every ~91.625 s. Use `TICKS_DISTANCE`/`get_ticks()` (64-bit) for intervals > 45 s (`n64sys.h:212,250-253`). **GOTCHA:** `srand(time(NULL))` is rewritten to a compile-time error in libdragon — no RTC is guaranteed; use `getentropy32()` (`n64sys.h:772-776`).

---

## 2. RCP — Reality Coprocessor

The RCP is the second main processor, running at **62.5 MHz** on real hardware (96 MHz on iQue). It contains two subsystems: the **RSP** (programmable) and the **RDP** (fixed-function). The RCP sits between the CPU and RDRAM — the CPU must go through the RCP to access RDRAM. ([n64brew RCP](https://n64brew.dev/wiki/Reality_Coprocessor))

### 2.1 RSP — Reality Signal Processor

A programmable MIPS processor with custom SIMD instructions for vectorized fixed-point operations (exposed as COP2). The RSP:
- Runs **microcode (ucode)** loaded into its IMEM (instruction memory, 4 KB) and DMEM (data memory, 4 KB).
- Performs matrix math, lighting, clipping, shading, and other parallel graphics tasks.
- Can directly drive the RDP by writing to its registers.
- Also handles audio mixing (the mixer ucode runs on the RSP).
- Communicates with the CPU via a lockless command queue (**rspq**): the CPU enqueues commands, the RSP pulls and executes them concurrently (`vendored/libdragon/include/rspq.h:16-23`).

**RSPQ architecture:**
- Low-priority buffer: 2 KB, double-buffered (`rspq_constants.h:13`).
- High-priority buffer: 512 B (`rspq_constants.h:14`) — preempts normal queue between commands; used for audio.
- DMEM buffer: 256 B (`rspq_constants.h:16`).
- Up to 16 overlays can be registered (`rspq_constants.h:18-21`); each overlay exposes up to 240 commands.
- Blocks (pre-recorded command sequences) can nest 8 levels deep (`rspq_constants.h:37`).
- Syncpoints are interrupt-based — "tens per frame OK, not hundreds/thousands" (`rspq.h:243-245`).

**GOTCHA:** RSP cannot be fully preempted — switching to highpri only happens between commands; long-running RSP commands hurt audio latency (`rspq.h:151-155`).

### 2.2 RDP — Reality Display Processor

A fixed-function rasterizer. It receives commands from the RSP (or CPU via the RSP) and:
- Draws triangles, rectangles, fills, textured blits.
- Has **4 KB of texture memory (TMEM)** — the central bottleneck for 3D.
- Performs Z-buffering, texturing, color combining, blending, anti-aliasing.
- Writes results to the framebuffer in RDRAM, which the VI then displays.

**TMEM details** (the single most important N64 limit for an agent to internalize):
- Total: 4096 bytes.
- RGBA32, CI4, CI8, YUV16 only get **2048 bytes** usable because their data is stored in TMEM's upper half / split / palette-aliased (palette lives at `TMEM_PALETTE_ADDR 0x800` = 2048, `rdpq_tex.c:32-33`). TLUT stores 256 × 16-bit colors × 4 replication = 2048 B = half of TMEM (`rdpq.h:599-607`).
- 8 tile descriptors (TILE0–TILE7, `rdpq.h:254-263`).
- Max 2048 texels per `rdpq_load_block` call (`rdpq.h:734-737`).
- Max texture coordinate: 1023 px (10.2 fixed-point, `rdpq.h:468-469`).
- **Auto-TMEM** (`rdpq_set_tile_autotmem`, `rdpq.h:848`) lets rdpq manage TMEM fitting transparently, but overflow is a **runtime RSP assert**, not compile-time (`rdpq.c:574-575`).

**RDP cycle modes:**
- **1-cycle (1cyc):** faster, preferred. rdpq auto-selects when possible.
- **2-cycle (2cyc):** ~2× slower (two blender passes), required for fog, two-pass blender, or 2nd combiner. rdpq auto-promotes when needed (`rdpq.c:94-131`).
- **Copy:** 4× fast, 16bpp only, CI4/CI8/RGBA16 only, Y-scale only, no rotation/mirror (`rdpq_mode.h:27-46`).
- **Fill:** 4×, fill rect, no blend.

---

## 3. RDRAM

**4 MiB base** (one 2 MiB module on-board). The **Expansion Pak** adds a second 2 MiB module for **8 MiB total**. The iQue Player reports 8 MiB only if exactly 8 MiB is assigned (`n64sys.h:523-525`). ([n64brew RDRAM](https://n64brew.dev/wiki/RDRAM))

**Extra bit:** each byte of RDRAM has an extra (9th) bit usable only by the RDP and VI core — typically stores AA coverage in the color buffer. Not accessible to the CPU.

**Memory map:**
- KSEG0 cached: `0x80000000` (`n64sys.h:58`).
- Uncached alias: `0xA0000000` (`n64sys.h:104`).
- `.intvectors` at `0x80000000`, `.text` at `0x80000400` (`n64.ld:23,32`).
- Heap starts at `HEAP_START_ADDR = __bss_end` (`n64sys.h:195`).
- Linker asserts ELF fits in 8 MiB − 64 KiB stack − 1 KiB low (`n64.ld:197`).

**Bandwidth:** RDRAM is the system's central bottleneck. The CPU is "very bandwidth-limited on RDRAM accesses" (`vendored/libdragon/include/mixer.h:46-56`). Hardware memset (`sys_hw_memset*`) uses MI repeat mode for ~6× 64-bit / ~12× 32-bit speedup (`n64sys.h:698-700`) — **GOTCHA:** unsupported on iQue, falls back to CPU memset (`n64sys.h:710-712`).

**Uncached allocations:** `malloc_uncached`/`malloc_uncached_aligned`/`free_uncached`/`realloc_uncached` (`n64sys.h:575-617`) return pointers in `0xA0000000` segment with no cacheline sharing — required for DMA targets (RSP, RDP, audio buffers).

**Layout optimization:** libdragon deliberately places the Z-buffer in the **last RDRAM bank** via `sbrak_top` for bandwidth gain (`display.c:599-602`). Framebuffers are allocated separately.

---

## 4. Cart bus / PI (Parallel Interface)

The PI (Parallel Interface) is the cart bus. Registers at `0xA4600000` (`vendored/libdragon/include/dma.h:44-48`):
- `PI_DRAM_ADDR 0xA4600000` — RDRAM address for DMA.
- `PI_CART_ADDR 0xA4600004` — cart ROM address for DMA.
- `PI_RD_LEN / PI_WR_LEN` — DMA length.
- `PI_STATUS 0xA4600010` — status/control.

**CPU-accessible PI ranges** (`dma.h:215-221`):
- `0x0500_0000–0x0FFF_FFFF` — N64DD / SRAM.
- `0x1000_0000–0x1FBF_FFFF` — cart ROM.
- `0x1FD0_0000–0x7FFF_FFFF` — other.

**DMA:** `dma_read`/`dma_write` (`dma.h:93,165`) — **GOTCHA:** these mangle the address into the ROM range `0x10000000–0x1FFFFFFF` (historical bug, `dma.h:87-92,159-163`); use `dma_read_async`/`dma_write_raw_async` for full 32-bit PI space. Alignment: RAM `%8`, PI `%2`, length `%2` for raw async (`dma.h:73,116`).

**ROM filesystem (rompak / DFS):** assets are packed into the ROM as a read-only FAT-like filesystem (DragonFS), registered under `rom:/` prefix. Generated by the `mkdfs` tool (`dragonfs.h:23`). Max file size 256 MiB, max 4 simultaneous open files (`dragonfs.h:33-35`). **GOTCHA:** DFS does NOT support compression — use the asset API (`asset_load`/`asset_fopen`) for compression (`dragonfs.h:44-45`). **GOTCHA:** DFS file data is only 2-byte aligned, not 4-byte (`dragonfs.h:258-259`).

**SD card:** `sd:/` prefix via FAT (ChaN FatFS, `src/fatfs/ff.c`). SD access through flashcart hardware (libcart). `asset_load` works with both `rom:/` and `sd:/`.

**Compression (asset API, NOT DFS):** three levels (`src/asset.c:47-92`):
- Level 0: none.
- Level 1 (default): **LZ4** (Yann Collet) — always linked, decompression faster than loading uncompressed.
- Level 2: **APLib** (header docs say "LZH5" but code uses APLib — stale docs).
- Level 3: **Shrinkler** (also a minishrinkler compress-side variant).
- **GOTCHA:** LZMA / YAPKI / RNC are NOT present in this libdragon commit. If an agent sees those names in old docs, they're wrong.
- `asset_init_compression(level)` must be called for levels 2 and 3 before loading (`asset.c:228-233`).

---

## 5. Practical budgets

These are SOFT practical budgets, not hard limits. See `performance-budgets.md` for detailed derivation.

| Budget | Value | Notes |
|---|---|---|
| Target frame time (60fps) | 16.67 ms | NTSC; PAL 60 = 16.67ms, PAL 50 = 20ms |
| Target frame time (30fps) | 33.33 ms | the common 3D target |
| Triangles per frame (30fps, tiny3d) | ~2,000–5,000 practical | depends on lighting (1-7 lights), texture switches, fill rate |
| Vertices per RSP load | 70 (hard) | `vendored/tiny3d/src/t3d/t3d.h:17` `T3D_VERTEX_CACHE_SIZE` |
| Lights per frame | 7 directional + 7 point (hard), 1-2 practical | `vendored/tiny3d/rsp/rsp_tiny3d.rspl:15` `LIGHT_COUNT 7`; with `RSPQ_PROFILE` clamped to 2 |
| Particles per draw (S8) | 344 (hard) | `vendored/tiny3d/src/tpx/tpx.c:19` `MAX_PARTICLES_S8` |
| Particles per draw (S16) | 228 (hard) | `vendored/tiny3d/src/tpx/tpx.c:20` `MAX_PARTICLES_S16` |
| Mixer channels (hard) | 32 | `vendored/libdragon/include/mixer.h:59` |
| Code budget (ROM ELF) | ~8 MiB − 64 KiB stack − 1 KiB | `vendored/libdragon/n64.ld:197` |
| Typical heap available | ~3.5 MiB (4MB system) / ~7.5 MiB (8MB) | after code + stack + framebuffers + Z + audio buffers |

---

## Implications for BF64 agents

1. **TMEM is 4 KB. Every texture decision flows from this number.** A 64×64 RGBA16 texture = 8 KB and does NOT fit in TMEM at all — you need CI4/CI8/I4/I8 or smaller dimensions, OR the BigTex streaming pipeline (which is a scene-level mode, not per-texture). See `display-and-video.md` and `textures.md` (Phase 2).
2. **RDRAM is the real bottleneck, not the CPU.** 4 MiB total minus code minus framebuffers minus Z minus audio buffers leaves ~3.5 MiB for assets. The Expansion Pak doubles this but you cannot assume it's present — detect with `is_memory_expanded()` and degrade gracefully.
3. **The two-processor split (CPU + RCP) means you must think about RSP time AND CPU time AND RDP fill rate.** A scene that's triangle-cheap but fill-rate-heavy (big transparent sprites, fog, post-process) can still drop frames. Profile with `RSPQ_PROFILE=1` (but note: profile builds reduce lights 7→2 and break vertex FX — see `libdragon-tiny3d.md`).
4. **Count register overflows every ~91.6 s.** Use 64-bit `get_ticks()` / `TICKS_DISTANCE` for any interval that could exceed 45 s. Never use `time(NULL)` — it's a compile error in libdragon; use `getentropy32()` for RNG seed.
5. **DMA alignment matters.** RAM must be 8-byte aligned for DMA; PI 2-byte; length 2-byte. Use `malloc_uncached` for DMA targets (RSP/RDP/audio) — cached memory will corrupt.
6. **DFS is read-only and compression-blind.** Assets in `rom:/` are not compressed by DFS; use `asset_load`/`asset_fopen` (with `mkasset -c <level>`) for LZ4/APLib/Shrinkler compression. Streaming windows are 2–256 KiB (default 4 KiB).
7. **iQue is not real hardware.** CPU/RCP clocks differ (144/96 MHz vs 93.75/62.5 MHz), `sys_hw_memset` falls back to CPU, memory detection differs. Test on real N64 or accurate emulator (Ares) — see `emulation-and-hardware-testing.md`.
8. **Don't assume 8 MiB.** The base N64 has 4 MiB. Always check `is_memory_expanded()` before allocating large heaps, and design the game to fit in 4 MiB if possible.
9. **The 9th RDRAM bit is invisible to CPU code.** It stores AA coverage in the color buffer, managed by the RDP/VI. You can't read or write it from C++.
10. **PI address mangling is a historical bug.** `dma_read`/`dma_write` force addresses into `0x10000000–0x1FFFFFFF`. For non-ROM PI space (SRAM, 64DD), use `dma_read_async`/`dma_write_raw_async`.