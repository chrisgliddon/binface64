/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "scene/components/ui.h"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "scene/object.h"
#include "scene/scene.h"
#include "renderer/drawLayer.h"
#include "ui/dialogue.h"
#include "ui/utf8.h"
#include "input/input.h"
#include "scene/camera.h"

namespace UIFormat = P64::UI::Format;

namespace
{
  struct InitData
  {
    uint16_t assetIdx{};
    uint8_t layer{};
    uint8_t flags{};
    P64::Comp::UI::DisplayTarget displayTarget{P64::Comp::UI::DisplayTarget::Shared};
    uint8_t displayPlayer{};
    uint8_t inputPlayerMask{1};
    uint8_t padding{};
  };

  const UIFormat::Element* elements(const UIFormat::Header *document)
  {
    return reinterpret_cast<const UIFormat::Element*>(reinterpret_cast<const uint8_t*>(document) + document->elementsOffset);
  }

  const char* strings(const UIFormat::Header *document)
  {
    return reinterpret_cast<const char*>(document) + document->stringsOffset;
  }

  const char* stringAt(const UIFormat::Header *document, uint16_t offset)
  {
    return offset == UIFormat::NO_INDEX ? "" : strings(document) + offset;
  }

  color_t colorFromU32(uint32_t value)
  {
    return {
      static_cast<uint8_t>(value >> 24),
      static_cast<uint8_t>(value >> 16),
      static_cast<uint8_t>(value >> 8),
      static_cast<uint8_t>(value),
    };
  }

  bool focusable(const P64::Comp::UI &data, uint16_t index)
  {
    if(index >= data.states.size())return false;
    const auto &element = elements(data.document)[index];
    if(!(element.flags & UIFormat::FOCUSABLE))return false;
    while(index != UIFormat::NO_INDEX) {
      if(!data.states[index].visible || !data.states[index].enabled)return false;
      index = elements(data.document)[index].parent;
    }
    return true;
  }

  bool effectivelyVisible(const P64::Comp::UI &data, uint16_t index)
  {
    while(index != UIFormat::NO_INDEX) {
      if(!data.states[index].visible)return false;
      index = elements(data.document)[index].parent;
    }
    return true;
  }

  uint16_t firstFocusable(const P64::Comp::UI &data)
  {
    for(uint16_t i=0; i<data.document->elementCount; ++i)if(focusable(data, i))return i;
    return UIFormat::NO_INDEX;
  }

  uint16_t spatialFocus(const P64::Comp::UI &data, uint16_t current, uint32_t direction)
  {
    if(current == UIFormat::NO_INDEX)return firstFocusable(data);
    const auto &element = elements(data.document)[current];
    if(element.focus[direction] != UIFormat::NO_INDEX && focusable(data, element.focus[direction])) {
      return element.focus[direction];
    }

    const auto &from = data.rects[current];
    float fromX = (from.x0 + from.x1) * 0.5f;
    float fromY = (from.y0 + from.y1) * 0.5f;
    float bestScore = 1.0e30f;
    uint16_t best = current;
    for(uint16_t i=0; i<data.document->elementCount; ++i) {
      if(i == current || !focusable(data, i))continue;
      const auto &rect = data.rects[i];
      float dx = (rect.x0 + rect.x1) * 0.5f - fromX;
      float dy = (rect.y0 + rect.y1) * 0.5f - fromY;
      bool inDirection = (direction == 0 && dy < 0) || (direction == 1 && dy > 0) ||
                         (direction == 2 && dx < 0) || (direction == 3 && dx > 0);
      if(!inDirection)continue;
      float primary = direction < 2 ? std::fabs(dy) : std::fabs(dx);
      float secondary = direction < 2 ? std::fabs(dx) : std::fabs(dy);
      float score = primary + secondary * 2.0f;
      if(score < bestScore) { bestScore = score; best = i; }
    }
    return best;
  }

  void sendUIEvent(P64::Object &obj, uint16_t type, uint32_t elementId, uint8_t player)
  {
    P64::Object::getScene().sendEvent(obj.id, obj.id, type, elementId, player + 1);
  }

  bool setDialogueText(void *context, uint32_t elementId, const char *value)
  {
    return static_cast<P64::Comp::UI*>(context)->setText(elementId, value);
  }

