/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "uiEditor.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <format>
#include <functional>
#include <tuple>
#include <unordered_map>
#include <unordered_set>

#include "IconsMaterialDesignIcons.h"
#include "misc/cpp/imgui_stdlib.h"
#include "../../../context.h"
#include "../../../utils/fs.h"
#include "../../../utils/hash.h"
#include "../../imgui/theme.h"

namespace
{
  ImVec4 parseColor(const nlohmann::json &value, const ImVec4 &fallback)
  {
    if(!value.is_string())return fallback;
    auto text = value.get<std::string>();
    if(text.size() != 9 || text[0] != '#')return fallback;
    try {
      auto packed = static_cast<uint32_t>(std::stoul(text.substr(1), nullptr, 16));
      return {
        static_cast<float>((packed >> 24) & 0xFF) / 255.0f,
        static_cast<float>((packed >> 16) & 0xFF) / 255.0f,
        static_cast<float>((packed >> 8) & 0xFF) / 255.0f,
        static_cast<float>(packed & 0xFF) / 255.0f,
      };
    } catch(...) { return fallback; }
  }

  std::string colorString(const ImVec4 &color)
  {
    auto byte = [](float value) { return static_cast<uint32_t>(std::clamp(value, 0.0f, 1.0f) * 255.0f + 0.5f); };
    return std::format("#{:02X}{:02X}{:02X}{:02X}", byte(color.x), byte(color.y), byte(color.z), byte(color.w));
  }

  bool contains(const ImVec4 &rect, const ImVec2 &point)
  {
    return point.x >= rect.x && point.x <= rect.z && point.y >= rect.y && point.y <= rect.w;
  }

  Project::AssetManagerEntry* resolveAssetRef(const nlohmann::json &reference)
  {
    if(!ctx.project)return nullptr;
    if(reference.is_number_integer() || reference.is_number_unsigned()) {
      return ctx.project->getAssets().getEntryByUUID(reference.get<uint64_t>());
    }
    if(!reference.is_string())return nullptr;
    std::string path = reference.get<std::string>();
    std::replace(path.begin(), path.end(), '\\', '/');
    if(path.starts_with("assets/"))path = path.substr(7);
    auto full = std::filesystem::path{ctx.project->getPath()} / "assets" / path;
    return ctx.project->getAssets().getByPath(full.string());
  }

  nlohmann::json makeElement(const std::string &id, const std::string &type)
  {
    nlohmann::json element{
      {"id", id}, {"type", type},
      {"layout", {{"anchors", {0.5, 0.5, 0.5, 0.5}}, {"offsets", {-60, -12, 60, 12}}}},
      {"visible", true}, {"enabled", true},
      {"style", {{"color", "#202030D8"}, {"textColor", "#FFFFFFFF"}, {"focusColor", "#E0B030FF"}}},
      {"children", nlohmann::json::array()}
    };
    if(type == "Image") { element["asset"] = 0; element["fit"] = "stretch"; }
    if(type == "Text" || type == "Button") {
      element["font"] = 0; element["text"] = type == "Button" ? "Button" : "Text"; element["align"] = "center";
    }
    if(type == "TextInput") {
      element["font"] = 0; element["value"] = ""; element["placeholder"] = "Enter text";
      element["charset"] = " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
      element["maxLength"] = 32; element["submitOnStart"] = true;
      element["align"] = "left"; element["focus"] = nlohmann::json::object();
    }
    if(type == "Button")element["focus"] = nlohmann::json::object();
    if(type == "ProgressBar") {
      element["value"] = 50;
      element["max"] = 100;
      element["thresholds"] = nlohmann::json::array();
      element["style"] = {{"color", "#202020FF"}, {"fillColor", "#40C060FF"}};
    }
    if(type == "Container") {
      element["layout"]["flow"] = "none";
      element["layout"]["gap"] = 0;
    }
    return element;
  }
}

Editor::UIEditor::UIEditor(uint64_t uuid) : assetUUID{uuid}
{
  reload();
}

void Editor::UIEditor::reload()
{
  auto asset = ctx.project ? ctx.project->getAssets().getEntryByUUID(assetUUID) : nullptr;
  if(!asset)return;
  path = asset->path;
  name = asset->name;
  try { document = nlohmann::json::parse(Utils::FS::loadTextFile(path)); }
  catch(...) { document = nlohmann::json::object(); }
  selectedId = "root";
  dirty = false;
  validate();
}

void Editor::UIEditor::save()
{
  Utils::FS::saveTextFile(path, document.dump(2) + "\n");
  dirty = false;
  if(ctx.project)ctx.project->getAssets().reloadAssetByUUID(assetUUID);
  validate();
}

void Editor::UIEditor::saveIfDirty()
{
  if(dirty)save();
}

void Editor::UIEditor::focus()
{
  ImGui::SetWindowFocus((ICON_MDI_MONITOR_DASHBOARD " UI: " + name + "###UI_" + std::to_string(assetUUID)).c_str());
}

