# Agentic Surface

**Audience:** agents and humans driving Binface64 without relying on editor-only state.
**Status:** active implementation with project, asset, scene, build/run, and UI focus-area workflows.
**Last reviewed:** 2026-07-12.

This page records the first machine-facing BF64 surface: structured N64 constraints, a deterministic asset validator, and a local operation history. It applies the source-review lesson that an agentic fork should expose the same core truths to headed UI, headless CLI, and future MCP tools instead of making agents scrape prose or infer GUI behavior.

---

## Current files

| File | Role |
|---|---|
| `bf64` | Stable repository-local launcher for the BF64 CLI. |
| `docs/docs/n64/limits.json` | Machine-readable version of the most important N64/BF64 limits. This is the source for validators and future MCP constraint tools. |
| `tools/bf64.py` | No-dependency CLI for toolchain setup, project creation, asset/focus workflows, scene/prefab/node-graph mutation, validation, build/run/profile, and operation history. |
| `.bf64/operations.jsonl` | Local, ignored audit log written by commands that support `--record`. |
| `tests/test_bf64_cli.py` | Fixture tests for the JSON contract and core validator behavior. |
| `.github/workflows/bf64-cli.yml` | CI job for JSON validity, CLI compilation, and unit tests. |

The Markdown docs remain the human-readable ground truth. `limits.json` is the agent-oriented index for constraints that must be mechanically enforced.

---

## Commands

List constraint topics:

```bash
./bf64 constraints list --json
```

Read a constraint topic:

```bash
./bf64 constraints texture --json
./bf64 constraints model --json
./bf64 constraints audio --json
```

Validate one asset:

```bash
./bf64 validate n64/examples/bigtex/assets/img00.bci.png --scene-pipeline bigtex --json
./bf64 validate n64/examples/jam25/assets/lab/floor00.ci4.png --texture-format CI4 --json
./bf64 validate n64/examples/jam25/assets/PlayerJump00.wav --role sfx --json
./bf64 validate n64/examples/empty/project.p64proj --json
./bf64 validate n64/examples/empty/data/scenes/1/scene.json --json
```

Inspect projects and scenes:

```bash
./bf64 new ./projects/agent_game --name "Agent Game" --json
./bf64 doctor --json
./bf64 doctor --strict --json
./bf64 toolchain detect --project ./projects/agent_game --json
./bf64 toolchain install --source ~/Documents/libdragon --prefix ~/Documents/libdragon-sdk --dry-run --json
./bf64 doctor --project ./projects/agent_game --n64-inst ~/Documents/libdragon-sdk --fix --json
./bf64 project status --project n64/examples/empty --json
./bf64 import ./crate.png --project ./projects/agent_game --dest textures/crate.png --texture-format RGBA16 --json
./bf64 import ./crate.png --project ./projects/agent_game --dry-run --json
./bf64 build --project n64/examples/empty --json
./bf64 build --project n64/examples/empty --strict-toolchain --json
./bf64 build --execute --project n64/examples/empty --pyrite64-binary ./pyrite64 --json
./bf64 run --project n64/examples/empty --json
./bf64 run --build --project n64/examples/empty --pyrite64-binary ./pyrite64 --emulator ares --json
./bf64 run --build --profile --project n64/examples/empty --json
./bf64 asset ls --project n64/examples/empty --json
./bf64 asset show assets/crate32.png --project n64/examples/empty --json
./bf64 asset validate-all --project n64/examples/empty --json
./bf64 asset validate-all --project n64/examples/empty --include-excluded --json
./bf64 scene ls --project n64/examples/empty --json
./bf64 scene show 1 --project n64/examples/empty --json
./bf64 scene validate --project n64/examples/empty --json
./bf64 scene create Gameplay --project ./projects/agent_game --json
./bf64 scene duplicate 1 --name "Gameplay Copy" --project ./projects/agent_game --json
./bf64 scene rename 2 Results --project ./projects/agent_game --json
./bf64 scene delete 2 --replacement 1 --project ./projects/agent_game --json
./bf64 scene object add 1 --name Player --project ./projects/agent_game --json
./bf64 scene object update 1 Player --position 0 100 0 --project ./projects/agent_game --json
./bf64 scene object reparent 1 Player --parent root --project ./projects/agent_game --json
./bf64 scene component add 1 Player camera --project ./projects/agent_game --json
./bf64 scene attach ui 1 Player assets/ui/hud.bfui --project ./projects/agent_game --json
./bf64 scene attach audio3d 1 Player assets/sfx/voice.wav --project ./projects/agent_game --json
./bf64 scene attach code 1 Player src/user/Player.cpp --project ./projects/agent_game --json
./bf64 prefab create actors/player --project ./projects/agent_game --json
./bf64 prefab object add actors/player --name CameraRig --project ./projects/agent_game --json
./bf64 prefab attach camera actors/player CameraRig --project ./projects/agent_game --json
./bf64 node-graph create intro --project ./projects/agent_game --json
./bf64 node-graph node add intro core.start --project ./projects/agent_game --json
./bf64 focus list --json
./bf64 ui new menus/title --project ./projects/agent_game --json
./bf64 ui ls --project ./projects/agent_game --json
./bf64 ui show assets/menus/title.bfui --project ./projects/agent_game --json
./bf64 ui validate --all --project ./projects/agent_game --json
./bf64 music tag assets/music/title.xm --project ./projects/agent_game --json
./bf64 music validate --project ./projects/agent_game --json
./bf64 sfx ls --project ./projects/agent_game --json
./bf64 environment ls --project ./projects/agent_game --json
./bf64 avatar ls --project ./projects/agent_game --json
./bf64 cutscene ls --project ./projects/agent_game --json
```

