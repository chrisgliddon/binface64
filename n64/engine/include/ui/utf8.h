/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <cstddef>
#include <string>

namespace P64::UI::Utf8
{
  struct Codepoint
  {
    const char *data{};
    size_t bytes{};
  };

  /** Returns the next code-point boundary, treating malformed bytes individually. */
  [[nodiscard]] size_t nextOffset(const char *text, size_t byteCount, size_t offset);
  [[nodiscard]] size_t count(const char *text);
  [[nodiscard]] bool at(const char *text, size_t index, Codepoint &result);
  bool appendCodepoint(std::string &value, const char *charset, size_t index, size_t maxCharacters);
  bool eraseLastCodepoint(std::string &value);
}
