# Agentic Surface

**Audience:** agents and humans driving Binface64 without relying on editor-only state.
**Status:** seed implementation, not the full Phase 5 CLI.
**Last reviewed:** 2026-07-09.

This page records the first machine-facing BF64 surface: structured N64 constraints, a deterministic asset validator, and a local operation history. It applies the source-review lesson that an agentic fork should expose the same core truths to headed UI, headless CLI, and future MCP tools instead of making agents scrape prose or infer GUI behavior.

---

## Current files

| File | Role |
|---|---|
| `bf64` | Stable repository-local launcher for the BF64 CLI. |
| `docs/docs/n64/limits.json` | Machine-readable version of the most important N64/BF64 limits. This is the source for validators and future MCP constraint tools. |
| `tools/bf64.py` | No-dependency seed CLI for constraint lookup, project/scene/asset inspection, asset preflight validation, and operation history. |
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
./bf64 doctor --json
./bf64 doctor --strict --json
./bf64 project status --project n64/examples/empty --json
./bf64 build --project n64/examples/empty --json
./bf64 build --project n64/examples/empty --strict-toolchain --json
./bf64 build --execute --project n64/examples/empty --pyrite64-binary ./pyrite64 --json
./bf64 run --project n64/examples/empty --json
./bf64 run --build --project n64/examples/empty --pyrite64-binary ./pyrite64 --emulator ares --json
./bf64 asset ls --project n64/examples/empty --json
./bf64 asset show assets/crate32.png --project n64/examples/empty --json
./bf64 asset validate-all --project n64/examples/empty --json
./bf64 scene ls --project n64/examples/empty --json
./bf64 scene show 1 --project n64/examples/empty --json
./bf64 scene validate --project n64/examples/empty --json
```

Record an operation and inspect history:

```bash
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
| 1 | User or asset error. Output includes actionable issues. |
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
- artifact paths when a command emits or plans build/import artifacts

---

## What The Validator Checks

Texture checks include extension, PNG header, explicit or inferred BF64 texture format, TMEM max texels, `.bci.png` 256x256 BigTex rules, compression values, and scene pipeline compatibility.

Model checks include `.glb`/`.gltf` parsing, total vertex/index counts, Fast64 `f3d_mat` material extras, skin-weight warning, supported animation target paths, and animation duration.

Audio checks include BF64 editor-supported extensions, `wavCompression`, `wavResampleRate`, WAV metadata, MP3 re-encode notice, XM channel cap, and common SFX mono warnings.

Project checks include parseability, `sceneIdOnBoot` / `sceneIdOnReset` / `sceneIdLastOpened` references, and per-scene validation.

Scene checks include `conf` / `graph` structure, object count budget, duplicate object UUIDs, component id range, render pipeline framebuffer constraints, BigTex `doClearColor: false`, and unusual audio frequencies.

`project status` combines project config, full scene validation, asset inventory counts, `doctor` toolchain checks, and suggested next actions. It is the first command agents should call when entering an unknown BF64 project.

`asset ls` lists project assets under `assets/`, classifies them as texture/model/audio/font/prefab/node_graph/unknown, reports sidecar presence and parseability, and includes the BF64 ROM output path where the editor build pipeline has one.

`asset show` resolves a project asset by `assets/<path>`, project-relative path, or unique basename, then returns the sidecar JSON and the matching read-only validation result.

`asset validate-all` validates every supported project asset kind and explicitly skips unsupported read-only kinds such as `.blend` source files, prefabs, and node graphs. It is the current bulk preflight command before a real build exists.

`build` defaults to a dry-run planner. It resolves project config, project/scene validation, bulk asset validation, build toolchain readiness, expected ROM path, generated Makefile/source/binary paths, asset outputs, and history artifact records. By default, missing N64 toolchain pieces are warnings so project validation remains usable on machines without the SDK. Use `--strict-toolchain` to promote them to exit code 2.

`build --execute` runs strict preflight first, resolves `./pyrite64` / `./pyrite64.exe` or an explicit `--pyrite64-binary`, then invokes the existing C++ CLI path: `<pyrite64-binary> --cli --cmd build <project.p64proj>`. It captures stdout/stderr tails, underlying return code, duration, and refreshed artifact existence in JSON/history.

`run` locates the expected `<romName>.z64`, uses project `pathEmu` by default, accepts `--emulator <command>` overrides, appends the ROM path to the emulator argv, and captures stdout/stderr tails, return code, duration, and ROM artifact metadata. `run --build` executes `build --execute` first, then launches the ROM if the build succeeds.

Known limits:

- This is preflight validation. The tiny3d importer, mksprite, audioconv64, and a real ROM build remain the source of truth for deep pipeline assertions.
- The model validator cannot prove the optimized retained-animation keyframe delta stays below 32768 ticks without running the tiny3d importer.
- The validator does not yet import assets, mutate scenes, or validate prefab/node-graph internals.
- `doctor` distinguishes default warnings from `--strict` environment errors. Missing N64 toolchain pieces do not block asset/scene validation.

---

## Design Rules For Future Agentic Work

1. Keep constraints structured. Any hard limit that an agent must obey should be represented in `limits.json` or a successor schema, with source citations back to the docs.
2. Keep output parseable. New commands must support `--json` and return rule ids, messages, fixes, sources, and deterministic exit codes.
3. Keep headed and headless paths aligned. Editor actions, CLI commands, MCP tools, and extensions should share validation logic or schemas wherever practical.
4. Keep an audit trail. Agent actions that change or validate project state should be recordable as JSONL so later humans and agents can reconstruct what happened.
5. Keep scene mutation behind a supported API. Do not teach agents to raw-edit scene JSON as the final interface; use the Phase 7 extension/scene API as the durable write surface.

---

## Expansion Backlog

- Add `new`, then `import`.
- Wrap `tools/bf64.py` from the Phase 6 MCP server instead of duplicating validation logic.
- Expand structured scene/project schemas and preserve JSON compatibility with tests.
- Extend artifact capture for future import commands.
- Decide whether duplicate scene UUID repair should be an explicit CLI command or only an editor action.
