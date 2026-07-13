/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "projectBuilder.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include "engine/include/input/input.h"
#include "../utils/binaryFile.h"
#include "../utils/fs.h"

namespace
{
  std::string identifier(const std::string &name)
  {
    std::string result{};
    result.reserve(name.size()+1);
    for(char value : name)result.push_back(std::isalnum(static_cast<unsigned char>(value)) ? value : '_');
    if(result.empty())result = "unnamed";
    if(std::isdigit(static_cast<unsigned char>(result.front())))result.insert(result.begin(), '_');
    return result;
  }

  P64::Input::AxisSource axisSource(const std::string &name)
  {
    if(name == "stick_x")return P64::Input::AxisSource::STICK_X;
    if(name == "stick_y")return P64::Input::AxisSource::STICK_Y;
    if(name == "dpad_x")return P64::Input::AxisSource::DPAD_X;
    if(name == "dpad_y")return P64::Input::AxisSource::DPAD_Y;
    if(name == "c_x")return P64::Input::AxisSource::C_X;
    if(name == "c_y")return P64::Input::AxisSource::C_Y;
    return P64::Input::AxisSource::NONE;
  }

  std::uint8_t quantizeUnit(float value)
  {
    return static_cast<std::uint8_t>(std::lround(std::clamp(value, 0.0f, 1.0f) * 255.0f));
  }
}

