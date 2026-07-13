/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "../components.h"

#include <algorithm>

#include "../../../context.h"
#include "../../../editor/imgui/helper.h"
#include "../../../utils/binaryFile.h"
#include "../../../utils/json.h"
#include "../../../utils/jsonBuilder.h"
#include "../../../utils/logger.h"
#include "../../assetManager.h"

namespace Project::Component::UI
{
  struct Data
  {
    PROP_U64(document);
    PROP_U32(layer);
    PROP_BOOL(active);
    PROP_S32(displayTarget);
    PROP_U32(displayPlayer);
    PROP_U32(inputPlayerMask);
  };

  std::shared_ptr<void> init(Object &obj)
  {
    auto data = std::make_shared<Data>();
    data->active.value = true;
    data->inputPlayerMask.value = 1;
    return data;
  }

  nlohmann::json serialize(const Entry &entry)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    return Utils::JSON::Builder{}
      .set(data.document)
      .set(data.layer)
      .set(data.active)
      .set(data.displayTarget)
      .set(data.displayPlayer)
      .set(data.inputPlayerMask)
      .doc;
  }

  std::shared_ptr<void> deserialize(nlohmann::json &doc)
  {
    auto data = std::make_shared<Data>();
    Utils::JSON::readProp(doc, data->document);
    Utils::JSON::readProp(doc, data->layer);
    Utils::JSON::readProp(doc, data->active, true);
    Utils::JSON::readProp(doc, data->displayTarget, 0);
    Utils::JSON::readProp(doc, data->displayPlayer, 0u);
    Utils::JSON::readProp(doc, data->inputPlayerMask, 1u);
    return data;
  }

  void build(Object &obj, Entry &entry, Build::SceneCtx &ctx)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    auto uuid = data.document.resolve(obj);
    auto found = ctx.assetUUIDToIdx.find(uuid);
    uint16_t assetIndex = 0xFFFF;
    if(found == ctx.assetUUIDToIdx.end()) {
      Utils::Logger::log("UI component document UUID not found: " + std::to_string(uuid), Utils::Logger::LEVEL_ERROR);
    } else {
      assetIndex = static_cast<uint16_t>(found->second);
    }
    uint32_t layer = data.layer.resolve(obj);
    uint32_t layerCount = ctx.scene ? ctx.scene->conf.layers2D.size() : 1;
    if(layer >= layerCount) {
      Utils::Logger::log("UI component 2D layer is outside the scene layer range; using layer 0", Utils::Logger::LEVEL_ERROR);
      layer = 0;
    }
    ctx.fileObj.write<uint16_t>(assetIndex);
    ctx.fileObj.write<uint8_t>(static_cast<uint8_t>(layer));
    ctx.fileObj.write<uint8_t>(data.active.resolve(obj) ? 1 : 0);
    ctx.fileObj.write<uint8_t>(static_cast<uint8_t>(std::clamp(data.displayTarget.resolve(obj), 0, 1)));
    ctx.fileObj.write<uint8_t>(static_cast<uint8_t>(std::min<uint32_t>(data.displayPlayer.resolve(obj), 3)));
    ctx.fileObj.write<uint8_t>(static_cast<uint8_t>(data.inputPlayerMask.resolve(obj) & 0x1F));
    ctx.fileObj.write<uint8_t>(0);
  }

  void draw(Object &obj, Entry &entry)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    if(!ImTable::start("Comp", &obj))return;
    ImTable::add("Name", entry.name);
    auto &documents = ctx.project->getAssets().getTypeEntries(FileType::UI_DOCUMENT);
    ImTable::addAssetVecComboBox("Document", documents, data.document.resolve(obj), [](auto){});
    ImTable::addObjProp("2D Layer", data.layer);
    ImTable::addObjProp("Active", data.active);
    ImTable::addComboBox("Display Target", data.displayTarget.resolve(obj), {"Shared / Fullscreen", "Player Viewport"});
    if(data.displayTarget.resolve(obj) == 1)ImTable::addObjProp("Display Player (0-3)", data.displayPlayer);
    auto &inputOwner = data.inputPlayerMask.resolve(obj);
    int owner = inputOwner == 0x01 ? 0 : inputOwner == 0x02 ? 1 : inputOwner == 0x04 ? 2
      : inputOwner == 0x08 ? 3 : inputOwner == 0x10 ? 4 : inputOwner == 0x0F ? 5 : 6;
    ImTable::addComboBox("Input Owner", owner, {
      "Port 1", "Port 2", "Port 3", "Port 4", "Host", "Any", "Disabled"
    });
    constexpr uint32_t OWNER_VALUES[7]{0x01, 0x02, 0x04, 0x08, 0x10, 0x0F, 0x00};
    inputOwner = OWNER_VALUES[std::clamp(owner, 0, 6)];
    ImTable::end();
  }
}