  P64::Comp::UI::Rect displayViewport(const P64::Comp::UI &data)
  {
    auto &scene = P64::Object::getScene();
    P64::Comp::UI::Rect viewport{
      0.0f, 0.0f,
      static_cast<float>(scene.getConf().screenWidth),
      static_cast<float>(scene.getConf().screenHeight)
    };
    if(data.displayTarget != P64::Comp::UI::DisplayTarget::Player)return viewport;
    auto *camera = scene.getCameraForPlayer(data.displayPlayer);
    if(camera == nullptr || !camera->isActive())return viewport;
    const auto &area = camera->getScreenArea();
    return {
      static_cast<float>(area.x), static_cast<float>(area.y),
      static_cast<float>(area.x + area.width), static_cast<float>(area.y + area.height)
    };
  }

  void calculateRects(P64::Comp::UI &data)
  {
    std::uint8_t visible[UIFormat::MAX_ELEMENTS]{};
    const std::uint16_t count = std::min<std::uint16_t>(data.document->elementCount, UIFormat::MAX_ELEMENTS);
    for(std::uint16_t index=0; index<count; ++index)visible[index] = data.states[index].visible ? 1 : 0;
    P64::UI::Layout::calculate(*data.document, elements(data.document), visible, data.rects.data());

    const auto viewport = displayViewport(data);
    const float scaleX = data.document->canvasWidth > 0
      ? (viewport.x1 - viewport.x0) / static_cast<float>(data.document->canvasWidth) : 1.0f;
    const float scaleY = data.document->canvasHeight > 0
      ? (viewport.y1 - viewport.y0) / static_cast<float>(data.document->canvasHeight) : 1.0f;
    for(auto &rect : data.rects) {
      rect = {
        viewport.x0 + rect.x0 * scaleX, viewport.y0 + rect.y0 * scaleY,
        viewport.x0 + rect.x1 * scaleX, viewport.y0 + rect.y1 * scaleY
      };
    }
  }

  int focusedPlayer(const P64::Comp::UI &data, uint16_t element)
  {
    const uint8_t mask = data.inputPlayerMask & 0x10
      ? static_cast<uint8_t>(1u << std::min<uint8_t>(P64::Input::getConfig().hostPort, 3))
      : data.inputPlayerMask & 0x0F;
    for(uint8_t player=0; player<4; ++player) {
      if((mask & (1u << player)) && data.focusedPlayers[player] == element)return player;
    }
    return -1;
  }

  uint8_t resolvedInputMask(const P64::Comp::UI &data)
  {
    if(data.inputPlayerMask & 0x10) {
      const auto host = std::min<uint8_t>(P64::Input::getConfig().hostPort, 3);
      return static_cast<uint8_t>(1u << host);
    }
    return data.inputPlayerMask & 0x0F;
  }

  uint32_t playerFocusColor(uint8_t player)
  {
    constexpr uint32_t COLORS[4]{0x4DA3FFFF, 0xFF5A5AFF, 0x62D26FFF, 0xFFD24DFF};
    return COLORS[player & 3u];
  }

  void drawBox(const P64::Comp::UI::Rect &rect, uint32_t packed)
  {
    auto color = colorFromU32(packed);
    if(color.a == 0)return;
    rdpq_set_mode_standard();
    rdpq_mode_combiner(RDPQ_COMBINER_FLAT);
    rdpq_mode_blender(RDPQ_BLENDER_MULTIPLY);
    rdpq_set_prim_color(color);
    rdpq_fill_rectangle(rect.x0, rect.y0, rect.x1, rect.y1);
  }

  void drawText(const P64::Comp::UI &data, uint16_t index, const char *text)
  {
    const auto &element = elements(data.document)[index];
    const auto &rect = data.rects[index];
    auto font = const_cast<rdpq_font_t*>(rdpq_text_get_font(static_cast<uint8_t>(element.assetIndex)));
    if(!font || !text || !*text)return;
    rdpq_fontstyle_t style{};
    style.color = colorFromU32(element.textColor);
    rdpq_font_style(font, 0, &style);
    rdpq_textparms_t parms{};
    parms.style_id = 0;
    parms.width = static_cast<int16_t>(std::max(0.0f, rect.x1 - rect.x0));
    parms.height = static_cast<int16_t>(std::max(0.0f, rect.y1 - rect.y0));
    parms.align = static_cast<rdpq_align_t>(element.align);
    parms.valign = VALIGN_CENTER;
    parms.wrap = WRAP_WORD;
    parms.disable_aa_fix = true;
    rdpq_text_print(&parms, static_cast<uint8_t>(element.assetIndex), rect.x0, rect.y0, text);
  }

