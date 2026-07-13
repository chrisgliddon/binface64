/**
 * Inexpensive fixed-function blob shadow for grounded movable objects.
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <cstdint>
#include <t3d/t3d.h>

#include "lib/matrixManager.h"

namespace P64 { class Object; }

namespace P64::Comp
{
  struct BlobShadow
  {
    static constexpr std::uint32_t ID = 16;
    static constexpr std::uint8_t SEGMENTS = 8;

    T3DVertPacked *vertices{};
    RingMat4FP matrix{};
    float radius{24.0f};
    float yOffset{1.0f};
    std::uint32_t color{0x10101870};
    std::uint8_t layer{1};

    static std::uint32_t getAllocSize([[maybe_unused]] void*) { return sizeof(BlobShadow); }
    static void initDelete(Object &object, BlobShadow *data, void *initData);
    static void draw(Object &object, BlobShadow *data, float deltaTime);
  };
}
