/**
* @copyright 2024 - Max Bebök
* @license MIT
*/
#include "audio/audioManager.h"
#include "assets/assetTypes.h"
#include "lib/logger.h"
#include "audioManagerPrivate.h"
#include "scene/camera.h"

#include <libdragon.h>
#include <array>

namespace
{
  constexpr uint32_t CHANNEL_COUNT = 32;
  constexpr uint8_t FLAG_XM = 1 << 0;
  constexpr uint8_t FLAG_SPATIAL = 1 << 1;
  constinit uint16_t nextUUID{1};
  P64::Audio::Spatial::Listener listener{};

  struct Slot
  {
    union
    {
      wav64_t* audioWAV{nullptr};
      xm64player_t* audioXM;
    };
    float volume{1.0f};
    float speed{1.0f};
    P64::Audio::Spatial::Vec3 position{};
    P64::Audio::Spatial::Settings spatialSettings{};
    uint16_t uuid{0};
    uint8_t flags{0};

    [[nodiscard]] bool hasAudio() const { return audioWAV != nullptr || audioXM != nullptr; }
    [[nodiscard]] bool isXM() const { return (flags & FLAG_XM) != 0; }
    [[nodiscard]] bool isSpatial() const { return (flags & FLAG_SPATIAL) != 0; }
    void clear() { *this = Slot{}; }
  };

  std::array<Slot, CHANNEL_COUNT> slots{};

  P64::Audio::Spatial::Vec3 toSpatial(const fm_vec3_t &value)
  {
    return {value.x, value.y, value.z};
  }

  Slot *getHandleSlot(uint16_t slot, uint16_t uuid)
  {
    if(uuid == 0 || slot >= slots.size())return nullptr;
    auto &entry = slots[slot];
    return entry.hasAudio() && entry.uuid == uuid ? &entry : nullptr;
  }

  uint32_t groupEnd(uint32_t start)
  {
    const uint16_t uuid = slots[start].uuid;
    uint32_t end = start;
    while(end < slots.size() && slots[end].hasAudio() && slots[end].uuid == uuid)++end;
    return end;
  }

  void updateVolume(uint32_t i) {
    auto& slot = slots[i];
    if(slot.isXM()) {
      xm64player_set_vol(slot.audioXM, slot.volume * P64::AudioManager::masterVol);
    } else {
      float left = slot.volume * P64::AudioManager::masterVol;
      float right = left;
      if(slot.isSpatial()) {
        const auto mix = P64::Audio::Spatial::calculate(slot.position, listener, slot.spatialSettings);
        left *= mix.left;
        right *= mix.right;
      }
      for(uint32_t channel = i; channel < groupEnd(i); ++channel) {
        mixer_ch_set_vol(static_cast<int>(channel), left, right);
      }
    }
  }

  int32_t getFreeSlots(int count = 1) {
    for(uint32_t i=0; i<slots.size(); ++i) {
      bool free = true;
      for(int j=0; j<count; ++j) {
        if(i+j >= slots.size() || slots[i+j].hasAudio()) {
          free = false;
          break;
        }
      }
      if(free)return (int32_t)i;
    }
    return -1;
  }

  uint16_t allocateUUID()
  {
    do { ++nextUUID; } while(nextUUID == 0);
    return nextUUID;
  }
}

namespace P64::AudioManager
{
  constinit float masterVol{1.0f};
  constinit uint64_t ticksUpdate{0};
  constinit int lastFreq{0};

  void setMasterVolume(float volume) {
    masterVol = volume;
    for(uint32_t i = 0; i < slots.size();) {
      if(!slots[i].hasAudio()) {
        ++i;
        continue;
      }
      updateVolume(i);
      i = groupEnd(i);
    }
  }

  void setListener(const fm_vec3_t &position, const fm_vec3_t &forward, const fm_vec3_t &up)
  {
    listener = {
      .position = toSpatial(position),
      .forward = toSpatial(forward),
      .up = toSpatial(up),
    };
  }

  void setListener(const Camera &camera)
  {
    setListener(camera.getPos(), camera.getViewDir(), camera.getUp());
  }

