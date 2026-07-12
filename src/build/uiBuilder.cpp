/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "projectBuilder.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <filesystem>
#include <limits>
#include <stdexcept>
#include <unordered_map>
#include <vector>

#include "../utils/fs.h"
#include "../utils/hash.h"
#include "../utils/json.h"
#include "../utils/logger.h"
#include "engine/include/ui/documentFormat.h"

namespace fs = std::filesystem;
namespace UIFormat = P64::UI::Format;

namespace
{
  struct SourceElement
  {
    nlohmann::json doc{};
    uint16_t parent{UIFormat::NO_INDEX};
  };

  uint32_t parseColor(const nlohmann::json &style, const char *key, uint32_t fallback)
  {
    if(!style.is_object() || !style.contains(key))return fallback;
    auto value = style[key].get<std::string>();
    if(value.size() != 9 || value[0] != '#') {
      throw std::runtime_error(std::string{"UI color "} + key + " must be #RRGGBBAA");
    }
    return static_cast<uint32_t>(std::stoul(value.substr(1), nullptr, 16));
  }

  int16_t quantAnchor(float value)
  {
    if(value < 0.0f || value > 1.0f)throw std::runtime_error("UI anchors must be in 0..1");
    return static_cast<int16_t>(std::round(value * 32767.0f));
  }

  int16_t checkedOffset(const nlohmann::json &value)
  {
    auto number = value.get<int32_t>();
    if(number < std::numeric_limits<int16_t>::min() || number > std::numeric_limits<int16_t>::max()) {
      throw std::runtime_error("UI layout offset exceeds signed 16-bit range");
    }
    return static_cast<int16_t>(number);
  }

  UIFormat::ElementType parseType(const std::string &type)
  {
    if(type == "Container")return UIFormat::ElementType::CONTAINER;
    if(type == "Image")return UIFormat::ElementType::IMAGE;
    if(type == "Text")return UIFormat::ElementType::TEXT;
    if(type == "Button")return UIFormat::ElementType::BUTTON;
    if(type == "TextInput")return UIFormat::ElementType::TEXT_INPUT;
    if(type == "ProgressBar")return UIFormat::ElementType::PROGRESS_BAR;
    throw std::runtime_error("Unknown UI element type: " + type);
  }

  UIFormat::TextAlign parseAlign(const std::string &align)
  {
    if(align == "left")return UIFormat::TextAlign::LEFT;
    if(align == "center")return UIFormat::TextAlign::CENTER;
    if(align == "right")return UIFormat::TextAlign::RIGHT;
    throw std::runtime_error("Unknown UI text alignment: " + align);
  }

  Project::AssetManagerEntry* resolveAsset(Project::Project &project, const nlohmann::json &reference)
  {
    auto &assets = project.getAssets();
    if(reference.is_number_unsigned() || reference.is_number_integer()) {
      return assets.getEntryByUUID(reference.get<uint64_t>());
    }
    if(!reference.is_string())return nullptr;

    std::string path = reference.get<std::string>();
    std::replace(path.begin(), path.end(), '\\', '/');
    if(path.starts_with("assets/"))path = path.substr(7);
    auto fullPath = fs::path{project.getPath()} / "assets" / path;
    if(auto entry = assets.getByPath(fullPath.string()))return entry;

    Project::AssetManagerEntry *found{};
    for(auto &typed : assets.getEntries()) {
      for(auto &entry : typed) {
        if(fs::path{entry.path}.filename() == fs::path{path}.filename()) {
          if(found)return nullptr; // ambiguous basename
          found = assets.getEntryByUUID(entry.getUUID());
        }
      }
    }
    return found;
  }

  uint16_t addString(std::vector<uint8_t> &strings, std::unordered_map<std::string, uint16_t> &offsets,
                     const nlohmann::json &value)
  {
    if(!value.is_string())return UIFormat::NO_INDEX;
    auto text = value.get<std::string>();
    auto existing = offsets.find(text);
    if(existing != offsets.end())return existing->second;
    if(strings.size() + text.size() + 1 > UIFormat::NO_INDEX) {
      throw std::runtime_error("UI string table exceeds 65534 bytes");
    }
    uint16_t offset = static_cast<uint16_t>(strings.size());
    offsets[text] = offset;
    strings.insert(strings.end(), text.begin(), text.end());
    strings.push_back(0);
    return offset;
  }

