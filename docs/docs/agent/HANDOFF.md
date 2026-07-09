# Handoff

**Repo:** `https://github.com/chrisgliddon/binface64` (fork of `HailToDodongo/pyrite64`)
**Current branch:** `main`
**Last session:** Asset import command (2026-07-09)
**Next session:** Phase 5 hardening — prefab/node-graph validators and duplicate UUID repair

This is the **only** memory between sessions. Read it first. Update it before ending a session.

---

## How to use this file

1. **Read order for a fresh session:** this file → `docs/docs/agent/AGENTIC_SURFACE.md` → `docs/docs/agent/ARCHITECTURE.md` → `docs/docs/agent/CODEMAP.md` → `docs/docs/agent/DIVERGENCE.md` → the relevant `docs/docs/n64/` files (when they exist) → the skill you're working on (when they exist).
2. **Before ending a session:** update the Phase Status Table, the "What this session completed" section, the Open Questions, and the Next Session Instructions. Commit.
3. **Never rely on conversation memory.** If you learned something this session that the next session needs, write it here.

---

## Phase status table

| Phase | Focus | Status | Commit | Session tokens | Notes |
|---|---|---|---|---|---|
| 0 | Codebase recon & architecture map | ✅ Done | `e5f5d7d` | ~moderate | ARCHITECTURE.md, CODEMAP.md, HANDOFF.md (this file), DIVERGENCE.md (early-start) all written |
| 1 | N64 hardware research compendium | ✅ Done | (this session) | ~moderate | 6 docs in docs/docs/n64/: hardware, performance-budgets, libdragon-tiny3d, display-and-video, audio, emulation-and-hardware-testing. n64.rst toctree + index.rst wired. Submodules init'd. |
| 2 | Asset requirements & limitations | ✅ Done | (this session) | ~moderate | 5 docs in docs/docs/n64/: textures, models-and-meshes, audio-assets, rom-budgets, asset-checklist. n64.rst toctree updated. 3 parallel explore subagents over vendored tiny3d gltf_importer, libdragon audioconv64/mixer, mksprite/rdpq_tex/BCI. Both Phase 0 open questions #8 (glTF material set) and #9 (audioconv64 .mp3) resolved. Sphinx build verified (3 pre-existing warnings, none new). |
| 3 | `/skills` scaffold + core engine skills | ⬜ Not started | — | ~300K est | Next session. See kickoff prompt in `phased-plan.md` Phase 3. |
| 4 | Asset & content pipeline skills | ⬜ Not started | — | ~300K est | |
| 5 | `bf64` CLI | 🌱 Seeded | (this session) | ~400K est | Out-of-order seed now includes root `./bf64`, `--version`, `doctor`, `new`, `import`, `project status`, dry-run/executable `build`, `run`, asset/project/scene validation, read-only `asset ls/show/validate-all`, read-only `scene ls/show/validate`, history schema v2, fixture tests, and CLI CI. Not the full Phase 5 CLI yet. |
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

## What this session (asset import command) completed

This session added `./bf64 import` as the asset-ingestion half of the agent create-import-build-run loop. It validates before mutation, copies one supported editor asset into `assets/`, writes a fresh sidecar UUID, and records the imported files in history.

### Files updated

| File | Change |
|---|---|
| `tools/bf64.py` | Bumped CLI to `0.9.0`; added `import`, `--dest`, `--force`, `--dry-run`, sidecar defaults, fresh UUIDs, import-time validator reuse, stale generated-output removal on overwrite, and import history artifacts. |
| `tests/test_bf64_cli.py` | Added tests for texture import, dry-run, overwrite refusal, invalid preflight with no mutation, forced overwrite cleanup, and `import --record`. |
| `docs/docs/agent/AGENTIC_SURFACE.md` | Documented import examples, supported extensions, dry-run/force behavior, history artifacts, and current limits. |
| `docs/docs/agent/HANDOFF.md` | Recorded this session and updated the Phase 5 seed status. |

### Current preferred commands

- `./bf64 --version`
- `./bf64 new ./projects/agent_game --name "Agent Game" --json`
- `./bf64 import ./crate.png --project ./projects/agent_game --dest textures/crate.png --texture-format RGBA16 --json`
- `./bf64 import ./crate.png --project ./projects/agent_game --dry-run --json`
- `./bf64 project status --project ./projects/agent_game --json`
- `./bf64 build --project ./projects/agent_game --json`
- `./bf64 run --project ./projects/agent_game --json`
- `./bf64 asset validate-all --project ./projects/agent_game --json`
- `./bf64 history list --json`

### Verification

