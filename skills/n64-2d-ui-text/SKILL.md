---
name: n64-2d-ui-text
description: Use when designing or implementing BF64 2D sprites, HUDs, fonts, readable text, icon sheets, menus, dialogue UI, or N64-resolution interface art.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: ui-text
  target_version: "BF64"
---

# N64 2D UI And Text

Use this for HUD, menus, dialogue, icons, labels, and font assets.

## Quick Start

```bash
./bf64 constraints texture --json
./bf64 validate ./hud.ci4.png --texture-format CI4 --json
./bf64 import ./ui-font.ttf --project <project> --dest fonts/ui-font.ttf --dry-run --json
```

## Design Rules

- Design at target display scale first; N64 output makes small text and thin strokes fail quickly.
- Use small sprite sheets with deliberate palettes.
- Prefer high-contrast text and icons over subtle shading.
- Keep UI textures TMEM-aware; CI4/IA4 are often better than full-color PNGs.
- Font assets are imported as `.ttf`; the build pipeline uses libdragon `mkfont`.

## Workflow

1. Decide if the UI is texture sprites, runtime text, or a mix.
2. Validate sprite sheets with explicit texture format.
3. Import fonts and sprite sheets through `./bf64 import`.
4. Keep strings short enough for low-resolution layouts.
5. Test in emulator screenshots, not only source art previews.

## Examples

- See [EXAMPLES.md](EXAMPLES.md) for HUD sprite/number drawing and centered menu text patterns from current BF64 examples.

## Grounding

- `docs/docs/n64/textures.md`
- `docs/docs/n64/display-and-video.md`
- `docs/docs/n64/asset-checklist.md`
- `docs/docs/agent/CODEMAP.md` `src/build/fontBuilder.cpp` and texture builder entries.

## Common Agent Mistakes

- Designing UI at modern desktop density.
- Using anti-aliased tiny fonts that blur at 320x240-style output.
- Treating source SVG/vector art as a runtime format.
- Forgetting UI art still competes for TMEM, ROM, and RDRAM.