  void flatten(const nlohmann::json &element, uint16_t parent, std::vector<SourceElement> &out)
  {
    if(!element.is_object())throw std::runtime_error("UI element must be an object");
    if(out.size() >= UIFormat::MAX_ELEMENTS)throw std::runtime_error("UI document exceeds 256 elements");
    uint16_t index = static_cast<uint16_t>(out.size());
    out.push_back({element, parent});
    auto children = element.value("children", nlohmann::json::array());
    if(!children.is_array())throw std::runtime_error("UI element children must be an array");
    for(const auto &child : children)flatten(child, index, out);
  }

  bool buildDocument(Project::Project &project, Build::SceneCtx &sceneCtx,
                     const Project::AssetManagerEntry &asset, const fs::path &outPath)
  {
    auto root = Utils::JSON::loadFile(asset.path);
    if(root.value("schema", std::string{}) != "bf64.ui" || root.value("version", 0) != UIFormat::VERSION) {
      throw std::runtime_error("unsupported schema/version");
    }
    const auto &canvas = root.at("canvas");
    auto widthValue = canvas.at("width").get<int32_t>();
    auto heightValue = canvas.at("height").get<int32_t>();
    if(widthValue < 1 || heightValue < 1 || widthValue > 640 || heightValue > 576) {
      throw std::runtime_error("canvas is outside the supported 1..640 by 1..576 range");
    }
    auto width = static_cast<uint16_t>(widthValue);
    auto height = static_cast<uint16_t>(heightValue);

    std::vector<SourceElement> source{};
    flatten(root.at("root"), UIFormat::NO_INDEX, source);

    std::unordered_map<std::string, uint16_t> idToIndex{};
    std::unordered_map<uint32_t, std::string> hashToId{};
    for(uint16_t i=0; i<source.size(); ++i) {
      auto id = source[i].doc.at("id").get<std::string>();
      if(id.empty() || idToIndex.contains(id))throw std::runtime_error("duplicate or empty element id: " + id);
      uint32_t hash = Utils::Hash::crc32(id);
      if(hashToId.contains(hash) && hashToId[hash] != id)throw std::runtime_error("element hash collision: " + id);
      idToIndex[id] = i;
      hashToId[hash] = id;
    }

    std::vector<uint8_t> strings{0};
    std::unordered_map<std::string, uint16_t> stringOffsets{{"", 0}};
    std::vector<UIFormat::Element> elements{};
    elements.reserve(source.size());

    for(const auto &sourceElement : source)
    {
      const auto &doc = sourceElement.doc;
      UIFormat::Element element{};
      auto id = doc.at("id").get<std::string>();
      element.id = Utils::Hash::crc32(id);
      element.parent = sourceElement.parent;
      element.type = parseType(doc.at("type").get<std::string>());
      if(doc.value("visible", true))element.flags |= UIFormat::VISIBLE;
      if(doc.value("enabled", true))element.flags |= UIFormat::ENABLED;
      if(element.type == UIFormat::ElementType::BUTTON || element.type == UIFormat::ElementType::TEXT_INPUT) {
        element.flags |= UIFormat::FOCUSABLE;
      }
      if(element.type == UIFormat::ElementType::TEXT_INPUT && doc.value("submitOnStart", true)) {
        element.flags |= UIFormat::SUBMIT_ON_START;
      }

      const auto &layout = doc.at("layout");
      const auto &anchors = layout.at("anchors");
      const auto &offsets = layout.at("offsets");
      if(!anchors.is_array() || anchors.size() != 4 || !offsets.is_array() || offsets.size() != 4) {
        throw std::runtime_error("UI anchors and offsets require four values");
      }
      for(uint32_t i=0; i<4; ++i) {
        element.anchors[i] = quantAnchor(anchors[i].get<float>());
        element.offsets[i] = checkedOffset(offsets[i]);
      }

      const auto style = doc.value("style", nlohmann::json::object());
      element.color = parseColor(style, "color", 0x00000000);
      element.textColor = parseColor(style, "textColor", 0xFFFFFFFF);
      element.focusColor = parseColor(style, "focusColor", 0xE0B030FF);
      element.align = parseAlign(doc.value("align", std::string{"left"}));
      auto fit = doc.value("fit", std::string{"stretch"});
      if(fit == "native")element.fit = UIFormat::ImageFit::NATIVE;
      else if(fit == "stretch")element.fit = UIFormat::ImageFit::STRETCH;
      else throw std::runtime_error("Unknown UI image fit: " + fit);

      if(element.type == UIFormat::ElementType::IMAGE) {
        auto image = resolveAsset(project, doc.at("asset"));
        if(!image || image->type != Project::FileType::IMAGE)throw std::runtime_error("image asset not found for " + id);
        if(image->isExcluded())throw std::runtime_error("image asset is excluded from builds for " + id);
        element.assetIndex = sceneCtx.assetUUIDToIdx.at(image->getUUID());
      }
      if(element.type == UIFormat::ElementType::TEXT || element.type == UIFormat::ElementType::BUTTON ||
         element.type == UIFormat::ElementType::TEXT_INPUT) {
        auto font = resolveAsset(project, doc.at("font"));
        if(!font || font->type != Project::FileType::FONT)throw std::runtime_error("font asset not found for " + id);
        if(font->isExcluded())throw std::runtime_error("font asset is excluded from builds for " + id);
        uint32_t fontId = font->conf.fontId.value;
        if(fontId == 0 || fontId >= 16)throw std::runtime_error("UI fonts must use an auto-load ID from 1 to 15");
        element.assetIndex = static_cast<uint16_t>(fontId);
      }

      if(doc.contains("text"))element.textOffset = addString(strings, stringOffsets, doc["text"]);
      if(doc.contains("placeholder"))element.altTextOffset = addString(strings, stringOffsets, doc["placeholder"]);
      if(doc.contains("charset"))element.charsetOffset = addString(strings, stringOffsets, doc["charset"]);
      if(element.type == UIFormat::ElementType::TEXT_INPUT) {
        element.textOffset = addString(strings, stringOffsets, doc.value("value", std::string{}));
        int maxLength = doc.value("maxLength", 32);
        if(maxLength < 1 || maxLength > 256)throw std::runtime_error("TextInput maxLength must be from 1 to 256");
        element.maxLength = static_cast<uint16_t>(maxLength);
      }

      auto focus = doc.value("focus", nlohmann::json::object());
      constexpr std::array<const char*, 4> DIRS{"up", "down", "left", "right"};
      for(uint32_t i=0; i<DIRS.size(); ++i) {
        element.focus[i] = UIFormat::NO_INDEX;
        if(focus.contains(DIRS[i])) {
          auto target = focus[DIRS[i]].get<std::string>();
          if(!idToIndex.contains(target))throw std::runtime_error("focus target not found: " + target);
          auto targetIndex = idToIndex[target];
          auto targetType = parseType(source[targetIndex].doc.at("type").get<std::string>());
          if(targetType != UIFormat::ElementType::BUTTON && targetType != UIFormat::ElementType::TEXT_INPUT) {
            throw std::runtime_error("focus target is not focusable: " + target);
          }
          element.focus[i] = targetIndex;
        }
      }

      if(element.type == UIFormat::ElementType::PROGRESS_BAR) {
        int maximum = doc.value("max", 100);
        int value = doc.value("value", maximum);
        if(maximum < 1 || maximum > 0xFFFF || value < 0 || value > maximum) {
          throw std::runtime_error("ProgressBar value/max must satisfy 0 <= value <= max <= 65535");
        }
        element.assetIndex = static_cast<uint16_t>(value);
        element.textOffset = static_cast<uint16_t>(maximum);
        element.textColor = parseColor(style, "fillColor", 0x40C060FF);
        element.thresholdColor1 = element.textColor;
        element.thresholdColor2 = element.textColor;

        auto thresholds = doc.value("thresholds", nlohmann::json::array());
        if(!thresholds.is_array() || thresholds.size() > 3) {
          throw std::runtime_error("ProgressBar supports at most three thresholds");
        }
        int previous = -1;
        for(size_t thresholdIndex=0; thresholdIndex<thresholds.size(); ++thresholdIndex) {
          const auto &threshold = thresholds[thresholdIndex];
          int thresholdMax = threshold.at("max").get<int>();
          if(thresholdMax < 0 || thresholdMax > maximum || thresholdMax <= previous) {
            throw std::runtime_error("ProgressBar thresholds must be strictly ascending in 0..max");
          }
          previous = thresholdMax;
          if(thresholdIndex == 0)element.altTextOffset = static_cast<uint16_t>(thresholdMax);
          else if(thresholdIndex == 1)element.charsetOffset = static_cast<uint16_t>(thresholdMax);
          else element.maxLength = static_cast<uint16_t>(thresholdMax);
          uint32_t thresholdColor = parseColor(threshold, "color", element.textColor);
          if(thresholdIndex == 0)element.focusColor = thresholdColor;
          else if(thresholdIndex == 1)element.thresholdColor1 = thresholdColor;
          else element.thresholdColor2 = thresholdColor;
        }
        element.focus[0] = static_cast<uint16_t>(thresholds.size());
      }
      elements.push_back(element);
    }

    Utils::BinaryFile output{};
    output.write<uint32_t>(UIFormat::MAGIC);
    output.write<uint16_t>(UIFormat::VERSION);
    output.write<uint16_t>(elements.size());
    output.write<uint16_t>(width);
    output.write<uint16_t>(height);
    output.write<uint32_t>(sizeof(UIFormat::Header));
    output.write<uint32_t>(sizeof(UIFormat::Header) + elements.size() * sizeof(UIFormat::Element));
    output.write<uint32_t>(strings.size());

    for(const auto &element : elements) {
      output.write<uint32_t>(element.id);
      output.write<uint16_t>(element.parent);
      output.write<uint8_t>(static_cast<uint8_t>(element.type));
      output.write<uint8_t>(element.flags);
      for(auto value : element.anchors)output.write<int16_t>(value);
      for(auto value : element.offsets)output.write<int16_t>(value);
      output.write<uint32_t>(element.color);
      output.write<uint32_t>(element.textColor);
      output.write<uint32_t>(element.focusColor);
      output.write<uint16_t>(element.assetIndex);
      output.write<uint16_t>(element.textOffset);
      output.write<uint16_t>(element.altTextOffset);
      output.write<uint16_t>(element.charsetOffset);
      output.write<uint16_t>(element.maxLength);
      for(auto value : element.focus)output.write<uint16_t>(value);
      output.write<uint8_t>(static_cast<uint8_t>(element.align));
      output.write<uint8_t>(static_cast<uint8_t>(element.fit));
      output.write<uint32_t>(element.thresholdColor1);
      output.write<uint32_t>(element.thresholdColor2);
    }
    output.writeArray(strings.data(), strings.size());
    output.writeToFile(outPath);
    return true;
  }
}

bool Build::buildUIAssets(Project::Project &project, SceneCtx &sceneCtx)
{
  const auto &documents = project.getAssets().getTypeEntries(Project::FileType::UI_DOCUMENT);
  for(const auto &document : documents)
  {
    if(document.isExcluded())continue;
    auto outPath = fs::path{project.getPath()} / document.outPath;
    fs::create_directories(outPath.parent_path());
    sceneCtx.files.push_back(Utils::FS::toUnixPath(document.outPath));
    // UI output embeds asset indices and font slots, so it depends on the full asset table
    // and sidecars in addition to the .bfui mtime. Rebuild deterministically every time.
    try {
      buildDocument(project, sceneCtx, document, outPath);
    } catch(const std::exception &error) {
      Utils::Logger::log("UI build failed for " + document.path + ": " + error.what(), Utils::Logger::LEVEL_ERROR);
      return false;
    }
  }
  return true;
}
