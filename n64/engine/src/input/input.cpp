/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "input/input.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <cstdlib>
#include <libdragon.h>

namespace
{
  using namespace P64::Input;

  void platformPoll() { joypad_poll(); }
  bool platformConnected(std::uint8_t port)
  {
    return port < PLAYER_COUNT && joypad_is_connected(static_cast<joypad_port_t>(port));
  }
  RawState platformRead(std::uint8_t port)
  {
    const auto raw = joypad_get_inputs(static_cast<joypad_port_t>(port));
    return {raw.stick_x, raw.stick_y, raw.btn.raw};
  }
  bool platformRumbleSupported(std::uint8_t port)
  {
    return port < PLAYER_COUNT && joypad_get_rumble_supported(static_cast<joypad_port_t>(port));
  }
  void platformSetRumble(std::uint8_t port, bool active)
  {
    if(port < PLAYER_COUNT)joypad_set_rumble_active(static_cast<joypad_port_t>(port), active);
  }

  constexpr Backend PLATFORM_BACKEND{
    platformPoll, platformConnected, platformRead, platformRumbleSupported, platformSetRumble
  };

  const Backend *activeBackend = &PLATFORM_BACKEND;
  Config inputConfig{};
  std::array<Snapshot, PLAYER_COUNT> snapshots{};
  std::array<std::uint32_t, PLAYER_COUNT> consumed{};
  std::array<float, PLAYER_COUNT> rumbleRemaining{};
  std::array<bool, PLAYER_COUNT> rumbleActive{};

  std::int32_t actionIndex(ActionId action)
  {
    for(std::uint8_t index=0; index<inputConfig.actionCount; ++index) {
      if(inputConfig.actions[index].id == action)return index;
    }
    return -1;
  }

  std::int32_t axisIndex(AxisId axis)
  {
    for(std::uint8_t index=0; index<inputConfig.axisCount; ++index) {
      if(inputConfig.axes[index].id == axis)return index;
    }
    return -1;
  }

  Stick normalizeStick(const RawState &raw, float deadZone)
  {
    float x = std::clamp(static_cast<float>(raw.stickX) / 85.0f, -1.0f, 1.0f);
    float y = std::clamp(static_cast<float>(raw.stickY) / 85.0f, -1.0f, 1.0f);
    const float magnitude = std::sqrt(x*x + y*y);
    if(magnitude <= deadZone || magnitude <= 0.00001f)return {};
    const float scaled = std::min(1.0f, (magnitude - deadZone) / std::max(0.00001f, 1.0f - deadZone));
    return {x / magnitude * scaled, y / magnitude * scaled};
  }

  float sourceValue(AxisSource source, const Snapshot &snapshot)
  {
    switch(source) {
      case AxisSource::STICK_X: return snapshot.stick.x;
      case AxisSource::STICK_Y: return snapshot.stick.y;
      case AxisSource::DPAD_X:
        return ((snapshot.buttonsHeld & mask(Button::D_RIGHT)) ? 1.0f : 0.0f) -
               ((snapshot.buttonsHeld & mask(Button::D_LEFT)) ? 1.0f : 0.0f);
      case AxisSource::DPAD_Y:
        return ((snapshot.buttonsHeld & mask(Button::D_UP)) ? 1.0f : 0.0f) -
               ((snapshot.buttonsHeld & mask(Button::D_DOWN)) ? 1.0f : 0.0f);
      case AxisSource::C_X:
        return ((snapshot.buttonsHeld & mask(Button::C_RIGHT)) ? 1.0f : 0.0f) -
               ((snapshot.buttonsHeld & mask(Button::C_LEFT)) ? 1.0f : 0.0f);
      case AxisSource::C_Y:
        return ((snapshot.buttonsHeld & mask(Button::C_UP)) ? 1.0f : 0.0f) -
               ((snapshot.buttonsHeld & mask(Button::C_DOWN)) ? 1.0f : 0.0f);
      case AxisSource::NONE: default: return 0.0f;
    }
  }

  bool bindingHeld(const DigitalBinding &binding, std::uint16_t heldButtons)
  {
    if(binding.buttons == 0)return false;
    return (heldButtons & binding.buttons) == binding.buttons &&
           (heldButtons & binding.chord) == binding.chord;
  }
}

void P64::Input::setBackend(const Backend *backend)
{
  stopAllRumble();
  activeBackend = backend ? backend : &PLATFORM_BACKEND;
  snapshots = {};
  consumed = {};
}