Record an operation and inspect history:

```bash
./bf64 new ./projects/agent_game --name "Agent Game" --record --json
./bf64 import ./crate.png --project ./projects/agent_game --record --json
./bf64 project status --project n64/examples/empty --record --json
./bf64 build --project n64/examples/empty --record --json
./bf64 build --execute --project n64/examples/empty --record --json
./bf64 run --project n64/examples/empty --record --json
./bf64 asset validate-all --project n64/examples/empty --record --json
./bf64 validate n64/examples/jam25/assets/PlayerJump00.wav --role sfx --record --json
./bf64 history list --json
```

---

## JSON contract

Validation output uses a stable shape:

```json
{
  "ok": true,
  "path": "asset/path",
  "kind": "texture",
  "metadata": {},
  "issues": [
    {
      "severity": "warning",
      "rule": "T4",
      "message": "What is wrong or uncertain.",
      "fix": "The next action to take.",
      "source": "docs/docs/n64/textures.md#section"
    }
  ]
}
```

Issue severities are `error`, `warning`, or `info`. Errors make `ok: false`.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Success. No validation errors. |
| 1 | User, project, or asset error. Output includes actionable issues. |
| 2 | Environment/toolchain error. Currently used by `doctor --strict`, `build --strict-toolchain`, `build --execute` preflight/binary resolution, and missing `run` emulator commands. |
| 3 | Internal tooling error. |
| 130 | Interrupted. |

---

## Operation History

Commands that support `--record` append JSONL records to `.bf64/operations.jsonl` by default. Use `--history-path <path>` in tests or automation when the default local history should not be touched.

Current records use `schema_version: 2` and include:

- `operation_id`
- command and argv
- exit code and duration
- BF64 CLI version and git revision
- path and project path when known
- issue count, issue summary, and full issues
- artifact paths when a command emits scaffold, import, build, or run artifacts

---

## What The Validator Checks

Texture checks include extension, PNG header, explicit or inferred BF64 texture format, TMEM max texels, `.bci.png` 256x256 BigTex rules, compression values, and scene pipeline compatibility.

Model checks include `.glb`/`.gltf` parsing, total vertex/index counts, Fast64 `f3d_mat` material extras, skin-weight warning, supported animation target paths, and animation duration.

Audio checks include BF64 editor-supported extensions, `wavCompression`, `wavResampleRate`, WAV metadata, MP3 re-encode notice, XM channel cap, and common SFX mono warnings.

Project checks include parseability, `sceneIdOnBoot` / `sceneIdOnReset` / `sceneIdLastOpened` references, and per-scene validation.

Scene checks include `conf` / `graph` structure, object count budget, duplicate object UUIDs, component id range, render pipeline framebuffer constraints, BigTex `doClearColor: false`, and unusual audio frequencies.

