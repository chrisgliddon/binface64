---
name: n64-concept-art
description: Use when generating or reviewing BF64 N64-style concept art, low-poly hero poses, turnarounds, texture references, sprite references, or asset prompts.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: concept-art
  target_version: "BF64"
---

# N64 Concept Art

Use this to create visual references that modelers and agents can turn into real BF64 assets.

## Hero Pose Prompt Pattern

```text
Create one low-poly Nintendo 64 era 3D asset concept for BF64/Pyrite64.
Subject: <one clear subject>.
Category: <player | enemy | hero prop | background prop | environment chunk>.
View: single 3/4 front view, centered, neutral gray background, faint scale grid.
Style: faceted low-poly geometry, flat colors, clear material zones, readable silhouette.
Budget label: show target triangles, ceiling triangles, material count, and intended texture format.
Avoid: PBR, glossy reflections, tiny separate parts, thin straps, photoreal texture detail, gradients, alpha tricks, multiple subjects.
Top-down check: the silhouette must stay readable when viewed from above at gameplay size.
```

## Asset Categories

- Player: readable silhouette, few strong color zones, animation-friendly proportions.
- Enemy: lower triangle count, exaggerated gameplay tell, simple materials.
- Hero prop: iconic shape, simple material zones, no sub-pixel detail.
- Background prop: very low geometry, strong top-down recognizability.
- Environment chunk: modular boundaries, repeated texture plan, collision shape in mind.

## Workflow

1. Start with a hero pose, not a full asset sheet.
2. Check against `n64-models`, `n64-textures`, and `n64-game-design-budgets`.
3. If accepted, request turnaround, texture reference, and in-game scale/context as follow-up assets.
4. Treat generated images as references only; real assets still need modeled geometry, texture validation, and BF64 import/build.

## Reference

- See [REFERENCE.md](REFERENCE.md) for prompt budget fields, starter visual budgets, review checklist, and follow-up prompt types.

## Grounding

- `docs/docs/n64/models-and-meshes.md`
- `docs/docs/n64/textures.md`
- `docs/docs/n64/performance-budgets.md`
- `docs/docs/n64/asset-checklist.md`

## Common Agent Mistakes

- Asking for beautiful high-detail renders that cannot become N64 assets.
- Creating concept art with material/texture complexity the pipeline cannot represent.
- Skipping the top-down readability test for gameplay assets.
- Treating generated concept images as importable game assets.
