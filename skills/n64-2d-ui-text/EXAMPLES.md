# N64 2D UI And Text Examples

Use these as current BF64 patterns for HUDs and menus.

## HUD Sprites And Numbers

`n64/examples/jam25/src/user/HUD.cpp`:

```cpp
DrawLayer::use2D();
  rspq_block_run(data->dplCoins);
  rdpq_set_prim_color({0xFF, 0xFF, 0xFF, 0xFF});
  User::Fonts::useNumber();
  User::Fonts::printNumber(SCREEN_EDGE + 20, 240 - baseY - 17, data->displayCoins);
DrawLayer::useDefault();
```

Pattern:

- Pre-build repeated sprite state into `rspq_block_t` when practical.
- Use `DrawLayer::use2D()` only for the 2D pass, then restore default.
- Keep HUD counters stable and update display values intentionally.

## Centered Menu Text

`n64/examples/jam25/src/user/TitleScreen.cpp` uses `rdpq_textparms_t`:

```cpp
constexpr rdpq_textparms_t TEXT_CENTER{
  .width = 320,
  .align = ALIGN_CENTER,
  .disable_aa_fix = true
};

rdpq_text_printf(&TEXT_CENTER, User::FONT_TEXT, 0, y, "Start Game");
```

Pattern:

- Set width to the target screen width for centered text.
- Use dedicated font ids and styles rather than reconfiguring global state blindly.
- Keep strings short; do not design desktop-width menu copy.

## Asset Checklist

- Validate sprite sheets with `./bf64 validate <png> --texture-format <format> --json`.
- Import `.ttf` fonts with `./bf64 import`.
- Confirm generated font/sprite outputs with a real build.
- Take emulator screenshots for text readability.

## Gotchas

- UI code is still N64 rendering code; reset render state after custom drawing.
- Thin strokes and low-contrast text fail even if the source art looks clean.
- Runtime text is not a substitute for long-form layout; design strings for the resolution.
