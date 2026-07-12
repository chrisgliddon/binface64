/**
* @copyright 2025 - Max Bebök
* @license MIT
*/
#include "editorScene.h"

#include "IconsMaterialDesignIcons.h"
#include "imgui.h"
#include "imgui_internal.h"
#include "../actions.h"
#include "../undoRedo.h"
#include "../selectionUtils.h"
#include "../../context.h"

#define IMVIEWGUIZMO_IMPLEMENTATION 1
#include "ImGuizmo.h"
#include "ImViewGuizmo.h"
#include "../../utils/logger.h"
#include "../../utils/ringBuffer.h"
#include "../../utils/updater.h"
#include "../imgui/notification.h"
#include "../imgui/theme.h"
#include "parts/assets/modelEditor.h"
#include <algorithm>
#include <filesystem>

namespace
{
  constinit bool preferencesOpen{false};
  constinit bool projectSettingsOpen{false};
  constinit bool needsSanityCheck{false};
  constinit Utils::RingBuffer<double, 16> fpsRingBuffer{};

  const char* assetTypeLabel(Project::FileType type)
  {
    using FT = Project::FileType;
    switch(type) {
      case FT::IMAGE: return "Texture";
      case FT::AUDIO: return "Audio";
      case FT::MUSIC_XM: return "XM Music";
      case FT::MODEL_3D: return "3D Model";
      case FT::FONT: return "Font";
      case FT::NODE_GRAPH: return "Node Graph";
      case FT::UI_DOCUMENT: return "UI Document";
      case FT::PREFAB: return "Prefab";
      default: return "Other";
    }
  }

  bool focusAccepts(const std::string &area, const Project::AssetManagerEntry &asset)
  {
    using FT = Project::FileType;
    if(area == "music")return asset.type == FT::MUSIC_XM || asset.type == FT::AUDIO;
    if(area == "sfx")return asset.type == FT::AUDIO;
    if(area == "environment")return asset.type == FT::MODEL_3D || asset.type == FT::IMAGE;
    if(area == "avatar")return asset.type == FT::MODEL_3D;
    if(area == "cutscene")return asset.type == FT::NODE_GRAPH || asset.type == FT::UI_DOCUMENT
      || asset.type == FT::AUDIO || asset.type == FT::MUSIC_XM;
    return false;
  }

  std::vector<std::string> focusTags(const Project::AssetManagerEntry &asset)
  {
    std::vector<std::string> tags{};
    if(!asset.conf.data.is_object())return tags;
    auto values = asset.conf.data.value("focusAreas", nlohmann::json::array());
    if(values.is_array()) {
      for(const auto &value : values)if(value.is_string())tags.push_back(value.get<std::string>());
    }
    auto legacy = asset.conf.data.value("focusArea", std::string{});
    if(!legacy.empty() && std::find(tags.begin(), tags.end(), legacy) == tags.end())tags.push_back(legacy);
    return tags;
  }

  bool hasFocusTag(const Project::AssetManagerEntry &asset, const std::string &area)
  {
    auto tags = focusTags(asset);
    return std::find(tags.begin(), tags.end(), area) != tags.end();
  }

  void setFocusTag(Project::AssetManagerEntry &asset, const std::string &area, bool enabled)
  {
    auto tags = focusTags(asset);
    auto found = std::find(tags.begin(), tags.end(), area);
    if(enabled && found == tags.end())tags.push_back(area);
    if(!enabled && found != tags.end())tags.erase(found);
    if(!asset.conf.data.is_object())asset.conf.data = nlohmann::json::object();
    asset.conf.data["focusAreas"] = tags;
    asset.conf.data.erase("focusArea");
    ctx.project->getAssets().markAssetMetaDirty(asset.getUUID());
  }

  const char* focusIcon(const std::string &area)
  {
    if(area == "music")return ICON_MDI_MUSIC;
    if(area == "sfx")return ICON_MDI_VOLUME_HIGH;
    if(area == "environment")return ICON_MDI_TERRAIN;
    if(area == "avatar")return ICON_MDI_HUMAN;
    if(area == "cutscene")return ICON_MDI_MOVIE_OPEN;
    return ICON_MDI_FOLDER_STAR;
  }
}

Editor::Scene::Scene()
{
  try { focusCatalog = Utils::JSON::loadFile(std::string{"data/focus-areas.json"}); }
  catch(...) { focusCatalog = nlohmann::json{{"areas", nlohmann::json::array()}}; }
  Editor::Actions::registerAction(Editor::Actions::Type::OPEN_NODE_GRAPH, [this](const std::string& asset)
  {
    printf("OPEN_NODE_GRAPH action called with asset: %s\n", asset.c_str());
    if(!ctx.project)return false;
    auto assetEntry = ctx.project->getAssets().getEntryByUUID(std::stoull(asset));
    if(assetEntry) {
      nodeEditors.push_back(std::make_unique<NodeEditor>(assetEntry->getUUID()));
      return true;
    }
    return false;
  });
  Editor::Actions::registerAction(Editor::Actions::Type::OPEN_UI_DOCUMENT, [this](const std::string &asset)
  {
    if(!ctx.project)return false;
    openUIEditor(std::stoull(asset));
    return true;
  });
  needsSanityCheck = true;

  loadSession();
  if(viewports.empty()) addViewport();
}

