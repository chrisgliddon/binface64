/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <libdragon.h>
#include <string>
#include <string_view>
#include <vector>

#include "assets/assetManager.h"
#include "scene/event.h"
#include "ui/documentFormat.h"

namespace P64 { class Object; }
namespace P64::UI { class DialogueRunner; }

namespace P64::UI
{
  constexpr uint32_t id(std::string_view value)
  {
    uint32_t crc = 0xFFFFFFFF;
    for(char character : value) {
      crc ^= static_cast<uint8_t>(character);
      for(uint32_t bit=0; bit<8; ++bit)crc = (crc & 1) ? (crc >> 1) ^ 0xEDB88320 : crc >> 1;
    }
    return ~crc;
  }
}

constexpr uint32_t operator""_ui(const char *value, size_t length)
{
  return P64::UI::id(std::string_view{value, length});
}

namespace P64::Comp
{
  struct UI
  {
    static constexpr uint32_t ID = 13;

    struct Rect { float x0{}, y0{}, x1{}, y1{}; };
    struct State
    {
      bool visible{true};
      bool enabled{true};
      bool hasTextOverride{false};
      std::string text{};
      sprite_t *imageOverride{};
      uint16_t value{};
      uint16_t maxValue{1};
    };

    const P64::UI::Format::Header *document{};
    std::vector<State> states{};
    std::vector<Rect> rects{};
    uint16_t focused{P64::UI::Format::NO_INDEX};
    uint16_t editing{P64::UI::Format::NO_INDEX};
    uint16_t keyboardIndex{};
    uint8_t layer{};
    bool active{true};
    std::string editOriginal{};

    static uint32_t getAllocSize([[maybe_unused]] uint16_t *initData) { return sizeof(UI); }
    static void initDelete(Object &obj, UI *data, uint16_t *initData);
    static void update(Object &obj, UI *data, float deltaTime);
    static void draw2D(Object &obj, UI *data, float deltaTime);

    [[nodiscard]] int32_t find(uint32_t id) const;
    [[nodiscard]] const char* getText(uint32_t id) const;
    bool setText(uint32_t id, const char *value);
    bool setVisible(uint32_t id, bool value);
    bool setEnabled(uint32_t id, bool value);
    bool setImage(uint32_t id, uint32_t assetIndex);
    bool setValue(uint32_t id, uint16_t current, uint16_t maximum);
    bool focus(uint32_t id);
    bool bindDialogue(P64::UI::DialogueRunner &runner, uint32_t textId, uint32_t speakerId=0);
  };
}