  void init(int freq)
  {
    if(freq != lastFreq)
    {
      if(lastFreq != 0)
      {
        Log::info("Audio freq. changed: %d -> %d", lastFreq, freq);
        stopAll();
        mixer_close();
        audio_close();
      }

      audio_init(freq, 3);
      mixer_init(CHANNEL_COUNT);
      slots = {};
      listener = {};
      lastFreq = freq;
    }
  }

  void update()
  {
    auto ticks = get_ticks();
    mixer_try_play();
    for(uint32_t i=0; i<CHANNEL_COUNT; ++i)
    {
      if(!slots[i].hasAudio())continue;

      bool isPlaying = slots[i].isXM()
        ? slots[i].audioXM->playing
        : mixer_ch_playing((int)i);

      if(isPlaying)
      {
        updateVolume(i);
        i = groupEnd(i) - 1;
      } else {
        // sound is stopped, free up slots again
        uint16_t uuid = slots[i].uuid;
        for(; i < CHANNEL_COUNT && slots[i].uuid == uuid; ++i) {
          slots[i].clear();
        }
        --i;
      }
    }
    ticksUpdate += get_ticks() - ticks;
  }

  void destroy() {
    stopAll();
    mixer_close();
    audio_close();
    lastFreq = 0;
  }

  Metrics getMetrics()
  {
    Metrics res{};
    for(uint32_t i=0; i<CHANNEL_COUNT; ++i)
    {
      if(slots[i].hasAudio())res.maskAlloc |= (1U << i);
      if(mixer_ch_playing(i)) {
        res.maskPlaying |= (1U << i);
      }
    }
    return res;
  }

  Audio::Handle play2D(wav64_t *audio) {
    if(audio == nullptr || audio->wave.channels == 0) {
      Log::warn("Cannot play an empty WAV asset");
      return {};
    }
    auto slot = getFreeSlots(audio->wave.channels);
    if(slot < 0) {
      Log::warn("No free audio channels left! needs: %d", audio->wave.channels);
      return {};
    }

    allocateUUID();
    for(int s=slot; s < slot + audio->wave.channels; ++s) {
      slots[s].audioWAV = audio;
      slots[s].uuid = nextUUID;
      slots[s].volume = 1.0f;
      slots[s].flags = 0;
    }

    wav64_play(audio, slot);
    //Log::info("Playing audio on channel %d, uuid: %d", slot, nextUUID);
    return Audio::Handle{(uint16_t)slot, nextUUID};
  }

  Audio::Handle play2D(xm64player_t* audio)
  {
    if(audio == nullptr) {
      Log::warn("Cannot play an empty XM asset");
      return {};
    }
    int channels = xm64player_num_channels(audio);
    auto slot = getFreeSlots(channels);
    if(slot < 0) {
      Log::warn("No free audio channels left! needs: %d", channels);
      return {};
    }

    allocateUUID();
    for(int s=slot; s < slot + channels; ++s) {
      slots[s].audioXM = audio;
      slots[s].uuid = nextUUID;
      slots[s].volume = 1.0f;
      slots[s].flags = FLAG_XM;
    }

    xm64player_play(audio, slot);
    return Audio::Handle{(uint16_t)slot, nextUUID};
  }

  Audio::Handle play2D(uint32_t assetId)
  {
    const uint8_t type = AssetManager::getTypeByIndex(assetId);
    if(type == Assets::Type::AUDIO) {
      return play2D(static_cast<wav64_t*>(AssetManager::getByIndex(assetId)));
    }
    if(type == Assets::Type::MUSIC_XM) {
      return play2D(static_cast<xm64player_t*>(AssetManager::getByIndex(assetId)));
    }
    Log::warn("Asset %lu is not WAV64 or XM64 audio", assetId);
    return {};
  }

  Audio::Handle play3D(
    wav64_t *audio,
    const fm_vec3_t &position,
    const Audio::Spatial::Settings &settings
  )
  {
    auto handle = play2D(audio);
    handle.setPosition(position);
    handle.setSpatialSettings(settings);
    handle.setSpatial(true);
    return handle;
  }

