/**
 * Fixed-angle, bounds-aware shared camera for local multiplayer groups.
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <array>
#include <cstdint>

namespace P64 { class Camera; }

namespace P64::Multiplayer
{
  class GroupCamera
  {
  public:
    static constexpr std::uint8_t MAX_TARGETS = 4;

    struct Point { float x{}, y{}, z{}; };
    struct Target { Point position{}; bool active{}; };
    struct Config
    {
      /** Fixed world-space orbit. Gameplay never mutates these angles. */
      float yawRadians{0.785398163f};
      float pitchRadians{0.698131701f};
      float minimumDistance{380.0f};
      float maximumDistance{760.0f};
      float baseDistance{360.0f};
      float distancePerUnit{0.9f};
      float boundsPadding{60.0f};
      float centroidSmoothing{8.0f};
      float zoomSmoothing{5.0f};
      Point lawnMinimum{-240.0f, -1000.0f, -160.0f};
      Point lawnMaximum{240.0f, 1000.0f, 160.0f};
    };
    struct Result
    {
      Point position{};
      Point lookAt{};
      float distance{};
      float yawRadians{};
      float pitchRadians{};
      std::uint8_t targetCount{};
    };

    GroupCamera();
    explicit GroupCamera(const Config &config);
    void configure(const Config &config);
    void reset();
    const Result& update(const std::array<Target, MAX_TARGETS> &targets, float deltaTime);
    void apply(Camera &camera) const;
    [[nodiscard]] const Config& config() const { return config_; }
    [[nodiscard]] const Result& result() const { return result_; }

  private:
    Config config_{};
    Result result_{};
    bool initialized_{};
  };
}