void Editor::Scene::addViewport()
{
  viewports.push_back(std::make_shared<Viewport3D>(nextViewportWinId));
  ++nextViewportWinId;
}

Editor::Scene::~Scene()
{
  // The active project's windows are persisted when it is torn down (see persistOpenWindows).
  Editor::Actions::registerAction(Editor::Actions::Type::OPEN_NODE_GRAPH, nullptr);
  Editor::Actions::registerAction(Editor::Actions::Type::OPEN_UI_DOCUMENT, nullptr);
}

void Editor::Scene::loadSession()
{
  try
  {
    auto json = Utils::JSON::loadFile(Utils::Proc::getAppDataPath() / "editorScene.json");
    if(json.contains("projects")) {
      for(const auto& [path, w] : json["projects"].items()) {
        WindowSet ws{};
        if(w.contains("winModels")) for(const auto& u : w["winModels"]) ws.models.push_back(u.get<uint64_t>());
        if(w.contains("winGraphs")) for(const auto& u : w["winGraphs"]) ws.graphs.push_back(u.get<uint64_t>());
        if(w.contains("winUI")) for(const auto& u : w["winUI"]) ws.ui.push_back(u.get<uint64_t>());
        sessionWindows[path] = std::move(ws);
      }
    }
    if(json.contains("viewports") && json["viewports"].is_array()) {
      for(const auto& v : json["viewports"]) {
        uint32_t id = v.value("winId", nextViewportWinId);
        auto vp = std::make_shared<Viewport3D>(id);
        vp->loadState(v);
        viewports.push_back(std::move(vp));
        nextViewportWinId = std::max(nextViewportWinId, id + 1);
      }
    }
    activeFocusArea = json.value("activeFocusArea", std::string{});
    if(!activeFocusArea.empty())activeWorkspace = Workspace::FOCUS;
  } catch(const std::exception& e) {}
}

void Editor::Scene::saveSession()
{
  nlohmann::json conf{};
  conf["projects"] = nlohmann::json::object();
  for(const auto& [path, ws] : sessionWindows) {
    conf["projects"][path] = { {"winModels", ws.models}, {"winGraphs", ws.graphs}, {"winUI", ws.ui} };
  }
  conf["viewports"] = nlohmann::json::array();
  for(const auto& vp : viewports) {
    conf["viewports"].push_back(vp->saveState());
  }
  conf["activeFocusArea"] = activeWorkspace == Workspace::FOCUS ? activeFocusArea : std::string{};
  Utils::FS::saveTextFile(Utils::Proc::getAppDataPath() / "editorScene.json", conf.dump(2));
}

void Editor::Scene::persistOpenWindows()
{
  if(!ctx.project)return;
  WindowSet ws{};
  for(const auto& [assetUUID, _] : modelEditors) ws.models.push_back(assetUUID);
  for(const auto& nodeEditor : nodeEditors) {
    if(nodeEditor && nodeEditor->getAssetUUID() != 0) ws.graphs.push_back(nodeEditor->getAssetUUID());
  }
  for(const auto &[assetUUID, _] : uiEditors)ws.ui.push_back(assetUUID);
  sessionWindows[ctx.project->getPath()] = std::move(ws);
  saveSession();
}

void Editor::Scene::closeAllEditors()
{
  nodeEditors.clear();
  modelEditors.clear();
  uiEditors.clear();
  pendingNodeEditorCloseUUID = 0;
  pendingNodeEditorClosePopup = false;
}

void Editor::Scene::onProjectClosing()
{
  persistOpenWindows();
  closeAllEditors();
  restoredForProject.clear();
}

void Editor::Scene::restoreWindows()
{
  auto it = sessionWindows.find(ctx.project->getPath());
  if(it == sessionWindows.end())return;
  for(auto uuid : it->second.models) {
    if(ctx.project->getAssets().getEntryByUUID(uuid)) openModelEditor(uuid);
  }
  for(auto uuid : it->second.graphs) {
    if(ctx.project->getAssets().getEntryByUUID(uuid)) {
      nodeEditors.push_back(std::make_shared<NodeEditor>(uuid));
    }
  }
  for(auto uuid : it->second.ui)if(ctx.project->getAssets().getEntryByUUID(uuid))openUIEditor(uuid);
}

void Editor::Scene::openModelEditor(uint64_t assetUUID)
{
  auto it = modelEditors.find(assetUUID);
  if(it != modelEditors.end()) {
    it->second->focus();
  } else {
    modelEditors[assetUUID] = std::make_unique<ModelEditor>(assetUUID);
  }
}

void Editor::Scene::openUIEditor(uint64_t assetUUID)
{
  activeWorkspace = Workspace::UI;
  activeFocusArea.clear();
  auto it = uiEditors.find(assetUUID);
  if(it != uiEditors.end())it->second->focus();
  else uiEditors[assetUUID] = std::make_shared<UIEditor>(assetUUID);
}

