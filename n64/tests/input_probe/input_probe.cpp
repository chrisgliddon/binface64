#include <array>
#include <cstdint>
#include <cstdio>
#include <libdragon.h>

#include "input/input.h"

namespace {
std::array<bool, P64::Input::PLAYER_COUNT> joined{};

void emitEvent(std::uint8_t port, const char* event, const P64::Input::Snapshot& snapshot) {
  debugf(
    "BF64_INPUT_PROBE_JSON:{\"port\":%u,\"event\":\"%s\",\"connected\":%s,"
    "\"joined\":%s,\"stick\":[%d,%d],\"pressed\":%u,\"held\":%u}\n",
    static_cast<unsigned>(port + 1), event,
    snapshot.connected ? "true" : "false", joined[port] ? "true" : "false",
    static_cast<int>(snapshot.raw.stickX), static_cast<int>(snapshot.raw.stickY),
    static_cast<unsigned>(snapshot.buttonsPressed), static_cast<unsigned>(snapshot.buttonsHeld)
  );
}

void draw() {
  console_clear();
  std::printf("BINFACE64 FOUR-PORT INPUT PROBE\n");
  std::printf("A toggles probe join. Disconnect/reconnect is stable.\n\n");
  for(std::uint8_t port = 0; port < P64::Input::PLAYER_COUNT; ++port) {
    const auto& state = P64::Input::get(port);
    std::printf(
      "P%u %-3s %-4s STICK %4d %4d  HELD %04X\n",
      static_cast<unsigned>(port + 1), state.connected ? "ON" : "OFF",
      joined[port] ? "JOIN" : "----", static_cast<int>(state.raw.stickX),
      static_cast<int>(state.raw.stickY), static_cast<unsigned>(state.buttonsHeld)
    );
  }
}
}

int main() {
  debug_init_isviewer();
  debug_init_usblog();
  console_init();
  console_set_render_mode(RENDER_AUTOMATIC);
  joypad_init();
  P64::Input::initialize();

  std::uint32_t frame{};
  for(;;) {
    P64::Input::update(1.0f / 60.0f);
    for(std::uint8_t port = 0; port < P64::Input::PLAYER_COUNT; ++port) {
      const auto& state = P64::Input::get(port);
      if(state.connectedThisFrame)emitEvent(port, frame == 0 ? "connect" : "reconnect", state);
      if(state.disconnectedThisFrame)emitEvent(port, "disconnect", state);
      if(state.connected && P64::Input::buttonPressed(port, P64::Input::Button::A)) {
        joined[port] = !joined[port];
        emitEvent(port, joined[port] ? "join" : "leave", state);
      } else if(state.connected && state.buttonsPressed != 0) {
        emitEvent(port, "button", state);
      }
    }
    if((frame++ % 6U) == 0U)draw();
  }
}