`scene create/duplicate/rename/delete` and `scene object add/update/remove/reparent` provide supported scene lifecycle and object-tree mutation. `scene component add/update/remove` uses the ABI-stable component registry, while `scene attach` resolves ergonomic UI, camera, model, collision, light, and Code adapters. Object UUIDs are persistent collision-checked 32-bit values; component UUIDs are persistent collision-checked 64-bit values. Asset/script assignments resolve source references to their stable UUIDs rather than accepting unverified serializer fields.

Every scene mutation supports `--dry-run`, `--json`, and `--record`, validates the proposed document, and writes JSON through same-directory atomic replacement. Referenced scene deletion uses a two-file transaction: it tombstones the scene directory, atomically rewrites project references, validates the complete project, and restores both on failure.

`new` creates an editor-compatible starter project from `n64/examples/empty`, patches `project.p64proj`, rejects project paths with spaces to match the headed editor/build launcher, ensures bootstrap files such as `assets/p64/font.ia4.png`, validates the generated project, and records scaffold artifacts in history. Non-empty targets still require an explicit mode: `--force` replaces scaffold paths, while `--merge` only adds missing paths, preserves an existing valid project config/scene/assets, merges ignore patterns, preflights type conflicts, and never removes generated outputs. `init --project .` is the merge-safe alias for asset-first repositories.

`import` copies one supported editor asset into `assets/`, writes a fresh `.conf` sidecar with a new UUID, validates before mutating, refuses target overwrites unless `--force` is passed, supports `--dry-run`, removes stale generated output for overwritten assets, and records imported asset/sidecar artifacts in history. Current supported imports are `.png`, `.glb`, `.gltf`, `.wav`, `.mp3`, `.xm`, `.ttf`, and `.otf`.

`project status` combines project config, full scene validation, asset inventory counts, `doctor` toolchain checks, and suggested next actions. It is the first command agents should call when entering an unknown BF64 project.

`asset ls` lists project assets under `assets/`, classifies them as texture/model/audio/font/ui/prefab/node_graph/unknown, reports sidecar presence and parseability, and includes the BF64 ROM output path where the editor build pipeline has one.

`asset exclusion list/add/remove` manages project-level exclusion globs in `project.p64proj`. Inputs are canonicalized relative to `assets/`; absolute paths and traversal segments are rejected. Mutations support `--dry-run`, atomic replacement, stable JSON, and `--record`. `asset ls` reports `sidecar_excluded`, `project_excluded`, `matched_exclusion_patterns`, the effective `exclude` state, and its source.

`focus list` reads the shared focus-area catalog used by the editor's **Focus** menu and the CLI. UI has a purpose-built document editor. Music, SFX, 3D Environment, 3D Avatars, and Cutscenes have dedicated tagged-asset workspaces plus matching `ls/validate/tag` namespaces. Membership is a multi-value `focusAreas` list in normal asset sidecars, so one asset can participate in several production slices.

`ui new/ls/show/validate` provide document-oriented authoring and comprehensive validation for versioned `.bfui` assets. Containers, images, text, buttons, controller text input, and progress/value bars share the same GUI, CLI validator, `.ui64` builder, and N64 runtime contract. The native editor build remains the source of compiled `.ui64` ROM assets.

`prefab ls/show/validate/create/duplicate/rename/delete`, `prefab object`, `prefab component`, and `prefab attach` provide the same stable-UUID, atomic, dry-run/recordable mutation discipline as scenes. Prefab/sidecar pair operations validate before commit and roll both paths back on failure.

`node-graph ls/show/validate/create/duplicate/rename/delete` plus `node/link/variable/group` expose the editor's structured graph document without raw JSON edits. Validation covers node UUID/type structure, links and ports, variables, groups, and sidecar pairing; duplicate operations regenerate persistent identities.

`asset show` resolves a project asset by `assets/<path>`, project-relative path, or unique basename, then returns the sidecar JSON and the matching read-only validation result.

`asset validate-all` and `build` share one asset-selection path. Assets whose sidecar contains `"exclude": true` or whose assets-relative path matches `project.p64proj` `assetExclusions` are omitted by default; pass `--include-excluded` for a complete source audit. Validation summaries report included, excluded, skipped, passed, and failed counts separately. Prefabs and node graphs are validated as structured assets when selected; unsupported read-only sources such as `.blend` files count as skipped.