void Editor::UIEditor::flatten(nlohmann::json &element, int parent, const ImVec4 &parentRect,
                               bool parentVisible, std::vector<FlatElement> &out)
{
  if(!element.is_object())return;
  auto layout = element.value("layout", nlohmann::json::object());
  auto anchors = layout.value("anchors", std::vector<float>{0,0,0,0});
  auto offsets = layout.value("offsets", std::vector<float>{0,0,0,0});
  if(anchors.size() != 4)anchors = {0,0,0,0};
  if(offsets.size() != 4)offsets = {0,0,0,0};
  float width = parentRect.z - parentRect.x;
  float height = parentRect.w - parentRect.y;
  ImVec4 rect{
    parentRect.x + width * anchors[0] + offsets[0],
    parentRect.y + height * anchors[1] + offsets[1],
    parentRect.x + width * anchors[2] + offsets[2],
    parentRect.y + height * anchors[3] + offsets[3],
  };
  bool visible = parentVisible && element.value("visible", true);
  int index = static_cast<int>(out.size());
  out.push_back({&element, parent, rect, visible});
  if(element.contains("children") && element["children"].is_array()) {
    const auto flow = layout.value("flow", std::string{"none"});
    const float gap = static_cast<float>(layout.value("gap", 0));
    float cursor = flow == "horizontal" ? rect.x : rect.y;
    for(auto &child : element["children"]) {
      const size_t childStart = out.size();
      flatten(child, index, rect, visible, out);
      if(childStart >= out.size() || (flow != "vertical" && flow != "horizontal"))continue;
      auto &childFlat = out[childStart];
      const float extent = flow == "horizontal"
        ? std::max(0.0f, childFlat.rect.z - childFlat.rect.x)
        : std::max(0.0f, childFlat.rect.w - childFlat.rect.y);
      const float delta = cursor - (flow == "horizontal" ? childFlat.rect.x : childFlat.rect.y);
      for(size_t moved=childStart; moved<out.size(); ++moved) {
        if(flow == "horizontal") {
          out[moved].rect.x += delta;
          out[moved].rect.z += delta;
        } else {
          out[moved].rect.y += delta;
          out[moved].rect.w += delta;
        }
      }
      if(childFlat.effectiveVisible) {
        cursor += extent + gap;
      } else if(flow == "horizontal") {
        childFlat.rect.z = childFlat.rect.x;
      } else {
        childFlat.rect.w = childFlat.rect.y;
      }
    }
  }
}

nlohmann::json* Editor::UIEditor::selected()
{
  if(!document.contains("root"))return nullptr;
  std::function<nlohmann::json*(nlohmann::json&)> find = [&](nlohmann::json &element) -> nlohmann::json* {
    if(element.value("id", std::string{}) == selectedId)return &element;
    if(element.contains("children"))for(auto &child : element["children"])if(auto found = find(child))return found;
    return nullptr;
  };
  return find(document["root"]);
}

void Editor::UIEditor::drawHierarchy(nlohmann::json &element)
{
  auto id = element.value("id", std::string{"(invalid)"});
  auto type = element.value("type", std::string{"Unknown"});
  bool hasChildren = element.contains("children") && !element["children"].empty();
  ImGuiTreeNodeFlags flags = ImGuiTreeNodeFlags_OpenOnArrow | ImGuiTreeNodeFlags_DefaultOpen |
    (selectedId == id ? ImGuiTreeNodeFlags_Selected : 0) |
    (!hasChildren ? ImGuiTreeNodeFlags_Leaf : 0);
  bool expanded = ImGui::TreeNodeEx(id.c_str(), flags, "%s  %s", type.c_str(), id.c_str());
  if(ImGui::IsItemClicked())selectedId = id;
  if(expanded) {
    if(hasChildren)for(auto &child : element["children"])drawHierarchy(child);
    ImGui::TreePop();
  }
}