  void drawKeyboard(const P64::Comp::UI &data)
  {
    if(data.editing == UIFormat::NO_INDEX)return;
    const auto &element = elements(data.document)[data.editing];
    const char *charset = stringAt(data.document, element.charsetOffset);
    size_t count = P64::UI::Utf8::count(charset);
    if(count == 0)return;
    constexpr int COLS = 10;
    constexpr float CELL_W = 28.0f;
    constexpr float CELL_H = 18.0f;
    int rows = static_cast<int>((count + COLS - 1) / COLS);
    const auto viewport = displayViewport(data);
    const float scaleX = data.document->canvasWidth > 0
      ? (viewport.x1 - viewport.x0) / static_cast<float>(data.document->canvasWidth) : 1.0f;
    const float scaleY = data.document->canvasHeight > 0
      ? (viewport.y1 - viewport.y0) / static_cast<float>(data.document->canvasHeight) : 1.0f;
    const float localX0 = (data.document->canvasWidth - COLS * CELL_W) * 0.5f;
    const float localY0 = data.document->canvasHeight - rows * CELL_H - 8.0f;
    const float x0 = viewport.x0 + localX0 * scaleX;
    const float y0 = viewport.y0 + localY0 * scaleY;
    const float cellWidth = CELL_W * scaleX;
    const float cellHeight = CELL_H * scaleY;
    drawBox({
      x0 - 4.0f * scaleX, y0 - 4.0f * scaleY,
      x0 + COLS * cellWidth + 4.0f * scaleX,
      viewport.y0 + (static_cast<float>(data.document->canvasHeight) - 4.0f) * scaleY
    }, 0x101018E8);
    for(size_t i=0; i<count; ++i) {
      float x = x0 + static_cast<float>(i % COLS) * cellWidth;
      float y = y0 + static_cast<float>(i / COLS) * cellHeight;
      if(i == data.keyboardIndex)drawBox(
        {x, y, x+cellWidth-2.0f*scaleX, y+cellHeight-2.0f*scaleY},
        playerFocusColor(data.editingPlayer < 4 ? data.editingPlayer : 0)
      );
      P64::UI::Utf8::Codepoint codepoint{};
      if(!P64::UI::Utf8::at(charset, i, codepoint))continue;
      char value[5]{};
      std::memcpy(value, codepoint.data, codepoint.bytes);
      rdpq_fontstyle_t style{};
      style.color = colorFromU32(element.textColor);
      auto font = const_cast<rdpq_font_t*>(rdpq_text_get_font(static_cast<uint8_t>(element.assetIndex)));
      if(font)rdpq_font_style(font, 0, &style);
      rdpq_text_print(nullptr, static_cast<uint8_t>(element.assetIndex), x+8.0f*scaleX, y+2.0f*scaleY, value);
    }
  }
}

void P64::Comp::UI::initDelete([[maybe_unused]] Object &obj, UI *data, uint16_t *initData_)
{
  if(initData_ == nullptr) {
    data->~UI();
    return;
  }
  auto *initData = reinterpret_cast<InitData*>(initData_);
  new(data) UI();
  data->document = static_cast<const UIFormat::Header*>(AssetManager::getByIndex(initData->assetIdx));
  assert(data->document && data->document->magic == UIFormat::MAGIC);
  assert(data->document->version == UIFormat::VERSION);
  data->layer = initData->layer;
  data->active = (initData->flags & 1) != 0;
  data->displayTarget = initData->displayTarget;
  data->displayPlayer = std::min<uint8_t>(initData->displayPlayer, 3);
  data->inputPlayerMask = initData->inputPlayerMask & 0x1F;
  data->states.resize(data->document->elementCount);
  data->rects.resize(data->document->elementCount);
  const auto *items = elements(data->document);
  for(uint16_t i=0; i<data->document->elementCount; ++i) {
    data->states[i].visible = (items[i].flags & UIFormat::VISIBLE) != 0;
    data->states[i].enabled = (items[i].flags & UIFormat::ENABLED) != 0;
    if(items[i].type == UIFormat::ElementType::TEXT_INPUT) {
      data->states[i].text = stringAt(data->document, items[i].textOffset);
      data->states[i].text.reserve(static_cast<size_t>(items[i].maxLength) * 4);
      data->states[i].hasTextOverride = true;
    } else if(items[i].type == UIFormat::ElementType::PROGRESS_BAR) {
      data->states[i].value = items[i].assetIndex;
      data->states[i].maxValue = items[i].textOffset;
    }
  }
  calculateRects(*data);
  data->focused = firstFocusable(*data);
  data->focusedPlayers.fill(data->focused);
}