- `python3 -m json.tool docs/docs/n64/limits.json >/tmp/bf64-limits.json`
- `python3 -m py_compile bf64 tools/bf64.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `./bf64 import /tmp/<dir>/crate.png --project /tmp/<dir>/game --texture-format RGBA16 --json`
- `./bf64 asset show assets/crate.png --project /tmp/<dir>/game --json`
- `PYRITE_DOCS_SKIP_DOXYGEN=1 sphinx-build -b html docs docs/_build/html` from a temporary `/tmp` venv (build succeeded with 12 existing warnings outside this change)

### Remaining Phase 5 gaps

- Add dedicated prefab and node-graph validators before allowing headless import for those asset kinds.
- Add explicit duplicate scene/object UUID repair with backups and history records.
- Consider a scene mutation command only after the supported API shape is clearer.
- Eventually split `tools/bf64.py` into modules once command count grows again.

---

## What this session (project generator command) completed

This session added `./bf64 new` as the creation half of the agent create-build-run loop. It mirrors the headed editor's starter template, patches project identity safely, refuses accidental overwrites, and records scaffold artifacts for later review.

### Files updated

| File | Change |
|---|---|
| `tools/bf64.py` | Bumped CLI to `0.8.0`; added `new`, editor-template copying from `n64/examples/empty`, safe ROM-name generation, no-spaces path guard, `--force`, `--name`, `--rom-name`, `--emulator`, `--n64-inst`, bootstrap repair for generated project files, project validation, JSON output, and history records. |
| `tests/test_bf64_cli.py` | Added tests for successful project creation, validation of generated projects, refusing non-empty targets, `--force` overwrites, path-space rejection, and `new --record`. |
| `docs/docs/agent/AGENTIC_SURFACE.md` | Documented `new`, creation examples, history recording, and current backlog. |
| `docs/docs/agent/HANDOFF.md` | Recorded this session and updated the Phase 5 seed status. |

### Current preferred commands

- `./bf64 --version`
- `./bf64 new ./projects/agent_game --name "Agent Game" --json`
- `./bf64 doctor --json`
- `./bf64 project status --project n64/examples/empty --json`
- `./bf64 build --project n64/examples/empty --json`
- `./bf64 build --execute --project n64/examples/empty --pyrite64-binary ./pyrite64 --json`
- `./bf64 run --project n64/examples/empty --json`
- `./bf64 run --build --project n64/examples/empty --pyrite64-binary ./pyrite64 --emulator ares --json`
- `./bf64 asset validate-all --project n64/examples/empty --json`
- `./bf64 history list --json`

### Verification

- `python3 -m py_compile bf64 tools/bf64.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `./bf64 new /tmp/<dir>/agent_game --name "Agent Game" --json`
- `./bf64 validate /tmp/<dir>/agent_game/project.p64proj --json`
- `PYRITE_DOCS_SKIP_DOXYGEN=1 sphinx-build -b html docs docs/_build/html` from a temporary `/tmp` venv (build succeeded with 12 existing warnings outside this change: missing/reused API page, README/faq not in toctree, and nodeGraphCustom MyST xrefs)

### Remaining Phase 5 gaps

- Dedicated prefab and node-graph validators, likely after Phase 3 skills clarify the node graph API and generated C++ shape.
- Explicit duplicate UUID repair command, with backups and history records.
- Eventually split `tools/bf64.py` into modules once command count grows again.

---

## What this session (ROM run command) completed

This session added `./bf64 run` as the runtime half of the build/run loop. It launches an existing ROM with the project emulator, supports `--build` to run executable build first, and keeps output/history machine-readable.

### Files updated

| File | Change |
|---|---|
| `tools/bf64.py` | Bumped CLI to `0.7.0`; added `run`, `--build`, `--emulator`, `--timeout`, `--build-timeout`, project `pathEmu` fallback, emulator command resolution, ROM artifact checks, subprocess output capture, and run history records. |
| `tests/test_bf64_cli.py` | Added fake emulator fixtures and tests for existing-ROM launch, missing ROM, missing emulator, and build-then-run wiring. |
| `docs/docs/agent/AGENTIC_SURFACE.md` | Documented `run`, `run --build`, run exit-code behavior, and current backlog. |
| `docs/docs/agent/HANDOFF.md` | Recorded this session and updated the Phase 5 seed status. |

### Current preferred commands

- `./bf64 --version`
- `./bf64 doctor --json`
- `./bf64 project status --project n64/examples/empty --json`
- `./bf64 build --project n64/examples/empty --json`
- `./bf64 build --execute --project n64/examples/empty --pyrite64-binary ./pyrite64 --json`
- `./bf64 run --project n64/examples/empty --json`
- `./bf64 run --build --project n64/examples/empty --pyrite64-binary ./pyrite64 --emulator ares --json`
- `./bf64 asset validate-all --project n64/examples/empty --json`
- `./bf64 history list --json`

### Verification

