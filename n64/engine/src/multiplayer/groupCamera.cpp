/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "multiplayer/groupCamera.h"

#include <algorithm>
#include <cmath>

#include "scene/camera.h"

namespace
{
  float smoothAlpha(float speed, float dt)
  {
    return speed <= 0.0f ? 1.0f : 1.0f - std::exp(-speed * std::max(0.0f, dt));
  }

  float mix(float from, float to, float alpha) { return from + (to - from) * alpha; }
}

P64::Multiplayer::GroupCamera::GroupCamera()
{
  configure(Config{});
}

P64::Multiplayer::GroupCamera::GroupCamera(const Config &config)
{
  configure(config);
}

void P64::Multiplayer::GroupCamera::configure(const Config &value)
{
  config_ = value;
  config_.minimumDistance = std::max(0.0f, config_.minimumDistance);
  config_.maximumDistance = std::max(config_.minimumDistance, config_.maximumDistance);
  config_.baseDistance = std::clamp(config_.baseDistance, config_.minimumDistance, config_.maximumDistance);
  config_.distancePerUnit = std::max(0.0f, config_.distancePerUnit);
  config_.boundsPadding = std::max(0.0f, config_.boundsPadding);
  reset();
}

void P64::Multiplayer::GroupCamera::reset()
{
  result_ = {};
  result_.yawRadians = config_.yawRadians;
  result_.pitchRadians = config_.pitchRadians;
  result_.distance = config_.baseDistance;
  initialized_ = false;
}

const P64::Multiplayer::GroupCamera::Result& P64::Multiplayer::GroupCamera::update(
  const std::array<Target, MAX_TARGETS> &targets,
  float deltaTime)
{
  Point minimum{};
  Point maximum{};
  Point centroid{};
  bool first = true;
  std::uint8_t count{};
  for(const auto &target : targets) {
    if(!target.active)continue;
    if(first)minimum = maximum = target.position;
    minimum.x = std::min(minimum.x, target.position.x);
    minimum.y = std::min(minimum.y, target.position.y);
    minimum.z = std::min(minimum.z, target.position.z);
    maximum.x = std::max(maximum.x, target.position.x);
    maximum.y = std::max(maximum.y, target.position.y);
    maximum.z = std::max(maximum.z, target.position.z);
    centroid.x += target.position.x;
    centroid.y += target.position.y;
    centroid.z += target.position.z;
    first = false;
    ++count;
  }
  if(count == 0)return result_;

  const float inverse = 1.0f / static_cast<float>(count);
  centroid.x = std::clamp(centroid.x * inverse, config_.lawnMinimum.x, config_.lawnMaximum.x);
  centroid.y = std::clamp(centroid.y * inverse, config_.lawnMinimum.y, config_.lawnMaximum.y);
  centroid.z = std::clamp(centroid.z * inverse, config_.lawnMinimum.z, config_.lawnMaximum.z);
  const float spanX = maximum.x - minimum.x;
  const float spanZ = maximum.z - minimum.z;
  const float requiredSpan = std::max(spanX, spanZ) + config_.boundsPadding;
  const float desiredDistance = std::clamp(
    config_.baseDistance + requiredSpan * config_.distancePerUnit,
    config_.minimumDistance,
    config_.maximumDistance
  );

  if(!initialized_) {
    result_.lookAt = centroid;
    result_.distance = desiredDistance;
    initialized_ = true;
  } else {
    const float centroidAlpha = smoothAlpha(config_.centroidSmoothing, deltaTime);
    const float zoomAlpha = smoothAlpha(config_.zoomSmoothing, deltaTime);
    result_.lookAt.x = mix(result_.lookAt.x, centroid.x, centroidAlpha);
    result_.lookAt.y = mix(result_.lookAt.y, centroid.y, centroidAlpha);
    result_.lookAt.z = mix(result_.lookAt.z, centroid.z, centroidAlpha);
    result_.distance = mix(result_.distance, desiredDistance, zoomAlpha);
  }

  const float horizontal = std::cos(config_.pitchRadians) * result_.distance;
  result_.position = {
    result_.lookAt.x + std::sin(config_.yawRadians) * horizontal,
    result_.lookAt.y + std::sin(config_.pitchRadians) * result_.distance,
    result_.lookAt.z + std::cos(config_.yawRadians) * horizontal,
  };
  result_.yawRadians = config_.yawRadians;
  result_.pitchRadians = config_.pitchRadians;
  result_.targetCount = count;
  return result_;
}

void P64::Multiplayer::GroupCamera::apply(Camera &camera) const
{
  camera.setLookAt(
    {result_.position.x, result_.position.y, result_.position.z},
    {result_.lookAt.x, result_.lookAt.y, result_.lookAt.z}
  );
}