void P64::Input::initialize(const Config *config)
{
  stopAllRumble();
  inputConfig = config ? *config : Config{};
  if(inputConfig.magic != CONFIG_MAGIC || inputConfig.version != CONFIG_VERSION)inputConfig = Config{};
  inputConfig.actionCount = std::min(inputConfig.actionCount, MAX_ACTIONS);
  inputConfig.axisCount = std::min(inputConfig.axisCount, MAX_AXES);
  snapshots = {};
  consumed = {};
  rumbleRemaining = {};
  rumbleActive = {};
}

bool P64::Input::loadConfig(const char *path)
{
  int fileSize{};
  void *file = asset_load(path, &fileSize);
  if(file == nullptr)return false;
  if(fileSize < static_cast<int>(sizeof(Config))) {
    free(file);
    return false;
  }
  Config loaded{};
  std::memcpy(&loaded, file, sizeof(Config));
  free(file);
  if(loaded.magic != CONFIG_MAGIC || loaded.version != CONFIG_VERSION)return false;
  initialize(&loaded);
  return true;
}

void P64::Input::shutdown()
{
  stopAllRumble();
  snapshots = {};
  consumed = {};
}

void P64::Input::update(float unscaledDeltaTime)
{
  clearConsumption();
  if(activeBackend->poll)activeBackend->poll();
  const float globalDeadZone = static_cast<float>(inputConfig.deadZone) / 255.0f;

  for(std::uint8_t player=0; player<PLAYER_COUNT; ++player)
  {
    const Snapshot previous = snapshots[player];
    auto &snapshot = snapshots[player];
    snapshot = {};
    const bool enabled = (inputConfig.enabledPortMask & (1u << player)) != 0;
    snapshot.connected = enabled && activeBackend->connected && activeBackend->connected(player);
    snapshot.connectedThisFrame = snapshot.connected && !previous.connected;
    snapshot.disconnectedThisFrame = !snapshot.connected && previous.connected;

    if(snapshot.disconnectedThisFrame || !snapshot.connected) {
      snapshot.buttonsReleased = previous.buttonsHeld;
      snapshot.actionsReleased = previous.actionsHeld;
      if(rumbleActive[player])stopRumble(player);
      continue;
    }

    snapshot.raw = activeBackend->read ? activeBackend->read(player) : RawState{};
    snapshot.buttonsHeld = snapshot.raw.buttons;
    snapshot.buttonsPressed = snapshot.buttonsHeld & ~previous.buttonsHeld;
    snapshot.buttonsReleased = previous.buttonsHeld & ~snapshot.buttonsHeld;
    snapshot.stick = normalizeStick(snapshot.raw, globalDeadZone);

    for(std::uint8_t action=0; action<inputConfig.actionCount; ++action) {
      bool isHeld = false;
      for(const auto &binding : inputConfig.actions[action].bindings) {
        if(bindingHeld(binding, snapshot.buttonsHeld)) { isHeld = true; break; }
      }
      if(isHeld)snapshot.actionsHeld |= 1u << action;
    }
    snapshot.actionsPressed = snapshot.actionsHeld & ~previous.actionsHeld;
    snapshot.actionsReleased = previous.actionsHeld & ~snapshot.actionsHeld;

    for(std::uint8_t axisSlot=0; axisSlot<inputConfig.axisCount; ++axisSlot) {
      float best = 0.0f;
      for(const auto &binding : inputConfig.axes[axisSlot].bindings) {
        if(binding.source == AxisSource::NONE)continue;
        const float deadZone = binding.deadZone ? static_cast<float>(binding.deadZone) / 255.0f : globalDeadZone;
        float value{};
        if(binding.source == AxisSource::STICK_X || binding.source == AxisSource::STICK_Y) {
          const auto bindingStick = normalizeStick(snapshot.raw, deadZone);
          value = binding.source == AxisSource::STICK_X ? bindingStick.x : bindingStick.y;
        } else {
          value = sourceValue(binding.source, snapshot);
        }
        value *= static_cast<float>(binding.scale) / 127.0f;
        if(std::fabs(value) > std::fabs(best))best = value;
      }
      snapshot.axes[axisSlot] = std::clamp(best, -1.0f, 1.0f);
    }

    if(rumbleActive[player]) {
      rumbleRemaining[player] -= std::max(0.0f, unscaledDeltaTime);
      if(rumbleRemaining[player] <= 0.0f)stopRumble(player);
    }
  }
}

const P64::Input::Config& P64::Input::getConfig() { return inputConfig; }

const P64::Input::Snapshot& P64::Input::get(std::uint8_t player)
{
  static const Snapshot empty{};
  return player < PLAYER_COUNT ? snapshots[player] : empty;
}