- `python3 -m py_compile bf64 tools/bf64.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `./bf64 run --project n64/examples/empty --json` returns exit code 1 when the ROM is missing
- `PYRITE_DOCS_SKIP_DOXYGEN=1 .venv/bin/sphinx-build -b html . _build/html` (same pre-existing warnings only)

### Remaining Phase 5 gaps

- Dedicated prefab and node-graph validators, likely after Phase 3 skills clarify the node graph API and generated C++ shape.
- Explicit duplicate UUID repair command, with backups and history records.
- Eventually split `tools/bf64.py` into modules once command count grows again.

---

## What this session (executable build mode) completed

This session made `./bf64 build --execute` call the existing C++ Pyrite64 CLI build path after a strict preflight gate. Dry-run remains the default, so agents can inspect a project without mutation unless they opt into execution.

### Files updated

| File | Change |
|---|---|
| `tools/bf64.py` | Bumped CLI to `0.6.0`; added `--execute`, `--pyrite64-binary`, `--timeout`, Pyrite64 binary resolution, strict preflight gating, subprocess output capture, artifact refresh, and environment-style exit code 2 for missing SDK/binary. |
| `tests/test_bf64_cli.py` | Added fake SDK and fake Pyrite64 fixtures; covered successful execute wiring and missing-binary exit code 2. |
| `docs/docs/agent/AGENTIC_SURFACE.md` | Documented executable build mode and clarified the current backlog. |
| `docs/docs/agent/HANDOFF.md` | Recorded this session and updated the Phase 5 seed status. |

### Current preferred commands

- `./bf64 --version`
- `./bf64 doctor --json`
- `./bf64 project status --project n64/examples/empty --json`
- `./bf64 build --project n64/examples/empty --json`
- `./bf64 build --execute --project n64/examples/empty --pyrite64-binary ./pyrite64 --json`
- `./bf64 asset validate-all --project n64/examples/empty --json`
- `./bf64 scene ls --project n64/examples/empty --json`
- `./bf64 history list --json`

### Verification

- `python3 -m py_compile bf64 tools/bf64.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `./bf64 build --project n64/examples/empty --json`
- `./bf64 build --execute --project n64/examples/empty --json` returns exit code 2 before mutation when SDK preflight fails
- `PYRITE_DOCS_SKIP_DOXYGEN=1 .venv/bin/sphinx-build -b html . _build/html` (same pre-existing warnings only)

### Remaining Phase 5 gaps

- Dedicated prefab and node-graph validators, likely after Phase 3 skills clarify the node graph API and generated C++ shape.
- Explicit duplicate UUID repair command, with backups and history records.
- Eventually split `tools/bf64.py` into modules once command count grows again.

---

## What this session (dry-run build planner) completed

This session added `./bf64 build` as a read-only build plan rather than an executor. It gives agents the same build-shape information the editor uses without creating `Makefile`, `filesystem/`, `build/`, `src/p64`, `engine/`, or ROM artifacts.

### Files updated

| File | Change |
|---|---|
| `tools/bf64.py` | Bumped CLI to `0.5.0`; added dry-run `build`, project-specific toolchain checks, expected ROM/Makefile/source/binary/asset artifact planning, bootstrap-file reporting, `--strict-toolchain`, and build history artifact records. |
| `tests/test_bf64_cli.py` | Added tests for dry-run build JSON and strict missing-toolchain exit code 2; factored a minimal project fixture helper. |
| `docs/docs/agent/AGENTIC_SURFACE.md` | Documented `build`, `--strict-toolchain`, planned artifacts, and the fact that executable ROM builds are not wired yet. |
| `docs/docs/agent/HANDOFF.md` | Recorded this session and updated the Phase 5 seed status. |

### Current preferred commands

- `./bf64 --version`
- `./bf64 doctor --json`
- `./bf64 project status --project n64/examples/empty --json`
- `./bf64 build --project n64/examples/empty --json`
- `./bf64 build --project n64/examples/empty --strict-toolchain --json`
- `./bf64 asset ls --project n64/examples/empty --json`
- `./bf64 asset validate-all --project n64/examples/empty --json`
- `./bf64 scene ls --project n64/examples/empty --json`
- `./bf64 history list --json`

### Verification

- `python3 -m py_compile bf64 tools/bf64.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `./bf64 build --project n64/examples/empty --json`
- `./bf64 build --project n64/examples/empty --strict-toolchain --json` returns exit code 2 when SDK pieces are missing
- `PYRITE_DOCS_SKIP_DOXYGEN=1 .venv/bin/sphinx-build -b html . _build/html` (same pre-existing warnings only)

### Remaining Phase 5 gaps

- Dedicated prefab and node-graph validators, likely after Phase 3 skills clarify the node graph API and generated C++ shape.
- Explicit duplicate UUID repair command, with backups and history records.
- Eventually split `tools/bf64.py` into modules once command count grows again.

---

## What this session (read-only asset inventory + bulk validation) completed

This session added the first project asset surface on top of the validator primitives. It stays read-only and is intended as the highest-value bridge before a real `build` command exists.

### Files updated

| File | Change |
|---|---|
| `tools/bf64.py` | Bumped CLI to `0.4.0`; added asset inventory helpers, sidecar parse checks, BF64 output/ROM path derivation, asset reference resolution, `asset ls`, `asset show`, and `asset validate-all`; wired asset commands into history schema v2. |
| `tests/test_bf64_cli.py` | Added fixture tests for asset listing, asset show validation, bulk validation skip behavior, and `asset ls --record` history command naming. |
| `docs/docs/agent/AGENTIC_SURFACE.md` | Documented the new asset commands, bulk validation behavior, and current unsupported read-only asset kinds. |
| `docs/docs/agent/HANDOFF.md` | Recorded this session and updated the Phase 5 seed status. |

### Current preferred commands

- `./bf64 --version`
- `./bf64 doctor --json`
- `./bf64 project status --project n64/examples/empty --json`
- `./bf64 asset ls --project n64/examples/empty --json`
- `./bf64 asset show assets/crate32.png --project n64/examples/empty --json`
- `./bf64 asset validate-all --project n64/examples/empty --json`
- `./bf64 scene ls --project n64/examples/empty --json`
- `./bf64 history list --json`

### Verification

- `python3 -m py_compile bf64 tools/bf64.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `./bf64 asset ls --project n64/examples/empty --json`
- `./bf64 asset show assets/crate32.png --project n64/examples/empty --json`
- `./bf64 asset validate-all --project n64/examples/empty --json`
- `PYRITE_DOCS_SKIP_DOXYGEN=1 .venv/bin/sphinx-build -b html . _build/html` (same pre-existing warnings only)