void Editor::Scene::drawFocusWorkspace(ImGuiID dockSpaceID)
{
  if(activeWorkspace != Workspace::FOCUS || activeFocusArea.empty())return;

  nlohmann::json area{};
  for(const auto &candidate : focusCatalog.value("areas", nlohmann::json::array())) {
    if(candidate.value("id", std::string{}) == activeFocusArea) {
      area = candidate;
      break;
    }
  }
  if(!area.is_object())return;

  auto label = area.value("label", activeFocusArea);
  std::string title = std::string{focusIcon(activeFocusArea)} + " " + label + " Focus";
  ImGui::SetNextWindowDockID(dockSpaceID, ImGuiCond_FirstUseEver);
  ImGui::Begin(title.c_str());
  ImGui::TextWrapped("%s", area.value("description", std::string{}).c_str());
  ImGui::TextDisabled("Tag compatible assets here; the same membership is used by bf64 %s ls/validate/tag.", activeFocusArea.c_str());
  ImGui::Separator();

  int compatibleCount = 0;
  int taggedCount = 0;
  if(ImGui::BeginTable("FocusAssets", 4, ImGuiTableFlags_RowBg | ImGuiTableFlags_BordersInnerV | ImGuiTableFlags_Resizable)) {
    ImGui::TableSetupColumn("Asset", ImGuiTableColumnFlags_WidthStretch);
    ImGui::TableSetupColumn("Kind", ImGuiTableColumnFlags_WidthFixed, 100_px);
    ImGui::TableSetupColumn("Membership", ImGuiTableColumnFlags_WidthFixed, 90_px);
    ImGui::TableSetupColumn("Path", ImGuiTableColumnFlags_WidthStretch);
    ImGui::TableHeadersRow();

    for(const auto &typed : ctx.project->getAssets().getEntries()) {
      for(const auto &asset : typed) {
        if(!focusAccepts(activeFocusArea, asset))continue;
        ++compatibleCount;
        bool tagged = hasFocusTag(asset, activeFocusArea);
        if(tagged)++taggedCount;

        ImGui::PushID(static_cast<int>(asset.getUUID()));
        ImGui::TableNextRow();
        ImGui::TableSetColumnIndex(0);
        bool selected = ctx.selAssetUUID == asset.getUUID();
        if(ImGui::Selectable(asset.name.c_str(), selected, ImGuiSelectableFlags_SpanAllColumns)) {
          ctx.selAssetUUID = asset.getUUID();
        }
        bool open = ImGui::IsItemHovered() && ImGui::IsMouseDoubleClicked(ImGuiMouseButton_Left);

        ImGui::TableSetColumnIndex(1);
        ImGui::TextUnformatted(assetTypeLabel(asset.type));
        ImGui::TableSetColumnIndex(2);
        if(ImGui::SmallButton(tagged ? "Remove" : "Add")) {
          if(auto *mutableAsset = ctx.project->getAssets().getEntryByUUID(asset.getUUID())) {
            setFocusTag(*mutableAsset, activeFocusArea, !tagged);
          }
        }
        ImGui::TableSetColumnIndex(3);
        ImGui::TextUnformatted(asset.path.c_str());

        if(open) {
          if(asset.type == Project::FileType::MODEL_3D)openModelEditor(asset.getUUID());
          else if(asset.type == Project::FileType::NODE_GRAPH)Actions::call(Actions::Type::OPEN_NODE_GRAPH, std::to_string(asset.getUUID()));
          else if(asset.type == Project::FileType::UI_DOCUMENT)openUIEditor(asset.getUUID());
        }
        ImGui::PopID();
      }
    }
    ImGui::EndTable();
  }

  if(compatibleCount == 0)ImGui::TextDisabled("No compatible assets yet. Import content, then return here to assign it.");
  ImGui::Separator();
  ImGui::Text("%d tagged / %d compatible", taggedCount, compatibleCount);
  ImGui::SameLine();
  if(ImGui::Button(ICON_MDI_CONTENT_SAVE_OUTLINE " Save Tags"))ctx.project->save();
  ImGui::End();
}

