# Handoff

**Repo:** `https://github.com/chrisgliddon/binface64` (fork of `HailToDodongo/pyrite64`)
**Current branch:** `main`
**Last session:** Phase 1 — N64 Hardware & Systems Research Compendium (2026-07-06)
**Next session:** Phase 2 — Asset Requirements & Limitations Research

This is the **only** memory between sessions. Read it first. Update it before ending a session.

---

## How to use this file

1. **Read order for a fresh session:** this file → `docs/docs/agent/ARCHITECTURE.md` → `docs/docs/agent/CODEMAP.md` → `docs/docs/agent/DIVERGENCE.md` → the relevant `docs/docs/n64/` files (when they exist) → the skill you're working on (when they exist).
2. **Before ending a session:** update the Phase Status Table, the "What this session completed" section, the Open Questions, and the Next Session Instructions. Commit.
3. **Never rely on conversation memory.** If you learned something this session that the next session needs, write it here.

---

## Phase status table

| Phase | Focus | Status | Commit | Session tokens | Notes |
|---|---|---|---|---|---|
| 0 | Codebase recon & architecture map | ✅ Done | `e5f5d7d` | ~moderate | ARCHITECTURE.md, CODEMAP.md, HANDOFF.md (this file), DIVERGENCE.md (early-start) all written |
| 1 | N64 hardware research compendium | ✅ Done | (this session) | ~moderate | 6 docs in docs/docs/n64/: hardware, performance-budgets, libdragon-tiny3d, display-and-video, audio, emulation-and-hardware-testing. n64.rst toctree + index.rst wired. Submodules init'd. |
| 2 | Asset requirements & limitations | ⬜ Not started | — | ~350K est | Next session. See kickoff prompt in `phased-plan.md` Phase 2. |
| 3 | `/skills` scaffold + core engine skills | ⬜ Not started | — | ~300K est | |
| 4 | Asset & content pipeline skills | ⬜ Not started | — | ~300K est | |
| 5 | `bf64` CLI | ⬜ Not started | — | ~400K est | |
| 6 | MCP server | ⬜ Not started | — | ~400K est | |
| 7 | Extensions system | ⬜ Not started | — | ~400K est (splittable 7a/7b) | |
| 8 | CONTRIBUTING.md, vision, agent onboarding | ⬜ Not started | — | ~250K est | |
| 9 | Dogfood micro-game + hardening | ⬜ Not started | — | ~400K est | |

**Cross-session invariants** (from `phased-plan.md`):
- This file is always updated before a session ends — it's the only memory.
- All N64 technical claims cite `docs/docs/n64/`; all API claims are verified against source.
- Upstream Pyrite64 credits stay intact; divergence is tracked in `docs/docs/agent/DIVERGENCE.md`.
- Every new capability ships with a matching skill in `/skills`.

---

## What this session (Phase 1) completed

### Documents created

| File | Purpose |
|---|---|
| `docs/docs/n64/hardware.md` | CPU (VR4300), RCP (RSP+RDP), RDRAM, TMEM, cart bus, DMA. Hard limits table + practical budgets + 10 agent implications. |
| `docs/docs/n64/performance-budgets.md` | Frame budget breakdown, triangle counts, RSP/RDP limits, lighting cost, memory budget, particle budget. Hard limits + practical budgets + 10 agent implications. |
| `docs/docs/n64/libdragon-tiny3d.md` | Version pins, libdragon API surface (display/rdpq/rspq/audio/filesystem/memory/tools), tiny3d API surface (lifecycle/vertex/materials/lighting/animation/culling/particles/textures/model-format), Pyrite64 engine layer. 12 agent implications. |
| `docs/docs/n64/display-and-video.md` | Resolutions, framebuffer formats, VI modes/filtering, Pyrite64's 3 render pipelines (Default/HDR+Bloom/BigTex), VI swapchain. 10 agent implications. |
| `docs/docs/n64/audio.md` | Sample rates, formats (WAV64/XM64/YM64), mixer, memory cost tables, Pyrite64 audio layer, music strategy. 10 agent implications. |
| `docs/docs/n64/emulation-and-hardware-testing.md` | Why accuracy matters, Ares/gopher64, flashcarts (64drive/EverDrive64/SummerCart64), test matrix, common hardware-only bugs. 10 agent implications. |
| `docs/docs/n64.rst` | Toctree for the `n64/` section. |
| `docs/index.rst` | +1 line: `docs/n64` in root toctree. |
| `docs/docs/agent/HANDOFF.md` (this file) | Updated for Phase 1 → Phase 2 transition. |

