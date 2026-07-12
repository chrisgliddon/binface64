/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "ui/utf8.h"

#include <cstdint>
#include <cstring>

size_t P64::UI::Utf8::nextOffset(const char *text, size_t byteCount, size_t offset)
{
  if(!text || offset >= byteCount)return byteCount;
  const auto lead = static_cast<uint8_t>(text[offset]);
  size_t length = 1;
  if((lead & 0xE0) == 0xC0)length = 2;
  else if((lead & 0xF0) == 0xE0)length = 3;
  else if((lead & 0xF8) == 0xF0)length = 4;
  if(length > byteCount-offset)return offset+1;
  for(size_t i=1; i<length; ++i) {
    if((static_cast<uint8_t>(text[offset+i]) & 0xC0) != 0x80)return offset+1;
  }
  return offset+length;
}

size_t P64::UI::Utf8::count(const char *text)
{
  if(!text)return 0;
  const size_t byteCount = std::strlen(text);
  size_t result = 0;
  for(size_t offset=0; offset<byteCount; ++result)offset = nextOffset(text, byteCount, offset);
  return result;
}

bool P64::UI::Utf8::at(const char *text, size_t index, Codepoint &result)
{
  result = {};
  if(!text)return false;
  const size_t byteCount = std::strlen(text);
  size_t current = 0;
  for(size_t offset=0; offset<byteCount; ++current) {
    const size_t next = nextOffset(text, byteCount, offset);
    if(current == index) {
      result = {text+offset, next-offset};
      return true;
    }
    offset = next;
  }
  return false;
}

bool P64::UI::Utf8::appendCodepoint(
  std::string &value,
  const char *charset,
  size_t index,
  size_t maxCharacters)
{
  if(count(value.c_str()) >= maxCharacters)return false;
  Codepoint codepoint{};
  if(!at(charset, index, codepoint))return false;
  value.append(codepoint.data, codepoint.bytes);
  return true;
}

bool P64::UI::Utf8::eraseLastCodepoint(std::string &value)
{
  if(value.empty())return false;
  const size_t byteCount = value.size();
  size_t last = 0;
  for(size_t offset=0; offset<byteCount;) {
    last = offset;
    offset = nextOffset(value.c_str(), byteCount, offset);
  }
  value.resize(last);
  return true;
}
