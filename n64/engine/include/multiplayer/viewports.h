/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once
#include <array>
#include <cstdint>

namespace P64::Multiplayer::Viewports
{
  struct Rect
  {
    std::int16_t x{};
    std::int16_t y{};
    std::int16_t width{};
    std::int16_t height{};
    [[nodiscard]] bool valid() const { return width > 0 && height > 0; }
  };

  enum class TwoPlayerLayout : std::uint8_t { Horizontal, Vertical, Custom };

  void setTwoPlayerLayout(TwoPlayerLayout layout);
  void setCustom(const std::array<Rect, 4> &rectangles);
  [[nodiscard]] TwoPlayerLayout getTwoPlayerLayout();
  [[nodiscard]] std::uint8_t calculate(
    std::uint8_t activePlayerMask,
    std::int16_t screenWidth,
    std::int16_t screenHeight,
    std::array<Rect, 4> &byPlayer
  );
}
