/**
 * @copyright 2026 - BF64 contributors
 * @license MIT
 */
#include "../components.h"

#include <algorithm>

#include "../../../context.h"
#include "../../../editor/imgui/helper.h"
#include "../../../editor/pages/parts/viewport3D.h"
#include "../../../utils/binaryFile.h"
#include "../../../utils/colors.h"
#include "../../../utils/json.h"
#include "../../../utils/jsonBuilder.h"
#include "../../../utils/logger.h"
#include "../../../utils/meshGen.h"
#include "../../assetManager.h"

namespace Project::Component::Audio3D
{
  struct Data
  {
    PROP_U64(audioUUID);
    PROP_FLOAT(volume);
    PROP_BOOL(loop);
    PROP_BOOL(autoPlay);
    PROP_FLOAT(minDistance);
    PROP_FLOAT(maxDistance);
    PROP_FLOAT(rolloff);
    PROP_FLOAT(pitch);
  };

  std::shared_ptr<void> init(Object &)
  {
    auto data = std::make_shared<Data>();
    data->volume.value = 1.0f;
    data->minDistance.value = 50.0f;
    data->maxDistance.value = 1000.0f;
    data->rolloff.value = 1.0f;
    data->pitch.value = 1.0f;
    return data;
  }

  nlohmann::json serialize(const Entry &entry)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    return Utils::JSON::Builder{}
      .set(data.audioUUID)
      .set(data.volume)
      .set(data.loop)
      .set(data.autoPlay)
      .set(data.minDistance)
      .set(data.maxDistance)
      .set(data.rolloff)
      .set(data.pitch)
      .doc;
  }

  std::shared_ptr<void> deserialize(nlohmann::json &doc)
  {
    auto data = std::make_shared<Data>();
    Utils::JSON::readProp(doc, data->audioUUID);
    Utils::JSON::readProp(doc, data->volume, 1.0f);
    Utils::JSON::readProp(doc, data->loop);
    Utils::JSON::readProp(doc, data->autoPlay);
    Utils::JSON::readProp(doc, data->minDistance, 50.0f);
    Utils::JSON::readProp(doc, data->maxDistance, 1000.0f);
    Utils::JSON::readProp(doc, data->rolloff, 1.0f);
    Utils::JSON::readProp(doc, data->pitch, 1.0f);
    return data;
  }

  void build(Object &obj, Entry &entry, Build::SceneCtx &ctx)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    const auto assetIt = ctx.assetUUIDToIdx.find(data.audioUUID.value);
    uint16_t assetId = 0xDEAD;
    if(assetIt == ctx.assetUUIDToIdx.end()) {
      Utils::Logger::log(
        "Component Audio3D: audio UUID not found: " + std::to_string(data.audioUUID.value),
        Utils::Logger::LEVEL_ERROR
      );
    } else {
      assetId = assetIt->second;
    }

    uint8_t flags = 0;
    if(data.loop.resolve(obj))flags |= 1 << 0;
    if(data.autoPlay.resolve(obj))flags |= 1 << 1;
    const float volume = std::clamp(data.volume.resolve(obj), 0.0f, 1.0f);
    const float minDistance = std::max(0.0f, data.minDistance.resolve(obj));
    const float maxDistance = std::max(minDistance, data.maxDistance.resolve(obj));
    const float rolloff = std::max(0.01f, data.rolloff.resolve(obj));
    const float pitch = std::clamp(data.pitch.resolve(obj), 0.125f, 8.0f);

    ctx.fileObj.write<uint16_t>(assetId);
    ctx.fileObj.write<uint16_t>(static_cast<uint16_t>(volume * 65535.0f));
    ctx.fileObj.write<float>(minDistance);
    ctx.fileObj.write<float>(maxDistance);
    ctx.fileObj.write<float>(rolloff);
    ctx.fileObj.write<uint16_t>(static_cast<uint16_t>(pitch * 4096.0f));
    ctx.fileObj.write<uint8_t>(flags);
    ctx.fileObj.write<uint8_t>(0);
  }

  void draw(Object &obj, Entry &entry)
  {
    auto &data = *static_cast<Data*>(entry.data.get());
    if(ImTable::start("Comp", &obj)) {
      ImTable::add("Name", entry.name);
      auto audio = ctx.project->getAssets().getTypeEntries(FileType::AUDIO);
      ImTable::addAssetVecComboBox("Audio", audio, data.audioUUID.resolve(obj), [](auto){});
      ImTable::addObjProp("Volume", data.volume);
      ImTable::addObjProp("Loop", data.loop);
      ImTable::addObjProp("Auto-Play", data.autoPlay);
      ImTable::addObjProp("Min Distance", data.minDistance);
      ImTable::addObjProp("Max Distance", data.maxDistance);
      ImTable::addObjProp("Rolloff", data.rolloff);
      ImTable::addObjProp("Pitch", data.pitch);
      ImTable::end();
    }
  }

  void draw3D(Object &obj, Entry &, Editor::Viewport3D &vp, SDL_GPUCommandBuffer*, SDL_GPURenderPass*)
  {
    glm::u8vec4 color{0xFF};
    if(ctx.isObjectSelected(obj.uuid))color = Utils::Colors::kSelectionTint;
    Utils::Mesh::addSprite(*vp.getSprites(), obj.pos.resolve(obj.propOverrides), obj.uuid, 4, color);
  }
}
