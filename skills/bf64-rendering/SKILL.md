---
name: bf64-rendering
description: Use when working on BF64 rendering, tiny3d materials, draw layers, lighting, HDR/bloom, BigTex, framebuffer choices, or render-pipeline validation.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: rendering
  target_version: "BF64"
---

# BF64 Rendering

Use this when deciding how something should render on the N64.

## Quick Start

```bash
./bf64 constraints texture --json
./bf64 validate <texture.png> --scene-pipeline default --json
./bf64 validate <bigtex.bci.png> --scene-pipeline bigtex --json
./bf64 scene validate --project <project> --json
```

## Pipeline Notes

- BF64 uses tiny3d through engine rendering code, not a desktop PBR renderer.
- Scene render pipelines include Default, HDR/Bloom, and BigTex.
- BigTex assets use `.bci.png`, must be exactly 256x256, and require render pipeline `2`.
- HDR and BigTex paths have framebuffer constraints; validate scenes before assuming a pipeline fits.
- Fast64 material features are limited to what tiny3d/BF64 imports and bakes.

## Workflow

1. Choose the simplest pipeline that satisfies the look.
2. Validate all textures with the intended scene pipeline.
3. Keep material choices compatible with Fast64/tiny3d import, not generic glTF PBR.
4. For BigTex, budget Expansion Pak/RDRAM and scene pipeline together.
5. Build and run on an accurate emulator before accepting visual features.

## Grounding

- `docs/docs/n64/display-and-video.md`
- `docs/docs/n64/textures.md`
- `docs/docs/n64/models-and-meshes.md`
- `docs/docs/agent/ARCHITECTURE.md` runtime renderer and asset pipeline sections.

## Common Agent Mistakes

- Designing with desktop PBR assumptions instead of N64 combiner/material limits.
- Importing a BigTex image without setting the scene to the BigTex pipeline.
- Treating editor preview rendering as proof of N64 runtime output.
- Ignoring fill-rate and framebuffer costs when adding post effects.
