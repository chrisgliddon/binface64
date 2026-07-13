/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <cstdint>

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
  void setActivity(std::uint8_t activePlayers, std::uint8_t activeCameras);
  void beginCamera(std::uint8_t cameraIndex);
  void recordObject(const void *object);
  void recordModel(const void *model);
  void recordProcedural(std::uint32_t triangles, std::uint32_t batches = 1, std::uint32_t materialChanges = 0);
  void recordChunk(std::uint32_t triangles, std::uint32_t batches);
  void recordParticles(std::uint32_t particleCount);
  void endFrame();
}
