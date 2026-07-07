# Handoff

**Repo:** `https://github.com/chrisgliddon/binface64` (fork of `HailToDodongo/pyrite64`)
**Current branch:** `main`
**Last session:** Phase 0 — Codebase Reconnaissance & Architecture Map (2026-07-06)
**Next session:** Phase 1 — N64 Hardware & Systems Research Compendium

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
| 0 | Codebase recon & architecture map | ✅ Done | (this session) | ~moderate | ARCHITECTURE.md, CODEMAP.md, HANDOFF.md (this file), DIVERGENCE.md (early-start) all written |
| 1 | N64 hardware research compendium | ⬜ Not started | — | ~350K est | Next session. See kickoff prompt in `phased-plan.md` Phase 1. |
| 2 | Asset requirements & limitations | ⬜ Not started | — | ~350K est | |
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

## Next session instructions (Phase 1)

**Phase:** 1 — N64 Hardware & Systems Research Compendium
**Estimated tokens:** ~350K
**Kickoff prompt:** see `docs/docs/project/phased-plan.md` Phase 1 section (lines 73-121).

**Before starting:**
1. Run `git submodule update --init --recursive` to get `vendored/libdragon`, `vendored/tiny3d`, etc. — Phase 1 needs to read the actual libdragon/tiny3d source/docs as ground truth.
2. Read this file, then `ARCHITECTURE.md` (esp. §2.4 render pipelines, §2.5 collision, §2.6 audio, §2.7 asset/memory), then `DIVERGENCE.md`.

**Outputs (per phased-plan.md):**
- `docs/docs/n64/hardware.md` — CPU (VR4300), RCP (RSP + RDP), RDRAM (4MB / 8MB Expansion Pak), TMEM (4KB), cart bus, DMA, bandwidth constraints
- `docs/docs/n64/performance-budgets.md` — practical frame budgets: triangle counts, fill rate, RSP microcode limits, what tiny3d achieves vs stock microcode
- `docs/docs/n64/libdragon-tiny3d.md` — what libdragon and tiny3d actually provide, constraints, idioms, versions vendored in BF64
- `docs/docs/n64/display-and-video.md` — resolutions, framebuffer formats, VI filtering, NTSC/PAL, HDR+Bloom and big-texture techniques Pyrite64 already supports
- `docs/docs/n64/audio.md` — mixer channels, sample rates, memory cost of audio, formats libdragon supports
- `docs/docs/n64/emulation-and-hardware-testing.md` — Ares (v147+), gopher64, flashcarts, why accuracy matters, test matrix

**Each doc must:**
- Lead with a "Hard limits" table up top (HARD hardware limits vs SOFT practical budgets, labeled).
- Have a "Practical budgets" section with real-world numbers, citing sources inline as URLs.
- End with "Implications for BF64 agents" — 5-10 bullet rules of thumb.
- Where sources disagree, note the disagreement and pick the conservative number.

**Section wiring:** each new `docs/docs/n64/*.md` needs a matching `docs/docs/n64.rst` toctree + one line added to `docs/index.rst` (per DIVERGENCE.md §6 — the only allowed `docs/` divergence pattern).

**Research sources (priority order):**
1. Vendored libdragon and tiny3d source/docs in this repo (ground truth for what BF64 can actually do).
2. libdragon docs (libdragon.dev), tiny3d README/docs (github.com/HailToDodongo/tiny3d).
3. N64brew wiki (n64brew.dev) for hardware specs.
4. Pyrite64 docs (hailtododongo.github.io/pyrite64) and FAQ.

**Cross-reference ARCHITECTURE.md §2.4-§2.7** — it already documents what the engine *does*; Phase 1 documents what the *hardware* allows, so the two are complementary. Don't duplicate engine behavior; cite it.

**Commit message:** `docs(n64): phase 1 hardware compendium`

**Update this file** before ending the session.

---

## Decisions made this session

1. **Hugo migration declined.** Original user request was to migrate docs to Hugo with a dark-mode Bootstrap-skinnable theme. After analysis, we instead migrated the BF64 planning docs (`docs/content/`) into the existing Sphinx/MyST tree as `docs/docs/project/` — staying rebaseable against upstream's `conf.py`/`Makefile`/`build_and_serve.sh` (see DIVERGENCE.md §6 for the rationale: changing the doc toolchain would diverge 5 shared files simultaneously, exactly what rebase hygiene exists to prevent).
2. **`docs/docs/agent/` and `docs/docs/n64/` will live under `docs/docs/`** (option A from the planning conversation), not at repo-top-level `docs/agent/`/`docs/n64/` as the phased plan's text literally says. This matches the existing tree structure (`docs/docs/manual/`, `docs/docs/dev/`, `docs/docs/version/`, `docs/docs/faq`, `docs/docs/project/`). The phased-plan.md path references (`docs/agent/...`, `docs/n64/...`) are now stale for these sections; the actual paths are `docs/docs/agent/...` and `docs/docs/n64/...`. **Phase 8 (CONTRIBUTING rewrite) should update phased-plan.md's path references, or note the convention in DIVERGENCE.md.**
3. **DIVERGENCE.md written as an early-start on Phase 0.** The phased plan lists it as a Phase 0 output; we wrote it earlier (in the same overall session, before the formal Phase 0 recon) because the fork-strategy decision was needed first to scope the recon. It's effectively complete; Phase 0's remaining job was ARCHITECTURE/CODEMAP/HANDOFF.
4. **Three parallel explore subagents** were used for the recon to fit the work in budget and keep the main context for synthesis. Their raw outputs were not retained as files — content is folded into ARCHITECTURE/CODEMAP.

---

## Known issues carried forward

- **Vendored submodules not checked out** in this workspace. All claims about tiny3d/ImGui/quickjs-ng internals are inferred. Phase 1 should check them out.
- **`phased-plan.md` path references** say `docs/agent/` and `docs/n64/` but the actual convention is `docs/docs/agent/` and `docs/docs/n64/`. Stale until Phase 8.
- **No `docs/docs/n64.rst` or `docs/docs/n64/` section yet** — created in Phase 1.
- **`vendored/` directory has empty subdirs** in this checkout — `ls vendored/tiny3d` returns nothing. Not a bug; submodules just need init.

---

## Quick links (the canonical read order for a fresh session)

1. **This file** (`docs/docs/agent/HANDOFF.md`)
2. `docs/docs/agent/ARCHITECTURE.md` — how the engine works
3. `docs/docs/agent/CODEMAP.md` — where to find things
4. `docs/docs/agent/DIVERGENCE.md` — fork policy & upstream relationship
5. `docs/docs/project/phased-plan.md` — the 10-phase plan
6. `docs/docs/project/gap-analysis.md` — why BF64 exists
7. `docs/docs/n64/*` — hardware/asset reference (Phase 1–2, not yet created)
8. `/skills/*` — agent skills (Phase 3–4, not yet created)
9. `docs/cli.md`, `docs/mcp.md`, `docs/extensions/DESIGN.md` — machine interfaces (Phase 5–7, not yet created)
10. `AGENTS.md` / `CLAUDE.md` — repo-root agent onboarding (Phase 8, not yet created)