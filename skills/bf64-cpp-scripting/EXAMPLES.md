# BF64 C++ Scripting Examples

These examples are grounded in current BF64 sources. Treat them as patterns to inspect, not copy-paste templates for every game.

## Minimal Runtime Script Shape

Current examples use a generated script namespace and `P64_DATA`:

```cpp
#include "script/userScript.h"

namespace P64::Script::C0123456789ABCDEF
{
  P64_DATA(
    float timer;
  );

  void init(Object& obj, Data *data)
  {
    data->timer = 0.0f;
  }

  void update(Object& obj, Data *data, float deltaTime)
  {
    data->timer += deltaTime;
  }
}
```

Source grounding:

- `n64/engine/include/script/userScript.h` defines `P64_DATA`.
- `n64/examples/jam25/src/user/Coin.cpp` shows `init`, `update`, `onCollision`, and `onEvent`.
- `n64/examples/jam25/src/user/HUD.cpp` shows `init`, `update`, `draw`, and `destroy`.

## Asset And Audio References

`Coin.cpp` uses generated asset hash literals and the audio manager:

```cpp
auto sfx = AudioManager::play2D("sfx/CoinGet.wav64"_asset);
sfx.setVolume(0.3f);
sfx.setSpeed(1.0f - Math::rand01()*0.1f);
```

Check:

- `n64/engine/include/audio/audioManager.h`
- Generated project header `src/p64/assetTable.h` after a build.
- `docs/docs/n64/audio-assets.md` before adding many simultaneous SFX.

## Runtime UI Drawing

`HUD.cpp` draws 2D UI inside `draw`:

```cpp
void draw(Object& obj, Data *data, float deltaTime)
{
  DrawLayer::use2D();
    rdpq_set_prim_color({0xFF, 0xFF, 0xFF, 0xFF});
    User::Fonts::useNumber();
    User::Fonts::printNumber(40, 223, data->displayCoins);
  DrawLayer::useDefault();
}
```

Rules:

- Always restore the draw layer.
- Keep text and sprite state local or explicitly reset it.
- Validate the source sprite/font assets before debugging draw code.

## Acceptance Check

Run:

```bash
./bf64 project status --project <project> --json
./bf64 build --project <project> --json
./bf64 build --execute --project <project> --pyrite64-binary ./pyrite64 --json
```
