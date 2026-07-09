---
name: skill-name
description: Use when working on a specific BF64 task domain and the agent needs focused guidance, source links, commands, and common mistakes.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: template
  target_version: "BF64"
---

# Skill Name

## When To Use

- Use this skill for a narrow BF64 task.
- Route broader questions through `bf64` first.

## Quick Start

```bash
./bf64 doctor --json
```

## Workflow

1. Read the grounding docs for the subsystem.
2. Prefer structured BF64 CLI commands over raw file edits.
3. Validate outputs with `./bf64 validate`, `./bf64 asset validate-all`, or the subsystem-specific build.

## Grounding

- `docs/docs/agent/AGENTIC_SURFACE.md`
- `docs/docs/agent/ARCHITECTURE.md`
- `docs/docs/agent/CODEMAP.md`
- `docs/docs/n64/limits.json`

## Common Agent Mistakes

- Guessing from generic N64 lore instead of BF64's current docs and validator.
- Editing generated files or ROM outputs instead of project source files.
- Skipping JSON validation before reporting success.
