---
name: n64-textures
description: Use when creating, converting, validating, or budgeting BF64 N64 textures, sprites, CI palettes, TMEM usage, alpha, compression, or BigTex assets.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: textures
  target_version: "BF64"
---

# N64 Textures

Use this before drawing, importing, or assigning texture assets.

## Quick Start

```bash
./bf64 constraints texture --json
./bf64 validate ./tile.ci4.png --texture-format CI4 --json
./bf64 validate ./wall.bci.png --texture-format BCI_256 --scene-pipeline bigtex --json
```

## Format Decisions

- Use CI4 for tiny palettes and broad reuse.
- Use CI8 when 16 colors are not enough but palette art still fits.
- Use RGBA16 when color fidelity or 1-bit alpha matters.
- Use IA/I formats for masks, monochrome UI, and intensity-driven art.
- Use BigTex only for 256x256 `.bci.png` assets in the BigTex pipeline.

## Workflow

1. Pick format from art need and TMEM budget, not source image size alone.
2. Name files with format hints when useful: `crate.ci4.png`, `panel.rgba16.png`, `wall.bci.png`.
3. Validate with explicit `--texture-format`.
4. Import through `./bf64 import`; let build run `mksprite` or BF64 BCI conversion.
5. Re-check scene pipeline when using BigTex.

## Grounding

- `docs/docs/n64/textures.md`
- `docs/docs/n64/display-and-video.md`
- `docs/docs/n64/rom-budgets.md`
- `docs/docs/n64/limits.json`

## Common Agent Mistakes

- Choosing RGBA32 because the source PNG has full color; it is usually too expensive.
- Forgetting CI palettes also consume TMEM.
- Using BigTex without 256x256 dimensions and render pipeline `2`.
- Designing sub-pixel texture details that disappear at N64 output resolution.
