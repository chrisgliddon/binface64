/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "multiplayerWorkspace.h"

#include <algorithm>
#include <array>
#include <functional>
#include <unordered_set>
#include <utility>

#include "imgui.h"
#include "misc/cpp/imgui_stdlib.h"
#include "IconsMaterialDesignIcons.h"
#include "../../../context.h"
#include "../../../project/component/components.h"
#include "../../../project/scene/scene.h"

namespace
{
  constexpr const char *BUTTON_NAMES[16]{
    "A", "B", "Z", "Start", "D-Up", "D-Down", "D-Left", "D-Right",
    "Y", "X", "L", "R", "C-Up", "C-Down", "C-Left", "C-Right"
  };
  constexpr const char *AXIS_SOURCES[7]{"none", "stick_x", "stick_y", "dpad_x", "dpad_y", "c_x", "c_y"};

  void drawMask(const char *label, std::uint16_t &mask)
  {
    ImGui::TextUnformatted(label);
    for(int bit=0; bit<16; ++bit) {
      if(bit % 4)ImGui::SameLine();
      bool enabled = (mask & (1u << bit)) != 0;
      ImGui::PushID(bit);
      if(ImGui::Checkbox(BUTTON_NAMES[bit], &enabled)) {
        if(enabled)mask |= 1u << bit;
        else mask &= ~(1u << bit);
      }
      ImGui::PopID();
    }
  }

  void drawPreview(int playerCount)
  {
    const ImVec2 origin = ImGui::GetCursorScreenPos();
    const ImVec2 size{320.0f, 240.0f};
    auto *draw = ImGui::GetWindowDrawList();
    draw->AddRectFilled(origin, {origin.x+size.x, origin.y+size.y}, IM_COL32(18, 18, 24, 255));
    std::array<ImVec4, 4> colors{
      ImVec4{0.30f,0.64f,1.0f,0.75f}, ImVec4{1.0f,0.35f,0.35f,0.75f},
      ImVec4{0.38f,0.82f,0.44f,0.75f}, ImVec4{1.0f,0.82f,0.30f,0.75f}
    };
    struct R { float x,y,w,h; } rects[4]{};
    if(playerCount == 1)rects[0] = {0,0,320,240};
    else if(playerCount == 2) { rects[0]={0,0,320,120}; rects[1]={0,120,320,120}; }
    else for(int i=0; i<playerCount; ++i)rects[i] = {
      static_cast<float>((i%2)*160), static_cast<float>((i/2)*120), 160, 120
    };
    for(int player=0; player<playerCount; ++player) {
      const auto &r = rects[player];
      const ImU32 color = ImGui::ColorConvertFloat4ToU32(colors[player]);
      draw->AddRectFilled({origin.x+r.x+1,origin.y+r.y+1}, {origin.x+r.x+r.w-1,origin.y+r.y+r.h-1}, color);
      const std::string label = "P" + std::to_string(player+1);
      draw->AddText({origin.x+r.x+8, origin.y+r.y+6}, IM_COL32_WHITE, label.c_str());
    }
    if(playerCount == 3)draw->AddText({origin.x+168, origin.y+128}, IM_COL32(180,180,190,255), "Shared UI");
    ImGui::InvisibleButton("viewport-preview", size);
  }

