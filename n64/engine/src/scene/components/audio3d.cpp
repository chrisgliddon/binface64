/**
 * @copyright 2026 - BF64 contributors
 * @license MIT
 */
#include "scene/components/audio3d.h"

#include <new>

#include "assets/assetTypes.h"
#include "lib/logger.h"

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
    if(AssetManager::getTypeByIndex(initData->assetIdx) == Assets::Type::AUDIO) {
      data->audio = static_cast<wav64_t*>(AssetManager::getByIndex(initData->assetIdx));
    } else {
      Log::warn("Audio3D asset %u is not a WAV64 waveform", static_cast<unsigned>(initData->assetIdx));
    }
    data->volume = static_cast<float>(initData->volume) * (1.0f / 65535.0f);
    data->pitch = initData->pitchQ12 == 0
      ? 1.0f
      : static_cast<float>(initData->pitchQ12) * (1.0f / 4096.0f);
    data->spatial = {
      .minDistance = initData->minDistance,
      .maxDistance = initData->maxDistance,
      .rolloff = initData->rolloff,
    };
    data->flags = initData->flags;
    if(data->audio != nullptr) {
      wav64_set_loop(data->audio, (data->flags & FLAG_LOOP) != 0);
      if((data->flags & FLAG_AUTO_PLAY) != 0)data->play(obj.pos);
    }
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
    handle.setPitch(pitch);
  }
}