void Editor::UIEditor::drawCanvas()
{
  if(!document.contains("canvas") || !document.contains("root"))return;
  auto &canvas = document["canvas"];
  float width = canvas.value("width", 320.0f);
  float height = canvas.value("height", 240.0f);
  auto avail = ImGui::GetContentRegionAvail();
  float fit = std::max(0.1f, std::min((avail.x - 24_px) / width, (avail.y - 24_px) / height));
  zoom = fit;
  ImVec2 origin = ImGui::GetCursorScreenPos();
  origin.x += std::max(0.0f, (avail.x - width*zoom) * 0.5f);
  origin.y += std::max(0.0f, (avail.y - height*zoom) * 0.5f);
  ImVec2 end{origin.x + width*zoom, origin.y + height*zoom};
  auto *draw = ImGui::GetWindowDrawList();
  draw->AddRectFilled(origin, end, IM_COL32(16,16,20,255));
  draw->AddRect(origin, end, IM_COL32(140,140,150,255), 0, 0, 1.0f);

  auto safe = canvas.value("safeArea", std::vector<float>{0,0,0,0});
  if(safe.size() == 4) {
    draw->AddRect({origin.x+safe[0]*zoom, origin.y+safe[1]*zoom},
                  {end.x-safe[2]*zoom, end.y-safe[3]*zoom}, IM_COL32(80,180,255,150));
  }

  std::vector<FlatElement> flat{};
  flatten(document["root"], -1, {0,0,width,height}, true, flat);
  ImVec4 selectedScreen{};
  bool hasSelectedScreen = false;
  for(auto &item : flat)
  {
    if(!item.effectiveVisible)continue;
    auto &element = *item.doc;
    ImVec2 p0{origin.x + item.rect.x*zoom, origin.y + item.rect.y*zoom};
    ImVec2 p1{origin.x + item.rect.z*zoom, origin.y + item.rect.w*zoom};
    auto style = element.value("style", nlohmann::json::object());
    auto bg = parseColor(style.value("color", "#00000000"), {0,0,0,0});
    if(bg.w > 0)draw->AddRectFilled(p0, p1, ImGui::ColorConvertFloat4ToU32(bg));
    auto type = element.value("type", std::string{});
    if(type == "Image") {
      Project::AssetManagerEntry *asset = element.contains("asset") ? resolveAssetRef(element["asset"]) : nullptr;
      if(asset && asset->texture)draw->AddImage(ImTextureID(asset->texture->getGPUTex()), p0, p1);
      else draw->AddText({p0.x+3,p0.y+3}, IM_COL32(180,180,190,255), "Image");
    }
    if(type == "ProgressBar") {
      int maximum = std::max(1, element.value("max", 100));
      int value = std::clamp(element.value("value", maximum), 0, maximum);
      auto fill = parseColor(style.value("fillColor", "#40C060FF"), {0.25f,0.75f,0.38f,1});
      auto thresholds = element.value("thresholds", nlohmann::json::array());
      if(thresholds.is_array())for(const auto &threshold : thresholds) {
        if(!threshold.is_object() || !threshold.contains("max") || !threshold["max"].is_number_integer())continue;
        if(value <= threshold["max"].get<int>()) {
          fill = parseColor(threshold.value("color", "#40C060FF"), fill);
          break;
        }
      }
      ImVec2 fillEnd{p0.x + (p1.x-p0.x) * static_cast<float>(value) / static_cast<float>(maximum), p1.y};
      if(fillEnd.x > p0.x)draw->AddRectFilled(p0, fillEnd, ImGui::ColorConvertFloat4ToU32(fill));
    }
    if(type == "Text" || type == "Button" || type == "TextInput") {
      std::string text = element.value("text", std::string{});
      if(type == "TextInput")text = element.value("value", std::string{});
      if(text.empty())text = element.value("placeholder", std::string{});
      auto col = parseColor(style.value("textColor", "#FFFFFFFF"), {1,1,1,1});
      auto size = ImGui::CalcTextSize(text.c_str());
      float x = p0.x + 3;
      auto align = element.value("align", std::string{"left"});
      if(align == "center")x = (p0.x+p1.x-size.x)*0.5f;
      if(align == "right")x = p1.x-size.x-3;
      draw->AddText({x, (p0.y+p1.y-size.y)*0.5f}, ImGui::ColorConvertFloat4ToU32(col), text.c_str());
    }
    if(element.value("id", std::string{}) == selectedId) {
      draw->AddRect(p0, p1, IM_COL32(255,176,46,255), 0, 0, 2.0f);
      draw->AddRectFilled({p1.x-4,p1.y-4}, {p1.x+4,p1.y+4}, IM_COL32(255,176,46,255));
      selectedScreen = {p0.x,p0.y,p1.x,p1.y};
      hasSelectedScreen = true;
    }
  }

  std::unordered_map<std::string, ImVec4> rectById{};
  for(const auto &item : flat)rectById[item.doc->value("id", std::string{})] = item.rect;
  for(const auto &item : flat) {
    if(!item.doc->contains("focus") || !(*item.doc)["focus"].is_object())continue;
    for(const auto &[direction, targetValue] : (*item.doc)["focus"].items()) {
      if(!targetValue.is_string() || !rectById.contains(targetValue.get<std::string>()))continue;
      const auto &target = rectById[targetValue.get<std::string>()];
      ImVec2 from{origin.x+(item.rect.x+item.rect.z)*0.5f*zoom, origin.y+(item.rect.y+item.rect.w)*0.5f*zoom};
      ImVec2 to{origin.x+(target.x+target.z)*0.5f*zoom, origin.y+(target.y+target.w)*0.5f*zoom};
      draw->AddLine(from, to, IM_COL32(80,180,255,140), 1.0f);
      draw->AddCircleFilled(to, 2.5f, IM_COL32(80,180,255,200));
    }
  }

  ImGui::SetCursorScreenPos(origin);
  ImGui::InvisibleButton("##UICanvas", {width*zoom, height*zoom});
  if(ImGui::IsItemClicked()) {
    ImVec2 mouse = ImGui::GetIO().MousePos;
    resizingSelection = hasSelectedScreen && std::fabs(mouse.x-selectedScreen.z) <= 8_px &&
      std::fabs(mouse.y-selectedScreen.w) <= 8_px && selectedId != "root";
    ImVec2 local{(mouse.x-origin.x)/zoom, (mouse.y-origin.y)/zoom};
    if(!resizingSelection)for(auto it=flat.rbegin(); it!=flat.rend(); ++it) {
      if(it->effectiveVisible && contains(it->rect, local)) { selectedId = it->doc->value("id", "root"); break; }
    }
    draggingSelection = false;
    if(selectedId != "root")if(auto element = selected()) {
      auto &offsets = (*element)["layout"]["offsets"];
      if(offsets.is_array() && offsets.size() == 4) {
        dragStartMouse = mouse;
        dragStartOffsets = {offsets[0].get<float>(), offsets[1].get<float>(),
                            offsets[2].get<float>(), offsets[3].get<float>()};
        draggingSelection = true;
      }
    }
  }
  if(ImGui::IsItemActive() && ImGui::IsMouseDragging(ImGuiMouseButton_Left) && draggingSelection) {
    if(auto element = selected()) {
      auto delta = ImGui::GetIO().MousePos - dragStartMouse;
      auto &offsets = (*element)["layout"]["offsets"];
      float snap = std::max(1.0f, canvas.value("snap", 1.0f));
      auto snapped = [snap](float value) { return std::round(value / snap) * snap; };
      if(resizingSelection) {
        offsets[2] = snapped(dragStartOffsets.z + delta.x/zoom);
        offsets[3] = snapped(dragStartOffsets.w + delta.y/zoom);
      } else {
        offsets[0] = snapped(dragStartOffsets.x + delta.x/zoom);
        offsets[1] = snapped(dragStartOffsets.y + delta.y/zoom);
        offsets[2] = snapped(dragStartOffsets.z + delta.x/zoom);
        offsets[3] = snapped(dragStartOffsets.w + delta.y/zoom);
      }
      dirty = true;
    }
  }
  if(!ImGui::IsMouseDown(ImGuiMouseButton_Left)) {
    resizingSelection = false;
    draggingSelection = false;
  }
}

