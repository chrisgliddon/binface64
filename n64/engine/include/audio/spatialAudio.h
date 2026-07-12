/**
 * Small dependency-free positional-audio math surface.
 */
#pragma once

namespace P64::Audio::Spatial
{
  struct Vec3
  {
    float x{};
    float y{};
    float z{};
  };

  struct Listener
  {
    Vec3 position{};
    Vec3 forward{0.0f, 0.0f, -1.0f};
    Vec3 up{0.0f, 1.0f, 0.0f};
  };

  struct Settings
  {
    float minDistance{50.0f};
    float maxDistance{1000.0f};
    /** Exponent applied to linear falloff. 1 is linear, 2 falls faster. */
    float rolloff{1.0f};
  };

  struct Mix
  {
    float left{};
    float right{};
    float attenuation{};
    float pan{0.5f};
    float distance{};
  };

  [[nodiscard]] Mix calculate(const Vec3 &source, const Listener &listener, const Settings &settings);
}