### Remaining Phase 5 gaps

- Dedicated prefab and node-graph validators, likely after Phase 3 skills clarify the node graph API and generated C++ shape.
- Explicit duplicate UUID repair command, with backups and history records.
- Eventually split `tools/bf64.py` into modules once command count grows again.

---

## What this session (CLI entrypoint + project status + history v2) completed

This session made the seed CLI easier for humans, agents, CI, and future MCP wrappers to call by adding a stable repository-local launcher and a project-level status summary.

### Files created

| File | Purpose |
|---|---|
| `bf64` | Executable root launcher that delegates to `tools/bf64.py`. This is now the preferred local command path. |

### Files updated

| File | Change |
|---|---|
| `tools/bf64.py` | Added `CLI_VERSION`, `--version`, `project status`, toolchain status reuse, asset inventory counts, suggested next actions, `--record` support for doctor/scene/project commands, and history schema v2. |
| `tests/test_bf64_cli.py` | Tests now execute `./bf64`, cover `--version`, `project status`, and v2 operation history records. |
| `.github/workflows/bf64-cli.yml` | Compiles both `bf64` and `tools/bf64.py`. |
| `docs/docs/agent/AGENTIC_SURFACE.md` | Updated command examples to `./bf64`, documented `project status`, and documented history schema v2. |
| `docs/docs/agent/HANDOFF.md` | Recorded this session and updated the Phase 5 seed status. |

### Current preferred commands

- `./bf64 --version`
- `./bf64 doctor --json`
- `./bf64 project status --project n64/examples/empty --json`
- `./bf64 project status --project n64/examples/empty --record --json`
- `./bf64 scene ls --project n64/examples/empty --json`
- `./bf64 validate n64/examples/empty/project.p64proj --json`
- `./bf64 history list --json`

### Verification

- `python3 -m py_compile bf64 tools/bf64.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `./bf64 --version`
- `./bf64 project status --project n64/examples/empty --json`
- `./bf64 project status --project n64/examples/empty --record --history-path /tmp/bf64-history.jsonl --json`

### Remaining Phase 5 gaps

- Explicit duplicate UUID repair command, with backups and history records.
- Eventually split `tools/bf64.py` into modules once command count grows again.

---

## What this session (CLI skeleton + scene validation) completed

This session hardened the seed agentic surface into the first useful slice of the Phase 5 CLI while staying read-only for project files.

### Files created

| File | Purpose |
|---|---|
| `tests/test_bf64_cli.py` | `unittest` coverage for constraint JSON, scene list/show, BigTex validation failure, project duplicate UUID validation, and default `doctor` behavior. |
| `.github/workflows/bf64-cli.yml` | CI workflow that checks `limits.json`, compiles `tools/bf64.py`, and runs CLI tests. |

### Files updated

| File | Change |
|---|---|
| `tools/bf64.py` | Added `doctor`, `scene ls`, `scene show`, `scene validate`, `validate --kind project`, and `validate --kind scene`. Project/scene validation now checks scene references, scene graph shape, duplicate object UUIDs, component id range, render pipeline framebuffer constraints, BigTex clear-color rule, object count, and unusual audio frequency. |
| `docs/docs/agent/AGENTIC_SURFACE.md` | Documented the new commands, CI/test files, project/scene checks, and remaining backlog. |
| `docs/docs/agent/HANDOFF.md` | Recorded this session, updated read order, and noted the Phase 5 seed status. |

### Verification

- `python3 -m json.tool docs/docs/n64/limits.json >/tmp/bf64-limits.json`
- `python3 -m py_compile tools/bf64.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `python3 tools/bf64.py scene ls --project n64/examples/empty --json`
- `python3 tools/bf64.py scene show 1 --project n64/examples/empty --depth 2`
- `python3 tools/bf64.py validate n64/examples/empty/project.p64proj --json`
- `python3 tools/bf64.py doctor --strict --json` returns exit code 2 when optional build/run toolchain pieces are missing.

### New finding