void Editor::UIEditor::drawInspector()
{
  if(document.contains("canvas") && document["canvas"].is_object()) {
    auto &canvas = document["canvas"];
    int width = canvas.value("width", 320);
    int height = canvas.value("height", 240);
    int snap = canvas.value("snap", 1);
    auto safe = canvas.value("safeArea", std::vector<int>{8,8,8,8});
    if(safe.size() != 4)safe = {8,8,8,8};
    ImGui::SeparatorText("Canvas");
    if(ImGui::DragInt("Width", &width, 1, 1, 640)) { canvas["width"] = width; dirty = true; }
    if(ImGui::DragInt("Height", &height, 1, 1, 576)) { canvas["height"] = height; dirty = true; }
    if(ImGui::DragInt4("Safe area", safe.data(), 1, 0, 576)) { canvas["safeArea"] = safe; dirty = true; }
    if(ImGui::DragInt("Snap", &snap, 1, 1, 64)) { canvas["snap"] = snap; dirty = true; }
  }

  ImGui::SeparatorText("Element");
  auto element = selected();
  if(!element) { ImGui::TextDisabled("No element selected"); return; }
  ImGui::Text("%s", element->value("type", "Unknown").c_str());
  std::string id = element->value("id", std::string{});
  if(ImGui::InputText("ID", &id) && !id.empty()) { (*element)["id"] = id; selectedId = id; dirty = true; }
  bool visible = element->value("visible", true);
  bool enabled = element->value("enabled", true);
  auto type = element->value("type", std::string{});
  if(ImGui::Checkbox("Visible", &visible)) { (*element)["visible"] = visible; dirty = true; }
  ImGui::SameLine();
  if(ImGui::Checkbox("Enabled", &enabled)) { (*element)["enabled"] = enabled; dirty = true; }

  auto &layout = (*element)["layout"];
  std::array<float,4> anchors{};
  std::array<float,4> offsets{};
  for(int i=0;i<4;++i) { anchors[i] = layout["anchors"][i]; offsets[i] = layout["offsets"][i]; }
  if(ImGui::DragFloat4("Anchors", anchors.data(), 0.01f, 0.0f, 1.0f, "%.2f")) {
    layout["anchors"] = anchors; dirty = true;
  }
  if(ImGui::DragFloat4("Offsets", offsets.data(), 1.0f, -32768, 32767, "%.0f")) {
    layout["offsets"] = offsets; dirty = true;
  }

  if(type == "Container") {
    constexpr std::array<const char*, 3> FLOW_NAMES{"none", "vertical", "horizontal"};
    std::string flow = layout.value("flow", std::string{"none"});
    int flowIndex = flow == "vertical" ? 1 : flow == "horizontal" ? 2 : 0;
    int gap = layout.contains("gap") && layout["gap"].is_number_integer()
      ? layout["gap"].get<int>()
      : 0;
    if(ImGui::Combo("Flow", &flowIndex, FLOW_NAMES.data(), static_cast<int>(FLOW_NAMES.size()))) {
      layout["flow"] = FLOW_NAMES[flowIndex];
      dirty = true;
    }
    if(ImGui::DragInt("Flow gap", &gap, 1, 0, 32767)) {
      layout["gap"] = std::clamp(gap, 0, 32767);
      dirty = true;
    }
  }

  if(type == "Text" || type == "Button") {
    std::string text = element->value("text", std::string{});
    if(ImGui::InputTextMultiline("Text", &text)) { (*element)["text"] = text; dirty = true; }
  }
  if(type == "TextInput") {
    std::string placeholder = element->value("placeholder", std::string{});
    std::string value = element->value("value", std::string{});
    std::string charset = element->value("charset", std::string{});
    int maxLength = element->value("maxLength", 32);
    bool submitOnStart = element->value("submitOnStart", true);
    if(ImGui::InputText("Placeholder", &placeholder)) { (*element)["placeholder"] = placeholder; dirty = true; }
    if(ImGui::InputText("Initial value", &value)) { (*element)["value"] = value; dirty = true; }
    if(ImGui::InputTextMultiline("Charset", &charset)) { (*element)["charset"] = charset; dirty = true; }
    if(ImGui::DragInt("Max length", &maxLength, 1, 1, 256)) { (*element)["maxLength"] = maxLength; dirty = true; }
    if(ImGui::Checkbox("Start submits", &submitOnStart)) { (*element)["submitOnStart"] = submitOnStart; dirty = true; }
  }
  if(type == "ProgressBar") {
    int maximum = element->value("max", 100);
    int value = element->value("value", maximum);
    if(ImGui::DragInt("Value", &value, 1, 0, std::max(1, maximum))) {
      (*element)["value"] = std::clamp(value, 0, std::max(1, maximum));
      dirty = true;
    }
    if(ImGui::DragInt("Maximum", &maximum, 1, 1, 0xFFFF)) {
      maximum = std::clamp(maximum, 1, 0xFFFF);
      (*element)["max"] = maximum;
      if(element->value("value", 0) > maximum)(*element)["value"] = maximum;
      dirty = true;
    }

    auto &thresholds = (*element)["thresholds"];
    if(!thresholds.is_array())thresholds = nlohmann::json::array();
    ImGui::SeparatorText("Thresholds");
    int removeThreshold = -1;
    for(size_t index=0; index<thresholds.size(); ++index) {
      auto &threshold = thresholds[index];
      if(!threshold.is_object())threshold = {{"max", 0}, {"color", "#D04040FF"}};
      ImGui::PushID(static_cast<int>(index));
      int thresholdMax = threshold.value("max", 0);
      if(ImGui::DragInt("Upper bound", &thresholdMax, 1, 0, maximum)) {
        threshold["max"] = std::clamp(thresholdMax, 0, maximum);
        dirty = true;
      }
      auto thresholdColor = parseColor(threshold.value("color", "#D04040FF"), {0.82f,0.25f,0.25f,1});
      if(ImGui::ColorEdit4("Color", &thresholdColor.x)) {
        threshold["color"] = colorString(thresholdColor);
        dirty = true;
      }
      if(ImGui::Button(ICON_MDI_DELETE " Remove threshold"))removeThreshold = static_cast<int>(index);
      ImGui::Separator();
      ImGui::PopID();
    }
    if(removeThreshold >= 0) {
      thresholds.erase(thresholds.begin() + removeThreshold);
      dirty = true;
    }
    int lastMax = thresholds.empty() ? -1 : thresholds.back().value("max", -1);
    bool canAdd = thresholds.size() < 3 && lastMax < maximum;
    if(!canAdd)ImGui::BeginDisabled();
    if(ImGui::Button(ICON_MDI_PLUS " Add threshold")) {
      int nextMax = lastMax + std::max(1, (maximum-lastMax)/2);
      thresholds.push_back({{"max", std::min(nextMax, maximum)}, {"color", "#D04040FF"}});
      dirty = true;
    }
    if(!canAdd)ImGui::EndDisabled();
  }

  if(type == "Button" || type == "TextInput") {
    std::vector<std::string> focusIds{};
    std::function<void(nlohmann::json&)> collectFocus = [&](nlohmann::json &node) {
      auto nodeType = node.value("type", std::string{});
      if(nodeType == "Button" || nodeType == "TextInput")focusIds.push_back(node.value("id", std::string{}));
      if(node.contains("children"))for(auto &child : node["children"])collectFocus(child);
    };
    collectFocus(document["root"]);
    auto &focus = (*element)["focus"];
    if(!focus.is_object())focus = nlohmann::json::object();
    for(const char *direction : {"up", "down", "left", "right"}) {
      std::string current = focus.value(direction, std::string{});
      std::string label = std::string{"Focus "} + direction;
      if(ImGui::BeginCombo(label.c_str(), current.empty() ? "<Automatic>" : current.c_str())) {
        if(ImGui::Selectable("<Automatic>", current.empty())) { focus.erase(direction); dirty = true; }
        for(const auto &target : focusIds)if(target != selectedId && ImGui::Selectable(target.c_str(), current == target)) {
          focus[direction] = target; dirty = true;
        }
        ImGui::EndCombo();
      }
    }
  }

  if(type == "Image") {
    auto &images = ctx.project->getAssets().getTypeEntries(Project::FileType::IMAGE);
    auto currentAsset = element->contains("asset") ? resolveAssetRef((*element)["asset"]) : nullptr;
    uint64_t current = currentAsset ? currentAsset->getUUID() : 0;
    const char *preview = "<Select image>";
    if(auto asset = ctx.project->getAssets().getEntryByUUID(current))preview = asset->name.c_str();
    if(ImGui::BeginCombo("Image", preview)) {
      for(const auto &asset : images)if(ImGui::Selectable(asset.name.c_str(), asset.getUUID()==current)) {
        (*element)["asset"] = asset.getUUID(); dirty = true;
      }
      ImGui::EndCombo();
    }
    const char *fits[] = {"stretch", "native"};
    int fit = element->value("fit", std::string{"stretch"}) == "native" ? 1 : 0;
    if(ImGui::Combo("Fit", &fit, fits, 2)) { (*element)["fit"] = fits[fit]; dirty = true; }
  }
  if(type == "Text" || type == "Button" || type == "TextInput") {
    auto &fonts = ctx.project->getAssets().getTypeEntries(Project::FileType::FONT);
    auto currentAsset = element->contains("font") ? resolveAssetRef((*element)["font"]) : nullptr;
    uint64_t current = currentAsset ? currentAsset->getUUID() : 0;
    const char *preview = "<Select font>";
    if(auto asset = ctx.project->getAssets().getEntryByUUID(current))preview = asset->name.c_str();
    if(ImGui::BeginCombo("Font", preview)) {
      for(const auto &asset : fonts)if(ImGui::Selectable(asset.name.c_str(), asset.getUUID()==current)) {
        (*element)["font"] = asset.getUUID(); dirty = true;
      }
      ImGui::EndCombo();
    }
    const char* aligns[] = {"left", "center", "right"};
    int align = element->value("align", std::string{"left"}) == "center" ? 1 : element->value("align", std::string{"left"}) == "right" ? 2 : 0;
    if(ImGui::Combo("Align", &align, aligns, 3)) { (*element)["align"] = aligns[align]; dirty = true; }
  }

  auto &style = (*element)["style"];
  if(!style.is_object())style = nlohmann::json::object();
  auto editColor = [&](const char *label, const char *key, const ImVec4 &fallback) {
    auto color = parseColor(style.value(key, colorString(fallback)), fallback);
    if(ImGui::ColorEdit4(label, &color.x)) { style[key] = colorString(color); dirty = true; }
  };
  editColor("Background", "color", {0,0,0,0});
  if(type == "ProgressBar") {
    editColor("Fill color", "fillColor", {0.25f,0.75f,0.38f,1});
  } else {
    editColor("Text color", "textColor", {1,1,1,1});
    editColor("Focus color", "focusColor", {0.88f,0.69f,0.19f,1});
  }

  ImGui::Separator();
  if(selectedId != "root") {
    if(ImGui::Button(ICON_MDI_ARROW_UP " Earlier"))moveSelected(-1);
    ImGui::SameLine();
    if(ImGui::Button(ICON_MDI_ARROW_DOWN " Later"))moveSelected(1);
    if(ImGui::Button(ICON_MDI_DELETE " Delete element"))deleteSelected();
  }
}

