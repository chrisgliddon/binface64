/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "../components.h"

#include <algorithm>

#include "../../../editor/imgui/helper.h"
#include "../../../utils/binaryFile.h"
#include "../../../utils/json.h"
#include "../../../utils/jsonBuilder.h"

namespace Project::Component::PlayerSpawn
{
  struct Data
  {
    PROP_S32(target);
    PROP_U32(index);
  };

  std::shared_ptr<void> init(Object&)
  {
    return std::make_shared<Data>();
  }

  nlohmann::json serialize(const Entry &entry)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    return Utils::JSON::Builder{}.set(data.target).set(data.index).doc;
  }

  std::shared_ptr<void> deserialize(nlohmann::json &doc)
  {
    auto data = std::make_shared<Data>();
    Utils::JSON::readProp(doc, data->target, 0);
    Utils::JSON::readProp(doc, data->index, 0u);
    return data;
  }

  void build(Object &object, Entry &entry, Build::SceneCtx &ctx)
  {
    (void)ctx;
    auto &data = *static_cast<Data*>(entry.data.get());
    ctx.fileObj.write<std::uint8_t>(static_cast<std::uint8_t>(std::clamp(data.target.resolve(object), 0, 2)));
    ctx.fileObj.write<std::uint8_t>(static_cast<std::uint8_t>(std::min<std::uint32_t>(data.index.resolve(object), 255)));
    ctx.fileObj.write<std::uint16_t>(0);
  }

  void draw(Object &object, Entry &entry)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    if(!ImTable::start("Comp", &object))return;
    ImTable::add("Name", entry.name);
    ImTable::addComboBox("Target", data.target.resolve(object), {"Neutral", "Player", "Team"});
    ImTable::addObjProp("Player / Team", data.index);
    ImTable::end();
  }
}