void Editor::Scene::draw()
{
  // Safe point to destroy viewports closed last frame: their render has completed.
  viewportsPendingClose.clear();

  // On a project switch, close the previous project's windows and restore this one's.
  if(ctx.project && ctx.project->getPath() != restoredForProject) {
    closeAllEditors();
    restoredForProject = ctx.project->getPath();
    restoreWindows();
  }

  float HEIGHT_TOP_BAR = 28_px;
  float HEIGHT_STATUS_BAR = 24_px;

  ImViewGuizmo::BeginFrame();
  ImGuizmo::BeginFrame();

  auto &io = ImGui::GetIO();
  auto viewport = ImGui::GetMainViewport();

  bool isRunning = ctx.isBuildOrRunning();

  ImGui::SetNextWindowPos({0, HEIGHT_TOP_BAR});
  ImGui::SetNextWindowSize({
    viewport->WorkSize.x,
    viewport->WorkSize.y - HEIGHT_TOP_BAR - HEIGHT_STATUS_BAR,
  });
  ImGui::SetNextWindowViewport(viewport->ID);

  ImGuiWindowFlags host_window_flags = 0;
  host_window_flags |= ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoDocking;
  host_window_flags |= ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoNavFocus;

  ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
  ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
  ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, {0,0});
  ImGui::Begin("MAIN_DOCK", NULL, host_window_flags);
  ImGui::PopStyleVar(3);

  auto dockSpaceID = ImGui::GetID("DockSpace");
  auto dockSpace = ImGui::DockBuilderGetNode(dockSpaceID);

  dockSpaceID = ImGui::DockSpace(dockSpaceID, ImVec2(0.0f, 0.0f), 0, 0);
  ImGui::End();

  if(!dockSpace)
  {
    ImGui::DockBuilderRemoveNode(dockSpaceID); // Clear out existing layout
    ImGui::DockBuilderAddNode(dockSpaceID); // Add empty node
    ImGui::DockBuilderSetNodeSize(dockSpaceID, ImGui::GetMainViewport()->Size);

    dockLeftID = ImGui::DockBuilderSplitNode(dockSpaceID, ImGuiDir_Left, 0.15f, nullptr, &dockSpaceID);
    dockRightID = ImGui::DockBuilderSplitNode(dockSpaceID, ImGuiDir_Right, 0.25f, nullptr, &dockSpaceID);
    dockBottomID = ImGui::DockBuilderSplitNode(dockSpaceID, ImGuiDir_Down, 0.25f, nullptr, &dockSpaceID);

    // Center
    ImGui::DockBuilderDockWindow("3D-Viewport", dockSpaceID);
    // ImGui::DockBuilderDockWindow("Node-Editor", dockSpaceID);

    // Left
    //ImGui::DockBuilderDockWindow("Project", dockLeftID);
    ImGui::DockBuilderDockWindow("Scene", dockLeftID);
    ImGui::DockBuilderDockWindow("Graph", dockLeftID);
    ImGui::DockBuilderDockWindow("Layers", dockLeftID);

    // Right
    ImGui::DockBuilderDockWindow("Asset", dockRightID);
    ImGui::DockBuilderDockWindow("Object", dockRightID);
    ImGui::DockBuilderDockWindow("Model", dockRightID);

    // Bottom
    ImGui::DockBuilderDockWindow("Files", dockBottomID);
    ImGui::DockBuilderDockWindow("Log", dockBottomID);
    ImGui::DockBuilderDockWindow("ROM", dockBottomID);

    ImGui::DockBuilderFinish(dockSpaceID);
  }

  hoveredViewport = nullptr;
  ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(2_px, 2_px));
  std::vector<size_t> viewportsToClose{};
  for(size_t i = 0; i < viewports.size(); ++i) {
    auto &vp = viewports[i];
    bool open = true;
    std::string title = vp->getWindowTitle();
    if(ImGui::Begin(title.c_str(), &open)) {
      // Right-clicking the docked tab offers opening another viewport.
      ImGuiWindow* win = ImGui::GetCurrentWindow();
      if(win->DockIsActive &&
         ImGui::IsMouseHoveringRect(win->DC.DockTabItemRect.Min, win->DC.DockTabItemRect.Max, false) &&
         ImGui::IsMouseClicked(ImGuiMouseButton_Right)) {
        ImGui::OpenPopup("ViewportTabCtx");
      }
      if(ImGui::BeginPopup("ViewportTabCtx")) {
        if(ImGui::MenuItem(ICON_MDI_PLUS " New Viewport")) wantNewViewport = true;
        ImGui::EndPopup();
      }
      vp->draw();
      if(vp->isViewHovered()) hoveredViewport = vp;
    }
    ImGui::End();
    if(!open) viewportsToClose.push_back(i);
  }
  ImGui::PopStyleVar(1);

  bool viewportsChanged = !viewportsToClose.empty();
  for(auto it = viewportsToClose.rbegin(); it != viewportsToClose.rend(); ++it) {
    viewports[*it]->detach();
    viewportsPendingClose.push_back(std::move(viewports[*it]));
    viewports.erase(viewports.begin() + *it);
  }
  if(wantNewViewport) {
    wantNewViewport = false;
    addViewport();
    viewportsChanged = true;
  }
  if(wantResetLayout) {
    wantResetLayout = false;
    // Collapse to a single default viewport so the rebuilt layout has a center window.
    hoveredViewport = nullptr;
    for(auto &vp : viewports) { vp->detach(); viewportsPendingClose.push_back(std::move(vp)); }
    viewports.clear();
    nextViewportWinId = 0;
    addViewport();
    viewportsChanged = true;
    ImGui::DockBuilderRemoveNode(dockSpaceID);
  }
  if(viewportsChanged) saveSession();

  std::vector<uint32_t> delIndices{};
  for(uint32_t i = 0; i < nodeEditors.size(); ++i) {
    auto &nodeEditor = nodeEditors[i];
    if (!nodeEditor->draw(dockSpaceID)) {
      if (nodeEditor->isDirty()) {
        pendingNodeEditorCloseUUID = nodeEditor->getAssetUUID();
        pendingNodeEditorClosePopup = true;
      } else {
        delIndices.push_back(i);
      }
    }
  }
  // Remove closed editors
  for(int32_t i = (int32_t)delIndices.size() - 1; i >= 0; --i) {
    nodeEditors.erase(nodeEditors.begin() + delIndices[i]);
  }

  if (pendingNodeEditorClosePopup) {
    ImGui::OpenPopup("Unsaved Node Graph");
    pendingNodeEditorClosePopup = false;
  }

  if (ImGui::BeginPopupModal("Unsaved Node Graph", nullptr, ImGuiWindowFlags_AlwaysAutoResize)) {
    auto itEditor = std::find_if(nodeEditors.begin(), nodeEditors.end(), [&](const std::shared_ptr<NodeEditor> &editor) {
      return editor && editor->getAssetUUID() == pendingNodeEditorCloseUUID;
    });

    if (itEditor == nodeEditors.end()) {
      pendingNodeEditorCloseUUID = 0;
      ImGui::CloseCurrentPopup();
    } else {
      auto &editor = *itEditor;
      ImGui::Text("The node graph '%s' has unsaved changes.", editor->getName().c_str());
      ImGui::Spacing();
      if (ImGui::Button("Save", {100_px, 0})) {
        editor->save();
        nodeEditors.erase(itEditor);
        pendingNodeEditorCloseUUID = 0;
        ImGui::CloseCurrentPopup();
      }
      ImGui::SameLine();
      if (ImGui::Button("Discard", {100_px, 0})) {
        editor->discardUnsavedChanges();
        nodeEditors.erase(itEditor);
        pendingNodeEditorCloseUUID = 0;
        ImGui::CloseCurrentPopup();
      }
      ImGui::SameLine();
      if (ImGui::Button("Cancel", {100_px, 0})) {
        pendingNodeEditorCloseUUID = 0;
        ImGui::CloseCurrentPopup();
      }
    }
    ImGui::EndPopup();
  }

  std::vector<uint64_t> delUUIDs{};
  for(auto &[uuid, editor] : modelEditors) {
    if (!editor->draw(dockSpaceID)) {
      delUUIDs.push_back(uuid);
    }
  }
  for(auto &uuid : delUUIDs)modelEditors.erase(uuid);

  delUUIDs.clear();
  for(auto &[uuid, editor] : uiEditors) {
    if(!editor->draw(dockSpaceID))delUUIDs.push_back(uuid);
  }
  for(auto uuid : delUUIDs)uiEditors.erase(uuid);

  if(activeWorkspace == Workspace::UI && uiEditors.empty())
  {
    ImGui::SetNextWindowDockID(dockSpaceID, ImGuiCond_FirstUseEver);
    ImGui::Begin(ICON_MDI_MONITOR_DASHBOARD " UI Workspace");
    ImGui::TextUnformatted("UI documents");
    ImGui::Separator();
    const auto &documents = ctx.project->getAssets().getTypeEntries(Project::FileType::UI_DOCUMENT);
    for(const auto &document : documents) {
      ImGui::PushID(static_cast<int>(document.getUUID()));
      if(ImGui::Selectable((ICON_MDI_FILE_DOCUMENT_OUTLINE " " + document.name).c_str()))openUIEditor(document.getUUID());
      ImGui::PopID();
    }
    if(documents.empty())ImGui::TextDisabled("No .bfui documents yet.");
    if(ImGui::Button(ICON_MDI_PLUS " Create UI Document")) {
      std::string name = "New_UI";
      uint32_t suffix = 2;
      while(ctx.project->getAssets().getByName(name + ".bfui"))name = "New_UI_" + std::to_string(suffix++);
      auto uuid = ctx.project->getAssets().createUIDocument(name);
      if(uuid)openUIEditor(uuid);
    }
    ImGui::End();
  }

  drawFocusWorkspace(dockSpaceID);

  ImGui::Begin("Object");
    objectInspector.draw();
  ImGui::End();

  ImGui::Begin("Asset");
    assetInspector.draw();
  ImGui::End();

  ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(2_px, 2_px));
  ImGui::Begin("Files");
  ImGui::PopStyleVar();
    assetsBrowser.draw();
  ImGui::End();

  if (ctx.project->getScenes().getLoadedScene()) {

    ImGui::Begin("Graph");
      sceneGraph.draw();
    ImGui::End();

    ImGui::Begin("Scene");
      sceneInspector.draw();
    ImGui::End();

    ImGui::Begin("Layers");
      layerInspector.draw();
    ImGui::End();
  }

  ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(2_px, 2_px));
  ImGui::Begin("Log");
  ImGui::PopStyleVar();;
    logWindow.draw();
  ImGui::End();

  ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(4_px, 4_px));
  ImGui::Begin("ROM");
  ImGui::PopStyleVar();
    memoryDashboard.draw();
  ImGui::End();

  if (preferencesOpen) {
    ImVec2 windowSize{500_px, 300_px};
    auto screenSize = ImGui::GetMainViewport()->WorkSize;
    ImGui::SetNextWindowPos({(screenSize.x - windowSize.x) / 2, (screenSize.y - windowSize.y) / 2}, ImGuiCond_Appearing, {0.0f, 0.0f});
    ImGui::SetNextWindowSize(windowSize, ImGuiCond_Appearing);

    // Thick borders
    ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 2.0_px);
    ImGui::PushStyleColor(ImGuiCol_Border, ImGui::GetStyleColorVec4(ImGuiCol_ButtonActive));
    ImGui::Begin(ICON_MDI_COG " Preferences", &preferencesOpen, ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoDocking);
    if (prefOverlay.draw()) {
      preferencesOpen = false;
    }
    ImGui::End();

    ImGui::PopStyleColor(1);
    ImGui::PopStyleVar(1);
  }

  if (projectSettingsOpen) {
    ImVec2 windowSize{600_px,400_px};
    auto screenSize = ImGui::GetMainViewport()->WorkSize;
    ImGui::SetNextWindowPos({(screenSize.x - windowSize.x) / 2, (screenSize.y - windowSize.y) / 2}, ImGuiCond_Appearing, {0.0f, 0.0f});
    ImGui::SetNextWindowSize(windowSize, ImGuiCond_Appearing);

    // Thick borders
    ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 2.0_px);
    ImGui::PushStyleColor(ImGuiCol_Border, ImGui::GetStyleColorVec4(ImGuiCol_ButtonActive));
    ImGui::Begin(ICON_MDI_FILE_COG_OUTLINE " Project Settings", &projectSettingsOpen,
      ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoDocking |
      ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse
    );
    if (projectSettings.draw()) {
      projectSettingsOpen = false;
    }
    ImGui::End();

    ImGui::PopStyleColor(1);
    ImGui::PopStyleVar(1);
  }

  // Top bar
  ImGui::SetNextWindowPos({0,0}, ImGuiCond_Always);
  ImGui::SetNextWindowSize({io.DisplaySize.x, 4}, ImGuiCond_Always);
  ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2{8_px,6_px});
  if(ImGui::Begin("TOP_BAR", 0,
    ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoTitleBar
    | ImGuiWindowFlags_MenuBar | ImGuiWindowFlags_NoBackground | ImGuiWindowFlags_NoDocking
  )) {
    if(ImGui::BeginMenuBar())
    {
      if(ImGui::BeginMenu("Project"))
      {
        if(ImGui::MenuItem(ICON_MDI_CONTENT_SAVE_OUTLINE " Save")) {
          ctx.project->save();
          save();
        }
        if(ImGui::MenuItem(ICON_MDI_FILE_COG_OUTLINE " Settings"))projectSettingsOpen = true;
        if(ImGui::MenuItem(ICON_MDI_CLOSE " Close"))Actions::call(Actions::Type::PROJECT_CLOSE);
        ImGui::EndMenu();
      }

      // Edit Menu with undo/redo functionality including description
      if(ImGui::BeginMenu("Edit"))
      {
        auto& history = UndoRedo::getHistory();

        std::string undoText = ICON_MDI_UNDO " Undo";
        if (history.canUndo()) {
          undoText += " (" + history.getUndoDescription() + ")";
        }
        if(ImGui::MenuItem(undoText.c_str(), "Ctrl+Z", false, history.canUndo())) {
          history.undo();
        }

        std::string redoText = ICON_MDI_REDO " Redo";
        if (history.canRedo()) {
          redoText += " (" + history.getRedoDescription() + ")";
        }
        if(ImGui::MenuItem(redoText.c_str(), "Ctrl+Y", false, history.canRedo())) {
          history.redo();
        }

        if(ImGui::MenuItem(ICON_MDI_COG " Preferences", "Ctrl+."))preferencesOpen = true;

        ImGui::EndMenu();
      }

      if(ImGui::BeginMenu("Build"))
      {
        if(ImGui::MenuItem(ICON_MDI_HAMMER " Build"))Actions::call(Actions::Type::PROJECT_BUILD);
        if(ImGui::MenuItem(ICON_MDI_PLAY " Build & Run"))Actions::call(Actions::Type::PROJECT_BUILD, "run");
        if(ImGui::MenuItem("Clean"))Actions::call(Actions::Type::PROJECT_CLEAN);
        ImGui::EndMenu();
      }

      if(ImGui::BeginMenu("Focus"))
      {
        bool sceneActive = activeWorkspace == Workspace::SCENE;
        bool uiActive = activeWorkspace == Workspace::UI;
        if(ImGui::MenuItem(ICON_MDI_CUBE_OUTLINE " Scene", nullptr, sceneActive)) {
          activeWorkspace = Workspace::SCENE;
          activeFocusArea.clear();
          ImGui::makeTabVisible("3D-Viewport");
        }
        for(const auto &area : focusCatalog.value("areas", nlohmann::json::array())) {
          auto id = area.value("id", std::string{});
          auto label = area.value("label", id);
          auto status = area.value("status", std::string{"planned"});
          bool available = status == "available";
          if(!available)ImGui::BeginDisabled();
          bool selected = id == "ui" ? uiActive : (activeWorkspace == Workspace::FOCUS && activeFocusArea == id);
          const char *icon = id == "ui" ? ICON_MDI_MONITOR_DASHBOARD : focusIcon(id);
          std::string menuLabel = std::string{icon} + " " + label;
          if(ImGui::MenuItem(menuLabel.c_str(), nullptr, selected)) {
            if(id == "ui") {
              activeWorkspace = Workspace::UI;
              activeFocusArea.clear();
              if(!uiEditors.empty())uiEditors.begin()->second->focus();
            } else {
              activeWorkspace = Workspace::FOCUS;
              activeFocusArea = id;
            }
            saveSession();
          }
          if(!available)ImGui::EndDisabled();
        }
        ImGui::EndMenu();
      }

      if(ImGui::BeginMenu("View"))
      {
        if(ImGui::MenuItem(ICON_MDI_PLUS " New Viewport")) wantNewViewport = true;
        ImGui::Separator();
        if(ImGui::MenuItem(ICON_MDI_MAGNIFY_PLUS " Zoom In")) {
          ImGui::Theme::changeZoom(+1);
        }
        if(ImGui::MenuItem(ICON_MDI_MAGNIFY_MINUS "Zoom Out")) {
          ImGui::Theme::changeZoom(-1);
        }
        if(ImGui::BeginMenu(ICON_MDI_PALETTE " Theme"))
        {
          for(const auto &theme : ImGui::Theme::getThemes())
          {
            bool selected = theme.id == ImGui::Theme::getCurrentTheme();
            if(ImGui::MenuItem(theme.name.c_str(), nullptr, selected))
            {
              ImGui::Theme::setTheme(theme.id);
              ctx.prefs.themeName = theme.id;
              ctx.prefs.save();
            }
          }
          ImGui::EndMenu();
        }
        if(ImGui::MenuItem("Reset Layout"))wantResetLayout = true;
        ImGui::EndMenu();
      }

      // Centered button to leave prefab-edit mode
      if(auto scene = ctx.project->getScenes().getLoadedScene()) {
        if(auto *editObj = Editor::SelectionUtils::getPrefabEditObject(*scene)) {
          std::string label = ICON_MDI_PENCIL_OFF " Exit Prefab Edit";
          float w = ImGui::CalcTextSize(label.c_str()).x + ImGui::GetStyle().FramePadding.x * 2.0f;
          ImGui::SetCursorPosX((ImGui::GetWindowWidth() - w) * 0.5f);
          ImVec4 red = ImGui::Theme::getColor("prefabEditBg", ImVec4{0.745f, 0.216f, 0.216f, 1.0f});
          red.w = 1.0f;
          ImGui::PushStyleColor(ImGuiCol_Button, red);
          ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImVec4{red.x * 1.25f, red.y * 1.25f, red.z * 1.25f, 1.0f});
          ImGui::PushStyleColor(ImGuiCol_ButtonActive,  ImVec4{red.x * 0.85f, red.y * 0.85f, red.z * 0.85f, 1.0f});
          if(ImGui::Button(label.c_str())) {
            ctx.project->getAssets().markPrefabDirty(editObj->uuidPrefab.value);
            ctx.prefabEditUUID = 0;
          }
          ImGui::PopStyleColor(3);
        }
      }

      ImGui::SetCursorPosX(ImGui::GetWindowWidth() - 40_px);

      const char* tooltip{};
      ImGui::PushFont(nullptr, 20.0_px);
      if(isRunning){
        ImGui::BeginDisabled();
        ImGui::MenuItem(ICON_MDI_STOP);
        ImGui::EndDisabled();
      } else {
        ImGui::PushStyleColor(ImGuiCol_Text, {0.6f, 0.85f, 0.6f, 1.0f});
        if(ImGui::MenuItem(ICON_MDI_PLAY))Actions::call(Actions::Type::PROJECT_BUILD, "run");
        if(ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal))tooltip = "Run (F12)";
        ImGui::PopStyleColor();
      }

      ImGui::PopFont();

      if(tooltip)ImGui::SetTooltip("%s", tooltip);

      ImGui::EndMenuBar();
    }
    ImGui::End();
  }
  ImGui::PopStyleVar();

  // Bottom Status bar
  ImGui::SetNextWindowPos({0, io.DisplaySize.y - HEIGHT_STATUS_BAR}, ImGuiCond_Always, {0.0f, 0.0f});
  ImGui::SetNextWindowSize({io.DisplaySize.x, HEIGHT_STATUS_BAR}, ImGuiCond_Always);
  ImGui::Begin("STATUS_BAR", 0,
    ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoTitleBar
    | ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse
    | ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoDocking
  );

  fpsRingBuffer.push((double)ctx.timeCpuSelf / 1000.0 / 1000.0);

  ImGui::SetCursorPosY(ImGui::GetCursorPosY() - 5_px);
  ImGui::PushFont(ImGui::Theme::getFontMono(), 16_px);
  
  ImVec4 textCol = ImGui::GetStyleColorVec4(ImGuiCol_Text);
  ImVec4 perfColor{textCol.x, textCol.y, textCol.z, 0.55f};
  if (io.Framerate < 45) perfColor = {0.85f, 0.30f, 0.30f, 1.0f};
  ImGui::TextColored(perfColor, "%d FPS | History: %d/%d %s | CPU: %.2fms",
    (int)roundf(io.Framerate),
    UndoRedo::getHistory().getUndoCount(),
    UndoRedo::getHistory().getRedoCount(),
    Utils::byteSize(UndoRedo::getHistory().getMemoryUsage()).c_str(),
    fpsRingBuffer.average()
  );

  ImGui::SameLine();
  auto posX = io.DisplaySize.x - 12_px;

  if(!ctx.newerVersion.empty()) {
    ImGui::PopFont();

    auto txt = ICON_MDI_DOWNLOAD " Update Available: " + ctx.newerVersion;
    posX -= ImGui::CalcTextSize(txt.c_str()).x + 4;
    auto posY = ImGui::GetCursorPosY();;
    ImGui::SetCursorPos({posX, posY - 2});

    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, {5_px, 2_px});
    ImGui::PushStyleColor(ImGuiCol_Button, {0.5f, 0.8f, 0.0f, 0.9f});
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, {0.5f, 0.8f, 0.0f, 0.75f});
    ImGui::PushStyleColor(ImGuiCol_ButtonActive, {1.0f, 0.5f, 0.0f, 0.6f});
    ImGui::PushStyleColor(ImGuiCol_Text, {0.0f, 0.0f, 0.0f, 1.0f});

    if(ImGui::Button(txt.c_str(), {0,0})) {
      Utils::Updater::doUpdate(ctx.newerVersion);
    }

    ImGui::PopStyleColor(4);
    ImGui::PopStyleVar(1);

    ImGui::SetCursorPosY(posY);
    ImGui::PushFont(ImGui::Theme::getFontMono());
    posX -= 8_px;
  }

  perfColor = {textCol.x, textCol.y, textCol.z, 0.45f};
  std::string txtInfo = "v" PYRITE_VERSION;
  #ifndef NDEBUG
    perfColor = {textCol.x, textCol.y, textCol.z, 0.65f};
    txtInfo += " [DEBUG]";
  #endif

  ImGui::SetCursorPosX(posX - ImGui::CalcTextSize(txtInfo.c_str()).x);
  ImGui::TextColored(perfColor, "%s", txtInfo.c_str());

  ImGui::PopFont();
  ImGui::End();

  // Global keyboard shortcuts
  if (!ImGui::GetIO().WantTextInput) {
    bool isCtrl = ImGui::GetIO().KeyCtrl;
    bool isShift = ImGui::GetIO().KeyShift;
    
    // Undo: Ctrl+Z
    if (isCtrl && ImGui::IsKeyPressed(ImGuiKey_Z)) {
      UndoRedo::getHistory().undo();
    }
    
    // Redo: Ctrl+Y
    if (isCtrl && ImGui::IsKeyPressed(ImGuiKey_Y)) {
      UndoRedo::getHistory().redo();
    }

    // Align focused object to the editor camera: Ctrl+Shift+F (uses the hovered viewport)
    if (isCtrl && isShift && ImGui::IsKeyPressed(ImGuiKey_F)) {
      auto vp = hoveredViewport ? hoveredViewport : (viewports.empty() ? nullptr : viewports.front());
      if (vp) vp->alignFocusedObjectToCamera();
    }

    // Preferences
    if (isCtrl && ImGui::IsKeyPressed(ImGuiKey_Period))preferencesOpen = true;
  }

  if(needsSanityCheck)
  {
    // check for duplicated asset UUIDs
    auto &assets = ctx.project->getAssets().getEntries();
    std::unordered_map<uint64_t, const Project::AssetManagerEntry*> uuids{};
    for (const auto &assetTypes : assets)
    {
      for (const auto &asset : assetTypes)
      {
        auto existing = uuids.find(asset.getUUID());
        if (existing != uuids.end()) {
          auto msg = "Duplicate UUID found: " + std::to_string(asset.getUUID()) + "\nAsset: " + asset.name
             + "\nWith: " + existing->second->name;
          if(ctx.window) {
            Editor::Noti::add(Noti::ERROR, msg);
          } else {
            Utils::Logger::log(msg, Utils::Logger::LEVEL_ERROR);
          }
        } else {
          uuids[asset.getUUID()] = &asset;
        }
      }
    }
    needsSanityCheck = false;
  }
}

void Editor::Scene::save()
{
  for(auto &nodeEditor : nodeEditors) {
    nodeEditor->save();
  }
  for(auto &[_, uiEditor] : uiEditors) {
    uiEditor->saveIfDirty();
  }
  persistOpenWindows();
  UndoRedo::getHistory().markSaved();
}

bool Editor::Scene::isDirty() const
{
  for(const auto &[_, uiEditor] : uiEditors) {
    if(uiEditor->isDirty())return true;
  }
  return false;
}
