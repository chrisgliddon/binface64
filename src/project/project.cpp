/**
* @copyright 2025 - Max Bebök
* @license MIT
*/
#include "project.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <string>

#include "../build/projectBuilder.h"
#include "../utils/fs.h"
#include "../utils/hash.h"
#include "../utils/json.h"
#include "../utils/jsonBuilder.h"
#include "../utils/string.h"
#include "../context.h"
#include "graph/nodeRegistry.h"

namespace
{
  /**
   * Recursively copy changed files from src to dst if file is different.
   * This is used to make sure updated engine code is put in the project.
   * Doing so each time would force a recompile, so the content is checked.
   *
   * @returns amount of files copied
   */
  int copyChangedEngineFiles(const fs::path& src, const fs::path& dst) {

    if (!fs::exists(src)) return 0;
    if (fs::is_directory(src)) {
      fs::create_directories(dst);
      int count = 0;
      for (const auto& entry : fs::directory_iterator(src)) {
        count += copyChangedEngineFiles(entry.path(), dst / entry.path().filename());
      }
      return count;
    }
    std::string srcHash{};
    std::string dstHash{};

    // Read destination file if exists
    if (fs::exists(dst)) {
      std::ifstream ifs(dst, std::ios::binary);
      dstHash = std::string((std::istreambuf_iterator(ifs)), std::istreambuf_iterator<char>());
      {
        std::ifstream ifsSrc(src, std::ios::binary);
        srcHash = std::string((std::istreambuf_iterator(ifsSrc)), std::istreambuf_iterator<char>());
      }
    }

    if (dstHash.empty() || srcHash != dstHash) {
      //printf("Copying updated engine file: %s\n", src.string().c_str());
      fs::copy_file(src, dst, fs::copy_options::overwrite_existing);
      return (dst.extension() == ".h");
    }
    return 0;
  }

  nlohmann::json romHeaderToJson(const Project::RomHeaderConf &h) {
    return {
      {"category", h.category}, {"region", h.region}, {"saveType", h.saveType},
      {"regionFree", h.regionFree}, {"rtc", h.rtc},
      {"controllers", {h.controllers[0], h.controllers[1], h.controllers[2], h.controllers[3]}},
    };
  }

  void romHeaderFromJson(const nlohmann::json &j, Project::RomHeaderConf &h) {
    h.category = j.value("category", 0);
    h.region = j.value("region", 0);
    h.saveType = j.value("saveType", 0);
    h.regionFree = j.value("regionFree", true);
    h.rtc = j.value("rtc", false);
    auto ctrl = j.value("controllers", nlohmann::json::array());
    for (int i = 0; i < 4; ++i) h.controllers[i] = (i < (int)ctrl.size()) ? ctrl[i].get<int>() : 0;
  }

  nlohmann::json metaLangToJson(const Project::MetaLang &l) {
    return {
      {"lang", l.lang}, {"name", l.name}, {"author", l.author}, {"releaseDate", l.releaseDate},
      {"osiLicense", l.osiLicense}, {"website", l.website}, {"shortDesc", l.shortDesc},
      {"longDesc", l.longDesc}, {"ageRating", l.ageRating}, {"screenshots", l.screenshots},
      {"boxFront", l.boxFront}, {"boxBack", l.boxBack}, {"boxTop", l.boxTop},
      {"boxBottom", l.boxBottom}, {"boxLeft", l.boxLeft}, {"boxRight", l.boxRight},
      {"cartFront", l.cartFront}, {"cartBack", l.cartBack},
    };
  }

  Project::MetaLang metaLangFromJson(const nlohmann::json &j) {
    Project::MetaLang l{};
    l.lang = j.value("lang", "");
    l.name = j.value("name", "");
    l.author = j.value("author", "");
    l.releaseDate = j.value("releaseDate", "");
    l.osiLicense = j.value("osiLicense", "");
    l.website = j.value("website", "");
    l.shortDesc = j.value("shortDesc", "");
    l.longDesc = j.value("longDesc", "");
    l.ageRating = j.value("ageRating", 0);
    l.screenshots = j.value("screenshots", std::vector<uint64_t>{});
    l.boxFront = j.value("boxFront", 0ull); l.boxBack = j.value("boxBack", 0ull);
    l.boxTop = j.value("boxTop", 0ull); l.boxBottom = j.value("boxBottom", 0ull);
    l.boxLeft = j.value("boxLeft", 0ull); l.boxRight = j.value("boxRight", 0ull);
    l.cartFront = j.value("cartFront", 0ull); l.cartBack = j.value("cartBack", 0ull);
    return l;
  }

  nlohmann::json metadataToJson(const Project::MetadataConf &m) {
    auto langs = nlohmann::json::array();
    for (const auto &l : m.langs) langs.push_back(metaLangToJson(l));
    return {{"enabled", m.enabled}, {"langs", langs}};
  }

