---
name: n64-game-design-budgets
description: Use when translating BF64 game ideas into N64-feasible scope, including actor counts, camera design, render cost, ROM/RDRAM, audio, asset counts, and QA risk.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: design
  target_version: "BF64"
---

# N64 Game Design Budgets

Use this before committing to a feature, level, art style, or production plan.

## Quick Start

```bash
./bf64 constraints list --json
./bf64 project status --project <project> --json
./bf64 asset validate-all --project <project> --json
```

## Budget Table To Produce

For any new feature or vertical slice, write a compact budget with:

- Camera and visible area.
- Peak visible actors and background objects.
- Peak visible triangles and texture formats.
- RDRAM costs: framebuffers, BigTex pools, resident assets, audio.
- ROM costs: models, textures, audio, fonts, scenes.
- Audio mixer channels: music plus simultaneous SFX.
- QA matrix: emulator, hardware/flashcart, logs/screenshots needed.

## Workflow

1. Convert the idea into worst-case simultaneous runtime load.
2. Query `limits.json` and the relevant skill docs.
3. Reduce scope until the budget has margin, not just a perfect-fit estimate.
4. Identify what the BF64 CLI can validate now and what needs a real build/run.
5. Record assumptions in the project docs or issue before implementation.

## Grounding

- `docs/docs/n64/performance-budgets.md`
- `docs/docs/n64/rom-budgets.md`
- `docs/docs/n64/hardware.md`
- `docs/docs/n64/emulation-and-hardware-testing.md`
- `docs/docs/n64/limits.json`

## Common Agent Mistakes

- Budgeting average scenes instead of peak scenes.
- Ignoring audio and framebuffer memory while optimizing only triangles.
- Designing levels around unlimited texture variety.
- Calling a design feasible before emulator/hardware QA requirements are known.
