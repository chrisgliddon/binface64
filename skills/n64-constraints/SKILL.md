---
name: n64-constraints
description: Use when making BF64 decisions about N64 hardware limits, memory, ROM size, TMEM, RSP/RDP budgets, emulator accuracy, or whether a design can fit real hardware.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "1"
  area: constraints
  target_version: "BF64"
---

# N64 Constraints

Use this before approving assets, rendering plans, audio mixes, or gameplay scope.

## Quick Start

```bash
./bf64 constraints list --json
./bf64 constraints texture --json
./bf64 constraints model --json
./bf64 constraints audio --json
python3 -m json.tool docs/docs/n64/limits.json >/tmp/bf64-limits.json
```

## Budget Anchors

- Texture facts come from `docs/docs/n64/textures.md` and `docs/docs/n64/limits.json`.
- Model facts come from `docs/docs/n64/models-and-meshes.md` and `limits.json`.
- Audio facts come from `docs/docs/n64/audio.md`, `audio-assets.md`, and `limits.json`.
- ROM/RDRAM facts come from `docs/docs/n64/rom-budgets.md`.
- Emulator and hardware-test facts come from `docs/docs/n64/emulation-and-hardware-testing.md`.

## Decision Workflow

1. Identify which budget is at risk: RDRAM, ROM, TMEM, RSP transform time, RDP fill rate, audio mixer channels, or emulator/hardware accuracy.
2. Read the matching `./bf64 constraints <topic> --json` output.
3. Cross-check the human docs for rationale when the design is near a limit.
4. Convert the decision into a validator-backed rule, import setting, or written budget.
5. If the design cannot fit, reduce simultaneous actors, visible triangles, texture size, audio channels, framebuffer effects, or ROM asset scope.

## Practical Defaults

- Prefer small CI4/CI8 textures for most game art; reserve RGBA formats for assets that need alpha/color fidelity.
- Keep individual model files under BF64's 65535 vertex/index limits and assume tiny3d still pays per visible triangle.
- Treat XM64 background music as mixer-channel budget, not free ambience.
- Test on Ares or gopher64; do not rely on Project64 for acceptance.
- Plan for real hardware or flashcart differences before claiming release readiness.

## Common Agent Mistakes

- Treating cartridge ROM space as the only limit while ignoring RDRAM, TMEM, and mixer channels.
- Saying "N64 can do it" without considering BF64's current importer and runtime pipelines.
- Using Project64 screenshots as proof of correctness.
- Repeating old libdragon/tiny3d assumptions instead of the pinned docs and `limits.json`.
