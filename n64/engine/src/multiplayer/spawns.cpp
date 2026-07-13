/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "multiplayer/spawns.h"

#include <array>
#include "multiplayer/session.h"
#include "scene/object.h"

namespace
{
  struct Entry
  {
    P64::Object *object{};
    P64::Multiplayer::Spawns::Target target{};
    std::uint8_t index{};
  };
  std::array<Entry, P64::Multiplayer::Spawns::MAX_SPAWNS> entries{};
  std::array<std::uint8_t, 4> cursors{};

  P64::Object* selectMatching(P64::Multiplayer::Spawns::Target target, std::uint8_t index, std::uint8_t &cursor)
  {
    std::uint8_t count{};
    for(const auto &entry : entries)if(entry.object && entry.target == target && entry.index == index)++count;
    if(count == 0)return nullptr;
    const std::uint8_t wanted = cursor++ % count;
    std::uint8_t current{};
    for(const auto &entry : entries)if(entry.object && entry.target == target && entry.index == index) {
      if(current++ == wanted)return entry.object;
    }
    return nullptr;
  }
}

bool P64::Multiplayer::Spawns::add(Object &object, Target target, std::uint8_t index)
{
  remove(object);
  for(auto &entry : entries)if(entry.object == nullptr) {
    entry = {&object, target, index};
    return true;
  }
  return false;
}

void P64::Multiplayer::Spawns::remove(Object &object)
{
  for(auto &entry : entries)if(entry.object == &object)entry = {};
}

void P64::Multiplayer::Spawns::clear()
{
  entries = {};
  cursors = {};
}

P64::Object* P64::Multiplayer::Spawns::select(std::uint8_t player)
{
  if(player >= 4)return nullptr;
  if(auto *spawn = selectMatching(Target::Player, player, cursors[player]))return spawn;
  const auto team = getSession().getPlayer(player).team;
  if(auto *spawn = selectMatching(Target::Team, team, cursors[player]))return spawn;
  return selectMatching(Target::Neutral, 0, cursors[player]);
}

std::uint8_t P64::Multiplayer::Spawns::count(Target target, std::uint8_t index)
{
  std::uint8_t result{};
  for(const auto &entry : entries)if(entry.object && entry.target == target && entry.index == index)++result;
  return result;
}