void Editor::UIEditor::addElement(const std::string &type)
{
  std::unordered_set<std::string> ids{};
  std::function<void(nlohmann::json&)> collect = [&](nlohmann::json &node) {
    ids.insert(node.value("id", std::string{}));
    if(node.contains("children"))for(auto &child : node["children"])collect(child);
  };
  collect(document["root"]);
  std::string base = type;
  base[0] = static_cast<char>(std::tolower(base[0]));
  std::string id = base;
  for(uint32_t index=2; ids.contains(id); ++index)id = base + std::to_string(index);
  auto value = makeElement(id, type);
  auto parent = selected();
  if(!parent || parent->value("type", std::string{}) != "Container")parent = &document["root"];
  (*parent)["children"].push_back(std::move(value));
  selectedId = id;
  dirty = true;
  validate();
}

void Editor::UIEditor::deleteSelected()
{
  if(selectedId == "root")return;
  std::function<bool(nlohmann::json&)> remove = [&](nlohmann::json &node) {
    if(!node.contains("children"))return false;
    auto &children = node["children"];
    for(auto it=children.begin(); it!=children.end(); ++it) {
      if(it->value("id", std::string{}) == selectedId) { children.erase(it); return true; }
      if(remove(*it))return true;
    }
    return false;
  };
  if(remove(document["root"])) { selectedId = "root"; dirty = true; validate(); }
}