  Audio::Handle play3D(
    uint32_t assetId,
    const fm_vec3_t &position,
    const Audio::Spatial::Settings &settings
  )
  {
    if(AssetManager::getTypeByIndex(assetId) != Assets::Type::AUDIO) {
      Log::warn("Asset %lu is not positional WAV64 audio", assetId);
      return {};
    }
    return play3D(static_cast<wav64_t*>(AssetManager::getByIndex(assetId)), position, settings);
  }

  void stopAll() {
    for(uint32_t i = 0; i < slots.size();) {
      if(!slots[i].hasAudio()) {
        ++i;
        continue;
      }
      const uint32_t end = groupEnd(i);
      if(slots[i].isXM())xm64player_stop(slots[i].audioXM);
      i = end;
    }
    for(uint32_t i=0; i<CHANNEL_COUNT; i++)mixer_ch_stop(i);
    slots = {};
  }
}

void P64::Audio::Handle::stop() {
  auto entry = getHandleSlot(slot, uuid);
  if(entry == nullptr)return;

  if(entry->isXM()) {
    auto *player = entry->audioXM;
    auto chCount = xm64player_num_channels(entry->audioXM);
    xm64player_stop(player);
    for(int s=slot; s < slot + chCount; ++s) {
      slots[s].clear();
    }
    uuid = 0;
    return;
  }

  const uint32_t end = groupEnd(slot);
  for(uint32_t channel = slot; channel < end; ++channel) {
    mixer_ch_stop(static_cast<int>(channel));
    slots[channel].clear();
  }
  uuid = 0;
}

void P64::Audio::Handle::setVolume(float volume)
{
  auto entry = getHandleSlot(slot, uuid);
  if(entry == nullptr)return;
  for(uint32_t channel = slot; channel < groupEnd(slot); ++channel)slots[channel].volume = volume;
  updateVolume(slot);
}

void P64::Audio::Handle::setSpeed(float speed)
{
  setPitch(speed);
}

void P64::Audio::Handle::setPitch(float ratio)
{
  auto entry = getHandleSlot(slot, uuid);
  if(entry == nullptr)return;

  if(entry->isXM())
  {
    Log::warn("setPitch is not supported for XM audio! uuid: %d", uuid);
    return;
  }

  if(!(ratio >= 0.125f))ratio = 0.125f;
  if(ratio > 8.0f)ratio = 8.0f;
  for(uint32_t channel = slot; channel < groupEnd(slot); ++channel) {
    slots[channel].speed = ratio;
    const float freq = slots[channel].audioWAV->wave.frequency * ratio;
    mixer_ch_set_freq(static_cast<int>(channel), freq);
  }
}

void P64::Audio::Handle::setPosition(const fm_vec3_t &position)
{
  auto entry = getHandleSlot(slot, uuid);
  if(entry == nullptr)return;
  const auto converted = toSpatial(position);
  for(uint32_t channel = slot; channel < groupEnd(slot); ++channel)slots[channel].position = converted;
  updateVolume(slot);
}

void P64::Audio::Handle::setSpatialSettings(const Spatial::Settings &settings)
{
  auto entry = getHandleSlot(slot, uuid);
  if(entry == nullptr)return;
  for(uint32_t channel = slot; channel < groupEnd(slot); ++channel)slots[channel].spatialSettings = settings;
  updateVolume(slot);
}

void P64::Audio::Handle::setSpatial(bool enabled)
{
  auto entry = getHandleSlot(slot, uuid);
  if(entry == nullptr)return;
  if(enabled && entry->isXM()) {
    P64::Log::warn("Spatial mixing is not supported for XM audio! uuid: %d", uuid);
    return;
  }
  for(uint32_t channel = slot; channel < groupEnd(slot); ++channel) {
    if(enabled)slots[channel].flags |= FLAG_SPATIAL;
    else slots[channel].flags &= static_cast<uint8_t>(~FLAG_SPATIAL);
  }
  updateVolume(slot);
}

bool P64::Audio::Handle::isDone() {
  auto entry = getHandleSlot(slot, uuid);
  if(entry == nullptr)return true;

  if(entry->isXM())
  {
    return !entry->audioXM->playing;
  } else {
    if (entry->audioWAV == nullptr) return true;
    return !mixer_ch_playing(slot);
  }
}
