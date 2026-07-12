/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <cstdint>

namespace P64::UI::Format
{
  constexpr uint32_t MAGIC = 0x42465549; // "BFUI"
  constexpr uint16_t VERSION = 1;
  constexpr uint16_t NO_INDEX = 0xFFFF;
  constexpr uint16_t MAX_ELEMENTS = 256;

  enum class ElementType : uint8_t
  {
    CONTAINER = 0,
    IMAGE,
    TEXT,
    BUTTON,
    TEXT_INPUT,
    PROGRESS_BAR,
  };

  [[nodiscard]] constexpr bool supportsText(ElementType type)
  {
    return type == ElementType::TEXT || type == ElementType::BUTTON || type == ElementType::TEXT_INPUT;
  }

  enum ElementFlags : uint8_t
  {
    VISIBLE = 1 << 0,
    ENABLED = 1 << 1,
    FOCUSABLE = 1 << 2,
    SUBMIT_ON_START = 1 << 3,
  };

  enum class TextAlign : uint8_t
  {
    LEFT = 0,
    CENTER,
    RIGHT,
  };

  enum class ImageFit : uint8_t
  {
    STRETCH = 0,
    NATIVE,
  };

  enum class Flow : uint16_t
  {
    NONE = 0,
    VERTICAL,
    HORIZONTAL,
  };

  struct __attribute__((packed)) Header
  {
    uint32_t magic{};
    uint16_t version{};
    uint16_t elementCount{};
    uint16_t canvasWidth{};
    uint16_t canvasHeight{};
    uint32_t elementsOffset{};
    uint32_t stringsOffset{};
    uint32_t stringBytes{};
  };

  struct __attribute__((packed)) Element
  {
    uint32_t id{};
    uint16_t parent{NO_INDEX};
    ElementType type{ElementType::CONTAINER};
    uint8_t flags{};
    int16_t anchors[4]{}; // normalized 0..1 encoded as 0..32767
    int16_t offsets[4]{};
    uint32_t color{};      // RRGGBBAA
    uint32_t textColor{};  // RRGGBBAA
    uint32_t focusColor{}; // RRGGBBAA
    uint16_t assetIndex{NO_INDEX}; // sprite asset index, or registered font id
    uint16_t textOffset{NO_INDEX};
    uint16_t altTextOffset{NO_INDEX}; // TextInput placeholder
    uint16_t charsetOffset{NO_INDEX};
    uint16_t maxLength{};
    uint16_t focus[4]{NO_INDEX, NO_INDEX, NO_INDEX, NO_INDEX}; // up/down/left/right
    TextAlign align{TextAlign::LEFT};
    ImageFit fit{ImageFit::STRETCH};
    // ProgressBar uses otherwise-unused per-type fields as follows:
    // assetIndex=value, textOffset=max, altTextOffset/charsetOffset/maxLength=threshold maxima,
    // focus[0]=threshold count, textColor=fill color, focusColor=threshold 0 color.
    // Container uses focus[0]=Flow and focus[1]=non-negative pixel gap.
    uint32_t thresholdColor1{};
    uint32_t thresholdColor2{};
  };

  static_assert(sizeof(Header) == 24);
  static_assert(sizeof(Element) == 64);
}