  void drawDiagnostics()
  {
    auto *scene = ctx.project->getScenes().getLoadedScene();
    if(!scene) { ImGui::TextDisabled("Open a scene to inspect camera, HUD, and spawn coverage."); return; }
    std::array<int, 4> cameras{};
    std::array<int, 4> huds{};
    std::array<int, 4> spawns{};
    int sharedCameras{};
    int neutralSpawns{};
    int teamSpawns{};
    struct ManualRect { std::string name; int x{}, y{}, width{}, height{}; };
    std::vector<ManualRect> manualRects{};
    std::vector<std::string> issues{};
    std::function<void(Project::Object&)> visit = [&](Project::Object &object) {
      for(auto &component : object.components) {
        if(component.id < 0 || component.id >= static_cast<int>(Project::Component::TABLE.size()))continue;
        const auto data = Project::Component::TABLE[component.id].funcSerialize(component);
        if(component.id == 3) {
          const int target = data.value("target", 0);
          const int player = data.value("player", 0);
          if(target == 1)++sharedCameras;
          if(target == 2) {
            if(player >= 0 && player < 4)++cameras[player];
            else issues.push_back("Camera '" + object.name + "' has an invalid player target");
          }
          const auto offset = data.value("vpOffset", nlohmann::json::array({0,0}));
          const auto size = data.value("vpSize", nlohmann::json::array({320,240}));
          if(target == 0 && offset.size() == 2 && size.size() == 2) {
            ManualRect rect{object.name, offset[0].get<int>(), offset[1].get<int>(), size[0].get<int>(), size[1].get<int>()};
            if(rect.x < 0 || rect.y < 0 || rect.width <= 0 || rect.height <= 0 ||
               rect.x + rect.width > scene->conf.fbWidth || rect.y + rect.height > scene->conf.fbHeight) {
              issues.push_back("Camera '" + object.name + "' has an invalid manual viewport rectangle");
            }
            manualRects.push_back(std::move(rect));
          }
        } else if(component.id == 13) {
          const int target = data.value("displayTarget", 0);
          const int player = data.value("displayPlayer", 0);
          if(target == 1 && player >= 0 && player < 4) {
            ++huds[player];
            const int mask = data.value("inputPlayerMask", 1);
            const bool hostOwns = mask == 0x10 && player == ctx.project->conf.multiplayer.hostPort;
            if(!(mask & (1 << player)) && !hostOwns)issues.push_back("Player " + std::to_string(player+1) + " HUD has the wrong input owner");
          }
        } else if(component.id == 15) {
          const int target = data.value("target", 0);
          const int player = data.value("index", 0);
          if(target == 1 && player >= 0 && player < 4)++spawns[player];
          else if(target == 0)++neutralSpawns;
          else if(target == 2)++teamSpawns;
        }
      }
      for(auto &child : object.children)visit(*child);
    };
    visit(scene->getRootObject());
    for(std::size_t left=0; left<manualRects.size(); ++left)for(std::size_t right=left+1; right<manualRects.size(); ++right) {
      const auto &a = manualRects[left];
      const auto &b = manualRects[right];
      if(a.x < b.x+b.width && b.x < a.x+a.width && a.y < b.y+b.height && b.y < a.y+a.height) {
        issues.push_back("Manual cameras '" + a.name + "' and '" + b.name + "' overlap");
      }
    }
    for(int player=0; player<4; ++player) {
      if(std::any_of(cameras.begin(), cameras.end(), [](int count){ return count > 0; }) && cameras[player] == 0)issues.push_back("Player " + std::to_string(player+1) + " is missing a camera target");
      if(cameras[player] > 1)issues.push_back("Player " + std::to_string(player+1) + " has duplicate camera targets");
      if(std::any_of(huds.begin(), huds.end(), [](int count){ return count > 0; }) && huds[player] == 0)issues.push_back("Player " + std::to_string(player+1) + " is missing a HUD target");
      if(huds[player] > 1)issues.push_back("Player " + std::to_string(player+1) + " has duplicate HUD targets");
      if(neutralSpawns == 0 && teamSpawns == 0 && std::any_of(spawns.begin(), spawns.end(), [](int count){ return count > 0; }) && spawns[player] == 0)issues.push_back("Player " + std::to_string(player+1) + " has no spawn");
    }
    if(sharedCameras > 1)issues.push_back("Scene has duplicate shared cameras");
    if(issues.empty())ImGui::TextColored({0.4f,0.9f,0.5f,1}, ICON_MDI_CHECK " No multiplayer scene conflicts found");
    for(const auto &issue : issues)ImGui::BulletText("%s", issue.c_str());
    ImGui::TextDisabled("Cameras P1-P4: %d / %d / %d / %d", cameras[0], cameras[1], cameras[2], cameras[3]);
    ImGui::TextDisabled("HUDs P1-P4: %d / %d / %d / %d", huds[0], huds[1], huds[2], huds[3]);
    ImGui::TextDisabled("Player spawns P1-P4: %d / %d / %d / %d", spawns[0], spawns[1], spawns[2], spawns[3]);
  }
}