### Method

Phase 1 was executed by:
1. Running `git submodule update --init --recursive` to check out `vendored/libdragon`, `vendored/tiny3d`, etc.
2. Verifying version pins (libdragon `b1011fe31` "preview" branch, tiny3d `bdcd946`).
3. Launching two parallel `explore` subagents: one deep-reading libdragon's hardware-facing APIs (display/rdpq/rspq/audio/filesystem/memory/tools/n64.mk), one deep-reading tiny3d's rendering capabilities (vertex format/materials/lighting/animation/culling/particles/textures/model-format/RSP ucode).
4. Fetching the n64brew wiki Main Page + VR4300 + RCP + RDRAM + RDP pages for hardware specs not in the vendored source.
5. Synthesizing all three sources into 6 reference docs, each with the required structure (hard limits table, practical budgets, implications for agents).

### Key findings

- **TMEM is 4 KB** (2 KB for RGBA32/CI4/CI8/YUV16). This is the single most important N64 limit for texture decisions.
- **tiny3d's vertex cache is 70 vertices** per RSP load, at 100% DMEM usage. The optimizer splits models into ≤70-vert parts with vertex-cache-aware triangle ordering.
- **7 directional + 7 point lights** (shared pool, `LIGHT_COUNT=7` in the ucode). Profile builds (`RSPQ_PROFILE=1`) clamp to 2.
- **tiny3d's ucode is written from scratch**, not based on proprietary code. No headline "tris at 30fps" figure is published; the closest data point is 8.8 ms RSP for a 3642-vert model.
- **libdragon has three compression levels** (LZ4/APLib/Shrinkler), not the two the header docs claim. LZMA/YAPKI/RNC are NOT present.
- **HDR+Bloom and BigTex pipelines are hard-locked to 320×240 RGBA16** with custom RSP ucodes. BigTex can't clear color.
- **32 mixer channels** (RSP-accelerated). A 10-channel XM costs <3% CPU and <10% RSP.
- **iQue is not real hardware**: CPU/RCP clocks differ (144/96 vs 93.75/62.5 MHz), `sys_hw_memset` falls back to CPU, memory detection differs.
- **Ares (v147+) and gopher64 are the only recommended emulators.** Project64/Android are explicitly not accurate enough.

---

## What this session (Phase 0) completed

### Documents created

| File | Purpose | Lines |
|---|---|---|
| `docs/docs/agent/ARCHITECTURE.md` | Editor, runtime, asset pipeline, build system — full architecture reference with file:line cites. | ~900 |
| `docs/docs/agent/CODEMAP.md` | Directory-by-directory annotated map + entry points index + serialization formats index. | ~350 |
| `docs/docs/agent/HANDOFF.md` (this file) | Session-to-session baton. | — |
| `docs/docs/agent/DIVERGENCE.md` (early-start, mostly complete) | Upstream-relationship & fork-divergence policy. | ~280 |

### Earlier in the same overall session (pre-Phase 0)

| File | Purpose |
|---|---|
| `docs/docs/project/gap-analysis.md` | Migrated from `docs/content/` into the Sphinx tree. |
| `docs/docs/project/phased-plan.md` | Migrated from `docs/content/` into the Sphinx tree. |
| `docs/docs/project.rst` | Toctree for the `project/` section. |
| `docs/docs/agent.rst` | Toctree for the `agent/` section. |
| `docs/index.rst` | +2 lines (`docs/project`, `docs/agent` toctree entries). |

### Method

Phase 0 was executed by launching three parallel `explore` subagents over the repo:
1. **Editor architecture** — mapped `src/main.cpp`, `src/editor/`, `src/project/` boot, main loop, UI framework, pages, project model, scene representation, node-graph scripting, actions/undo, toolchain/update.
2. **N64 runtime architecture** — mapped `n64/engine/` build target, public API surface (`include/`), scene/object/component model, render loop, collision/physics, audio, asset/memory management, script callbacks, examples/tests.
3. **Asset pipeline & project format** — mapped `src/project/assets/`, `src/project/component/`, `src/renderer/`, `src/utils/`, `data/`, GLTF/fast64 import, texture pipeline, material system, audio, node-graph assets, scripts, themes/fonts, build outputs.

