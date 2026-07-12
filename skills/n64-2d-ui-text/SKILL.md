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
./bf64 ui new menus/title --project <project> --json
./bf64 ui validate --all --project <project> --json
```

## Design Rules

- Design at target display scale first; N64 output makes small text and thin strokes fail quickly.
- Use small sprite sheets with deliberate palettes.
- Prefer high-contrast text and icons over subtle shading.
- Keep UI textures TMEM-aware; CI4/IA4 are often better than full-color PNGs.
- Font assets are imported as `.ttf` or `.otf`; the build pipeline uses libdragon `mkfont`.
- Fonts referenced by `.bfui` documents need an auto-load ID from 1 through 15.
- Runtime code addresses elements with the `_ui` literal and receives activate/change/submit object events.
- TextInput keyboards, maximum lengths, and erase behavior count complete UTF-8 code points; do not pre-split controller charsets into bytes.
- Use `ProgressBar` plus `UI::setValue(id, current, max)` for mutable HUD meters; authored thresholds provide up to three absolute upper-bound colors.
- Use `P64::UI::DialogueRunner` for UTF-8-safe typewriter reveal and manual/timed line progression; bind it with `UI::bindDialogue` and keep controller policy in game code.

## Workflow

1. Create or open a `.bfui` document in the UI workspace or with `./bf64 ui new`.
2. Decide if each element is a texture sprite, runtime text, or a mix.
3. Validate and import fonts and sprite sheets through `./bf64 import`.
4. Author `Container`, `Image`, `Text`, `Button`, `TextInput`, and `ProgressBar` elements with stable IDs.
5. Run `./bf64 ui validate --all`, build, and test emulator screenshots rather than trusting only the desktop preview.
6. For dialogue, store line strings for the runner's full lifetime, update it once per frame, and map the game's confirm action to `advance()`.

## Examples

- See [EXAMPLES.md](EXAMPLES.md) for HUD sprite/number drawing and centered menu text patterns from current BF64 examples.

## Grounding

- `docs/docs/n64/textures.md`
- `docs/docs/n64/display-and-video.md`
- `docs/docs/n64/asset-checklist.md`
- `docs/docs/agent/CODEMAP.md` `src/build/fontBuilder.cpp` and texture builder entries.
- `docs/docs/project/ui-focus-area.md`
- `docs/docs/project/dialogue.md`

## Common Agent Mistakes

- Designing UI at modern desktop density.
- Using anti-aliased tiny fonts that blur at 320x240-style output.
- Treating source SVG/vector art as a runtime format.
- Forgetting UI art still competes for TMEM, ROM, and RDRAM.
- Splitting UTF-8 text manually or rebuilding a game-side typewriter when `DialogueRunner` already preserves code-point boundaries.
