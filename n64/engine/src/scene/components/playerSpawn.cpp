/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "scene/components/playerSpawn.h"
#include "scene/object.h"

void P64::Comp::PlayerSpawn::initDelete(Object &object, PlayerSpawn*, InitData *initData)
{
  if(initData == nullptr) {
    Multiplayer::Spawns::remove(object);
    return;
  }
  Multiplayer::Spawns::add(object, initData->target, initData->index);
}
