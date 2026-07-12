/**
 * @copyright 2026 - BF64 contributors
 * @license MIT
 */
#pragma once

#include "assets/assetManager.h"
#include "audio/audioManager.h"
#include "scene/object.h"

namespace P64::Comp
{
  struct Audio3D
  {
    static constexpr uint32_t ID = 14;

    static constexpr uint8_t FLAG_LOOP = 1 << 0;
    static constexpr uint8_t FLAG_AUTO_PLAY = 1 << 1;

    struct InitData
    {
      uint16_t assetIdx;
      uint16_t volume;
      float minDistance;
      float maxDistance;
      float rolloff;
      uint16_t pitchQ12;
      uint8_t flags;
      uint8_t padding;
    };

    wav64_t *audio{};
    Audio::Spatial::Settings spatial{};
    float volume{1.0f};
    float pitch{1.0f};
    uint8_t flags{};
    Audio::Handle handle{};

    static uint32_t getAllocSize([[maybe_unused]] InitData *initData)
    {
      return sizeof(Audio3D);
    }

    static void initDelete(Object &obj, Audio3D *data, InitData *initData);
    static void update(Object &obj, Audio3D *data, [[maybe_unused]] float deltaTime);

    void play(const fm_vec3_t &position);
    void stop() { handle.stop(); }
    void setVolume(float value) { volume = value; handle.setVolume(value); }
    void setPitch(float value) { pitch = value; handle.setPitch(value); }
  };
}
