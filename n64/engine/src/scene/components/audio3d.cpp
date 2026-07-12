/**
 * @copyright 2026 - BF64 contributors
 * @license MIT
 */
#include "scene/components/audio3d.h"

#include <cassert>
#include <new>

namespace P64::Comp
{
  void Audio3D::initDelete(Object &obj, Audio3D *data, InitData *initData)
  {
    if(initData == nullptr) {
      data->handle.stop();
      data->~Audio3D();
      return;
    }

    new(data) Audio3D();
    data->audio = static_cast<wav64_t*>(AssetManager::getByIndex(initData->assetIdx));
    assert(data->audio);
    data->volume = static_cast<float>(initData->volume) * (1.0f / 65535.0f);
    data->spatial = {
      .minDistance = initData->minDistance,
      .maxDistance = initData->maxDistance,
      .rolloff = initData->rolloff,
    };
    data->flags = initData->flags;
    wav64_set_loop(data->audio, (data->flags & FLAG_LOOP) != 0);
    if((data->flags & FLAG_AUTO_PLAY) != 0)data->play(obj.pos);
  }

  void Audio3D::update(Object &obj, Audio3D *data, float)
  {
    if(!data->handle.isDone())data->handle.setPosition(obj.pos);
  }

  void Audio3D::play(const fm_vec3_t &position)
  {
    handle.stop();
    handle = AudioManager::play3D(audio, position, spatial);
    handle.setVolume(volume);
  }
}
