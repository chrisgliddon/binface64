/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "json.hpp"
#include "imgui.h"

namespace Editor
{
  class UIEditor
  {
    struct FlatElement
    {
      nlohmann::json *doc{};
      int parent{-1};
      ImVec4 rect{}; // canvas x0,y0,x1,y1
      bool effectiveVisible{true};
    };

    uint64_t assetUUID{};
    std::string path{};
    std::string name{};
    nlohmann::json document{};
    std::string selectedId{"root"};
    bool open{true};
    bool dirty{false};
    bool confirmClose{false};
    bool resizingSelection{false};
    bool draggingSelection{false};
    ImVec2 dragStartMouse{};
    ImVec4 dragStartOffsets{};
    float zoom{1.0f};
    bool documentUsable{false};
    std::vector<std::string> validationIssues{};

    void reload();
    void save();
    void flatten(nlohmann::json &element, int parent, const ImVec4 &parentRect, bool parentVisible,
                 std::vector<FlatElement> &out);
    nlohmann::json* selected();
    void drawHierarchy(nlohmann::json &element);
    void drawCanvas();
    void drawInspector();
    void validate();
    void addElement(const std::string &type);
    void deleteSelected();
    void moveSelected(int direction);

  public:
    explicit UIEditor(uint64_t uuid);
    [[nodiscard]] uint64_t getAssetUUID() const { return assetUUID; }
    [[nodiscard]] bool isDirty() const { return dirty; }
    void saveIfDirty();
    void focus();
    bool draw(ImGuiID dockId);
  };
}
