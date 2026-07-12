/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "../components.h"

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
  };

  std::shared_ptr<void> init(Object &obj)
  {
    auto data = std::make_shared<Data>();
    data->active.value = true;
    return data;
  }

  nlohmann::json serialize(const Entry &entry)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    return Utils::JSON::Builder{}
      .set(data.document)
      .set(data.layer)
      .set(data.active)
      .doc;
  }

  std::shared_ptr<void> deserialize(nlohmann::json &doc)
  {
    auto data = std::make_shared<Data>();
    Utils::JSON::readProp(doc, data->document);
    Utils::JSON::readProp(doc, data->layer);
    Utils::JSON::readProp(doc, data->active, true);
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
    ImTable::end();
  }
}