Each agent's report was synthesized into the three Phase 0 deliverables. The agents' raw outputs were large (~17KB+ each) and were not retained as separate files — their content is fully folded into ARCHITECTURE.md and CODEMAP.md.

### Key findings (the short version)

- **Two-binary split.** Editor (`src/`, host SDL3/ImGui) and runtime (`n64/engine/`, N64 ROM) are completely separate programs with independent Object/Component models. They share ABI only through three manual relative includes and the binary blobs the editor bakes. Drift between them is silent.
- **CMake dummies.** `n64/CMakeLists.txt` and `n64/examples/*/CMakeLists.txt` are IDE-only; the real build is `n64/engine/Makefile` + per-game generated `Makefile`.
- **13 components** (Code, Model static/anim, Light, Camera, CollMesh, Collider, Audio2D, Constraint, Culling, NodeGraph, RigidBody, CharBody), with editor-side `Component::TABLE` (ids 0-12) and runtime `COMP_TABLE[16]` (ids 0-12) as parallel registries.
- **3 render pipelines** (Default, HDR+Bloom, BigTex-256) — the latter two are hard-locked to 320×240 RGBA16 and use custom hand-written RSP ucodes.
- **Physics is deep.** AABB-tree broadphase, GJK/EPA narrowphase, 6 shapes, RigidBody + MeshCollider + CharacterBody, raycast/sphere-sweep/capsule-sweep. Bullet-style warm starting, split-impulse.
- **Node graphs compile to C++ with `goto`-based coroutines.** Node specs are JS (run in embedded quickjs-ng); ~44 built-in node ids + user nodes from `<project>/nodes/*.js`. Codegen emits `NODE_<uuid>:` labels.
- **Project format:** `.p64proj` JSON + `data/scenes/<id>/scene.json` (object tree) + per-asset `.conf` JSON sidecars. Scenes serialize as `{"conf":..., "graph":<object tree>}` (the `graph` field is the object tree, not a node graph — confusing naming).
- **Whole-scene-snapshot undo**, not command-pattern; cleared on scene switch.
- **All asset pointers invalidated on scene change** (`Scene::~Scene` → `AssetManager::freeAll`).
- **Tests run on-device only** (`n64/tests/test_obj_states/`), self-report via `debugf`/onscreen. No host-side runner.

See ARCHITECTURE.md §5 for the full Gotchas index (~40 items).

---

## Open questions / things to verify in later phases

1. **Vendored submodule contents not checked out** in this workspace. ARCHITECTURE/CODEMAP claims about `vendored/tiny3d/` (glTF importer), `vendored/imgui/` (version), `vendored/quickjs-ng/` (node host) are inferred from call sites and CMake lists, not from reading the submodule source. **Phase 1 should run `git submodule update --init --recursive` and verify the tiny3d glTF importer + libdragon API surface against actual source.**
2. **ImGui version** unknown — `vendored/imgui` not checked out. The editor uses `imgui_internal.h` (`helper.h:27`); the SDL3 GPU backend is unreleased-stable upstream. Phase 8 (CONTRIBUTING/README rewrite) or any ImGui-touching work should pin and record the version.
3. **`P64_DATA` size cap** is `static_assert(sizeof(Data) < 0xFFFF)` (`userScript.h:19`) — 64KB-1 per-instance. Not yet documented whether the editor enforces this at authoring time or only fails at build.
4. **`res_<uuid>` fallback declaration** in node-graph codegen: ARCHITECTURE §1.7 notes that the codegen emits `res_<uuid>` as a fallback value name but the *declaration* of that variable isn't visible in `Graph::build` — it must be declared by the consuming node's `build` or by the runtime header. **Phase 3 (node-graph skill) should verify this by reading a generated `.cpp`** (e.g. from `n64/examples/jam25/src/p64/`).
5. **`codeParser.cpp` fragility** (regex comment-strip, string-offset UUID extraction, `hasFunction` return-type matching) is documented as a GOTCHA but not stress-tested. **Phase 5 (CLI) or Phase 7 (Extensions) should add a parser test if they touch script discovery.**
6. **Mtime-based asset build skip** (`projectBuilder.cpp:288-297`) can skip needed rebuilds on coarse-mtime or clock-skew filesystems. Phase 5 (CLI `bf64 build`) should consider replacing with content-hash, or at least documenting the risk.
7. **`make clean` re-enters the editor binary** (`baseMakefile.mk:64-65`) and re-runs `Project` ctor → engine-file sync → possible forced clean. Recursive clean risk if versions mismatch. Phase 5 should audit this path.
8. **`vendored/tiny3d` glTF importer** handles materials, bones, animations, BVH, mesh optimization. The exact material feature set (which fast64 CC modes, which blender modes) needs Phase 2 verification against the actual importer source for the asset skills to be authoritative.
9. **Audio: `audioconv64` flags applied to `.mp3` input** — undocumented whether mp3 accepts `--wav-*` flags. Phase 2 (audio-assets.md) should verify by running audioconv64 on a fixture mp3.
10. **Two parallel UUID systems** (32-bit scene object uuids vs 64-bit asset/prefab/component uuids) — a documented class of bugs. Not yet audited for actual mismatches. Phase 5/7 should be careful.