`python3 tools/bf64.py scene validate --project n64/examples/jam25 --json` reports a duplicate object UUID in scene 7 (`Map-Intro`): `3900369638`. This is likely a real authoring data problem because editor scene lookup uses a UUID-keyed map. Do not auto-repair it silently; if we add repair, make it an explicit command with a backup/write audit.

### Remaining Phase 5 gaps

- Formal `bf64` entry point/package instead of `python3 tools/bf64.py`.
- `project status`, `new`, `build`, `run`, and `import`.
- Machine-readable operation ids, argv, tool version, repo revision, duration, and artifact paths in `.bf64/operations.jsonl`.
- Read-only asset/project inventory commands.
- Write access only through the future extension/scene API, not raw JSON mutation.

---

## What this session (agentic surface seed) completed

This session applied lessons from reviewing Mixar's agentic-fork approach without installing/building it locally. The goal was a low-risk BF64 seed that makes N64 constraints and validation usable by both humans and agents before the full Phase 5 CLI/MCP work.

### Files created

| File | Purpose |
|---|---|
| `docs/docs/n64/limits.json` | Machine-readable N64/BF64 limits for texture, model, audio, scene, and ROM constraints. Intended as the backing data for CLI and future MCP constraint tools. |
| `tools/bf64.py` | No-dependency seed CLI with `constraints`, `validate`, and `history` commands. Emits stable JSON, deterministic exit codes, and actionable rule/fix/source issues. |
| `docs/docs/agent/AGENTIC_SURFACE.md` | Design and usage notes for the current agentic surface, including JSON contract, examples, limits, and expansion backlog. |

### Files updated

| File | Change |
|---|---|
| `docs/docs/agent.rst` | Added `agent/AGENTIC_SURFACE` to the Sphinx toctree. |
| `docs/docs/n64/asset-checklist.md` | Added pointer to `limits.json` and `tools/bf64.py validate`. Clarified BCI, animation, and XM rules. |
| `docs/docs/n64/audio.md` | Removed the stale MP3 uncertainty; MP3 uses the WAV conversion path and accepts `--wav-*` flags. |
| `docs/docs/n64/rom-budgets.md` | Corrected BCI_256 ROM math: BF64 256x256 BCI files are 64 KiB, 1 B/pixel on disk. |
| `docs/docs/n64/textures.md` | Clarified CI alpha handling in BF64/mksprite and BCI_256 ROM byte cost. |
| `.gitignore` | Ignored `.bf64/` local operation history. |

### Seed CLI behavior

- `python3 tools/bf64.py constraints list --json`
- `python3 tools/bf64.py constraints texture --json`
- `python3 tools/bf64.py validate <asset> --json`
- `python3 tools/bf64.py validate <asset> --record --json`
- `python3 tools/bf64.py history list --json`

The validator currently covers PNG texture preflight, glTF/GLB model preflight, WAV/MP3/XM audio preflight, and font extension checks. It is intentionally scoped: importer/build tools remain the source of truth for deep pipeline assertions.

### Follow-up for the real Phase 5 CLI

- Promote or wrap `tools/bf64.py` as the formal `bf64` entry point.
- Add `doctor`, `new`, `build`, `run`, `import`, `scene ls`, and `scene show`.
- Add fixture-based tests that lock the JSON schema and common validator results.
- Add exit code 2 for toolchain/environment failures.
- Add repo revision, command argv, operation ids, and tool version to `.bf64/operations.jsonl`.
- Make the Phase 6 MCP server wrap the CLI rather than duplicating validation logic.

---

## What this session (Phase 2) completed

### Documents created

