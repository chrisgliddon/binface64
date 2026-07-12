/**
 * @copyright 2026 - BF64 contributors
 * @license MIT
 */
#include "audio/spatialAudio.h"

#include <algorithm>
#include <cmath>

namespace P64::Audio::Spatial
{
  namespace
  {
    Vec3 subtract(const Vec3 &a, const Vec3 &b)
    {
      return {a.x - b.x, a.y - b.y, a.z - b.z};
    }

    float dot(const Vec3 &a, const Vec3 &b)
    {
      return a.x * b.x + a.y * b.y + a.z * b.z;
    }

    Vec3 cross(const Vec3 &a, const Vec3 &b)
    {
      return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
      };
    }

    float length(const Vec3 &value)
    {
      return std::sqrt(dot(value, value));
    }

    Vec3 normalize(const Vec3 &value, const Vec3 &fallback)
    {
      const float magnitude = length(value);
      if(magnitude <= 0.00001f) return fallback;
      return {value.x / magnitude, value.y / magnitude, value.z / magnitude};
    }
  }

  Mix calculate(const Vec3 &source, const Listener &listener, const Settings &settings)
  {
    const Vec3 offset = subtract(source, listener.position);
    const float distance = length(offset);
    float attenuation = 0.0f;
    if(distance <= settings.minDistance) {
      attenuation = 1.0f;
    } else if(distance < settings.maxDistance && settings.maxDistance > settings.minDistance) {
      const float t = (distance - settings.minDistance) / (settings.maxDistance - settings.minDistance);
      attenuation = std::pow(std::max(0.0f, 1.0f - t), std::max(0.01f, settings.rolloff));
    }

    const Vec3 forward = normalize(listener.forward, {0.0f, 0.0f, -1.0f});
    const Vec3 up = normalize(listener.up, {0.0f, 1.0f, 0.0f});
    const Vec3 right = normalize(cross(forward, up), {1.0f, 0.0f, 0.0f});
    const Vec3 direction = normalize(offset, forward);
    const float pan = std::clamp(0.5f + dot(direction, right) * 0.5f, 0.0f, 1.0f);

    return {
      .left = attenuation * std::sqrt(1.0f - pan),
      .right = attenuation * std::sqrt(pan),
      .attenuation = attenuation,
      .pan = pan,
      .distance = distance,
    };
  }
}
