# N64 Audio Assets Reference

## Source-To-Runtime Path

| Source | BF64 import | Runtime output | Notes |
|---|---|---|---|
| `.wav` | yes | `.wav64` | Use for SFX, voice, short ambience. |
| `.mp3` | yes | `.wav64` | Prototype convenience; gets converted. |
| `.xm` | yes | `.xm64` | Use for background music and module-style loops. |
| `.mid` | no | no direct output | Keep as source; convert/export to `.xm` first. |
| song JSON | no | no direct output | Useful as deterministic composition source only if a project tool converts it. |

## MIDI-Derived Music Workflow

BF64 does not yet have Fresh Cut's `hop audio xm64` command. Until it does:

1. Keep `.mid` or song JSON as editable source material outside the BF64 import path.
2. Export a fixed-tempo, fixed-meter arrangement.
3. Convert to `.xm` with an explicit tracker/conversion tool.
4. Simplify to the target XM channel budget.
5. Validate/import the `.xm`:

```bash
./bf64 validate ./theme.xm --role music --json
./bf64 import ./theme.xm --project <project> --dest audio/music/theme.xm --dry-run --json
```

## Runtime Playback Pattern

Runtime code can play asset-table entries through the audio manager:

```cpp
auto handle = AudioManager::play2D("sfx/UiOk.wav64"_asset);
handle.setVolume(0.3f);
```

Check `n64/engine/include/audio/audioManager.h` and examples under `n64/examples/jam25/src/user`.

## Tooling Gap To Fill

Add a BF64-native deterministic converter later:

```bash
./bf64 audio xm64 <song.mid-or-json> --soundfont <sf2> --out <project>/assets/audio/music/theme.xm --json
```

Minimum behavior:

- Fixed tempo/meter only for v1.
- Emit `.xm` source and optionally run `audioconv64` when toolchain is present.
- Report channel count, sample memory estimate, loop points, and licensing reminders.
- Reuse `docs/docs/n64/limits.json` audio budgets.