void Editor::MultiplayerWorkspace::draw()
{
  auto &conf = ctx.project->conf;
  if(ImGui::CollapsingHeader("Controllers", ImGuiTreeNodeFlags_DefaultOpen)) {
    for(int player=0; player<4; ++player) {
      ImGui::PushID(player);
      ImGui::InputText(("Player " + std::to_string(player+1) + " label").c_str(), &conf.multiplayer.controllers[player].name);
      ImGui::SameLine();
      ImGui::Checkbox("Rumble Pak", &conf.multiplayer.controllers[player].rumble);
      ImGui::PopID();
    }
    ImGui::TextUnformatted("Enabled physical ports");
    for(int player=0; player<4; ++player) {
      if(player)ImGui::SameLine();
      bool enabled = (conf.multiplayer.enabledPortMask & (1u << player)) != 0;
      ImGui::PushID(100 + player);
      if(ImGui::Checkbox(("P" + std::to_string(player+1)).c_str(), &enabled)) {
        if(enabled)conf.multiplayer.enabledPortMask |= 1u << player;
        else conf.multiplayer.enabledPortMask &= ~(1u << player);
        conf.multiplayer.enabledPortMask &= 0x0F;
        if(conf.multiplayer.enabledPortMask == 0)conf.multiplayer.enabledPortMask = 1u << player;
        if((conf.multiplayer.enabledPortMask & (1u << conf.multiplayer.hostPort)) == 0) {
          for(std::uint8_t port=0; port<4; ++port)if(conf.multiplayer.enabledPortMask & (1u << port)) {
            conf.multiplayer.hostPort = port;
            break;
          }
        }
      }
      ImGui::PopID();
    }
    int hostPort = conf.multiplayer.hostPort;
    if(ImGui::Combo("Shared UI host", &hostPort, "Player 1\0Player 2\0Player 3\0Player 4\0")) {
      conf.multiplayer.hostPort = static_cast<std::uint8_t>(hostPort);
    }
    ImGui::RadioButton("4 MB target", &conf.multiplayer.targetRdramMB, 4); ImGui::SameLine();
    ImGui::RadioButton("8 MB target", &conf.multiplayer.targetRdramMB, 8);
  }

  if(ImGui::CollapsingHeader("Actions and Axes", ImGuiTreeNodeFlags_DefaultOpen)) {
    ImGui::SliderFloat("Default dead zone", &conf.input.deadZone, 0.0f, 0.95f, "%.2f");
    int removeAction = -1;
    for(std::size_t index=0; index<conf.input.actions.size(); ++index) {
      auto &action = conf.input.actions[index];
      ImGui::PushID(static_cast<int>(index));
      bool open = ImGui::TreeNode("action", "Action: %s", action.name.empty() ? "<unnamed>" : action.name.c_str());
      ImGui::SameLine(); if(ImGui::SmallButton(ICON_MDI_DELETE))removeAction = static_cast<int>(index);
      if(open) {
        ImGui::InputText("Name", &action.name);
        int removeBinding = -1;
        for(std::size_t binding=0; binding<action.bindings.size(); ++binding) {
          ImGui::PushID(static_cast<int>(binding));
          drawMask("Buttons", action.bindings[binding].buttons);
          drawMask("Chord", action.bindings[binding].chord);
          if(ImGui::SmallButton("Remove binding"))removeBinding = static_cast<int>(binding);
          ImGui::Separator();
          ImGui::PopID();
        }
        if(removeBinding >= 0)action.bindings.erase(action.bindings.begin()+removeBinding);
        if(action.bindings.size() < 4 && ImGui::Button("Add binding"))action.bindings.push_back({});
        ImGui::TreePop();
      }
      ImGui::PopID();
    }
    if(removeAction >= 0)conf.input.actions.erase(conf.input.actions.begin()+removeAction);
    if(conf.input.actions.size() < 32 && ImGui::Button(ICON_MDI_PLUS " Action"))conf.input.actions.push_back({"action", {{1,0}}});

    int removeAxis = -1;
    for(std::size_t index=0; index<conf.input.axes.size(); ++index) {
      auto &axis = conf.input.axes[index];
      ImGui::PushID(1000 + static_cast<int>(index));
      bool open = ImGui::TreeNode("axis", "Axis: %s", axis.name.empty() ? "<unnamed>" : axis.name.c_str());
      ImGui::SameLine(); if(ImGui::SmallButton(ICON_MDI_DELETE))removeAxis = static_cast<int>(index);
      if(open) {
        ImGui::InputText("Name", &axis.name);
        for(std::size_t binding=0; binding<axis.bindings.size(); ++binding) {
          auto &value = axis.bindings[binding];
          ImGui::PushID(static_cast<int>(binding));
          if(ImGui::BeginCombo("Source", value.source.c_str())) {
            for(const char *source : AXIS_SOURCES)if(ImGui::Selectable(source, value.source == source))value.source = source;
            ImGui::EndCombo();
          }
          ImGui::SliderFloat("Scale", &value.scale, -1.0f, 1.0f);
          ImGui::SliderFloat("Dead zone", &value.deadZone, 0.0f, 0.95f);
          ImGui::PopID();
        }
        if(axis.bindings.size() < 4 && ImGui::Button("Add binding"))axis.bindings.push_back({});
        ImGui::TreePop();
      }
      ImGui::PopID();
    }
    if(removeAxis >= 0)conf.input.axes.erase(conf.input.axes.begin()+removeAxis);
    if(conf.input.axes.size() < 8 && ImGui::Button(ICON_MDI_PLUS " Axis"))conf.input.axes.push_back({"axis", {{"stick_x",1,0}}});
  }

  if(ImGui::CollapsingHeader("Viewport Preview", ImGuiTreeNodeFlags_DefaultOpen)) {
    ImGui::SliderInt("Players", &previewPlayers_, 1, 4);
    drawPreview(previewPlayers_);
  }
  if(ImGui::CollapsingHeader("Scene Diagnostics", ImGuiTreeNodeFlags_DefaultOpen))drawDiagnostics();
  if(ImGui::Button(ICON_MDI_CONTENT_SAVE_OUTLINE " Save Multiplayer Settings"))ctx.project->save();
}