  void metadataFromJson(const nlohmann::json &j, Project::MetadataConf &m) {
    m.enabled = j.value("enabled", false);
    m.langs.clear();
    for (const auto &lj : j.value("langs", nlohmann::json::array())) {
      m.langs.push_back(metaLangFromJson(lj));
    }
    if (m.langs.empty()) m.langs.push_back(Project::MetaLang{}); // always keep a default entry
  }

  nlohmann::json inputToJson(const Project::InputConf &input) {
    auto actions = nlohmann::json::array();
    for(const auto &action : input.actions) {
      auto bindings = nlohmann::json::array();
      for(const auto &binding : action.bindings)bindings.push_back({
        {"buttons", binding.buttons}, {"chord", binding.chord}
      });
      actions.push_back({{"name", action.name}, {"bindings", bindings}});
    }
    auto axes = nlohmann::json::array();
    for(const auto &axis : input.axes) {
      auto bindings = nlohmann::json::array();
      for(const auto &binding : axis.bindings)bindings.push_back({
        {"source", binding.source}, {"scale", binding.scale}, {"deadZone", binding.deadZone}
      });
      axes.push_back({{"name", axis.name}, {"bindings", bindings}});
    }
    return {{"deadZone", input.deadZone}, {"actions", actions}, {"axes", axes}};
  }

  void inputFromJson(const nlohmann::json &j, Project::InputConf &input) {
    input = {};
    input.deadZone = j.value("deadZone", 0.18f);
    for(const auto &item : j.value("actions", nlohmann::json::array())) {
      Project::InputAction action{};
      action.name = item.value("name", "");
      for(const auto &binding : item.value("bindings", nlohmann::json::array())) {
        action.bindings.push_back({
          static_cast<std::uint16_t>(binding.value("buttons", 0u)),
          static_cast<std::uint16_t>(binding.value("chord", 0u))
        });
      }
      input.actions.push_back(std::move(action));
    }
    for(const auto &item : j.value("axes", nlohmann::json::array())) {
      Project::InputAxis axis{};
      axis.name = item.value("name", "");
      for(const auto &binding : item.value("bindings", nlohmann::json::array())) {
        axis.bindings.push_back({
          binding.value("source", "none"), binding.value("scale", 1.0f), binding.value("deadZone", 0.0f)
        });
      }
      input.axes.push_back(std::move(axis));
    }
  }

  nlohmann::json multiplayerToJson(const Project::MultiplayerConf &multiplayer) {
    auto controllers = nlohmann::json::array();
    for(const auto &controller : multiplayer.controllers)controllers.push_back({
      {"name", controller.name}, {"rumble", controller.rumble}
    });
    return {
      {"controllers", controllers},
      {"enabledPortMask", multiplayer.enabledPortMask},
      {"hostPort", multiplayer.hostPort},
      {"targetRdramMB", multiplayer.targetRdramMB}
    };
  }

  void multiplayerFromJson(const nlohmann::json &j, Project::MultiplayerConf &multiplayer) {
    multiplayer = {};
    const auto controllers = j.value("controllers", nlohmann::json::array());
    for(std::size_t index=0; index<multiplayer.controllers.size() && index<controllers.size(); ++index) {
      multiplayer.controllers[index].name = controllers[index].value("name", "Player " + std::to_string(index+1));
      multiplayer.controllers[index].rumble = controllers[index].value("rumble", true);
    }
    multiplayer.enabledPortMask = static_cast<std::uint8_t>(j.value("enabledPortMask", 0x0F) & 0x0F);
    multiplayer.hostPort = static_cast<std::uint8_t>(std::clamp(j.value("hostPort", 0), 0, 3));
    multiplayer.targetRdramMB = j.value("targetRdramMB", 4);
  }
}

std::string Project::ProjectConf::serialize() const {
  return Utils::JSON::Builder{}
    .set("name", name)
    .set("romName", romName)
    .set("pathEmu", pathEmu)
    .set("pathN64Inst", pathN64Inst)
    .set("editorVersion", editorVersion)
    .set("romHeader", romHeaderToJson(romHeader))
    .set("metadata", metadataToJson(metadata))
    .set("input", inputToJson(input))
    .set("multiplayer", multiplayerToJson(multiplayer))
    .set("sceneIdOnBoot", sceneIdOnBoot)
    .set("sceneIdOnReset", sceneIdOnReset)
    .set("sceneIdLastOpened", sceneIdLastOpened)
    .set("debugMenu", debugMenu)
    .set("assetExclusions", assetExclusions)
    .set("collLayer0", collLayerNames[0])
    .set("collLayer1", collLayerNames[1])
    .set("collLayer2", collLayerNames[2])
    .set("collLayer3", collLayerNames[3])
    .set("collLayer4", collLayerNames[4])
    .set("collLayer5", collLayerNames[5])
    .set("collLayer6", collLayerNames[6])
    .set("collLayer7", collLayerNames[7])
    .toString();
}

