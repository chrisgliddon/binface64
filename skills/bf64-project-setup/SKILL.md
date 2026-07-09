---
name: bf64-project-setup
description: Use when creating, opening, checking, building, or running a BF64 project, including toolchain setup, starter project layout, and project path pitfalls.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "1"
  area: project
  target_version: "BF64"
---

# BF64 Project Setup

Use this for first-run setup or when entering an unfamiliar project.

## Quick Start

```bash
./bf64 doctor --json
./bf64 new ./projects/agent_game --name "Agent Game" --json
./bf64 project status --project ./projects/agent_game --json
./bf64 build --project ./projects/agent_game --json
```

## Project Rules

- A project config is `project.p64proj`.
- The starter template is copied from `n64/examples/empty`.
- Avoid spaces in project paths; the editor launcher rejects them because downstream Makefile/libdragon tooling is fragile.
- Use `./bf64 build --execute` only after `doctor --strict` or strict build preflight is clean.
- ROM output is `<romName>.z64`; `run` needs that ROM plus an emulator command.

## Workflow

1. Run `./bf64 doctor --json` and note missing toolchain pieces.
2. Create with `./bf64 new <dir> --name "<Name>" --json`; use `--force` only when replacing an intended target.
3. Inspect with `project status`; fix scene, asset, and toolchain issues before adding content.
4. Use `asset import` and scene/editor operations for content, then `asset validate-all`.
5. Build dry-run first, then `build --execute --pyrite64-binary <path>`.
6. Run with Ares or gopher64 and capture stdout/stderr/log tails.

## Grounding

- `docs/docs/agent/AGENTIC_SURFACE.md`
- `docs/docs/agent/ARCHITECTURE.md` sections on editor boot, actions, and build pipeline.
- `docs/docs/agent/CODEMAP.md` sections on top-level layout and `src/build`.

## Common Agent Mistakes

- Creating projects under paths with spaces.
- Editing copied template generated outputs instead of source assets and project files.
- Treating missing N64 toolchain warnings as irrelevant when the user asked for a real ROM.
- Forgetting that headed Pyrite64 editor state and headless BF64 commands must stay aligned.
