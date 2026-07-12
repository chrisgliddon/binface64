/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <cstdint>
#include <limits>
#include <string>
#include <type_traits>

#include "json.hpp"

#include "../utils/prop.h"

namespace Project
{
  enum class ComprTypes : int
  {
    DEFAULT = 0,
    LEVEL_0,
    LEVEL_1,
    LEVEL_2,
    LEVEL_3,
  };

  struct AssetConf
  {
  private:
    template<typename T>
    [[nodiscard]] static T valueOr(const nlohmann::json &doc, const std::string &key, const T &fallback)
    {
      const auto value = doc.find(key);
      if(value == doc.end() || value->is_null())return fallback;
      try {
        if constexpr(std::is_same_v<T, bool>) {
          return value->is_boolean() ? value->template get<bool>() : fallback;
        } else if constexpr(std::is_integral_v<T> && std::is_signed_v<T>) {
          if(value->is_number_unsigned()) {
            const auto raw = value->template get<std::uint64_t>();
            return raw <= static_cast<std::uint64_t>(std::numeric_limits<T>::max())
              ? static_cast<T>(raw)
              : fallback;
          }
          if(!value->is_number_integer())return fallback;
          const auto raw = value->template get<std::int64_t>();
          return raw >= static_cast<std::int64_t>(std::numeric_limits<T>::min()) &&
                 raw <= static_cast<std::int64_t>(std::numeric_limits<T>::max())
            ? static_cast<T>(raw)
            : fallback;
        } else if constexpr(std::is_integral_v<T> && std::is_unsigned_v<T>) {
          if(value->is_number_unsigned()) {
            const auto raw = value->template get<std::uint64_t>();
            return raw <= static_cast<std::uint64_t>(std::numeric_limits<T>::max())
              ? static_cast<T>(raw)
              : fallback;
          }
          if(!value->is_number_integer())return fallback;
          const auto raw = value->template get<std::int64_t>();
          return raw >= 0 && static_cast<std::uint64_t>(raw) <= std::numeric_limits<T>::max()
            ? static_cast<T>(raw)
            : fallback;
        } else if constexpr(std::is_same_v<T, std::string>) {
          return value->is_string() ? value->template get<std::string>() : fallback;
        }
        return value->template get<T>();
      } catch(const nlohmann::json::exception &) {
        return fallback;
      }
    }

  public:
    uint64_t uuid{0};
    int format{0};
    int baseScale{16};
    bool gltfBVH{false};

    ComprTypes compression{ComprTypes::DEFAULT};
    bool exclude{false};

    PROP_BOOL(wavForceMono);
    PROP_U32(wavResampleRate);
    PROP_S32(wavCompression);

    PROP_U32(fontId);
    PROP_STRING(fontCharset);

    // Extensible object for asset-type-specific metadata.
    nlohmann::json data = nlohmann::json::object();

    /** Load present, correctly typed fields while preserving defaults for omitted legacy fields. */
    void deserialize(const nlohmann::json &doc)
    {
      if(!doc.is_object())return;
      uuid = valueOr<uint64_t>(doc, "uuid", uuid);
      format = valueOr<int>(doc, "format", format);
      baseScale = valueOr<int>(doc, "baseScale", baseScale);
      compression = static_cast<ComprTypes>(
        valueOr<int>(doc, "compression", static_cast<int>(compression))
      );
      gltfBVH = valueOr<bool>(doc, "gltfBVH", gltfBVH);
      wavForceMono.value = valueOr<bool>(doc, wavForceMono.name, wavForceMono.value);
      wavResampleRate.value = valueOr<uint32_t>(doc, wavResampleRate.name, wavResampleRate.value);
      wavCompression.value = valueOr<int32_t>(doc, wavCompression.name, wavCompression.value);
      fontId.value = valueOr<uint32_t>(doc, fontId.name, fontId.value);
      fontCharset.value = valueOr<std::string>(doc, fontCharset.name, fontCharset.value);
      exclude = valueOr<bool>(doc, "exclude", exclude);
      const auto dataValue = doc.find("data");
      if(dataValue != doc.end() && dataValue->is_object())data = *dataValue;
    }

    std::string serialize() const;
  };
}