---

## Next session instructions (Phase 2)

**Phase:** 2 — Asset Requirements & Limitations Research
**Estimated tokens:** ~350K
**Kickoff prompt:** see `docs/docs/project/phased-plan.md` Phase 2 section (lines 125-170).

**Before starting:**
1. Submodules are now checked out (Phase 1 ran `git submodule update --init --recursive`). The vendored libdragon/tiny3d source is available.
2. Read this file, then the `docs/docs/n64/` compendium (especially `hardware.md`, `libdragon-tiny3d.md`, `display-and-video.md`, `audio.md`), then `ARCHITECTURE.md` §3 (asset pipeline), then `CODEMAP.md` §8 (serialization formats index).

**Outputs (per phased-plan.md):**
- `docs/docs/n64/textures.md` — every texture format (RGBA16/32, CI4/CI8, IA4/8/16, I4/I8), TMEM fitting math, mipmaps, palettes, big-texture streaming technique
- `docs/docs/n64/models-and-meshes.md` — vertex budgets, GLTF→fast64→tiny3d pipeline, material system, skinning/animation limits, what fast64 materials map to
- `docs/docs/n64/audio-assets.md` — format conversion, sample-rate/memory tradeoff tables, music (sequenced vs streamed) guidance
- `docs/docs/n64/rom-budgets.md` — cart sizes (4–64MB), compression, asset packing in BF64, how to budget a whole game
- `docs/docs/n64/asset-checklist.md` — one-page pre-flight checklist an agent runs before importing any asset

**Each doc must:**
- Lead with a "Hard limits" table up top.
- Distinguish engine-enforced limits (cite the enforcing code path) from hardware limits from best-practice budgets.
- End with "Implications for BF64 agents" — 5-10 bullet rules of thumb.
- Where sources disagree, note the disagreement and pick the conservative number.

**Section wiring:** each new `docs/docs/n64/*.md` is already wired into `docs/docs/n64.rst` — add the new pages to the existing toctree (no new `.rst` or `index.rst` line needed; the `n64` section is already wired).

**Research sources:**
1. The actual asset pipeline code in this repo (find the texture converter, GLTF importer, ROM packer — CODEMAP.md tells you where).
2. libdragon/tiny3d docs (now checked out in `vendored/`).
3. The Phase 1 compendium (`docs/docs/n64/`) as the hardware/formats ground truth.
4. Pyrite64 docs and the fast64 settings doc (`vendored/tiny3d/docs/fast64Settings.md`).