| File | Purpose |
|---|---|
| `docs/docs/n64/textures.md` | Every N64 texture format (RGBA16/32, CI4/CI8, IA4/8/16, I4/I8), bits-per-texel, palette rules, TMEM fitting math + lookup table (max square per format), mipmap cost, BCI_256 + BigTex streaming technique, mksprite CLI surface, runtime material/texture binding (2 slots, 8 placeholders), the `.sprite` file format. 12 agent implications. |
| `docs/docs/n64/models-and-meshes.md` | The GLTF→fast64→tiny3d pipeline: vertex format (16 B/vert, no tangent/UV1), the 70-vertex RSP cache split (meshopt + greedy most-connected-first partitioner + TriStripper, no degenerates), rigid 1-bone-per-vertex skinning (glTF weights discarded), armature ancestor constraint, animation (60 Hz resample, linear/slerp only, 18.2 min max, 32-bit quat + 16-bit scalar quantization, .sdata streaming), full fast64 material feature set (CC 1/2cyc, fog, vertexFx, blend/zmodes, 20 rendermode presets), `.t3dm` binary format, common export mistakes. 14 agent implications. |
| `docs/docs/n64/audio-assets.md` | Accepted inputs (.wav/.mp3/.aiff/.xm/.ym), audioconv64 full CLI, **MP3 definitively accepts all `--wav-*` flags** (Phase 0 #9 resolved), sample rate/size tradeoff tables (raw vs vadpcm vs opus), mono vs stereo (2-channel cost), compression modes (raw/vadpcm/opus), XM64 format (libxm, ping-pong unrolled, channel-count assert, setSpeed unsupported), YM64, Audio2D component (6 bytes, opus auto-inject), mixer memory cost (256 KiB @ 32k mono), real-world jam25 audio budget (~17.6 MiB). 12 agent implications. |
| `docs/docs/n64/rom-budgets.md` | Cart sizes (4-64 MiB), n64tool packing (no compression — use mkasset per-asset), DFS (no compression, 2-byte align), asset API compression (LZ4/APLib/Shrinkler, NOT LZMA/YAPKI/RNC), BF64 filesystem layout, the asset table binary, worked 8 MiB example budget, RDRAM static cost (~1.4 MiB), BigTex RDRAM cost (1.125 MiB, Expansion Pak required), per-asset ROM cost cheat sheet. 12 agent implications. |
| `docs/docs/n64/asset-checklist.md` | Single-page pre-flight checklist with PASS/FAIL/WARN rules: Textures (T1-T10, TMEM max-square lookup), Models (M1-M14), Audio (A1-A12), Fonts (F1-F3), Scenes & prefabs (S1-S8), Scripts (C1-C7), ROM budget (R1-R8). Plus quick size estimation helpers for texture/audio/model/RDRAM costs. |
| `docs/docs/n64.rst` | Toctree updated: +5 entries (textures, models-and-meshes, audio-assets, rom-budgets, asset-checklist). |
| `docs/docs/agent/HANDOFF.md` (this file) | Updated for Phase 2 → Phase 3 transition. |

### Method

Phase 2 was executed by:
1. Reading the prerequisite context (Phase 1 n64/ compendium, ARCHITECTURE.md §3 asset pipeline, CODEMAP.md §8 serialization formats, `vendored/tiny3d/docs/fast64Settings.md`).
2. Launching **three parallel `explore` subagents** over the actual pipeline source:
   - **tiny3d glTF importer** — deep-read `vendored/tiny3d/tools/gltf_importer/` (parser, writer, materialParser, boneParser, nodeParser, animParser, meshOptimizer, meshBVH, meshConverter, animConverter, structs.h, fast64Types.h, rdp.h) + `vendored/tiny3d/docs/{modelFormat,modelOpt,fast64Settings}.md` + runtime `t3dmodel.h`/`t3d.h`. Resolved Phase 0 open question #8 (exact material feature set).
   - **libdragon audio pipeline** — deep-read `vendored/libdragon/tools/audioconv64/` (audioconv64.cpp, conv_wav64.cpp, conv_xm64.cpp) + `vendored/libdragon/include/{audio,mixer,wav64,xm64}.h` + `vendored/libdragon/src/audio/{mixer,audio,wav64,xm64}.c` + BF64 `src/build/audioBuilder.cpp` + `src/project/component/types/compAudio2d.cpp` + `n64/engine/src/audio/audioManager.cpp` + jam25 audio assets. Resolved Phase 0 open question #9 (MP3 + `--wav-*` flags: YES, all apply).
   - **mksprite + texture formats** — deep-read `vendored/libdragon/tools/mksprite/mksprite.c` + `vendored/libdragon/include/{sprite,surface,rdpq}.h` + `vendored/libdragon/src/rdpq/rdpq_tex.c` + `vendored/libdragon/src/sprite_internal.h` + `vendored/libdragon/src/rdpq/rdpq_sprite.c` + BF64 `src/build/textureBuilder.cpp` + `src/build/tools/bci.cpp` + `src/utils/textureFormats.h` + `n64/engine/include/renderer/material.h` + `n64/engine/src/renderer/bigtex/*` + jam25/bigtex/material_test example assets.
3. Synthesizing all three reports into 5 reference docs, each with the required structure (hard limits table up top, engine-enforced vs hardware vs best-practice distinction, "Implications for BF64 agents" 10-14 bullets at the end).
4. Writing the single-page `asset-checklist.md` with mechanical PASS/FAIL rules cross-referencing the source doc + section.
5. Wiring all 5 new pages into `docs/docs/n64.rst` toctree.
6. Verifying the Sphinx build (`PYRITE_DOCS_SKIP_DOXYGEN=1 .venv/bin/sphinx-build`): **build succeeded, 3 pre-existing warnings (Doxygen skip + README/faq not in toctree), none from the new docs.**

### Key findings

- **TMEM fitting math** is fully derived from `rdpq_tex_can_upload` (`rdpq_tex.c:371-384`): 8-byte pitch alignment, 2 KB split for RGBA32/CI4/CI8/YUV16, even-width for 4bpp. Max square per format: RGBA16=44×44, CI8=42×42, CI4=64×64, I4/IA4=85×85, RGBA32=32×32. The existing user docs' "Max. Pixels" table is byte-budget-only (no pitch alignment) — the actual max square is smaller.
- **mksprite AUTO downgrades aggressively**: RGBA → CI8 if ≤256 colors, CI8 → CI4 if ≤16, GREY → I4 if ≤16. Manual format forcing usually wastes ROM/TMEM.
- **BCI_256 = 0.75 B/pixel** (16 B per 4×4 block: 4 RGBA5551 colors + 16×2-bit indices). 256×256 = 64 KiB. Uses `rand()` for k-means palette init (`bci.cpp:46`) — **non-deterministic** across builds. BigTex pool = 18 textures × 64 KiB = 1.125 MiB at fixed 0x80400000 (Expansion Pak required).
- **glTF importer is rigid-skinning only**: `parser.cpp:309` keeps only `joins[0]`, discards weights. Despite glTF VEC4 joints/weights, each vertex is assigned to exactly one bone. The "up to 3 bones per triangle" means a triangle's 3 verts can belong to 3 different bones (handled by auto-splitting parts), NOT that a vertex blends 3 bones.
- **Armature ancestor constraint** (`parser.cpp:74-119`): the importer rejects armatures whose ancestor nodes have non-identity transforms. The skin root must be at the top of any transform chain.
- **fast64 `f3d_mat` extras are mandatory** (`materialParser.cpp:195-203`): every material must carry the blob or the importer throws. "Include → Custom Properties" must be checked during GLTF export. There is NO fallback for vanilla glTF materials.
- **Animation is resampled at 60 Hz linear/slerp only** (`animParser.cpp:119-160`): step and CubicSpline glTF inputs are silently treated as linear. Max 18.2 minutes (65535 ticks @ 60 Hz, `timeNext < 2^15`). Keyframes: 32-bit smallest-3 quat (rotation) / 16-bit per-channel normalized (scalar). Streaming via separate `.sdata` files.
- **Morph target animations unsupported** — `weights` path throws "Unknown animation target".
- **MP3 is a first-class WAV-equivalent input**: `conv_wav64.cpp:706-739` branches only on extension to pick the decoder, then runs the identical mono/seek/resample/compress pipeline. All `--wav-*` flags apply. Only asymmetry: no smpl/cue metadata discovery, and opus forces 48 kHz.
- **VADPCM frame = 16 samples → 9 bytes/channel** (`vadpcm/codec/vadpcm.h:39,42`). 4-bit default + Huffman (on for wav64, off for xm64). Opus forced to 48 kHz, bitrate = `3000 + resampleRate*channels` bps.
- **XM64 ping-pong loops are unrolled** (`conv_xm64.cpp:507-521`): RSP mixer only does forward loops. XM with >32 channels aborts at runtime.
- **BF64 exposes only 3 audio conf fields** (`wavForceMono`, `wavResampleRate`, `wavCompression`) — NOT `--wav-loop`, `--wav-seek`, `--xm-8bit`, `--xm-ext-samples`, or the vadpcm `bits=`/`huffman=` sub-opts. To use these, invoke audioconv64 manually.
- **jam25 audio ROM budget ~17.6 MiB**: 4 MP3 music tracks decode to larger VADPCM wav64s than the source MP3s. Music dominates the ROM cost. Switching to XM64 or Opus would cut this dramatically.
- **n64tool does NOT compress** — only packs. Compression is per-asset via `mkasset -c <level>` (LZ4 default, APLib/Shrinkler tighter). DFS does NOT compress either (`dragonfs.h:44-45`). LZMA/YAPKI/RNC are NOT present in this libdragon commit.
- **RDRAM static cost ~1.4 MiB** (code + 3× framebuffer + Z + 32-ch mixer + AI buffers + stack), leaving ~3.5 MiB heap on 4 MiB systems, ~7.5 MiB on 8 MiB. BigTex pool alone = 1.125 MiB (Expansion Pak required).

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
8. **`vendored/tiny3d` glTF importer** handles materials, bones, animations, BVH, mesh optimization. The exact material feature set (which fast64 CC modes, which blender modes) needs Phase 2 verification against the actual importer source for the asset skills to be authoritative. **RESOLVED in Phase 2** — see `docs/docs/n64/models-and-meshes.md` §5. Full fast64 material feature set documented: CC 1/2cyc (COMBINED/TEX0/TEX1/PRIM/SHADE/ENV/NOISE + alpha variants), 20 rendermode presets, fog (DEFAULT/DISABLED/ACTIVE), vertexFx (NONE/SPHERE only from importer; runtime has more), 4 blend modes, 4 z-modes, 3 texture filters, 2 texture slots, per-axis S/T clamp/mirror/mask/shift/low/high. NO tangent/bitangent/UV1/normal-mapping/PBR/morph-targets.
9. **Audio: `audioconv64` flags applied to `.mp3` input** — undocumented whether mp3 accepts `--wav-*` flags. Phase 2 (audio-assets.md) should verify by running audioconv64 on a fixture mp3. **RESOLVED in Phase 2** — see `docs/docs/n64/audio-assets.md` §3. **YES — MP3 accepts and honors ALL `--wav-*` flags.** `conv_wav64.cpp:706-739` branches only on extension to pick the decoder (read_mp3 vs read_wav), then runs the identical mono/seek/resample/compress pipeline. Only asymmetries: no smpl/cue metadata discovery, and opus forces 48 kHz regardless of `--wav-resample`.
10. **Two parallel UUID systems** (32-bit scene object uuids vs 64-bit asset/prefab/component uuids) — a documented class of bugs. Not yet audited for actual mismatches. Phase 5/7 should be careful.

---

## Next session instructions (Phase 3)

**Phase:** 3 — `/skills` Scaffold + Core Engine Skills
**Estimated tokens:** ~300K
**Kickoff prompt:** see `docs/docs/project/phased-plan.md` Phase 3 section (lines 174 onward).

**Before starting:**
1. Submodules are checked out. The vendored libdragon/tiny3d source is available.
2. Read this file, then `docs/docs/agent/AGENTIC_SURFACE.md`, then `ARCHITECTURE.md` (full — especially §1.7 node graphs, §2 runtime, §3 asset pipeline), then `CODEMAP.md`, then the `docs/docs/n64/` compendium (all 11 docs plus `limits.json`: hardware, performance-budgets, libdragon-tiny3d, display-and-video, audio, emulation-and-hardware-testing, textures, models-and-meshes, audio-assets, rom-budgets, asset-checklist). The n64/ docs are the ground truth that skills will cite.
3. Optionally read `vendored/tiny3d/docs/{modelFormat,modelOpt,fast64Settings}.md` and the example games in `n64/examples/` for concrete patterns.

**Outputs (per phased-plan.md):**
- `/skills/README.md` — index, philosophy, versioning policy (pinned to BF64 + tiny3d + libdragon versions, mirroring bevy-skills' pin-to-version approach)
- `/skills/_TEMPLATE/SKILL.md` — canonical skill format
- Core skills, each a folder with `SKILL.md` (+ `examples/` where useful):
  - `bf64-project-setup` — create/open a project, toolchain install, build a ROM, run in Ares/gopher64
  - `bf64-scenes` — scene creation, object/component model, serialization format
  - `bf64-node-graph` — the visual scripting system: node types, wiring, patterns
  - `bf64-rendering` — tiny3d usage through BF64: materials, lighting, HDR/bloom, big textures
  - (see phased-plan.md for the full list and any additions)

**Each skill must:**
- Pin to the BF64 version + tiny3d commit `bdcd946` + libdragon commit `b1011fe31` (mirror the bevy-skills pin-to-version approach).
- Cite the `docs/docs/n64/` compendium for hardware/asset claims, and `ARCHITECTURE.md`/`CODEMAP.md` for engine API claims.
- Include runnable examples where useful (the example games in `n64/examples/` are the reference).

**Section wiring:** `/skills/` is a new top-level directory (not under `docs/`). The README.md is the index. No Sphinx toctree wiring needed unless we later add a `docs/skills.rst` pointing at them.

**Open questions from Phase 0/1/2 to resolve or carry into Phase 3:**
- `res_<uuid>` fallback declaration in node-graph codegen (Phase 0 open question #4) — **Phase 3 (node-graph skill) should verify this by reading a generated `.cpp`** from `n64/examples/jam25/src/p64/`.
- ImGui version still unknown (vendored/imgui checked out at `913a3c6` but version string not read). Phase 8 or any ImGui-touching work should record it.

**Commit message:** `docs(skills): phase 3 core engine skills` (or split across multiple commits if natural)

**Update this file** before ending the session.

---

## Next session instructions (Phase 2) — COMPLETED

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
- **`audioconv64` flags on `.mp3` input** (Phase 0 open question #9) — **RESOLVED in Phase 2.** MP3 accepts all `--wav-*` flags. See `docs/docs/n64/audio-assets.md` §3.
- **tiny3d glTF importer exact material feature set** (Phase 0 open question #8) — **RESOLVED in Phase 2.** See `docs/docs/n64/models-and-meshes.md` §5.
- **ImGui version** still unknown (vendored/imgui is now checked out at `913a3c6` but the version string wasn't read this session). Phase 8 or any ImGui-touching work should record it.

---

## Quick links (the canonical read order for a fresh session)

1. **This file** (`docs/docs/agent/HANDOFF.md`)
2. `docs/docs/agent/ARCHITECTURE.md` — how the engine works
3. `docs/docs/agent/CODEMAP.md` — where to find things
4. `docs/docs/agent/DIVERGENCE.md` — fork policy & upstream relationship
5. `docs/docs/project/phased-plan.md` — the 10-phase plan
6. `docs/docs/project/gap-analysis.md` — why BF64 exists
7. `docs/docs/n64/*` — hardware/SDK reference (Phase 1 done: hardware, performance-budgets, libdragon-tiny3d, display-and-video, audio, emulation-and-hardware-testing; **Phase 2 done: textures, models-and-meshes, audio-assets, rom-budgets, asset-checklist**)
8. `/skills/*` — agent skills (Phase 3–4, not yet created)
9. `docs/cli.md`, `docs/mcp.md`, `docs/extensions/DESIGN.md` — machine interfaces (Phase 5–7, not yet created)
10. `AGENTS.md` / `CLAUDE.md` — repo-root agent onboarding (Phase 8, not yet created)