int32_t P64::Comp::UI::find(uint32_t id) const
{
  if(!document)return -1;
  const auto *items = elements(document);
  for(uint16_t i=0; i<document->elementCount; ++i)if(items[i].id == id)return i;
  return -1;
}

const char* P64::Comp::UI::getText(uint32_t id) const
{
  int32_t index = find(id);
  if(index < 0)return nullptr;
  if(!UIFormat::supportsText(elements(document)[index].type))return nullptr;
  if(states[index].hasTextOverride)return states[index].text.c_str();
  return stringAt(document, elements(document)[index].textOffset);
}

bool P64::Comp::UI::reserveText(uint32_t id, size_t capacity)
{
  const int32_t index = find(id);
  if(index < 0 || !UIFormat::supportsText(elements(document)[index].type))return false;
  states[index].text.reserve(capacity);
  return true;
}

bool P64::Comp::UI::setText(uint32_t id, const char *value)
{
  int32_t index = find(id);
  if(index < 0)return false;
  const auto &element = elements(document)[index];
  if(!UIFormat::supportsText(element.type))return false;
  const char *safeValue = value ? value : "";
  if(element.type == UIFormat::ElementType::TEXT_INPUT && P64::UI::Utf8::count(safeValue) > element.maxLength)return false;
  states[index].text = safeValue;
  states[index].hasTextOverride = true;
  return true;
}

bool P64::Comp::UI::setVisible(uint32_t id, bool value)
{
  int32_t index = find(id);
  if(index < 0)return false;
  states[index].visible = value;
  return true;
}

bool P64::Comp::UI::setEnabled(uint32_t id, bool value)
{
  int32_t index = find(id);
  if(index < 0)return false;
  states[index].enabled = value;
  return true;
}

bool P64::Comp::UI::setImage(uint32_t id, uint32_t assetIndex)
{
  int32_t index = find(id);
  if(index < 0 || elements(document)[index].type != UIFormat::ElementType::IMAGE)return false;
  states[index].imageOverride = static_cast<sprite_t*>(AssetManager::getByIndex(assetIndex));
  return true;
}

bool P64::Comp::UI::setValue(uint32_t id, uint16_t current, uint16_t maximum)
{
  int32_t index = find(id);
  if(index < 0 || maximum == 0 || elements(document)[index].type != UIFormat::ElementType::PROGRESS_BAR)return false;
  states[index].value = std::min(current, maximum);
  states[index].maxValue = maximum;
  return true;
}

bool P64::Comp::UI::focus(uint32_t id)
{
  return focus(id, 0);
}

bool P64::Comp::UI::focus(uint32_t id, uint8_t player)
{
  if(player >= focusedPlayers.size())return false;
  int32_t index = find(id);
  if(index < 0 || !focusable(*this, index))return false;
  focusedPlayers[player] = index;
  if(player == 0)focused = index;
  return true;
}

bool P64::Comp::UI::bindDialogue(P64::UI::DialogueRunner &runner, uint32_t textId, uint32_t speakerId)
{
  const int32_t textIndex = find(textId);
  if(textIndex < 0 || !UIFormat::supportsText(elements(document)[textIndex].type))return false;
  if(speakerId != P64::UI::DialogueRunner::NO_ELEMENT) {
    const int32_t speakerIndex = find(speakerId);
    if(speakerIndex < 0 || !UIFormat::supportsText(elements(document)[speakerIndex].type))return false;
  }
  runner.bind(setDialogueText, this, textId, speakerId);
  return true;
}

