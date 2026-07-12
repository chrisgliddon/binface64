/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <cstdint>

#include "ui/documentFormat.h"

namespace P64::UI::Layout
{
  struct Rect
  {
    float x0{};
    float y0{};
    float x1{};
    float y1{};
  };

  /**
   * Resolve anchored rectangles and simple container flow without allocation.
   * `visible` contains one byte per element; hidden direct children collapse
   * inside vertical/horizontal flow containers.
   */
  void calculate(
    const Format::Header &header,
    const Format::Element *elements,
    const std::uint8_t *visible,
    Rect *rects
  );
}
