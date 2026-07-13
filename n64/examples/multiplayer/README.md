# Binface64 local multiplayer reference

This project keeps physical ports fixed to players 1–4 and demonstrates both reference genres from one adaptive ROM:

- `Lobby`: each connected port presses Start to become ready. No active players uses the shared camera; ready players activate automatic split-screen cameras.
- `Arena`: FFA or alternating teams, score limit, stocks, delayed respawn, per-port rumble, disconnect pause/reconnect confirmation, results, and rematch.
- `Race`: countdown, checkpoint completion order, round standings, tiebreak state, and rematch.

Scene 1 contains one shared camera, four player-target cameras, and player/neutral spawn points. Scene 2 is a shared-camera configuration. `src/user/MultiplayerModes.cpp` is an automatically discovered global script and drives both modes using the genre-neutral runtime APIs.

Controls:

- Start joins/readies a fixed physical port; Left/Right selects FFA or alternating teams before anyone joins.
- A or Z scores in the arena and records a finish in the race; B loses an arena stock.
- L+Start pauses. Controller removal also pauses; reconnect and press A to confirm.
- A advances a completed round or resolves a tiebreak. Start returns match results to the ready lobby.

The built-in debug font draws a shared status line and a colored per-player HUD inside each active viewport, keeping the reference project asset-light enough for the 4 MB profile target.

Profile the 4 MB acceptance target with:

```sh
./bf64 run --build --rdram 4 --profile --profile-warmup 180 --profile-frames 600 --project n64/examples/multiplayer
```

Repeat with `--rdram 8` to validate the enhanced asset-budget path. Hardware certification still requires four physical controllers and four Rumble Paks.