bool P64::Input::connected(std::uint8_t player) { return get(player).connected; }
bool P64::Input::buttonPressed(std::uint8_t player, Button button) { return (get(player).buttonsPressed & mask(button)) != 0; }
bool P64::Input::buttonHeld(std::uint8_t player, Button button) { return (get(player).buttonsHeld & mask(button)) != 0; }
bool P64::Input::buttonReleased(std::uint8_t player, Button button) { return (get(player).buttonsReleased & mask(button)) != 0; }
P64::Input::Buttons P64::Input::rawButtonsPressed(std::uint8_t player) { Buttons value{}; value.raw = get(player).buttonsPressed; return value; }
P64::Input::Buttons P64::Input::rawButtonsHeld(std::uint8_t player) { Buttons value{}; value.raw = get(player).buttonsHeld; return value; }
P64::Input::Buttons P64::Input::rawButtonsReleased(std::uint8_t player) { Buttons value{}; value.raw = get(player).buttonsReleased; return value; }

bool P64::Input::pressed(std::uint8_t player, ActionId action, bool shouldConsume)
{
  const auto index = actionIndex(action);
  if(player >= PLAYER_COUNT || index < 0 || (consumed[player] & (1u << index)))return false;
  const bool result = (snapshots[player].actionsPressed & (1u << index)) != 0;
  if(result && shouldConsume)consumed[player] |= 1u << index;
  return result;
}

bool P64::Input::held(std::uint8_t player, ActionId action, bool shouldConsume)
{
  const auto index = actionIndex(action);
  if(player >= PLAYER_COUNT || index < 0 || (consumed[player] & (1u << index)))return false;
  const bool result = (snapshots[player].actionsHeld & (1u << index)) != 0;
  if(result && shouldConsume)consumed[player] |= 1u << index;
  return result;
}

bool P64::Input::released(std::uint8_t player, ActionId action, bool shouldConsume)
{
  const auto index = actionIndex(action);
  if(player >= PLAYER_COUNT || index < 0 || (consumed[player] & (1u << index)))return false;
  const bool result = (snapshots[player].actionsReleased & (1u << index)) != 0;
  if(result && shouldConsume)consumed[player] |= 1u << index;
  return result;
}

float P64::Input::axis(std::uint8_t player, AxisId requestedAxis)
{
  const auto index = axisIndex(requestedAxis);
  return player < PLAYER_COUNT && index >= 0 ? snapshots[player].axes[index] : 0.0f;
}

P64::Input::RoutedButtons P64::Input::route(Owner owner)
{
  RoutedButtons result{};
  if(owner == Owner::Disabled)return result;

  std::uint8_t first = 0;
  std::uint8_t last = 0;
  if(owner == Owner::Any) {
    first = 0;
    last = PLAYER_COUNT - 1;
  } else {
    const auto requested = owner == Owner::Host
      ? inputConfig.hostPort
      : static_cast<std::uint8_t>(owner);
    if(requested >= PLAYER_COUNT)return result;
    first = last = requested;
  }

  for(std::uint8_t port=first; port<=last; ++port) {
    const auto &snapshot = snapshots[port];
    if(!snapshot.connected)continue;
    result.pressed |= snapshot.buttonsPressed;
    result.held |= snapshot.buttonsHeld;
    result.released |= snapshot.buttonsReleased;
    if(result.sourcePort == 0xFF &&
       (snapshot.buttonsPressed || snapshot.buttonsHeld || snapshot.buttonsReleased)) {
      result.sourcePort = port;
    }
  }
  return result;
}

void P64::Input::consume(std::uint8_t player, ActionId action)
{
  const auto index = actionIndex(action);
  if(player < PLAYER_COUNT && index >= 0)consumed[player] |= 1u << index;
}

void P64::Input::clearConsumption() { consumed = {}; }

bool P64::Input::rumbleSupported(std::uint8_t player)
{
  return player < PLAYER_COUNT && (inputConfig.rumbleEnabledMask & (1u << player)) &&
         snapshots[player].connected && activeBackend->rumbleSupported &&
         activeBackend->rumbleSupported(player);
}

bool P64::Input::rumble(std::uint8_t player, float seconds)
{
  if(seconds <= 0.0f || !rumbleSupported(player) || !activeBackend->setRumble)return false;
  activeBackend->setRumble(player, true);
  rumbleActive[player] = true;
  rumbleRemaining[player] = seconds;
  return true;
}

void P64::Input::stopRumble(std::uint8_t player)
{
  if(player >= PLAYER_COUNT)return;
  if(rumbleActive[player] && activeBackend->setRumble)activeBackend->setRumble(player, false);
  rumbleActive[player] = false;
  rumbleRemaining[player] = 0.0f;
}

void P64::Input::stopAllRumble()
{
  for(std::uint8_t player=0; player<PLAYER_COUNT; ++player)stopRumble(player);
}