void Editor::UIEditor::moveSelected(int direction)
{
  std::function<bool(nlohmann::json&)> move = [&](nlohmann::json &node) {
    if(!node.contains("children") || !node["children"].is_array())return false;
    auto &children = node["children"];
    for(size_t index=0; index<children.size(); ++index) {
      if(children[index].value("id", std::string{}) == selectedId) {
        int target = static_cast<int>(index) + direction;
        if(target >= 0 && target < static_cast<int>(children.size())) {
          std::swap(children[index], children[target]);
          dirty = true;
        }
        return true;
      }
      if(move(children[index]))return true;
    }
    return false;
  };
  move(document["root"]);
}

void Editor::UIEditor::validate()
{
  validationIssues.clear();
  documentUsable = true;
  auto issue = [&](const std::string &message, bool structural = false) {
    validationIssues.push_back(message);
    if(structural)documentUsable = false;
  };
  if(!document.is_object()) {
    issue("Document must be a JSON object", true);
    return;
  }
  if(!document.contains("schema") || !document["schema"].is_string() || document["schema"] != "bf64.ui") {
    issue("Schema must be bf64.ui");
  }
  if(!document.contains("version") || !document["version"].is_number_integer() || document["version"] != 1) {
    issue("Only document version 1 is supported");
  }
  if(!document.contains("canvas") || !document["canvas"].is_object()) {
    issue("Canvas must be an object", true);
  } else {
    const auto &canvas = document["canvas"];
    if(!canvas.contains("width") || !canvas["width"].is_number_integer() ||
       canvas["width"].get<int64_t>() < 1 || canvas["width"].get<int64_t>() > 640) {
      issue("Canvas width must be an integer from 1 to 640", true);
    }
    if(!canvas.contains("height") || !canvas["height"].is_number_integer() ||
       canvas["height"].get<int64_t>() < 1 || canvas["height"].get<int64_t>() > 576) {
      issue("Canvas height must be an integer from 1 to 576", true);
    }
    if(canvas.contains("safeArea")) {
      const auto &safe = canvas["safeArea"];
      if(!safe.is_array() || safe.size() != 4 || std::any_of(safe.begin(), safe.end(), [](const auto &value) {
        return !value.is_number_integer() || value.template get<int64_t>() < 0;
      }))issue("Canvas safeArea must contain four non-negative integers", true);
    }
    if(canvas.contains("snap") && (!canvas["snap"].is_number_integer() ||
       canvas["snap"].get<int64_t>() < 1 || canvas["snap"].get<int64_t>() > 64)) {
      issue("Canvas snap must be an integer from 1 to 64", true);
    }
  }

  std::unordered_set<std::string> ids{};
  std::unordered_set<std::string> focusableIds{};
  std::unordered_map<uint32_t, std::string> hashes{};
  std::vector<std::tuple<std::string, std::string, std::string>> focusRefs{};
  uint32_t elementCount{};
  auto validId = [](const std::string &id) {
    if(id.empty() || id.size() > 64 || (!std::isalpha(static_cast<unsigned char>(id[0])) && id[0] != '_'))return false;
    return std::all_of(id.begin()+1, id.end(), [](unsigned char value) {
      return std::isalnum(value) || value == '_' || value == '.' || value == '-';
    });
  };
  auto validColor = [](const nlohmann::json &value) {
    if(!value.is_string())return false;
    auto text = value.get<std::string>();
    return text.size() == 9 && text[0] == '#' && std::all_of(text.begin()+1, text.end(), [](unsigned char value) {
      return std::isxdigit(value);
    });
  };
  std::function<void(nlohmann::json&)> check = [&](nlohmann::json &element) {
    ++elementCount;
    if(!element.is_object()) { issue("Element must be an object", true); return; }
    std::string id{};
    if(!element.contains("id") || !element["id"].is_string())issue("Element ID must be a string", true);
    else {
      id = element["id"].get<std::string>();
      if(!validId(id))issue("Invalid element ID: " + id);
      else if(!ids.insert(id).second)issue("Duplicate element ID: " + id);
      else {
        auto hash = Utils::Hash::crc32(id);
        if(hashes.contains(hash))issue("Runtime ID hash collision: " + id);
        else hashes[hash] = id;
      }
    }

    std::string type{};
    if(!element.contains("type") || !element["type"].is_string())issue("Element type must be a string", true);
    else {
      type = element["type"].get<std::string>();
      constexpr std::array TYPES{"Container", "Image", "Text", "Button", "TextInput", "ProgressBar"};
      if(std::find(TYPES.begin(), TYPES.end(), type) == TYPES.end())issue("Unsupported element type: " + type);
    }
    if(type == "Button" || type == "TextInput")focusableIds.insert(id);

    if(!element.contains("layout") || !element["layout"].is_object())issue("Element " + id + " needs a layout object", true);
    else {
      const auto &layout = element["layout"];
      for(const char *field : {"anchors", "offsets"}) {
        if(!layout.contains(field) || !layout[field].is_array() || layout[field].size() != 4 ||
           std::any_of(layout[field].begin(), layout[field].end(), [](const auto &value) { return !value.is_number(); })) {
          issue("Element " + id + " layout." + field + " must contain four numbers", true);
        }
      }
      if(layout.contains("anchors") && layout["anchors"].is_array() && layout["anchors"].size() == 4 &&
         std::all_of(layout["anchors"].begin(), layout["anchors"].end(), [](const auto &value) { return value.is_number(); })) {
        const auto &values = layout["anchors"];
        bool invalid = std::any_of(values.begin(), values.end(), [](const auto &value) {
          auto number = value.template get<double>(); return number < 0.0 || number > 1.0;
        });
        if(invalid || values[0].get<double>() > values[2].get<double>() || values[1].get<double>() > values[3].get<double>()) {
          issue("Element " + id + " anchors must be ordered values in 0..1");
        }
      }
      if(layout.contains("offsets") && layout["offsets"].is_array() && layout["offsets"].size() == 4 &&
         std::all_of(layout["offsets"].begin(), layout["offsets"].end(), [](const auto &value) { return value.is_number(); })) {
        if(std::any_of(layout["offsets"].begin(), layout["offsets"].end(), [](const auto &value) {
          auto number = value.template get<double>();
          return number < -32768.0 || number > 32767.0 || std::floor(number) != number;
        }))issue("Element " + id + " offsets must be signed 16-bit integers");
      }
      const auto flow = layout.value("flow", std::string{"none"});
      if(flow != "none" && flow != "vertical" && flow != "horizontal") {
        issue("Element " + id + " flow must be none, vertical, or horizontal");
      } else if(flow != "none" && type != "Container") {
        issue("Element " + id + " flow is only supported on Container elements");
      }
      const auto gapValue = layout.value("gap", nlohmann::json{0});
      if(!gapValue.is_number_integer() || gapValue.get<int64_t>() < 0 || gapValue.get<int64_t>() > 32767) {
        issue("Element " + id + " flow gap must be an integer in 0..32767");
      }
    }
    for(const char *field : {"visible", "enabled"})if(element.contains(field) && !element[field].is_boolean()) {
      issue("Element " + id + " " + field + " must be a boolean", true);
    }
    if(element.contains("style")) {
      if(!element["style"].is_object())issue("Element " + id + " style must be an object", true);
      else for(const char *field : {"color", "textColor", "focusColor", "fillColor"}) {
        if(element["style"].contains(field) && !validColor(element["style"][field])) {
          issue("Element " + id + " style." + field + " must be #RRGGBBAA", true);
        }
      }
    }

    if(type == "Image") {
      auto asset = element.contains("asset") ? resolveAssetRef(element["asset"]) : nullptr;
      if(!asset || asset->type != Project::FileType::IMAGE)issue("Element " + id + " needs a valid image asset");
      if(element.contains("fit") && (!element["fit"].is_string() ||
         (element["fit"] != "stretch" && element["fit"] != "native")))issue("Element " + id + " fit must be stretch or native", true);
    }
    if(type == "Text" || type == "Button" || type == "TextInput") {
      auto font = element.contains("font") ? resolveAssetRef(element["font"]) : nullptr;
      if(!font || font->type != Project::FileType::FONT)issue("Element " + id + " needs a valid font asset");
      else if(font->conf.fontId.value < 1 || font->conf.fontId.value > 15)issue("Element " + id + " font needs auto-load ID 1..15");
      if(element.contains("align") && (!element["align"].is_string() ||
         (element["align"] != "left" && element["align"] != "center" && element["align"] != "right"))) {
        issue("Element " + id + " alignment must be left, center, or right", true);
      }
      if(element.contains("text") && !element["text"].is_string())issue("Element " + id + " text must be a string", true);
    }
    if(type == "TextInput") {
      for(const char *field : {"value", "placeholder", "charset"})if(element.contains(field) && !element[field].is_string()) {
        issue("Element " + id + " " + field + " must be a string", true);
      }
      if(!element.contains("charset") || !element["charset"].is_string() || element["charset"].get<std::string>().empty()) {
        issue("Element " + id + " needs a non-empty controller charset");
      }
      int64_t maxLength = 32;
      if(element.contains("maxLength")) {
        if(!element["maxLength"].is_number_integer())issue("Element " + id + " maxLength must be an integer", true);
        else maxLength = element["maxLength"].get<int64_t>();
      }
      if(maxLength < 1 || maxLength > 256)issue("Element " + id + " maxLength must be from 1 to 256");
      if(element.contains("value") && element["value"].is_string() && element["value"].get<std::string>().size() > static_cast<size_t>(std::max<int64_t>(0, maxLength))) {
        issue("Element " + id + " initial value exceeds maxLength");
      }
      if(element.contains("submitOnStart") && !element["submitOnStart"].is_boolean()) {
        issue("Element " + id + " submitOnStart must be a boolean", true);
      }
    }
    if(type == "ProgressBar") {
      int64_t maximum = 100;
      if(!element.contains("max") || !element["max"].is_number_integer()) {
        issue("Element " + id + " ProgressBar max must be an integer", true);
      } else maximum = element["max"].get<int64_t>();
      if(maximum < 1 || maximum > 0xFFFF)issue("Element " + id + " ProgressBar max must be from 1 to 65535");
      if(!element.contains("value") || !element["value"].is_number_integer()) {
        issue("Element " + id + " ProgressBar value must be an integer", true);
      } else {
        auto value = element["value"].get<int64_t>();
        if(value < 0 || value > maximum)issue("Element " + id + " ProgressBar value must be in 0..max");
      }
      if(element.contains("thresholds")) {
        const auto &thresholds = element["thresholds"];
        if(!thresholds.is_array() || thresholds.size() > 3) {
          issue("Element " + id + " ProgressBar thresholds must be an array with at most three entries", true);
        } else {
          int64_t previous = -1;
          for(const auto &threshold : thresholds) {
            if(!threshold.is_object()) {
              issue("Element " + id + " ProgressBar threshold must be an object", true);
              continue;
            }
            if(!threshold.contains("max") || !threshold["max"].is_number_integer()) {
              issue("Element " + id + " ProgressBar threshold max must be an integer", true);
            } else {
              auto thresholdMax = threshold["max"].get<int64_t>();
              if(thresholdMax < 0 || thresholdMax > maximum || thresholdMax <= previous) {
                issue("Element " + id + " ProgressBar thresholds must be strictly ascending in 0..max");
              }
              previous = thresholdMax;
            }
            if(!threshold.contains("color") || !validColor(threshold["color"])) {
              issue("Element " + id + " ProgressBar threshold color must be #RRGGBBAA", true);
            }
          }
        }
      }
    }
    if(type == "Button" || type == "TextInput") {
      if(element.contains("focus")) {
        if(!element["focus"].is_object())issue("Element " + id + " focus must be an object", true);
        else for(const char *direction : {"up", "down", "left", "right"})if(element["focus"].contains(direction)) {
          if(!element["focus"][direction].is_string())issue("Element " + id + " focus target must be a string", true);
          else focusRefs.emplace_back(id, direction, element["focus"][direction].get<std::string>());
        }
      }
    }

    if(element.contains("children")) {
      if(!element["children"].is_array())issue("Element " + id + " children must be an array", true);
      else for(auto &child : element["children"])check(child);
    }
  };
  if(document.contains("root"))check(document["root"]); else issue("Document has no root element", true);
  if(elementCount > 256)issue("Document exceeds the 256 element runtime limit");
  for(const auto &[source, direction, target] : focusRefs) {
    if(!ids.contains(target))issue("Element " + source + " focus." + direction + " target does not exist: " + target);
    else if(!focusableIds.contains(target))issue("Element " + source + " focus." + direction + " target is not focusable: " + target);
  }
}