void Project::Project::deserialize(const nlohmann::json &doc) {
  conf.name = doc.value("name", "New Project");
  conf.romName = doc.value("romName", "pyrite64");
  conf.pathEmu = doc.value("pathEmu", "ares");
  conf.pathN64Inst = doc.value("pathN64Inst", "");
  conf.editorVersion = doc.value("editorVersion", "");
  romHeaderFromJson(doc.value("romHeader", nlohmann::json::object()), conf.romHeader);
  metadataFromJson(doc.value("metadata", nlohmann::json::object()), conf.metadata);
  inputFromJson(doc.value("input", nlohmann::json::object()), conf.input);
  multiplayerFromJson(doc.value("multiplayer", nlohmann::json::object()), conf.multiplayer);
  conf.sceneIdOnBoot = doc.value("sceneIdOnBoot", 1);
  conf.sceneIdOnReset = doc.value("sceneIdOnReset", 1);
  conf.sceneIdLastOpened = doc.value("sceneIdLastOpened", 1);
  conf.debugMenu = doc.value("debugMenu", true);
  conf.assetExclusions = doc.value("assetExclusions", std::vector<std::string>{});

  for(int i=0; i<8; ++i) {
    conf.collLayerNames[i] = doc.value("collLayer" + std::to_string(i), "Layer " + std::to_string(i));
  }
}

Project::Project::Project(const std::string &p64projPath)
  : pathConfig{p64projPath}
{
  path = fs::path(p64projPath).parent_path().string();

  auto configJSON = Utils::JSON::loadFile(pathConfig);
  if (configJSON.empty()) {
    throw std::runtime_error("Not a valid project!");
  }

  // ensure relevant directories and files exist + some basic self-repair
  fs::path f{path};
  fs::create_directories(f);
  fs::create_directories(f / "data");
  fs::create_directories(f / "data" / "scenes");
  fs::create_directories(f / "assets");
  fs::create_directories(f / "assets" / "p64");
  fs::create_directories(f / "src");
  fs::create_directories(f / "src" / "p64");
  fs::create_directories(f / "src" / "user");

  Utils::FS::ensureFile(f / ".gitignore", "data/build/baseGitignore");
  // ensureFile only writes a missing file, so older projects keep their old .gitignore.
  // Make sure the generated metadata/ dir is ignored by appending the entry if absent.
  {
    auto gitignorePath = f / ".gitignore";
    auto content = Utils::FS::loadTextFile(gitignorePath);
    bool hasEntry = false;
    for (auto &line : Utils::splitString(content, '\n')) {
      if (!line.empty() && line.back() == '\r') line.pop_back();
      if (line == "metadata") { hasEntry = true; break; }
    }
    if (!hasEntry) {
      if (!content.empty() && content.back() != '\n') content += "\n";
      content += "metadata\n";
      Utils::FS::saveTextFile(gitignorePath, content);
    }
  }
  Utils::FS::ensureFile(f / "Makefile.custom", "data/build/baseMakefile.custom");
  Utils::FS::ensureFile(f / "assets" / "p64" / "font.ia4.png", "data/build/assets/font.ia4.png");

  deserialize(configJSON);
  savedState = conf.serialize();

  int verCmp = conf.editorVersion.empty() ? -1 : Utils::compareSemVer(conf.editorVersion, PYRITE_VERSION);
  if (verCmp < 0) {
    printf("Project saved with older editor version (%s < %s), forcing clean\n",
      conf.editorVersion.empty() ? "none" : conf.editorVersion.c_str(), PYRITE_VERSION);
    Build::cleanProject(*this, {
      .code = true,
      .assets = true,
      .engine = true,
      .engineSrc = true,
    });
  } else if (verCmp > 0) {
    openedFromNewerVersion = true;
    printf("Warning: project saved with newer editor version (%s > %s)\n",
      conf.editorVersion.c_str(), PYRITE_VERSION);
  }

  // Load the graph node definitions for this project (builtins + <project>/nodes/*.js).
  // Done here so every entry point (editor and CLI build) gets the same set.
  ::Project::Graph::Node::reloadSpecs(path + "/nodes");

  //auto t = SDL_GetTicksNS();
  if(copyChangedEngineFiles("n64/engine", f / "engine") > 0)
  {
    printf("New Engine files copied, force clean build build\n");
    Build::cleanProject(*this, {
      .code = true,
      .assets = false,
      .engine = true,
    });
  }
  //t = SDL_GetTicksNS() - t;
  //printf("Engine files sync took %.2f ms\n", t / 1e6);


  assets.reload();
  scenes.reload();
}

void Project::Project::saveConfig()
{
  conf.editorVersion = PYRITE_VERSION;
  openedFromNewerVersion = false;
  auto serializedConfig = conf.serialize();
  Utils::FS::saveTextFile(pathConfig, serializedConfig);
  savedState = serializedConfig;
}

void Project::Project::save() {
  saveConfig();
  assets.save();
  scenes.save();
  markSaved();
}
