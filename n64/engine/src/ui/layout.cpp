/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "ui/layout.h"

#include <algorithm>
#include <array>

namespace
{
  P64::UI::Format::Flow flowOf(const P64::UI::Format::Element &element)
  {
    if(element.type != P64::UI::Format::ElementType::CONTAINER) {
      return P64::UI::Format::Flow::NONE;
    }
    const auto flow = static_cast<P64::UI::Format::Flow>(element.focus[0]);
    return flow == P64::UI::Format::Flow::VERTICAL || flow == P64::UI::Format::Flow::HORIZONTAL
      ? flow
      : P64::UI::Format::Flow::NONE;
  }
}

void P64::UI::Layout::calculate(
  const Format::Header &header,
  const Format::Element *elements,
  const std::uint8_t *visible,
  Rect *rects)
{
  if(elements == nullptr || rects == nullptr)return;
  const std::uint16_t count = std::min<std::uint16_t>(header.elementCount, Format::MAX_ELEMENTS);
  std::array<float, Format::MAX_ELEMENTS> cursors{};
  constexpr float Q = 1.0f / 32767.0f;

  for(std::uint16_t index=0; index<count; ++index) {
    const auto &element = elements[index];
    Rect parent{0, 0, static_cast<float>(header.canvasWidth), static_cast<float>(header.canvasHeight)};
    if(element.parent != Format::NO_INDEX && element.parent < index)parent = rects[element.parent];
    const float width = parent.x1 - parent.x0;
    const float height = parent.y1 - parent.y0;
    Rect rect{
      parent.x0 + width * static_cast<float>(element.anchors[0]) * Q + element.offsets[0],
      parent.y0 + height * static_cast<float>(element.anchors[1]) * Q + element.offsets[1],
      parent.x0 + width * static_cast<float>(element.anchors[2]) * Q + element.offsets[2],
      parent.y0 + height * static_cast<float>(element.anchors[3]) * Q + element.offsets[3],
    };

    if(element.parent != Format::NO_INDEX && element.parent < index) {
      const auto parentFlow = flowOf(elements[element.parent]);
      const bool isVisible = visible == nullptr || visible[index] != 0;
      const float gap = static_cast<float>(elements[element.parent].focus[1]);
      if(parentFlow == Format::Flow::VERTICAL) {
        const float extent = std::max(0.0f, rect.y1 - rect.y0);
        rect.y0 = cursors[element.parent];
        rect.y1 = isVisible ? rect.y0 + extent : rect.y0;
        if(isVisible)cursors[element.parent] = rect.y1 + gap;
      } else if(parentFlow == Format::Flow::HORIZONTAL) {
        const float extent = std::max(0.0f, rect.x1 - rect.x0);
        rect.x0 = cursors[element.parent];
        rect.x1 = isVisible ? rect.x0 + extent : rect.x0;
        if(isVisible)cursors[element.parent] = rect.x1 + gap;
      }
    }

    rects[index] = rect;
    const auto flow = flowOf(element);
    if(flow == Format::Flow::VERTICAL)cursors[index] = rect.y0;
    else if(flow == Format::Flow::HORIZONTAL)cursors[index] = rect.x0;
  }
}
