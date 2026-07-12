---
name: bf64-cli
description: Use when running BF64 headless workflows: constraints, validate, import, project status, scenes, assets, build, run, JSON output, and operation history.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "1"
  area: cli
  target_version: "BF64"
---

# BF64 CLI

Use the repo-local launcher `./bf64`. Prefer `--json` for agent work and `--record` when the operation should leave an audit trail.

## Quick Start

```bash
./bf64 doctor --json
./bf64 project status --project n64/examples/empty --json
./bf64 asset validate-all --project n64/examples/empty --json
./bf64 asset validate-all --project n64/examples/empty --include-excluded --json
./bf64 asset exclusion add 'reference/**' --project <project> --dry-run --json
./bf64 build --project n64/examples/empty --json
./bf64 history list --json
```

## Core Commands

| Goal | Command |
|---|---|
| Check environment | `./bf64 doctor --json` |
| Detect/install SDK | `./bf64 toolchain detect --json` / `toolchain install --dry-run --json` |
| List constraints | `./bf64 constraints list --json` |
| Validate one file | `./bf64 validate <path> --json` |
| Create project | `./bf64 new <dir> --name "<Name>" --json` |
| Initialize existing repo | `./bf64 init --project <dir> --json` / `./bf64 new <dir> --merge --json` |
| Import asset | `./bf64 import <file> --project <project> --dry-run --json` |
| Inspect project | `./bf64 project status --project <project> --json` |
| List/show scenes | `./bf64 scene ls --project <project> --json` / `scene show <id>` |
| Mutate scenes | `./bf64 scene create/duplicate/rename/delete ... --project <project> --json` |
| Mutate objects/components | `./bf64 scene object ...` / `./bf64 scene component ...` / `./bf64 scene attach ...` |
| Mutate prefabs | `./bf64 prefab create/object/component/attach/... --project <project> --json` |
| Mutate node graphs | `./bf64 node-graph create/node/link/variable/group/... --project <project> --json` |
| List/show assets | `./bf64 asset ls --project <project> --json` / `asset show <asset>` |
| Manage asset globs | `./bf64 asset exclusion list/add/remove ... --project <project> --json` |
| Audit excluded sources | `./bf64 asset validate-all --project <project> --include-excluded --json` |
| Plan build | `./bf64 build --project <project> --json` |
| Execute build | `./bf64 build --execute --project <project> --pyrite64-binary ./pyrite64 --json` |
| Run ROM | `./bf64 run --project <project> --emulator ares --json` |
| Profile ROM | `./bf64 run --build --profile --project <project> --json` |
| Inspect/tag focus slice | `./bf64 focus list --json` / `./bf64 music|sfx|environment|avatar|cutscene ...` |

## JSON Contract

Validation results include `ok`, `path`, `kind`, `metadata`, and `issues[]`. Issues use `severity`, `rule`, `message`, optional `fix`, and optional `source`.

Exit codes are documented in `docs/docs/agent/AGENTIC_SURFACE.md`: `0` success, `1` user/project/asset error, `2` environment/toolchain error, `3` internal tooling error, `130` interrupted.

## Workflow

1. Start unknown projects with `project status`.
2. Validate before importing or building.
3. Use `--dry-run` for imports until the destination and sidecar are confirmed.
4. Use `--record` for mutating or acceptance-significant commands.
5. Summarize the JSON issues instead of pasting raw blobs unless requested.
6. Use `run --build --profile` for performance claims; attach the emitted `bf64.profile` JSON rather than transcribing emulator status text.

## Common Agent Mistakes

- Running headed editor actions when a headless `./bf64` command already exposes the same preflight.
- Ignoring nonzero exit codes because JSON still printed.
- Importing without `--dry-run` when destination paths or sidecars are uncertain.
- Using `new --force` for an asset-first repository when `init`/`new --merge` can preserve it.
- Creating one sidecar per draft/reference file when a project `asset exclusion` glob is clearer.
- Treating dry-run build output as proof that the N64 toolchain produced a ROM.
