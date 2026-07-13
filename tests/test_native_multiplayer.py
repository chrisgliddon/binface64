import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_INCLUDE = ROOT / "n64" / "engine" / "include"
ENGINE_SRC = ROOT / "n64" / "engine" / "src"


class NativeMultiplayerTests(unittest.TestCase):
    def compile_and_run(self, sources: list[Path], harness: str, stubs: dict[str, str] | None = None) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, contents in (stubs or {}).items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")
            harness_path = root / "test.cpp"
            harness_path.write_text(harness, encoding="utf-8")
            binary = root / "test"
            proc = subprocess.run(
                [
                    "g++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                    "-I", str(root), "-I", str(ENGINE_INCLUDE),
                    *map(str, sources), str(harness_path), "-o", str(binary),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            run = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_source_player_events_and_five_bit_view_masks(self) -> None:
        self.compile_and_run(
            [],
            r'''
#include <cassert>
#include <new>
#include "scene/event.h"
#include "scene/object.h"
int main() {
  P64::ObjectEvent legacy{};
  assert(legacy.sourcePlayer == 1);
  P64::ObjectEventQueue events;
  events.add(7, 3, P64::EVENT_TYPE_UI_ACTIVATE, 99, 4);
  assert(events.events.size() == 1 && events.events[0].event.sourcePlayer == 4);

  alignas(P64::Object) unsigned char storage[sizeof(P64::Object)]{};
  auto *object = new(storage) P64::Object;
  assert(object->getViewMask() == 0x1F);
  object->setViewMask(0x05);
  assert(object->getViewMask() == 0x05);
  object->setViewMask(0);
  assert(object->getViewMask() == 0);
}
''',
            {"libdragon.h": "#pragma once\nstruct fm_quat_t { float x{},y{},z{},w{}; };\nstruct fm_vec3_t { float x{},y{},z{}; };\n"},
        )

    def test_viewports_compact_non_contiguous_ports(self) -> None:
        self.compile_and_run(
            [ENGINE_SRC / "multiplayer" / "viewports.cpp"],
            r'''
#include <cassert>
#include "multiplayer/viewports.h"
int main() {
  using namespace P64::Multiplayer::Viewports;
  std::array<Rect, 4> rects{};
  assert(calculate(0, 320, 240, rects) == 0);
  assert(calculate(1u << 2, 320, 240, rects) == 1);
  assert(rects[2].x == 0 && rects[2].y == 0 && rects[2].width == 320 && rects[2].height == 240);
  assert(calculate((1u << 0) | (1u << 2), 320, 240, rects) == 2);
  assert(rects[0].x == 0 && rects[0].y == 0 && rects[0].width == 320 && rects[0].height == 120);
  assert(!rects[1].valid());
  assert(rects[2].x == 0 && rects[2].y == 120 && rects[2].width == 320 && rects[2].height == 120);
  assert(calculate(0x0D, 320, 240, rects) == 3);
  assert(rects[0].x == 0 && rects[0].y == 0);
  assert(rects[2].x == 160 && rects[2].y == 0);
  assert(rects[3].x == 0 && rects[3].y == 120);
  setTwoPlayerLayout(TwoPlayerLayout::Vertical);
  assert(calculate(0x09, 320, 240, rects) == 2);
  assert(rects[0].width == 160 && rects[3].x == 160 && rects[3].height == 240);
  setCustom({Rect{2, 3, 100, 200}, Rect{110, 3, 100, 200}, Rect{}, Rect{}});
  setTwoPlayerLayout(TwoPlayerLayout::Custom);
  assert(calculate(0x06, 320, 240, rects) == 2);
  assert(rects[1].x == 2 && rects[2].x == 110);
  assert(calculate(0x0F, 321, 241, rects) == 4);
  assert(rects[0].width == 160 && rects[1].width == 161);
  assert(rects[2].height == 121 && rects[3].x == 160);
}
''',
        )

    def test_session_pause_tiebreak_stocks_respawn_and_race(self) -> None:
        self.compile_and_run(
            [ENGINE_SRC / "multiplayer" / "session.cpp"],
            r'''
#include <cassert>
#include "input/input.h"
#include "multiplayer/session.h"

namespace { bool ports[4]{}; }
namespace P64::Input {
bool connected(std::uint8_t player) { return player < 4 && ports[player]; }
void stopAllRumble() {}
}
namespace { void onEvent(const P64::Multiplayer::Event&, void *context) { ++*static_cast<int*>(context); } }
namespace { P64::Object* customSpawn(std::uint8_t player, void*) { return player == 2 ? reinterpret_cast<P64::Object*>(1) : nullptr; } }

int main() {
  using namespace P64::Multiplayer;
  Session session;
  Config config{};
  config.timeLimitSeconds = 0.1f;
  config.startingStocks = 2;
  config.roundsToWin = 2;
  config.respawnDelaySeconds = 0.05f;
  session.configure(config);
  session.reset(false);
  int eventCount = 0;
  assert(session.addEventCallback(onEvent, &eventCount));
  assert(session.addSpawnCallback(customSpawn));
  assert(session.resolveSpawn(2) == reinterpret_cast<P64::Object*>(1));
  assert(session.resolveSpawn(0) == nullptr);
  ports[0] = ports[2] = true;
  session.syncControllers();
  assert(session.setReady(0) && session.setReady(2));
  assert(session.activeMask() == 0x05 && session.readyMask() == 0x05);
  assert(session.beginCountdown(0.01f));
  session.update(0.02f);
  assert(session.getState() == State::Playing);
  assert(session.addScore(0, 3) && session.addScore(2, 3));
  session.update(0.2f);
  assert(session.getState() == State::Tiebreak);
  assert(session.resolveTiebreak(0));
  assert(session.getState() == State::RoundEnd && session.getPlayer(0).roundWins == 1);

  config.timeLimitSeconds = 0.0f;
  session.configure(config);
  session.rematch();
  session.setReady(0); session.setReady(2); session.beginCountdown(0);
  assert(session.loseStock(2));
  assert(session.getPlayer(2).respawnPending);
  session.update(0.1f);
  assert(session.getPlayer(2).respawnReady && session.consumeRespawn(2));
  assert(session.loseStock(2));
  assert(session.getState() == State::RoundEnd);

  session.rematch();
  session.setReady(0); session.setReady(2); session.beginCountdown(0);
  ports[2] = false;
  session.syncControllers();
  assert(session.getState() == State::Paused && session.getPauseReason() == PauseReason::ControllerDisconnected);
  ports[2] = true;
  session.syncControllers();
  assert(session.confirmReconnect(2));
  assert(session.getState() == State::Playing);
  assert(session.pause());
  ports[2] = false;
  session.syncControllers();
  assert(session.getState() == State::Paused && session.getPauseReason() == PauseReason::ControllerDisconnected);
  ports[2] = true;
  session.syncControllers();
  assert(session.confirmReconnect(2) && session.getState() == State::Playing);

  config.disconnectPolicy = DisconnectPolicy::PauseWhenAllActiveDisconnected;
  session.configure(config);
  session.rematch();
  session.setReady(0); session.setReady(2); session.beginCountdown(0);
  ports[2] = false;
  session.syncControllers();
  assert(session.getState() == State::Playing);
  ports[0] = false;
  session.syncControllers();
  assert(session.getState() == State::Paused);
  ports[2] = true;
  session.syncControllers();
  assert(session.confirmReconnect(2));
  assert(session.getState() == State::Playing);
  ports[0] = true;
  session.syncControllers();

  session.rematch();
  session.setReady(0); session.setReady(2); session.beginCountdown(0);
  assert(session.finish(2));
  assert(session.finish(0));
  assert(session.getState() == State::RoundEnd && session.getPlayer(2).roundWins == 1);

  config.teams = true;
  config.scoreLimit = 4;
  config.startingStocks = 0;
  config.teamAssignment = TeamAssignment::Alternating;
  session.configure(config);
  session.rematch();
  ports[1] = ports[3] = true;
  session.syncControllers();
  for(std::uint8_t player=0; player<4; ++player)assert(session.setReady(player));
  assert(session.beginCountdown(0));
  assert(session.addScore(0, 2));
  assert(session.addScore(2, 2));
  assert(session.getState() == State::RoundEnd);
  assert(session.getPlayer(0).roundWins == 1 && session.getPlayer(2).roundWins == 1);
  assert(eventCount > 0);
  session.removeEventCallback(onEvent, &eventCount);
  session.removeSpawnCallback(customSpawn);
  assert(session.resolveSpawn(2) == nullptr);

  config.teams = false;
  config.scoreLimit = 0;
  config.startingStocks = 2;
  config.teamAssignment = TeamAssignment::Manual;
  session.configure(config);
  session.rematch();
  ports[1] = ports[2] = ports[3] = false;
  session.syncControllers();
  assert(session.setReady(0) && session.beginCountdown(0));
  assert(session.loseStock(0));
  assert(session.getState() == State::Playing && session.getPlayer(0).respawnPending);
  assert(session.loseStock(0));
  assert(session.getState() == State::Tiebreak);
}
''',
        )

    def test_input_snapshots_chords_consumption_dead_zone_and_rumble_cleanup(self) -> None:
        stubs = {
            "libdragon.h": r'''
#pragma once
#include <cstdint>
#include <cstdlib>
typedef std::uint8_t joypad_port_t;
struct joypad_buttons_t { std::uint16_t raw{}; };
struct joypad_inputs_t { joypad_buttons_t btn{}; std::int8_t stick_x{}; std::int8_t stick_y{}; };
void joypad_poll(); bool joypad_is_connected(joypad_port_t); joypad_inputs_t joypad_get_inputs(joypad_port_t);
bool joypad_get_rumble_supported(joypad_port_t); void joypad_set_rumble_active(joypad_port_t, bool);
void* asset_load(const char*, void*);
'''
        }
        self.compile_and_run(
            [ENGINE_SRC / "input" / "input.cpp"],
            r'''
#include <cassert>
#include <cmath>
#include <libdragon.h>
#include "input/input.h"

namespace {
  bool plugged[4]{}; P64::Input::RawState raw[4]{}; bool motor[4]{}; int stops{};
  void poll() {}
  bool backendConnected(std::uint8_t p) { return plugged[p]; }
  P64::Input::RawState read(std::uint8_t p) { return raw[p]; }
  bool supported(std::uint8_t) { return true; }
  void setMotor(std::uint8_t p, bool on) { motor[p] = on; if(!on)++stops; }
}
void joypad_poll() {}
bool joypad_is_connected(joypad_port_t) { return false; }
joypad_inputs_t joypad_get_inputs(joypad_port_t) { return {}; }
bool joypad_get_rumble_supported(joypad_port_t) { return false; }
void joypad_set_rumble_active(joypad_port_t, bool) {}
void* asset_load(const char*, void*) { return nullptr; }

int main() {
  using namespace P64::Input;
  Config config{};
  config.actionCount = 1;
  config.actions[0].id = "dash"_action;
  config.actions[0].bindings[0] = {mask(Button::A), mask(Button::Z)};
  config.axisCount = 1;
  config.hostPort = 3;
  config.axes[0].id = "move_x"_axis;
  config.axes[0].bindings[0] = {AxisSource::STICK_X, 127, 0, 0};
  config.rumbleEnabledMask = 0x07;
  Backend backend{poll, backendConnected, read, supported, setMotor};
  setBackend(&backend);
  initialize(&config);
  plugged[0] = plugged[3] = true;
  raw[0].buttons = mask(Button::A) | mask(Button::Z);
  raw[3].buttons = mask(Button::B);
  raw[0].stickX = 5;
  update(0.016f);
  assert(get(0).connectedThisFrame && get(3).connectedThisFrame && !get(1).connected);
  assert(pressed(0, "dash"_action));
  assert(pressed(0, "dash"_action, true));
  assert(!held(0, "dash"_action));
  assert(axis(0, "move_x"_axis) == 0.0f);
  assert(route(Owner::Port1).pressed == (mask(Button::A) | mask(Button::Z)));
  assert(route(Owner::Port4).pressed == mask(Button::B));
  assert(route(Owner::Host).sourcePort == 3 && route(Owner::Host).pressed == mask(Button::B));
  assert(route(Owner::Any).pressed == (mask(Button::A) | mask(Button::B) | mask(Button::Z)));
  assert(route(Owner::Disabled).pressed == 0 && route(Owner::Disabled).sourcePort == 0xFF);
  raw[0].stickX = 25;
  update(0.016f);
  assert(axis(0, "move_x"_axis) > 0.1f);
  raw[0].stickX = 85;
  update(0.016f);
  assert(held(0, "dash"_action));
  assert(std::fabs(axis(0, "move_x"_axis) - 1.0f) < 0.001f);
  assert(rumble(0, 0.05f) && motor[0]);
  assert(rumbleSupported(0));
  assert(!rumbleSupported(3) && !rumble(3, 0.05f));
  plugged[0] = false;
  update(0.016f);
  assert(get(0).disconnectedThisFrame && get(0).buttonsReleased == (mask(Button::A) | mask(Button::Z)));
  assert(get(0).actionsReleased == 1 && !motor[0] && stops > 0);
  stopAllRumble();
}
''',
            stubs,
        )

    def test_group_camera_tracks_bounds_clamps_and_never_rotates(self) -> None:
        stubs = {
            "scene/camera.h": r'''
#pragma once
namespace P64 {
struct CameraPoint { float x{}, y{}, z{}; };
class Camera {
public:
  CameraPoint position{}, target{};
  void setLookAt(const CameraPoint &p, const CameraPoint &t, const CameraPoint& = {0,1,0}) {
    position = p; target = t;
  }
};
}
'''
        }
        self.compile_and_run(
            [ENGINE_SRC / "multiplayer" / "groupCamera.cpp"],
            r'''
#include <array>
#include <cassert>
#include <cmath>
#include "multiplayer/groupCamera.h"
#include "scene/camera.h"
int main() {
  using Camera = P64::Multiplayer::GroupCamera;
  Camera::Config config{};
  config.yawRadians = 0.7f; config.pitchRadians = 0.6f;
  config.minimumDistance = 100; config.maximumDistance = 500;
  config.baseDistance = 100; config.distancePerUnit = 1; config.boundsPadding = 0;
  config.centroidSmoothing = 0; config.zoomSmoothing = 0;
  config.lawnMinimum = {-50,-10,-40}; config.lawnMaximum = {50,10,40};
  Camera camera(config);
  std::array<Camera::Target, 4> targets{};
  targets[0] = {{-200,0,-100}, true};
  targets[2] = {{200,0,100}, true};
  auto first = camera.update(targets, 1.0f);
  assert(first.targetCount == 2 && first.lookAt.x == 0 && first.lookAt.z == 0);
  assert(first.distance == 500 && first.yawRadians == 0.7f && first.pitchRadians == 0.6f);
  targets = {};
  targets[3] = {{200,30,100}, true};
  auto clamped = camera.update(targets, 1.0f);
  assert(clamped.targetCount == 1);
  assert(clamped.lookAt.x == 50 && clamped.lookAt.y == 10 && clamped.lookAt.z == 40);
  assert(clamped.distance == 100);
  const auto retained = camera.update({}, 1.0f);
  assert(retained.lookAt.x == 50 && retained.yawRadians == first.yawRadians);
  P64::Camera runtimeCamera;
  camera.apply(runtimeCamera);
  assert(std::fabs(runtimeCamera.target.x - 50) < 0.001f);
}
''',
            stubs,
        )

    def test_multilistener_audio_uses_strongest_channels(self) -> None:
        self.compile_and_run(
            [ENGINE_SRC / "audio" / "spatialAudio.cpp"],
            r'''
#include <cassert>
#include "audio/spatialAudio.h"
int main() {
  using namespace P64::Audio::Spatial;
  Listener listeners[2]{};
  listeners[0].position = {-10,0,0};
  listeners[1].position = {10,0,0};
  Settings settings{0, 100, 1};
  auto leftOnly = calculate({-10,0,-10}, listeners[0], settings);
  auto rightOnly = calculate({-10,0,-10}, listeners[1], settings);
  auto combined = calculateStrongest({-10,0,-10}, listeners, 2, settings);
  assert(combined.left >= leftOnly.left && combined.left >= rightOnly.left);
  assert(combined.right >= leftOnly.right && combined.right >= rightOnly.right);
  assert(combined.left <= 1.0f && combined.right <= 1.0f);
}
''',
        )


if __name__ == "__main__":
    unittest.main()