void P64::Comp::UI::unscaledUpdate(Object &obj, UI *data, [[maybe_unused]] float unscaledDeltaTime)
{
  if(!data->active || !data->document)return;
  calculateRects(*data);
  const auto *items = elements(data->document);
  data->focusedPlayers[0] = data->focused;

  if(data->editing != UIFormat::NO_INDEX)
  {
    const uint8_t player = data->editingPlayer < 4 ? data->editingPlayer : 0;
    const uint16_t pressed = P64::Input::get(player).buttonsPressed;
    auto hit = [pressed](P64::Input::Button button) { return (pressed & P64::Input::mask(button)) != 0; };
    const auto &element = items[data->editing];
    const char *charset = stringAt(data->document, element.charsetOffset);
    uint16_t charsetCount = static_cast<uint16_t>(P64::UI::Utf8::count(charset));
    constexpr uint16_t COLS = 10;
    if(charsetCount > 0) {
      if(hit(P64::Input::Button::D_LEFT))data->keyboardIndex = data->keyboardIndex == 0 ? charsetCount-1 : data->keyboardIndex-1;
      if(hit(P64::Input::Button::D_RIGHT))data->keyboardIndex = (data->keyboardIndex+1) % charsetCount;
      if(hit(P64::Input::Button::D_UP))data->keyboardIndex = data->keyboardIndex < COLS ? data->keyboardIndex : data->keyboardIndex-COLS;
      if(hit(P64::Input::Button::D_DOWN) && data->keyboardIndex+COLS < charsetCount)data->keyboardIndex += COLS;
      if(hit(P64::Input::Button::A) && P64::UI::Utf8::appendCodepoint(
          data->states[data->editing].text, charset, data->keyboardIndex, element.maxLength)) {
        sendUIEvent(obj, EVENT_TYPE_UI_CHANGE, element.id, player);
      }
    }
    if(hit(P64::Input::Button::C_LEFT) && P64::UI::Utf8::eraseLastCodepoint(data->states[data->editing].text)) {
      sendUIEvent(obj, EVENT_TYPE_UI_CHANGE, element.id, player);
    }
    if(hit(P64::Input::Button::B)) {
      data->states[data->editing].text = data->editOriginal;
      data->editing = UIFormat::NO_INDEX;
      data->editingPlayer = 0xFF;
    } else if(hit(P64::Input::Button::START) && (element.flags & UIFormat::SUBMIT_ON_START)) {
      sendUIEvent(obj, EVENT_TYPE_UI_SUBMIT, element.id, player);
      data->editing = UIFormat::NO_INDEX;
      data->editingPlayer = 0xFF;
    }
    return;
  }

  for(uint8_t player=0; player<4; ++player)
  {
    if((resolvedInputMask(*data) & (1u << player)) == 0)continue;
    const uint16_t pressed = P64::Input::get(player).buttonsPressed;
    auto hit = [pressed](P64::Input::Button button) { return (pressed & P64::Input::mask(button)) != 0; };
    uint32_t direction = 4;
    if(hit(P64::Input::Button::D_UP))direction = 0;
    else if(hit(P64::Input::Button::D_DOWN))direction = 1;
    else if(hit(P64::Input::Button::D_LEFT))direction = 2;
    else if(hit(P64::Input::Button::D_RIGHT))direction = 3;
    if(direction < 4)data->focusedPlayers[player] = spatialFocus(*data, data->focusedPlayers[player], direction);
    if(player == 0)data->focused = data->focusedPlayers[0];
    const uint16_t focused = data->focusedPlayers[player];
    if(focused == UIFormat::NO_INDEX || !hit(P64::Input::Button::A))continue;

    const auto &element = items[focused];
    if(element.type == UIFormat::ElementType::BUTTON) {
      sendUIEvent(obj, EVENT_TYPE_UI_ACTIVATE, element.id, player);
    } else if(element.type == UIFormat::ElementType::TEXT_INPUT) {
      data->editing = focused;
      data->editingPlayer = player;
      data->editOriginal = data->states[data->editing].text;
      data->keyboardIndex = 0;
      break;
    }
  }
}

