/**
* @copyright 2024 - Max Bebök
* @license MIT
*/
#pragma once
#include <fgeom.h>
#include <libdragon.h>
#include "assets/assetManager.h"
#include "audio/spatialAudio.h"

namespace P64 { class Camera; }

namespace P64::Audio
{
  /**
   * Audio handle, returned by the audio manager when playing audio.
   * This can be used to change settings after it started playing.
   *
   * Internally, this will only store 4 bytes as a reference,
   * so this object is fast and safe to copy and move.
   *
   * If the audio is already stopped, the handle will be invalidated.
   * You are still able to safely call methods on it, but they will be ignored.
   *
   * A default constructed handle will be invalid by default.
   */
  class Handle
  {
    private:
      uint16_t slot{0};
      uint16_t uuid{0};

    public:
      Handle() = default;
      explicit Handle(uint16_t _slot, uint16_t _uuid) : slot{_slot}, uuid{_uuid} {}

      /**
       * Stops the audio, if already stopped nothing will happen.
       * Note that stopping will make the handle invalid.
       */
      void stop();
      void setVolume(float volume);
      /** Playback-frequency ratio, clamped to 0.125x..8x for WAV64. */
      void setPitch(float ratio);
      /** Backward-compatible alias for setPitch. */
      void setSpeed(float speed);
      /** Move a positional sound without restarting playback. */
      void setPosition(const fm_vec3_t &position);
      void setSpatialSettings(const Spatial::Settings &settings);
      /** Switch between listener-relative 3D mixing and normal centered 2D. */
      void setSpatial(bool enabled);
      bool isDone();
  };
}

/**
 * Global audio manager.
 * This will manage creation and playback of all audio in the engine.
 */
namespace P64::AudioManager
{
  extern uint64_t ticksUpdate;

  void setMasterVolume(float volume);

  Audio::Handle play2D(wav64_t *audio);
  Audio::Handle play2D(xm64player_t *audio);
  Audio::Handle play3D(
    wav64_t *audio,
    const fm_vec3_t &position,
    const Audio::Spatial::Settings &settings = {}
  );

  /** Set the listener explicitly, normally once per frame. */
  void setListener(const fm_vec3_t &position, const fm_vec3_t &forward, const fm_vec3_t &up = {0, 1, 0});
  /** Convenience overload using a BF64 camera transform. */
  void setListener(const Camera &camera);
  void clearListeners();
  bool addListener(const fm_vec3_t &position, const fm_vec3_t &forward, const fm_vec3_t &up = {0, 1, 0});
  bool addListener(const Camera &camera);
  [[nodiscard]] uint8_t getListenerCount();

  /** Dispatch WAV64/XM64 playback from the generated asset type tag. */
  Audio::Handle play2D(uint32_t assetId);

  /** Play a typed WAV64 asset positionally; XM64 is intentionally unsupported. */
  Audio::Handle play3D(
    uint32_t assetId,
    const fm_vec3_t &position,
    const Audio::Spatial::Settings &settings = {}
  );

  void stopAll();
}
