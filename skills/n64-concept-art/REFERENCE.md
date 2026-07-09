# N64 Concept Art Reference

## Prompt Budget Fields

Include these fields in any asset prompt:

```text
Asset name:
Category:
Gameplay role:
Target triangle count:
Triangle ceiling:
Material/color zones:
Texture format target:
Camera/gameplay view:
Top-down readability requirement:
Avoid:
```

## Starter Budgets

These are prompt budgets, not engine-enforced truth. Validate final assets with `n64-models`, `n64-textures`, and `./bf64 validate`.

| Category | Target | Ceiling | Materials |
|---|---:|---:|---:|
| Player | 500-800 tris | 1000 tris | up to 4 |
| Enemy | 250-450 tris | 600 tris | 1-3 |
| Hero prop | 30-120 tris | 200 tris | 1-2 |
| Background prop | up to 60 tris | 200 tris | 1 |
| Environment chunk | 1500-2500 visible tris | 3500 visible tris | repeated palette |

## Review Checklist

- Silhouette reads at thumbnail size.
- Main gameplay view reads without rotating the camera.
- Material zones are clear enough to model and texture.
- No thin straps, hair strands, fingers, tiny alpha details, or PBR-only features.
- Texture detail can fit 16x16, 32x32, or another explicit N64-friendly target.
- The concept implies a simple collision shape.

## Follow-Up Prompts

After a hero pose is accepted:

- Turnaround sheet: front, side, back, top, and 3/4 view.
- Texture reference: flat diffuse zones, palette swatches, no lighting baked into detail unless intentional.
- In-game context: target camera, nearby props, scale grid, UI-safe readability.
