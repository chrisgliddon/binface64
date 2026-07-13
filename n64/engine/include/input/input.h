/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string_view>

namespace P64::Input
{
  constexpr std::uint8_t PLAYER_COUNT = 4;
  constexpr std::uint8_t MAX_ACTIONS = 32;
  constexpr std::uint8_t MAX_AXES = 8;
  constexpr std::uint8_t MAX_BINDINGS = 4;
  constexpr std::uint32_t CONFIG_MAGIC = 0x50363449; // P64I
  constexpr std::uint16_t CONFIG_VERSION = 2;

  using ActionId = std::uint32_t;
  using AxisId = std::uint32_t;

  /** Stable FNV-1a identifier used by generated inputActions.h constants. */
  constexpr std::uint32_t id(std::string_view value)
  {
    std::uint32_t hash = 2166136261u;
    for(char character : value) {
      hash ^= static_cast<std::uint8_t>(character);
      hash *= 16777619u;
    }
    return hash;
  }

  enum class Button : std::uint16_t
  {
    A      = 1u << 0,
    B      = 1u << 1,
    Z      = 1u << 2,
    START  = 1u << 3,
    D_UP   = 1u << 4,
    D_DOWN = 1u << 5,
    D_LEFT = 1u << 6,
    D_RIGHT= 1u << 7,
    Y      = 1u << 8,
    X      = 1u << 9,
    L      = 1u << 10,
    R      = 1u << 11,
    C_UP   = 1u << 12,
    C_DOWN = 1u << 13,
    C_LEFT = 1u << 14,
    C_RIGHT= 1u << 15,
  };

  constexpr std::uint16_t mask(Button button) { return static_cast<std::uint16_t>(button); }
  constexpr std::uint16_t operator|(Button lhs, Button rhs) { return mask(lhs) | mask(rhs); }

  enum class AxisSource : std::uint8_t
  {
    NONE,
    STICK_X,
    STICK_Y,
    DPAD_X,
    DPAD_Y,
    C_X,
    C_Y,
  };

  union Buttons
  {
    std::uint16_t raw{};
    struct
    {
      std::uint16_t a:1, b:1, z:1, start:1;
      std::uint16_t d_up:1, d_down:1, d_left:1, d_right:1;
      std::uint16_t y:1, x:1, l:1, r:1;
      std::uint16_t c_up:1, c_down:1, c_left:1, c_right:1;
    };
  };

  struct RawState
  {
    union { std::int8_t stickX{}; std::int8_t stick_x; };
    union { std::int8_t stickY{}; std::int8_t stick_y; };
    union { std::uint16_t buttons{}; Buttons btn; };
  };

  struct DigitalBinding
  {
    std::uint16_t buttons{};
    std::uint16_t chord{};
  };

  struct ActionDefinition
  {
    ActionId id{};
    std::array<DigitalBinding, MAX_BINDINGS> bindings{};
  };

  struct AxisBinding
  {
    AxisSource source{AxisSource::NONE};
    std::int8_t scale{127};
    /** Per-binding dead zone in 0..255, or zero to use the global dead zone. */
    std::uint8_t deadZone{};
    std::uint8_t padding{};
  };

  struct AxisDefinition
  {
    AxisId id{};
    std::array<AxisBinding, MAX_BINDINGS> bindings{};
  };

  /** Binary-compatible contents of rom:/p64/input. */
  struct Config
  {
    std::uint32_t magic{CONFIG_MAGIC};
    std::uint16_t version{CONFIG_VERSION};
    std::uint8_t actionCount{};
    std::uint8_t axisCount{};
    std::uint8_t deadZone{46};
    /** Bit 0..3 enable physical controller ports 1..4. */
    std::uint8_t enabledPortMask{0x0F};
    /** Zero-based port used by host-owned shared UI. */
    std::uint8_t hostPort{};
    /** Bit 0..3 permit Rumble Pak use for physical ports 1..4. */
    std::uint8_t rumbleEnabledMask{0x0F};
    std::array<ActionDefinition, MAX_ACTIONS> actions{};
    std::array<AxisDefinition, MAX_AXES> axes{};
  };

  struct Stick
  {
    float x{};
    float y{};
  };

  /** Immutable for the duration of a frame. Player indices are fixed ports 0..3. */
  struct Snapshot
  {
    RawState raw{};
    Stick stick{};
    std::uint16_t buttonsPressed{};
    std::uint16_t buttonsHeld{};
    std::uint16_t buttonsReleased{};
    std::uint32_t actionsPressed{};
    std::uint32_t actionsHeld{};
    std::uint32_t actionsReleased{};
    std::array<float, MAX_AXES> axes{};
    bool connected{};
    bool connectedThisFrame{};
    bool disconnectedThisFrame{};
  };

  enum class Owner : std::uint8_t
  {
    Port1,
    Port2,
    Port3,
    Port4,
    Host,
    Any,
    Disabled,
  };

  struct RoutedButtons
  {
    std::uint16_t pressed{};
    std::uint16_t held{};
    std::uint16_t released{};
    /** First contributing zero-based port, or 0xFF when no port contributed. */
    std::uint8_t sourcePort{0xFF};
  };

  /** Injectable platform backend. Passing nullptr to setBackend restores libdragon. */
  struct Backend
  {
    void (*poll)(){};
    bool (*connected)(std::uint8_t port){};
    RawState (*read)(std::uint8_t port){};
    bool (*rumbleSupported)(std::uint8_t port){};
    void (*setRumble)(std::uint8_t port, bool active){};
  };

  void setBackend(const Backend *backend);
  void initialize(const Config *config = nullptr);
  bool loadConfig(const char *path = "rom:/p64/input");
  void shutdown();
  void update(float unscaledDeltaTime);

  [[nodiscard]] const Config& getConfig();
  [[nodiscard]] const Snapshot& get(std::uint8_t player);
  [[nodiscard]] bool connected(std::uint8_t player);
  [[nodiscard]] bool buttonPressed(std::uint8_t player, Button button);
  [[nodiscard]] bool buttonHeld(std::uint8_t player, Button button);
  [[nodiscard]] bool buttonReleased(std::uint8_t player, Button button);
  [[nodiscard]] Buttons rawButtonsPressed(std::uint8_t player);
  [[nodiscard]] Buttons rawButtonsHeld(std::uint8_t player);
  [[nodiscard]] Buttons rawButtonsReleased(std::uint8_t player);
  [[nodiscard]] bool pressed(std::uint8_t player, ActionId action, bool consume = false);
  [[nodiscard]] bool held(std::uint8_t player, ActionId action, bool consume = false);
  [[nodiscard]] bool released(std::uint8_t player, ActionId action, bool consume = false);
  [[nodiscard]] float axis(std::uint8_t player, AxisId axis);
  /** Deterministically route raw button snapshots for UI/shared-menu ownership. */
  [[nodiscard]] RoutedButtons route(Owner owner);
  void consume(std::uint8_t player, ActionId action);
  void clearConsumption();

  [[nodiscard]] bool rumbleSupported(std::uint8_t player);
  bool rumble(std::uint8_t player, float seconds);
  void stopRumble(std::uint8_t player);
  void stopAllRumble();
}

constexpr P64::Input::ActionId operator""_action(const char *value, std::size_t length)
{
  return P64::Input::id(std::string_view{value, length});
}

constexpr P64::Input::AxisId operator""_axis(const char *value, std::size_t length)
{
  return P64::Input::id(std::string_view{value, length});
}
