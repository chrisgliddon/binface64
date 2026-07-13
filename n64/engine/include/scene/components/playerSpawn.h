/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once
#include <cstdint>
#include "multiplayer/spawns.h"

namespace P64 { class Object; }

namespace P64::Comp
{
  struct PlayerSpawn
  {
    static constexpr std::uint32_t ID = 15;
    struct InitData
    {
      Multiplayer::Spawns::Target target{Multiplayer::Spawns::Target::Neutral};
      std::uint8_t index{};
      std::uint8_t padding[2]{};
    };
    static std::uint32_t getAllocSize([[maybe_unused]] InitData*) { return sizeof(PlayerSpawn); }
    static void initDelete(Object &object, PlayerSpawn *data, InitData *initData);
  };
}