`build` defaults to a dry-run planner. It resolves project config, project/scene validation, bulk asset validation, build toolchain readiness, expected ROM path, generated Makefile/source/binary paths, asset outputs, and history artifact records. By default, missing N64 toolchain pieces are warnings so project validation remains usable on machines without the SDK. Use `--strict-toolchain` to promote them to exit code 2.

`build --execute` runs strict preflight first, resolves `./pyrite64` / `./pyrite64.exe` or an explicit `--pyrite64-binary`, then invokes the existing C++ CLI path: `<pyrite64-binary> --cli --cmd build <project.p64proj>`. It captures stdout/stderr tails, underlying return code, duration, and refreshed artifact existence in JSON/history.

`run` locates the expected `<romName>.z64`, uses project `pathEmu` by default, accepts `--emulator <command>` overrides, appends the ROM path to the emulator argv, and captures stdout/stderr tails, return code, duration, and ROM artifact metadata. `run --build` executes `build --execute` first, then launches the ROM if the build succeeds.

`run --build --profile` embeds a bounded warm-up/sample request, consumes the runtime `BF64_PROFILE_JSON:` record, terminates the emulator after capture, and atomically writes a `bf64.profile` v1 artifact. It combines frame-time/FPS percentiles, model triangle/draw/material counters, peak RDRAM allocation footprint, audio voices, ROM/DFS/ELF sizes, BF64 target revision, and emulator version. Installed Ares Flatpaks are discovered automatically when no `ares` executable is on `PATH`.

`toolchain detect/install` and `doctor --fix` provide the supported Linux setup path. Discovery has deterministic explicit/project/environment/default precedence. Install can bootstrap a missing cross-compiler, installs libdragon host/target tools and pinned Tiny3D without `sudo`, and supports a complete `--dry-run`. `doctor --fix` atomically persists `pathN64Inst` plus `.bf64/env.sh` and rolls both back if final validation fails.

The runtime shippability surface now includes redundant checksummed EEPROM 4K/16K save slots (`save/saveManager.h`), listener-relative `Audio3D` playback/component id 14, and the input-agnostic `UI::DialogueRunner` typewriter/line sequencer. These are C++ engine APIs rather than new CLI data formats; their project guides define the stable contracts and Ares verification path.

Known limits:

- This is preflight validation. The tiny3d importer, mksprite, audioconv64, and a real ROM build remain the source of truth for deep pipeline assertions.
- The model validator cannot prove the optimized retained-animation keyframe delta stays below 32768 ticks without running the tiny3d importer.
- `doctor` distinguishes default warnings from `--strict` environment errors. Missing N64 toolchain pieces do not block asset/scene validation.
- Focus-area workspaces currently organize and validate existing asset formats; Music/SFX/Environment/Avatar/Cutscene do not introduce separate timeline, mixer, modeling, or animation asset formats.
- Dialogue sequencing is runtime C++ over stable `.bfui` IDs; branching/localized dialogue source assets and visual timeline authoring remain future layers.

---

## Design Rules For Future Agentic Work

1. Keep constraints structured. Any hard limit that an agent must obey should be represented in `limits.json` or a successor schema, with source citations back to the docs.
2. Keep output parseable. New commands must support `--json` and return rule ids, messages, fixes, sources, and deterministic exit codes.
3. Keep headed and headless paths aligned. Editor actions, CLI commands, MCP tools, and extensions should share validation logic or schemas wherever practical.
4. Keep an audit trail. Agent actions that change or validate project state should be recordable as JSONL so later humans and agents can reconstruct what happened.
5. Keep scene mutation behind a supported API. Do not teach agents to raw-edit scene JSON as the final interface; use the Phase 7 extension/scene API as the durable write surface.

---

## Expansion Backlog

- Wrap `tools/bf64.py` from the Phase 6 MCP server instead of duplicating validation logic.
- Continue expanding structured component-data validation while preserving editor JSON compatibility.
- Decide whether duplicate scene UUID repair should be an explicit CLI command or only an editor action.
- Add authored localization/branching dialogue and richer cutscene timeline formats on top of the current runner, UI, and node-graph APIs.
- Add domain-specific editing depth to the non-UI focus workspaces as stable music-mix, environment-set, avatar, or cutscene formats emerge.
