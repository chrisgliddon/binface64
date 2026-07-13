# Local multiplayer

Binface64 supports one to four local players. Physical controller port 1 is always player 1, through port 4 as player 4; disconnected or inactive ports may be omitted from a split-screen layout without renumbering the remaining players.

## Project input map

Input maps live in `project.p64proj`. A project may define at most 32 digital actions and 8 axes, with up to 4 alternative bindings each:

```json
{
  "input": {
    "deadZone": 0.18,
    "actions": [
      {"name": "confirm", "bindings": [{"buttons": 1, "chord": 0}]},
      {"name": "pause", "bindings": [{"buttons": 8, "chord": 1024}]}
    ],
    "axes": [
      {"name": "move_x", "bindings": [
        {"source": "stick_x", "scale": 1.0, "deadZone": 0.18},
        {"source": "dpad_x", "scale": 1.0, "deadZone": 0.0}
      ]}
    ]
  },
  "multiplayer": {
    "targetRdramMB": 4,
    "controllers": [
      {"name": "Player 1", "rumble": true},
      {"name": "Player 2", "rumble": true},
      {"name": "Player 3", "rumble": true},
      {"name": "Player 4", "rumble": true}
    ]
  }
}
```

`buttons` and `chord` are bitmasks matching `P64::Input::Button`. The build writes `rom:/p64/input` and generates `src/p64/inputActions.h`. Names also have compile-time FNV-1a identifiers:

```cpp
#include "input/input.h"
#include "p64/inputActions.h"

if (P64::Input::pressed(0, P64::Actions::confirm, true)) {
  // Port 1 pressed confirm; the action is consumed for this frame.
}
float movement = P64::Input::axis(2, "move_x"_axis); // Port 3
```

Call `P64::Input::get(player)` for the immutable per-frame snapshot. It contains raw state, normalized stick values, connection transitions, pressed/held/released buttons, action bitsets, and axes. Direct libdragon joypad access remains available to project code, but mixing two consumers of the same input can make ownership ambiguous.

Rumble is binary and port-specific. `P64::Input::rumble(player, seconds)` safely starts a timed effect; capability can be checked with `rumbleSupported`. The engine stops effects on timeout, disconnect, input shutdown, session reset, and scene teardown.

## Match and round state

`P64::Multiplayer::getSession()` is process-lifetime state and survives scene transitions. Configure rules in C++:

```cpp
P64::Multiplayer::Config rules{};
rules.scoreLimit = 5;
rules.timeLimitSeconds = 120.0f;
rules.startingStocks = 3;
rules.roundsToWin = 2;
rules.respawnDelaySeconds = 1.25f;
rules.teams = true;
rules.teamAssignment = P64::Multiplayer::TeamAssignment::Alternating;

auto &session = P64::Multiplayer::getSession();
session.configure(rules);
session.reset(true);
```

The state sequence uses `Lobby`, `Countdown`, `Playing`, `Paused`, `RoundEnd`, `MatchEnd`, and `Tiebreak`. Use readiness, score, stock, elimination, finish, respawn, round, rematch, and object-binding methods on `Session`. Automatic score or time ranking enters `Tiebreak` when it cannot identify one winner; game code must call `resolveTiebreak`.

Event and custom spawn callbacks are fixed-capacity function-pointer entries and allocate no memory. `Session::resolveSpawn` checks custom spawn providers in registration order. `Player Spawn` components (component ID 15) register neutral, player, or team locations; `P64::Multiplayer::Spawns::select(player)` picks the applicable authored location with deterministic round-robin selection.

Disconnecting an active controller pauses gameplay and fixed updates by default. Input, session timers, audio, UI, global `onSceneUnscaledUpdate`, and component `unscaledUpdate` callbacks continue. After reconnection, call `confirmReconnect(player)`; gameplay resumes when the configured disconnect policy is satisfied.

## Cameras, visibility, and UI

A camera target is `Manual`, `Shared`, or `Player`. Manual cameras retain their authored viewport. Shared cameras cover the framebuffer; player cameras receive automatic rectangles for active player identities:

- one player: full screen;
- two players: horizontal split by default;
- three or four players: 2×2 grid, leaving the final quadrant free in a three-player game.

Use `P64::Multiplayer::Viewports::setTwoPlayerLayout` for vertical layout or `setCustom` for C++ rectangles. Objects have a five-bit view mask: bits 0–3 are players 1–4 and bit 4 is shared. The backward-compatible default is `0x1f`.

`P64::Multiplayer::GroupCamera` is an optional fixed-angle shared-camera helper. It computes a smoothed, bounds-clamped centroid and zoom from up to four active targets without rotating gameplay orientation.

UI documents target the shared display or one player viewport and have a four-bit input-player mask. Focus is independent per player. Text editing has one exclusive owner until submission or cancellation. UI events set `ObjectEvent::sourcePlayer` to a one-based player number; legacy event senders and `focus(id)` continue to mean player 1.

In split-screen mode, positional audio evaluates all active player cameras and keeps the strongest left and right contribution. Shared-camera mode uses the shared listener.

## Editor and CLI

Open **Focus → Multiplayer** for input maps, controller metadata, layout preview, and camera/HUD/spawn diagnostics.

The automation CLI has stable JSON output and supports dry-run/record conventions:

```sh
./bf64 multiplayer status --project path/to/game --json
./bf64 multiplayer validate --project path/to/game --json
./bf64 scene attach player-spawn 1 42 --spawn-target player --spawn-index 0 --project path/to/game --json
./bf64 run --build --rdram 4 --profile --profile-warmup 180 --profile-frames 600 --project path/to/game
```

Validation covers controller metadata, rumble declarations, action hashes and bindings, camera targets and rectangles, HUD ownership, view masks, spawns, and 4 MB/8 MB compatibility. Default RGBA16 at 320×240 is the certification target; BigTex requires the 8 MB path.

See `n64/examples/multiplayer` for an adaptive shared/split configuration, arena match helpers, and checkpoint-race flow. Emulator profiling cannot replace the final four-controller and per-port Rumble Pak test on an N64 or flashcart.

For hardware bring-up, `n64/tests/input_probe` builds a small standalone ROM that displays all four fixed ports and emits structured connect/join/disconnect/reconnect records over the debug channel.