bool Build::buildInputConfig(Project::Project &project, SceneCtx &sceneCtx)
{
  const auto &input = project.conf.input;
  if(input.actions.size() > P64::Input::MAX_ACTIONS)throw std::runtime_error("Input map exceeds 32 actions");
  if(input.axes.size() > P64::Input::MAX_AXES)throw std::runtime_error("Input map exceeds 8 axes");
  if(input.deadZone < 0.0f || input.deadZone >= 1.0f)throw std::runtime_error("Input dead zone must be in [0, 1)");

  std::unordered_map<std::uint32_t, std::string> hashes{};
  std::unordered_map<std::string, std::string> identifiers{};
  std::unordered_set<std::string> actionNames{};
  std::unordered_set<std::string> axisNames{};
  auto validateName = [&](const std::string &name) {
    if(name.empty())throw std::runtime_error("Input action and axis names must not be empty");
    const auto hash = P64::Input::id(name);
    if(auto found = hashes.find(hash); found != hashes.end() && found->second != name) {
      throw std::runtime_error("Input hash collision between '" + found->second + "' and '" + name + "'");
    }
    hashes[hash] = name;
    const auto cppName = identifier(name);
    if(auto found = identifiers.find(cppName); found != identifiers.end() && found->second != name) {
      throw std::runtime_error("Input names '" + found->second + "' and '" + name + "' generate the same C++ identifier");
    }
    identifiers[cppName] = name;
  };
  for(const auto &action : input.actions) {
    validateName(action.name);
    if(!actionNames.insert(action.name).second)throw std::runtime_error("Duplicate input action '" + action.name + "'");
    if(action.bindings.empty() || action.bindings.size() > P64::Input::MAX_BINDINGS) {
      throw std::runtime_error("Input action '" + action.name + "' requires one to four bindings");
    }
    for(const auto &binding : action.bindings)if(binding.buttons == 0) {
      throw std::runtime_error("Input action '" + action.name + "' has an empty button binding");
    }
  }
  for(const auto &axis : input.axes) {
    validateName(axis.name);
    if(!axisNames.insert(axis.name).second)throw std::runtime_error("Duplicate input axis '" + axis.name + "'");
    if(axis.bindings.empty() || axis.bindings.size() > P64::Input::MAX_BINDINGS) {
      throw std::runtime_error("Input axis '" + axis.name + "' requires one to four bindings");
    }
    for(const auto &binding : axis.bindings) {
      if(axisSource(binding.source) == P64::Input::AxisSource::NONE) {
        throw std::runtime_error("Input axis '" + axis.name + "' has invalid source '" + binding.source + "'");
      }
      if(binding.scale < -1.0f || binding.scale > 1.0f) {
        throw std::runtime_error("Input axis '" + axis.name + "' scale must be in [-1, 1]");
      }
      if(binding.deadZone < 0.0f || binding.deadZone >= 1.0f) {
        throw std::runtime_error("Input axis '" + axis.name + "' dead zone must be in [0, 1)");
      }
    }
  }

  Utils::BinaryFile output{};
  output.write<std::uint32_t>(P64::Input::CONFIG_MAGIC);
  output.write<std::uint16_t>(P64::Input::CONFIG_VERSION);
  output.write<std::uint8_t>(static_cast<std::uint8_t>(input.actions.size()));
  output.write<std::uint8_t>(static_cast<std::uint8_t>(input.axes.size()));
  output.write<std::uint8_t>(quantizeUnit(input.deadZone));
  output.write<std::uint8_t>(project.conf.multiplayer.enabledPortMask & 0x0F);
  output.write<std::uint8_t>(std::min<std::uint8_t>(project.conf.multiplayer.hostPort, 3));
  std::uint8_t rumbleEnabledMask{};
  for(std::uint8_t player=0; player<project.conf.multiplayer.controllers.size(); ++player) {
    if(project.conf.multiplayer.controllers[player].rumble)rumbleEnabledMask |= 1u << player;
  }
  output.write<std::uint8_t>(rumbleEnabledMask);

  for(std::uint8_t slot=0; slot<P64::Input::MAX_ACTIONS; ++slot) {
    const Project::InputAction *action = slot < input.actions.size() ? &input.actions[slot] : nullptr;
    output.write<std::uint32_t>(action ? P64::Input::id(action->name) : 0);
    if(action && action->bindings.size() > P64::Input::MAX_BINDINGS) {
      throw std::runtime_error("Input action '" + action->name + "' exceeds four bindings");
    }
    for(std::uint8_t binding=0; binding<P64::Input::MAX_BINDINGS; ++binding) {
      const auto *value = action && binding < action->bindings.size() ? &action->bindings[binding] : nullptr;
      output.write<std::uint16_t>(value ? value->buttons : 0);
      output.write<std::uint16_t>(value ? value->chord : 0);
    }
  }

  for(std::uint8_t slot=0; slot<P64::Input::MAX_AXES; ++slot) {
    const Project::InputAxis *axis = slot < input.axes.size() ? &input.axes[slot] : nullptr;
    output.write<std::uint32_t>(axis ? P64::Input::id(axis->name) : 0);
    if(axis && axis->bindings.size() > P64::Input::MAX_BINDINGS) {
      throw std::runtime_error("Input axis '" + axis->name + "' exceeds four bindings");
    }
    for(std::uint8_t binding=0; binding<P64::Input::MAX_BINDINGS; ++binding) {
      const auto *value = axis && binding < axis->bindings.size() ? &axis->bindings[binding] : nullptr;
      output.write<std::uint8_t>(value ? static_cast<std::uint8_t>(axisSource(value->source)) : 0);
      const float scale = value ? std::clamp(value->scale, -1.0f, 1.0f) : 0.0f;
      output.write<std::int8_t>(static_cast<std::int8_t>(std::lround(scale * 127.0f)));
      output.write<std::uint8_t>(value ? quantizeUnit(value->deadZone) : 0);
      output.write<std::uint8_t>(0);
    }
  }

  const auto outputPath = std::filesystem::path(project.getPath()) / "filesystem" / "p64" / "input";
  output.writeToFile(outputPath);
  (void)sceneCtx;

  std::string header =
    "// AUTO-GENERATED FILE - input action and axis identifiers\n"
    "#pragma once\n#include \"input/input.h\"\n\nnamespace P64::Actions {\n";
  for(const auto &action : input.actions) {
    header += "  inline constexpr Input::ActionId " + identifier(action.name) + " = " + std::to_string(P64::Input::id(action.name)) + "u;\n";
  }
  header += "}\n\nnamespace P64::Axes {\n";
  for(const auto &axis : input.axes) {
    header += "  inline constexpr Input::AxisId " + identifier(axis.name) + " = " + std::to_string(P64::Input::id(axis.name)) + "u;\n";
  }
  header += "}\n";
  Utils::FS::saveTextFile(std::filesystem::path(project.getPath()) / "src" / "p64" / "inputActions.h", header);
  return true;
}