**Open questions from Phase 0/1 to resolve in Phase 2:**
- Verify `audioconv64` behavior on `.mp3` input with `--wav-*` flags (Phase 0 open question #9).
- Verify the tiny3d glTF importer's exact material feature set (which fast64 CC modes, which blender modes) against the actual importer source (`vendored/tiny3d/tools/gltf_importer/`).

**Commit message:** `docs(n64): phase 2 asset requirements`

**Update this file** before ending the session.

---

## Decisions made this session

1. **Hugo migration declined.** Original user request was to migrate docs to Hugo with a dark-mode Bootstrap-skinnable theme. After analysis, we instead migrated the BF64 planning docs (`docs/content/`) into the existing Sphinx/MyST tree as `docs/docs/project/` — staying rebaseable against upstream's `conf.py`/`Makefile`/`build_and_serve.sh` (see DIVERGENCE.md §6 for the rationale: changing the doc toolchain would diverge 5 shared files simultaneously, exactly what rebase hygiene exists to prevent).
2. **`docs/docs/agent/` and `docs/docs/n64/` will live under `docs/docs/`** (option A from the planning conversation), not at repo-top-level `docs/agent/`/`docs/n64/` as the phased plan's text literally says. This matches the existing tree structure (`docs/docs/manual/`, `docs/docs/dev/`, `docs/docs/version/`, `docs/docs/faq`, `docs/docs/project/`). The phased-plan.md path references (`docs/agent/...`, `docs/n64/...`) are now stale for these sections; the actual paths are `docs/docs/agent/...` and `docs/docs/n64/...`. **Phase 8 (CONTRIBUTING rewrite) should update phased-plan.md's path references, or note the convention in DIVERGENCE.md.**
3. **DIVERGENCE.md written as an early-start on Phase 0.** The phased plan lists it as a Phase 0 output; we wrote it earlier (in the same overall session, before the formal Phase 0 recon) because the fork-strategy decision was needed first to scope the recon. It's effectively complete; Phase 0's remaining job was ARCHITECTURE/CODEMAP/HANDOFF.
4. **Three parallel explore subagents** were used for the recon to fit the work in budget and keep the main context for synthesis. Their raw outputs were not retained as files — content is folded into ARCHITECTURE/CODEMAP.

---

## Known issues carried forward

- **`phased-plan.md` path references** say `docs/agent/` and `docs/n64/` but the actual convention is `docs/docs/agent/` and `docs/docs/n64/`. Stale until Phase 8.
- **`res_<uuid>` fallback declaration** in node-graph codegen (Phase 0 open question #4) — still unverified. Phase 3 should check a generated `.cpp` from `n64/examples/jam25/src/p64/`.
- **`codeParser.cpp` fragility** (Phase 0 open question #5) — not stress-tested. Phase 5/7 should add a parser test if they touch script discovery.
- **Mtime-based asset build skip** (Phase 0 open question #6) — Phase 5 should audit.
- **`make clean` re-enters editor binary** (Phase 0 open question #7) — Phase 5 should audit.
- **Two parallel UUID systems** (Phase 0 open question #10) — not audited for actual mismatches. Phase 5/7 should be careful.
- **`audioconv64` flags on `.mp3` input** (Phase 0 open question #9) — deferred to Phase 2.
- **tiny3d glTF importer exact material feature set** (Phase 0 open question #8) — deferred to Phase 2.
- **ImGui version** still unknown (vendored/imgui is now checked out at `913a3c6` but the version string wasn't read this session). Phase 8 or any ImGui-touching work should record it.

---

## Quick links (the canonical read order for a fresh session)

1. **This file** (`docs/docs/agent/HANDOFF.md`)
2. `docs/docs/agent/ARCHITECTURE.md` — how the engine works
3. `docs/docs/agent/CODEMAP.md` — where to find things
4. `docs/docs/agent/DIVERGENCE.md` — fork policy & upstream relationship
5. `docs/docs/project/phased-plan.md` — the 10-phase plan
6. `docs/docs/project/gap-analysis.md` — why BF64 exists
7. `docs/docs/n64/*` — hardware/SDK reference (Phase 1 done: hardware, performance-budgets, libdragon-tiny3d, display-and-video, audio, emulation-and-hardware-testing; Phase 2 pending: textures, models-and-meshes, audio-assets, rom-budgets, asset-checklist)
8. `/skills/*` — agent skills (Phase 3–4, not yet created)
9. `docs/cli.md`, `docs/mcp.md`, `docs/extensions/DESIGN.md` — machine interfaces (Phase 5–7, not yet created)
10. `AGENTS.md` / `CLAUDE.md` — repo-root agent onboarding (Phase 8, not yet created)