/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once
#include <cstdint>

namespace P64 { class Object; }

namespace P64::Multiplayer::Spawns
{
  enum class Target : std::uint8_t { Neutral, Player, Team };
  constexpr std::uint8_t MAX_SPAWNS = 64;

  bool add(Object &object, Target target, std::uint8_t index);
  void remove(Object &object);
  void clear();
  [[nodiscard]] Object* select(std::uint8_t player);
  [[nodiscard]] std::uint8_t count(Target target, std::uint8_t index = 0);
}
