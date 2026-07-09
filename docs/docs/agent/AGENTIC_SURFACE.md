# Agentic Surface

**Audience:** agents and humans driving Binface64 without relying on editor-only state.
**Status:** seed implementation, not the full Phase 5 CLI.
**Last reviewed:** 2026-07-09.

This page records the first machine-facing BF64 surface: structured N64 constraints, a deterministic asset validator, and a local operation history. It applies the source-review lesson that an agentic fork should expose the same core truths to headed UI, headless CLI, and future MCP tools instead of making agents scrape prose or infer GUI behavior.

---

## Current files

| File | Role |
|---|---|
| `docs/docs/n64/limits.json` | Machine-readable version of the most important N64/BF64 limits. This is the source for validators and future MCP constraint tools. |
| `tools/bf64.py` | No-dependency seed CLI for constraint lookup, asset preflight validation, and operation history. |
| `.bf64/operations.jsonl` | Local, ignored audit log written by `tools/bf64.py validate --record`. |

The Markdown docs remain the human-readable ground truth. `limits.json` is the agent-oriented index for constraints that must be mechanically enforced.

---

## Commands

List constraint topics:

```bash
python3 tools/bf64.py constraints list --json
```

Read a constraint topic:

```bash
python3 tools/bf64.py constraints texture --json
python3 tools/bf64.py constraints model --json
python3 tools/bf64.py constraints audio --json
```

Validate one asset:

```bash
python3 tools/bf64.py validate n64/examples/bigtex/assets/img00.bci.png --scene-pipeline bigtex --json
python3 tools/bf64.py validate n64/examples/jam25/assets/lab/floor00.ci4.png --texture-format CI4 --json
python3 tools/bf64.py validate n64/examples/jam25/assets/PlayerJump00.wav --role sfx --json
```

Record an operation and inspect history:

```bash
python3 tools/bf64.py validate n64/examples/jam25/assets/PlayerJump00.wav --role sfx --record --json
python3 tools/bf64.py history list --json
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
| 3 | Internal tooling error. |
| 130 | Interrupted. |

Phase 5 should reserve exit code 2 for environment/toolchain errors when `doctor`, `build`, and `run` land.

---

## What The Validator Checks

Texture checks include extension, PNG header, explicit or inferred BF64 texture format, TMEM max texels, `.bci.png` 256x256 BigTex rules, compression values, and scene pipeline compatibility.

Model checks include `.glb`/`.gltf` parsing, total vertex/index counts, Fast64 `f3d_mat` material extras, skin-weight warning, supported animation target paths, and animation duration.

Audio checks include BF64 editor-supported extensions, `wavCompression`, `wavResampleRate`, WAV metadata, MP3 re-encode notice, XM channel cap, and common SFX mono warnings.

Known limits:

- This is preflight validation. The tiny3d importer, mksprite, audioconv64, and a real ROM build remain the source of truth for deep pipeline assertions.
- The model validator cannot prove the optimized retained-animation keyframe delta stays below 32768 ticks without running the tiny3d importer.
- The validator does not yet import assets, mutate scenes, build ROMs, or launch emulators.

---

## Design Rules For Future Agentic Work

1. Keep constraints structured. Any hard limit that an agent must obey should be represented in `limits.json` or a successor schema, with source citations back to the docs.
2. Keep output parseable. New commands must support `--json` and return rule ids, messages, fixes, sources, and deterministic exit codes.
3. Keep headed and headless paths aligned. Editor actions, CLI commands, MCP tools, and extensions should share validation logic or schemas wherever practical.
4. Keep an audit trail. Agent actions that change or validate project state should be recordable as JSONL so later humans and agents can reconstruct what happened.
5. Keep scene mutation behind a supported API. Do not teach agents to raw-edit scene JSON as the final interface; use the Phase 7 extension/scene API as the durable write surface.

---

## Expansion Backlog

- Promote the seed CLI into the formal Phase 5 `bf64` command surface or add a wrapper entry point.
- Add `doctor`, `new`, `build`, `run`, `import`, `scene ls`, and `scene show`.
- Add fixture-based tests for validator behavior and JSON compatibility.
- Wrap `tools/bf64.py` from the Phase 6 MCP server instead of duplicating validation logic.
- Add structured scene/project schemas for read-only queries first, then mutation through extensions.
- Add operation ids, command arguments, tool version, and repo revision to `.bf64/operations.jsonl`.