void P64::Comp::UI::draw2D([[maybe_unused]] Object &obj, UI *data, [[maybe_unused]] float deltaTime)
{
  if(!data->active || !data->document)return;
  auto &scene = Object::getScene();
  if(data->displayTarget == DisplayTarget::Player) {
    auto *camera = scene.getCameraForPlayer(data->displayPlayer);
    if(camera == nullptr || !camera->isActive())return;
    const auto &area = camera->getScreenArea();
    rdpq_set_scissor(area.x, area.y, area.x + area.width, area.y + area.height);
  } else {
    rdpq_set_scissor(0, 0, scene.getConf().screenWidth, scene.getConf().screenHeight);
  }
  DrawLayer::use2D(data->layer);
  calculateRects(*data);
  const auto *items = elements(data->document);
  for(uint16_t i=0; i<data->document->elementCount; ++i)
  {
    if(!effectivelyVisible(*data, i))continue;
    const auto &element = items[i];
    const auto &rect = data->rects[i];
    const int focusOwner = focusedPlayer(*data, i);
    const bool selected = focusOwner >= 0;
    if(element.type == UIFormat::ElementType::CONTAINER || element.type == UIFormat::ElementType::BUTTON ||
       element.type == UIFormat::ElementType::TEXT_INPUT || element.type == UIFormat::ElementType::PROGRESS_BAR) {
      drawBox(rect, selected ? playerFocusColor(static_cast<uint8_t>(focusOwner)) : element.color);
    }
    if(element.type == UIFormat::ElementType::PROGRESS_BAR) {
      const auto &state = data->states[i];
      uint32_t fillColor = element.textColor;
      const uint16_t thresholdMaxima[3]{element.altTextOffset, element.charsetOffset, element.maxLength};
      const uint32_t thresholdColors[3]{element.focusColor, element.thresholdColor1, element.thresholdColor2};
      const uint16_t thresholdCount = std::min<uint16_t>(element.focus[0], 3);
      for(uint16_t threshold=0; threshold<thresholdCount; ++threshold) {
        if(state.value <= thresholdMaxima[threshold]) {
          fillColor = thresholdColors[threshold];
          break;
        }
      }
      if(state.value > 0 && state.maxValue > 0) {
        Rect fill = rect;
        const float ratio = static_cast<float>(state.value) / static_cast<float>(state.maxValue);
        fill.x1 = fill.x0 + (fill.x1 - fill.x0) * ratio;
        drawBox(fill, fillColor);
      }
    }
    if(element.type == UIFormat::ElementType::IMAGE) {
      auto *sprite = data->states[i].imageOverride;
      if(!sprite)sprite = static_cast<sprite_t*>(AssetManager::getByIndex(element.assetIndex));
      if(sprite) {
        rdpq_set_mode_standard();
        rdpq_mode_combiner(RDPQ_COMBINER_TEX_FLAT);
        rdpq_mode_blender(RDPQ_BLENDER_MULTIPLY);
        rdpq_set_prim_color({255,255,255,255});
        if(element.fit == UIFormat::ImageFit::NATIVE) {
          rdpq_sprite_blit(sprite, rect.x0, rect.y0, nullptr);
        } else {
          rdpq_blitparms_t params{};
          params.scale_x = (rect.x1 - rect.x0) / sprite->width;
          params.scale_y = (rect.y1 - rect.y0) / sprite->height;
          rdpq_sprite_blit(sprite, rect.x0, rect.y0, &params);
        }
      }
    }
    if(element.type == UIFormat::ElementType::TEXT || element.type == UIFormat::ElementType::BUTTON) {
      drawText(*data, i, data->states[i].hasTextOverride ? data->states[i].text.c_str() : stringAt(data->document, element.textOffset));
    } else if(element.type == UIFormat::ElementType::TEXT_INPUT) {
      const char *text = data->states[i].text.empty() ? stringAt(data->document, element.altTextOffset) : data->states[i].text.c_str();
      drawText(*data, i, text);
    }
  }
  drawKeyboard(*data);
  DrawLayer::use2D();
  rdpq_set_scissor(0, 0, scene.getConf().screenWidth, scene.getConf().screenHeight);
}
