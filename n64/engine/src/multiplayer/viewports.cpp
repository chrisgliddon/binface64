/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "multiplayer/viewports.h"

namespace
{
  P64::Multiplayer::Viewports::TwoPlayerLayout layout = P64::Multiplayer::Viewports::TwoPlayerLayout::Horizontal;
  std::array<P64::Multiplayer::Viewports::Rect, 4> custom{};
}

void P64::Multiplayer::Viewports::setTwoPlayerLayout(TwoPlayerLayout value) { layout = value; }
void P64::Multiplayer::Viewports::setCustom(const std::array<Rect, 4> &rectangles) { custom = rectangles; }
P64::Multiplayer::Viewports::TwoPlayerLayout P64::Multiplayer::Viewports::getTwoPlayerLayout() { return layout; }

std::uint8_t P64::Multiplayer::Viewports::calculate(
  std::uint8_t activePlayerMask,
  std::int16_t screenWidth,
  std::int16_t screenHeight,
  std::array<Rect, 4> &byPlayer)
{
  byPlayer = {};
  std::uint8_t players[4]{};
  std::uint8_t count{};
  for(std::uint8_t player=0; player<4; ++player)if(activePlayerMask & (1u << player))players[count++] = player;
  if(count == 0 || screenWidth <= 0 || screenHeight <= 0)return 0;
  if(count == 1) {
    byPlayer[players[0]] = {0, 0, screenWidth, screenHeight};
    return count;
  }
  if(count == 2) {
    if(layout == TwoPlayerLayout::Custom) {
      byPlayer[players[0]] = custom[0];
      byPlayer[players[1]] = custom[1];
    } else if(layout == TwoPlayerLayout::Vertical) {
      const std::int16_t leftWidth = screenWidth / 2;
      byPlayer[players[0]] = {0, 0, leftWidth, screenHeight};
      byPlayer[players[1]] = {leftWidth, 0, static_cast<std::int16_t>(screenWidth-leftWidth), screenHeight};
    } else {
      const std::int16_t topHeight = screenHeight / 2;
      byPlayer[players[0]] = {0, 0, screenWidth, topHeight};
      byPlayer[players[1]] = {0, topHeight, screenWidth, static_cast<std::int16_t>(screenHeight-topHeight)};
    }
    return count;
  }
  const std::int16_t leftWidth = screenWidth / 2;
  const std::int16_t topHeight = screenHeight / 2;
  const Rect cells[4]{
    {0, 0, leftWidth, topHeight},
    {leftWidth, 0, static_cast<std::int16_t>(screenWidth-leftWidth), topHeight},
    {0, topHeight, leftWidth, static_cast<std::int16_t>(screenHeight-topHeight)},
    {leftWidth, topHeight, static_cast<std::int16_t>(screenWidth-leftWidth), static_cast<std::int16_t>(screenHeight-topHeight)},
  };
  for(std::uint8_t index=0; index<count; ++index)byPlayer[players[index]] = cells[index];
  return count;
}