bool Editor::UIEditor::draw(ImGuiID dockId)
{
  validate();
  std::string title = ICON_MDI_MONITOR_DASHBOARD " UI: " + name + (dirty ? " *" : "") + "###UI_" + std::to_string(assetUUID);
  ImGui::SetNextWindowDockID(dockId, ImGuiCond_FirstUseEver);
  if(!ImGui::Begin(title.c_str(), &open, ImGuiWindowFlags_MenuBar)) {
    ImGui::End();
    if(!open && dirty) { open = true; confirmClose = true; }
    return open;
  }
  if(dirty && ImGui::IsWindowFocused(ImGuiFocusedFlags_RootAndChildWindows) &&
     ImGui::IsKeyChordPressed(ImGuiMod_Ctrl | ImGuiKey_S))save();
  if(ImGui::BeginMenuBar()) {
    if(ImGui::MenuItem(ICON_MDI_CONTENT_SAVE " Save", "Ctrl+S", false, dirty))save();
    if(ImGui::MenuItem(ICON_MDI_REFRESH " Reload"))reload();
    if(ImGui::BeginMenu(ICON_MDI_PLUS " Add")) {
      for(const char *type : {"Container", "Image", "Text", "Button", "TextInput", "ProgressBar"})if(ImGui::MenuItem(type))addElement(type);
      ImGui::EndMenu();
    }
    ImGui::TextDisabled("320x240-style preview; emulator output is authoritative");
    ImGui::EndMenuBar();
  }

  if(ImGui::BeginTable("UIEditorLayout", 3, ImGuiTableFlags_Resizable | ImGuiTableFlags_BordersInnerV)) {
    ImGui::TableSetupColumn("Hierarchy", ImGuiTableColumnFlags_WidthFixed, 220_px);
    ImGui::TableSetupColumn("Canvas", ImGuiTableColumnFlags_WidthStretch);
    ImGui::TableSetupColumn("Inspector", ImGuiTableColumnFlags_WidthFixed, 300_px);
    ImGui::TableNextColumn();
    ImGui::BeginChild("HierarchyPane");
    if(documentUsable && document.contains("root"))drawHierarchy(document["root"]);
    ImGui::SeparatorText("Validation");
    if(validationIssues.empty())ImGui::TextColored({0.4f,0.9f,0.5f,1}, ICON_MDI_CHECK " Valid");
    for(const auto &problem : validationIssues)ImGui::TextWrapped(ICON_MDI_ALERT " %s", problem.c_str());
    ImGui::EndChild();
    ImGui::TableNextColumn();
    ImGui::BeginChild("CanvasPane");
    if(documentUsable)drawCanvas(); else ImGui::TextDisabled("Fix structural validation errors before previewing this document.");
    ImGui::EndChild();
    ImGui::TableNextColumn();
    ImGui::BeginChild("InspectorPane");
    if(documentUsable)drawInspector(); else ImGui::TextDisabled("Inspector unavailable for a malformed document.");
    ImGui::EndChild();
    ImGui::EndTable();
  }
  ImGui::End();

  if(!open && dirty) { open = true; confirmClose = true; }
  std::string popup = "Unsaved UI Document###UI_Close_" + std::to_string(assetUUID);
  if(confirmClose)ImGui::OpenPopup(popup.c_str());
  if(ImGui::BeginPopupModal(popup.c_str(), nullptr, ImGuiWindowFlags_AlwaysAutoResize)) {
    ImGui::Text("%s has unsaved changes.", name.c_str());
    if(ImGui::Button("Save", {100_px, 0})) { save(); open = false; confirmClose = false; ImGui::CloseCurrentPopup(); }
    ImGui::SameLine();
    if(ImGui::Button("Discard", {100_px, 0})) { dirty = false; open = false; confirmClose = false; ImGui::CloseCurrentPopup(); }
    ImGui::SameLine();
    if(ImGui::Button("Cancel", {100_px, 0})) { confirmClose = false; ImGui::CloseCurrentPopup(); }
    ImGui::EndPopup();
  }
  return open;
}
