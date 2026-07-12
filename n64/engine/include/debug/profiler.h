/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <cstdint>
#include <t3d/t3dmodel.h>

namespace P64::Profiler
{
  struct Config
  {
    uint16_t warmupFrames{};
    uint16_t sampleFrames{};
  };

  void configure(Config config);
  [[nodiscard]] bool isActive();
  void beginFrame(float deltaTime);
  void recordObject(const T3DObject *object);
  void recordModel(const T3DModel *model);
  void endFrame();
}
