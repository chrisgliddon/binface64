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

namespace Project::Component::BlobShadow
{
  struct Data
  {
    PROP_FLOAT(radius);
    PROP_FLOAT(yOffset);
    PROP_VEC4(color);
    PROP_U32(layer);
  };

  std::shared_ptr<void> init(Object&)
  {
    auto data = std::make_shared<Data>();
    data->radius.value = 24.0f;
    data->yOffset.value = 1.0f;
    data->color.value = {0.04f, 0.04f, 0.06f, 0.44f};
    data->layer.value = 1;
    return data;
  }

  nlohmann::json serialize(const Entry &entry)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    return Utils::JSON::Builder{}.set(data.radius).set(data.yOffset).set(data.color).set(data.layer).doc;
  }

  std::shared_ptr<void> deserialize(nlohmann::json &doc)
  {
    auto data = std::make_shared<Data>();
    Utils::JSON::readProp(doc, data->radius, 24.0f);
    Utils::JSON::readProp(doc, data->yOffset, 1.0f);
    Utils::JSON::readProp(doc, data->color, glm::vec4{0.04f, 0.04f, 0.06f, 0.44f});
    Utils::JSON::readProp(doc, data->layer, 1u);
    return data;
  }

  void build(Object &object, Entry &entry, Build::SceneCtx &ctx)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    ctx.fileObj.write<float>(std::max(1.0f, data.radius.resolve(object)));
    ctx.fileObj.write<float>(data.yOffset.resolve(object));
    ctx.fileObj.writeRGBA(data.color.resolve(object));
    ctx.fileObj.write<std::uint8_t>(static_cast<std::uint8_t>(std::min<std::uint32_t>(data.layer.resolve(object), 255)));
    ctx.fileObj.write<std::uint8_t>(0); ctx.fileObj.write<std::uint8_t>(0); ctx.fileObj.write<std::uint8_t>(0);
  }

  void draw(Object &object, Entry &entry)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    if(!ImTable::start("Comp", &object))return;
    ImTable::add("Name", entry.name);
    ImTable::addObjProp("Radius", data.radius);
    ImTable::addObjProp("Ground Offset", data.yOffset);
    ImTable::addObjProp("Color", data.color);
    ImTable::addObjProp("3D Layer", data.layer);
    ImTable::end();
  }
}
