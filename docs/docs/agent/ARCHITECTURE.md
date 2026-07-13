# Architecture

**Engine:** Pyrite64 (forked as Binface64)
**Scope of this doc:** the editor, the N64 runtime, the asset pipeline, and the build system — everything an agent needs to understand before extending the engine.
**Last reviewed:** 2026-07-06 (Pyrite64 v0.7.0-era, upstream commit `104a2d2`)
**Audience:** LLM agents in later BF64 sessions. Optimize for retrievability: every claim cites a file path + line-ish location.

---

## 0. The two-binary split (read this first)

Pyrite64 is **two separate programs** that share data only through files the editor bakes:

| | Editor | Runtime |
|---|---|---|
| Binary | `pyrite64` (host SDL3/ImGui app) | `<romName>.z64` (N64 ROM) |
| Source root | `src/` | `n64/engine/` + per-game `n64/examples/<game>/` |
| Build | root `CMakeLists.txt` (host gcc) | `n64/engine/Makefile` + generated per-game `Makefile` (gcc-mips / libdragon) |
| Object model | `Project::Object` (`src/project/scene/object.h`) — `shared_ptr` tree, glm, JSON | `P64::Object` (`n64/engine/include/scene/object.h`) — single heap alloc, packed refs, fixed-point |
| Component model | `Project::Component::CompInfo` (`src/project/component/components.h`) — function pointers for editor draw/build/serialize | `P64::ComponentDef` (`n64/engine/include/scene/componentTable.h`) — function pointers for runtime update/draw/event |
| Linking | editor never calls runtime code | runtime never knows the editor exists |

The editor reads **three** runtime headers manually to stay ABI-compatible with the binary blobs it bakes into the ROM: `n64/engine/include/renderer/material.h` (via `src/build/t3dmBuilder.cpp`), `n64/engine/include/script/globalScript.h` (via `src/build/scriptBuilder.cpp`), `n64/engine/include/collision/types.h` (via `src/project/component/types/compCollBody.cpp`). Drift between the two object/component models is silent until the ROM misbehaves.

**GOTCHA:** `n64/CMakeLists.txt` and every `n64/examples/*/CMakeLists.txt` are **IDE dummies** (their headers say so verbatim, `n64/CMakeLists.txt:1-8`). They use host gcc and C++23 and are never invoked by the real toolchain. The real build is the engine `Makefile` + per-game generated `Makefile`. Editing CMake expecting it to affect the ROM will do nothing.

---

## 1. Editor architecture

### 1.1 Boot sequence

Entry point: `src/main.cpp:154` (`main`). Order:

1. `Project::Component::init()` (`main.cpp:156`) — populates `TABLE_SORTED_BY_NAME` (`src/project/component/components.cpp:12`).
2. `fs::current_path(Utils::Proc::getAppResourcePath())` (`main.cpp:157`) — **CWD is rewritten to the app's read-only data dir** (SDL base path or `XDG_DATA_HOME`). Every relative path in the editor (themes, fonts, node scripts, templates) only resolves because of this. Project paths are always passed absolute. **GOTCHA:** code that assumes the user's project CWD will be wrong.
3. `ctx.toolchain.scan()` (`main.cpp:158`) — see §4.1.
4. `CLI::run(argc, argv)` (`main.cpp:160`, `src/cli.cpp:26`). If `--cli` is set it dispatches to `Build::buildProject` or `Build::cleanProject` and exits. Otherwise returns `GUI` and boot continues. `--experimental` and a positional project path are remembered.
5. Background version-check thread (`main.cpp:168-175`) → `Utils::Updater::getNewerVersion()` (see §1.6).
6. `SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)` (`main.cpp:183`). Optional `SDL_ShaderCross_Init` under `HAS_SHADER_CROSS` (`main.cpp:189`).
7. `Editor::Window editorWindow; editorWindow.init(...)` (`main.cpp:197-198`, `src/editor/window.cpp:28`). Loads saved window state from `<appData>/editor.json`. **GOTCHA:** Wayland code paths (`window.cpp:31-54, 103-106, 154-156`) deliberately ignore window position (Wayland doesn't support it) and store/restore a `sessionID` instead.
8. `SDL_StartTextInput(ctx.window)` (`main.cpp:206`). Fallback (`useTextInputFallback`) for WSL/some platforms injects ASCII 32-126 manually (`main.cpp:352-365`).
9. GPU device: `SDL_CreateGPUDevice(SDL_GPU_SHADERFORMAT_SPIRV | MSL | DXIL, debugMode, nullptr)` (`main.cpp:212`). Claims the window (`main.cpp:226`). Selects `SDL_GPU_PRESENTMODE_IMMEDIATE`, falling back to `VSYNC` and setting `ctx.forceVSync`. **GOTCHA:** `ctx.forceVSync` silently overrides the user's `useVSync` preference every frame (`main.cpp:381`), so on hardware without immediate present the VSync toggle in Preferences does nothing.
10. Repeat-addressing `SDL_GPUSampler` stored globally as `texSamplerRepeat` (`main.cpp:243-256`) — used by the launcher's tiled background.
11. ImGui context: `IMGUI_CHECKVERSION`, `ImGui::CreateContext()` (`main.cpp:259-260`). ConfigFlags: `NavEnableKeyboard | NavEnableGamepad | DockingEnable` (`main.cpp:262-264`). `ViewportsEnable` is commented out (`main.cpp:266`). Theme applied (`ImGui::Theme::setTheme()` / `update()`, `main.cpp:268-269`).
12. ImGui backends: `ImGui_ImplSDL3_InitForSDLGPU` (`main.cpp:272`) and `ImGui_ImplSDLGPU3_Init` (`main.cpp:279`). **ImGui docking branch** (`vendored/imgui`, `ocornut/imgui`) with SDL3's GPU backend — version not checkable here because the submodule isn't checked out in this workspace.
13. Editor setup (`main.cpp:281-299`): `Editor::Actions::init()` (`src/editor/actions.cpp` + `src/editor/globalActions.cpp:42`), `Renderer::Scene scene{}` stored in `ctx.scene` (`main.cpp:285`), `Editor::ThumbnailCache` (`main.cpp:287`), `Editor::Launcher editorMain{ctx.gpu}` (`main.cpp:289`), `ctx.editorScene = std::make_unique<Editor::Scene>()` (`main.cpp:290`). `ctx.prefs.load()` (`main.cpp:292`) and theme re-applied. If a project path was given on the CLI it's opened via `Editor::Actions::call(PROJECT_OPEN, ...)` (`main.cpp:296`).

### 1.2 Main loop

`src/main.cpp:304-492`, per frame:

1. `frameStart = SDL_GetTicksNS()` (`main.cpp:306`).
2. Theme refresh: forces `"dark"` while in launcher, user's theme once a project is open (`main.cpp:309-314`). `ImGui::Theme::update()` runs each frame but only rebuilds when `needsUpdate` is set (`src/editor/imgui/theme.cpp:237`).
3. **Event pump** `while (SDL_PollEvent(&event))` (`main.cpp:319-367`): translates `SDL_EVENT_PINCH_*` into mouse-wheel events (`main.cpp:322-332`, magic-number `lastPinch` hack — **GOTCHA**); `ImGui_ImplSDL3_ProcessEvent`; window close; on `WINDOW_MOVED/RESIZED/RESTORED/SHOWN` calls `editorWindow.trackGeometry()`; on `DROP_FILE` with `.p64proj` opens the project (`main.cpp:346-348`) — **GOTCHA:** bypasses the launcher's no-spaces-in-path check; text-input fallback injection.
4. Global keybinds (`main.cpp:369-379`) via `ImGui::IsKeyChordPressed(ctx.prefs.keymap.*)`: `build` (F11), `buildAndRun` (F12), `reloadAssets` (F5). Checked after the event pump so they fire once per frame.
5. VSync present-mode switching (`main.cpp:381-390`).
6. `Utils::FilePicker::poll()` and `ctx.project->getAssets().pollWatch()` (`main.cpp:394-397`) — asset hot-reload watcher.
7. `updateWindowTitle()` (`main.cpp:399`, defined `main.cpp:112`) — appends ` *` if dirty. Caches `prevTitle`, only calls `SDL_SetWindowTitle` on change.
8. Minimized-skip: `SDL_Delay(10); continue;` (`main.cpp:401-404`) — the entire ImGui frame is skipped while minimized.
9. **ImGui frame begin** (`main.cpp:406-408`): `ImGui_ImplSDLGPU3_NewFrame`, `ImGui_ImplSDL3_NewFrame`, `ImGui::NewFrame`.
10. More global keybinds gated on `!ImGui::GetIO().WantTextInput` (`main.cpp:410-440`): zoom (Ctrl+wheel), copy/paste/save.
11. `scene.update();` (`main.cpp:443`) — `Renderer::Scene::update()` is currently a no-op (`src/renderer/scene.cpp:86`).
12. **Editor drawing** (`main.cpp:445-451`): if a project is loaded, wraps `ctx.editorScene->draw()` in `Editor::UndoRedo::getHistory().begin()` / `end()` (this is how undo snapshots are captured — see §1.5); otherwise `editorMain.draw()` (launcher).
13. `Editor::Noti::draw()` (`main.cpp:453`) — toast notifications (`src/editor/imgui/notification.cpp:42`).
14. `ImGui::Render()` (`main.cpp:457`) then `scene.draw()` (`main.cpp:458`) — `Renderer::Scene::draw` (`src/renderer/scene.cpp:90`) acquires a GPU command buffer, the swapchain texture, runs registered copy passes, render passes (the `Viewport3D` onRenderPass callbacks), then `ImGui_ImplSDLGPU3_RenderDrawData`, then post-render callbacks, then `SDL_SubmitGPUCommandBuffer`. **GOTCHA:** if `swapTex == nullptr` (window minimized during the frame) it submits an empty command buffer and returns early (`scene.cpp:100-103`), but ImGui draw data is already prepared — wasted work.
15. `ctx.runDeferredActions()` (`main.cpp:460`) — `Context::deferAction` (`src/context.h:81`) lets editor code schedule lambdas that need to run *after* the current frame's GPU submit (e.g. deleting GPU resources the just-submitted draw list still references).
16. Close handling (`main.cpp:462-478`): if `closeRequested`, calls `confirmCloseWithUnsavedChanges()` (`main.cpp:71`) which shows an SDL message box (Save/Discard). **GOTCHA:** if the user picks "Discard", `ctx.wantsProjectClose` is set and the teardown runs `onProjectClosing` which *persists the open windows list* (`editorScene.cpp:123`) into `editorScene.json` — discarded scene changes still write the session file.
17. Manual frame limiter when not VSync (`main.cpp:482-491`): `SDL_DelayNS` to hit `ctx.prefs.fpsLimit`. Subtracts 100ms from the target to leave headroom. **GOTCHA:** only runs in non-VSync mode; in VSync mode there's no separate CPU-frame-cap.

**Teardown** (`main.cpp:493-514`): `ctx.editorScene.reset()` (twice — line 493 then 499 with a comment about needing to destroy before GPU teardown), `editorWindow.saveState()`, `updateCheckThread.join()`, `SDL_WaitForGPUIdle`, ImGui/SDL backend shutdown, GPU device + window destroyed, `SDL_Quit`.

### 1.3 UI framework

Custom ImGui wrapper layer in `src/editor/imgui/`:

- **`helper.h`/`helper.cpp`** (`src/editor/imgui/helper.h`, 1021 lines; `helper.cpp`, 222 lines). The biggest single piece of editor UI infrastructure. Provides `ImGui::SideBySide`, `CollapsingSubHeader`, `IconButton`, `HelpIcon` (a `?` glyph opening docs at `PYRITE_DOCS_URL + docPath + ".html"`, `helper.cpp:44`), `IconToggle`, `VectorComboBox`, `HandleComboBoxDragDrop` (drag-drop of `ASSET`/`OBJECT` payloads onto combos), `rotationInput` (quaternion/euler toggle), `makeTabVisible` (uses `imgui_internal.h` to poke `DockNode->TabBar->NextSelectedTabId`). The **`ImTable` namespace** (`helper.h:183-1021`) is the property-table abstraction used by every component inspector: 2-column ImGui table, column 0 label, column 1 input. Key members: `start`, `add`, `end`, `addComboBox`, `addVecComboBox`, `addAssetVecComboBox`/`addObjectVecComboBox` (drag-drop variants), `addCheckBox`, `addMultiSelectMask8`, `bitMaskCombo`, `addColor`, `addPath` (folder picker), `addKeybind` (interactive rebinding). Searchable combos via `drawComboSearchFilter` + `labelMatchesFilter`/`labelMatchesPascalWordFilter` (PascalCase-aware fuzzy filter, e.g. `xp` matches `XML Parser`). **Prefab-override machinery** (`helper.h:185-220`): `ImTable::obj` is the currently-drawn object; `isPrefabLocked()` returns true when drawing a prefab instance not in edit mode; `ForceLockScope`/`PrefabEditScope` are RAII guards. `addObjProp` (`helper.h:876-975`) is the central property widget: shows a lock toggle to add/remove an override on a prefab instance, resolves the effective value through the `Property<T>::resolve` cascade, right-click offers "Reset to prefab". `typedInput<T>` (`helper.h:819-850`) does `if constexpr` dispatch over `float/bool/int/u32/u16/u8/vec2/vec3/vec4/quat/ivec2/string`. **GOTCHA:** `ImTable::add` (`helper.h:249`) does `ImGui::Text("%s", name.c_str())` which crashes if `name` contains a `%` — fine in practice because labels are constants, but user-facing names from scripts could in principle contain one. **GOTCHA:** `helper.h` includes `imgui_internal.h` (line 27); any non-trivial ImGui upgrade can break `makeTabVisible` and the `DockTabItemRect` reads in `editorScene.cpp:243`.

- **`theme.h`/`theme.cpp`** (`src/editor/imgui/theme.h`, 46 lines; `theme.cpp`, 272 lines). JSON-driven theming. Themes live in `data/themes/<id>.json` (`theme.cpp:164`). `applyThemeJson` (`theme.cpp:38`) maps color names (via `ImGui::GetStyleColorName`) to `ImGuiCol_*` indices and reads a fixed set of style scalars (`TabBarOverlineSize`, `WindowRounding`, `FrameRounding`, ...; `theme.cpp:57-70`). `custom` sub-object holds named colors queried by `getColor`/`getColorU32` (`theme.cpp:177-191`) — used by callers like `editorScene.cpp:519` (`prefabEditBg`). Zoom is a 12-step table `ZOOM_VALUES` (`theme.cpp:73-86`) applied via `style.ScaleAllSizes` + font reload (`theme.cpp:266-267`). The `_px` user-defined literal (`theme.h:41-46`) multiplies any pixel value by `zoomFactor`, used everywhere as `28_px`, `2_px`, etc. Fonts: default `./data/Altinn-DINExp.ttf`, icons merged from `./data/materialdesignicons-webfont.ttf`, mono `./data/GoogleSansCode.ttf` (`theme.cpp:88,144,147`). **GOTCHA:** theme fonts load relative to CWD (which was rewritten to the app resource path at boot) — moving the binary breaks theming silently. **GOTCHA:** `loadFonts` only rebuilds the atlas when the *UI font path* changes (`theme.cpp:116`), not when only zoom changes — it scales `style.FontSizeBase` instead (`theme.cpp:156`). Icon font merged once at original size; zooming far in makes icons blurry.

- **`notification.h`/`notification.cpp`** (`src/editor/imgui/notification.h`, 20 lines; `notification.cpp`, 141 lines). Toast notifications drawn into `ImGui::GetForegroundDrawList()` at bottom-right, with scroll-in/out animations (`notification.cpp:67-77`) and MDI success/error icons. Thread-safe via `notiMutex`. `showAction` is a separate transient center-screen message (`notification.cpp:108`) used by e.g. zoom changes. Types: `INFO`, `SUCCESS`, `ERROR` (`notification.h:10`). Error toasts stay twice as long (`notification.cpp:33`).

**`Editor::Window`** (`src/editor/window.h:15`) is a thin SDL window wrapper, not a windowing framework. Owns the SDL_Window + icon, persists geometry to `editor.json`, has Wayland-specific paths. No window class hierarchy — panels are free functions or simple classes with a `draw()` method, hosted inside ImGui.

### 1.4 Editor pages & panels

`src/editor/pages/`:

- **`launcher.cpp/.h`** — full-screen home screen shown when no project is open (`main.cpp:450`). Draws splash BG (`splashBG.png`), title logo, action cards ("Create Project", "Open Project", "Toolchain"), and a row of recent-project cartridge cards (`launcher.cpp:245-373`) pulled from `ctx.prefs.recentProjects`. Each recent card resolves a metadata cart/box image path (`globalActions.cpp:64-74`). `CreateProjectOverlay` and `ToolchainOverlay` drawn at the end (`launcher.cpp:393-394`). **GOTCHA:** the launcher rejects project paths containing spaces (`launcher.cpp:202-205`) because the downstream Makefile/libdragon toolchain can't handle them — but the rejection happens at open time only via the file picker; dropping a `.p64proj` with spaces from the OS (`main.cpp:346-348`) bypasses this check.

- **`editorScene.cpp/.h`** — the main editor host, instantiated once as `ctx.editorScene`. Owns the dockspace (`MAIN_DOCK`/`DockSpace`, `editorScene.cpp:191-231`), a default 3-split layout (left 15% / right 25% / bottom 25%, lines 206-208) built with `ImGui::DockBuilder*` only on first run, then docks the named panels (lines 211-228): center `3D-Viewport`, left `Scene`/`Graph`/`Layers`, right `Asset`/`Object`/`Model`, bottom `Files`/`Log`/`ROM`. Supports multiple 3D viewports (`viewports` vector, `editorScene.h:26`) and a `viewportsPendingClose` deferred-destruction list (`editorScene.h:29`); closed viewports are kept alive one extra frame so the just-submitted ImGui draw list referencing their framebuffer texture doesn't crash (`editorScene.cpp:157, 261-265`). Top menu bar (`Project`/`Edit`/`Build`/`View`), a centered "Exit Prefab Edit" button when in prefab-edit mode (`editorScene.cpp:513-530`), bottom status bar with FPS, undo/redo counts + memory, version + update-available button (lines 557-622). Global keyboard shortcuts for undo/redo/align/preferences (lines 624-647). Per-project open-window persistence: `sessionWindows` map keyed by project path (`editorScene.h:60-61, 103-113`), saved to `editorScene.json` in the app data dir (`editorScene.cpp:89-101`). On project switch it calls `closeAllEditors` + `restoreWindows` (`editorScene.cpp:130-142, 160-164`). **GOTCHA:** `restoreWindows` keys `sessionWindows` by `ctx.project->getPath()` which is the project *directory*, not the `.p64proj` file path — two `.p64proj` files in the same directory would share a window set.

Panel classes (all in `src/editor/pages/parts/`, each a class with a `draw()` method):

| Class | File | Docked under |
|---|---|---|
| `Editor::Viewport3D` | `parts/viewport3D.h/.cpp` | center ("3D-Viewport") — 3D scene preview with camera, gizmos, object picking; registers render/copy/postrender callbacks on `Renderer::Scene` |
| `Editor::SceneGraph` | `parts/sceneGraph.h/.cpp` | left ("Graph") — the object tree / outliner |
| `Editor::SceneInspector` | `parts/sceneInspector.h/.cpp` | left ("Scene") — scene-level settings (framebuffer, physics, layers editor) |
| `Editor::LayerInspector` | `parts/layerInspector.h/.cpp` | left ("Layers") — per-layer render config |
| `Editor::AssetsBrowser` | `parts/assetsBrowser.h/.cpp` | bottom ("Files") — file browser with tabs and rename/delete context menu |
| `Editor::AssetInspector` | `parts/assetInspector.h/.cpp` | right ("Asset") — per-asset import settings |
| `Editor::ObjectInspector` | `parts/objectInspector.h/.cpp` | right ("Object") — object transform + component list + per-component UI (delegates to `Component::TABLE[id].funcDraw`) |
| `Editor::LogWindow` | `parts/logWindow.h/.cpp` | bottom ("Log") — tail of `Utils::Logger` |
| `Editor::MemoryDashboard` | `parts/memoryDashboard.h/.cpp` | bottom ("ROM") — cart size estimate, asset size breakdown (`memoryDashboard.h:14-30`) |
| `Editor::NodeEditor` | `parts/nodeEditor.h/.cpp` | docked into the dockspace by `Editor::Scene::draw` (`editorScene.cpp:284-299`) — see §1.7 |
| `Editor::ModelEditor` | `parts/assets/modelEditor.h/.cpp` | right ("Model") — 3D model preview/edit |
| `Editor::PreferenceOverlay` | `parts/preferenceOverlay.h/.cpp` | modal — preferences UI |
| `Editor::ProjectSettings` | `parts/projectSettings.h/.cpp` | modal — project settings |
| `Editor::CreateProjectOverlay` (free functions) | `parts/createProjectOverlay.h/.cpp` | modal overlay drawn by launcher |
| `Editor::ToolchainOverlay` (free functions) | `parts/toolchainOverlay.h/.cpp` | modal overlay drawn by launcher |
| Asset sub-editors: `MatInstanceEditor`, `TextureEditor` | `parts/assets/*` | used by `AssetInspector` |

### 1.5 Actions & undo

**Actions** — `src/editor/actions.{cpp,h}` + `src/editor/globalActions.cpp`. A simple typed callback registry. `Editor::Actions::Type` enum (`actions.h:12`): `PROJECT_OPEN, PROJECT_CLOSE, PROJECT_BUILD, PROJECT_CREATE, PROJECT_CLEAN, ASSETS_RELOAD, COPY, PASTE, OPEN_NODE_GRAPH`. `actionCallbacks[0xFF]` (`actions.cpp:13`) is a flat array of 255 `std::function<bool(const std::string&)>` slots indexed by enum. `registerAction(type, fn)` installs one; `call(type, arg)` dispatches with try/catch that logs + shows an error notification on exception. `init()` clears the table and calls `initGlobalActions()`. **GOTCHA:** the table is fixed at 255 entries indexed by `uint8_t` — adding more than 255 action types silently overflows; the enum uses `uint8_t` underlying type so the compiler would catch it, but the array size is a magic number `0xFF` rather than `static_cast<uint8_t>(Type::_COUNT)`.

`initGlobalActions` (`globalActions.cpp:42`) registers:
- `PROJECT_OPEN` (`globalActions.cpp:44`): tears down the outgoing project (`onProjectClosing` + delete + UndoRedo clear), constructs `new Project::Project(path)`, loads the last-opened scene, warns if the project was saved with a newer editor version, resolves the metadata cart image and adds the project to `ctx.prefs.recentProjects` + saves prefs.
- `PROJECT_CLOSE` (`globalActions.cpp:89`): sets `ctx.wantsProjectClose = true`; the main loop does the actual teardown (`main.cpp:467-478`).
- `PROJECT_CLEAN` (`globalActions.cpp:94`): refuses if build running; calls `Build::cleanProject` with all flags set.
- `PROJECT_CREATE` (`globalActions.cpp:106`): parses JSON payload `{path, name, rom}`, creates the directory (must be empty), copies `n64/examples/empty` recursively, removes `p64_project.z64`/`Makefile`/`build`/`filesystem`, patches `name`/`romName` into the copied `project.p64proj`. **GOTCHA:** does *not* automatically open the new project — the user must open it from recents. **GOTCHA:** no validation that `n64/examples/empty` exists — if the submodule isn't checked out, creation silently copies nothing meaningful.
- `PROJECT_BUILD` (`globalActions.cpp:148`): refuses if build running; focuses the Log window; saves project + editor scene; deletes the existing `.z64`; builds a `runCmd` if arg == "run" (emulator path + z64 path); launches `std::async(std::launch::async, Build::buildProject, ...)` stored in `ctx.futureBuildRun`. The worker thread saves/restores the `PATH` env var (`globalActions.cpp:165-181`) — **GOTCHA:** this scopes the toolchain's PATH manipulations to the build, but races with any other code reading `PATH` during the build. On completion it runs the emulator via `Utils::Proc::runSyncLogged` (`globalActions.cpp:189`) — **GOTCHA:** this *blocks* the worker thread until the emulator exits, so `ctx.isBuildOrRunning()` (`context.h:89`) stays true while the emulator is open; that's by-design to prevent concurrent builds but means closing the emulator is the only way to clear the "running" state.
- `ASSETS_RELOAD` (`globalActions.cpp:196`): `ctx.project->getAssets().reload()`.
- `COPY` (`globalActions.cpp:203`): serializes the selected objects (excluding any whose parent is also selected, `globalActions.cpp:219-228`) into `ctx.clipboard.entries` as `{data: json string, refUUID: parent uuid}`.
- `PASTE` (`globalActions.cpp:245`): clears selection, for each clipboard entry calls `scene->addObject(data, refUUID)` and selects the new uuid. Marks UndoRedo "Paste Object".

`OPEN_NODE_GRAPH` is registered in `Editor::Scene`'s constructor (`editorScene.cpp:35-45`), not in `initGlobalActions`.

**Undo/Redo** — `src/editor/undoRedo.{cpp,h}`. A **whole-scene-snapshot** undo system, *not* a fine-grained command pattern. `Editor::UndoRedo::History` (`undoRedo.h:34`) has two stacks of `Entry{state: string, description: string, selection: vector<uint32_t>}` (`undoRedo.h:19`), a `maxHistorySize` (default 100, `undoRedo.h:39`), a `snapshotScene` pointer set during `begin()`, an optional `savedState` for dirty detection.

- `begin()` (`undoRedo.cpp:64`): called at the start of `ctx.editorScene->draw()` (`main.cpp:446`). Captures the currently-loaded scene into `snapshotScene` and, if the undo stack is empty, pushes an "Initial State" entry with the full serialized scene (`undoRedo.cpp:68-78`). **GOTCHA:** every frame a project is open, an initial snapshot is taken if none exists — but only the first one; subsequent frames reuse it.
- `end()` (`undoRedo.cpp`): compares the current scene serialization to the snapshot taken at `begin()`. If different, pushes a new `Entry` with the new state + a description (set by `Editor::UndoRedo::setActionName()` during the frame). Trims the redo stack on push. Trims undo stack to `maxHistorySize`.
- `undo()`/`redo()`: pop/push and `deserialize` the state string into `snapshotScene`. Clear the selection, restore the saved selection UUIDs.
- `markSaved()`: updates `savedState` to current — used for the title-bar dirty indicator.

**GOTCHA:** scene switching is destructive to undo history — there is no per-scene undo stack. `SceneManager::loadScene` (`sceneManager.cpp:131`) clears the undo history.

### 1.6 Update / network

`src/utils/updater.cpp` + `src/utils/network.cpp`. `Utils::Updater::getNewerVersion()` fetches a release-info URL (run on a background thread at boot, `main.cpp:168-175`). The result, if any, surfaces as a button in the status bar (`editorScene.cpp` status bar) and opens the download page in the browser. No auto-update of the binary itself — just a notification. `network.cpp` is the thin HTTP/S fetch helper used by the updater.

### 1.7 Node-graph scripting

**Editor** — `src/editor/pages/parts/nodeEditor.{cpp,h}`. `Editor::NodeEditor` (`nodeEditor.h:11`) is one per open graph asset. Constructed with an asset UUID (`nodeEditor.cpp:32`), loads the graph JSON from the asset's file path (`nodeEditor.cpp:54`), configures the `ImNodeFlow` pin styles for logic vs value pins (`nodeEditor.cpp:34-52`), and registers right-click / dropped-link popup handlers (`nodeEditor.cpp:60-87`). `draw()` (`nodeEditor.cpp:208`) renders a variables panel on the left (`drawVariablesPanel`, `nodeEditor.cpp:341` — add/remove/rename variables with types `i32, u32, f32, vec3, quat, objref`) and the `ImFlow` canvas on the right, themed per-frame from the active theme (`nodeEditor.cpp:247-255`). `syncVariablePins` (`nodeEditor.cpp:394`) keeps Get/Set-Var nodes' pin types in sync with the variable declarations. `drawCreateMenu` (`nodeEditor.cpp:95`) is the searchable, categorized node-spawn menu that filters by the dragged pin's compatible type (`nodeEditor.cpp:114-122`). Saving writes the graph JSON (minified) plus the asset's `.conf` (`nodeEditor.cpp:282-294`). **GOTCHA:** node-graph dirty tracking is dual: the `NodeEditor` has its own `dirty` flag comparing `graph.serialize(false)` to `savedState` (`nodeEditor.cpp:264-277`), *and* it calls into `ctx.project->getAssets().markNodeGraphDirty/clearNodeGraphDirty` so the asset manager also knows — these must stay consistent or the launcher/asset browser shows stale dirty state. `Editor::Scene::draw` (`editorScene.cpp:284-299`) wraps node-editor close in an "Unsaved Node Graph" modal (`editorScene.cpp:301-338`).

**Graph model** — `src/project/graph/graph.{cpp,h}`. `Project::Graph::Graph` (`graph.h:49`) wraps an `ImFlow::ImNodeFlow graph` plus `variables` (vector of `GraphVar{name, type}`, `graph.h:29`), `repeatable` flag (dead-end paths yield + restart at Start, `graph.h:55`), and build helpers.
- **Serialize** (`graph.cpp:202`): `{repeatable, view:[scrollX,scrollY,scale], variables[], nodes[{uuid, typeId, pos, ...per-spec props}], links[{src, srcPort, dst, dstPort, points?}], groups[]}`. The `view` field is excluded from dirty checks via the `withView` arg (`graph.h:64`).
- **Deserialize** (`graph.cpp:110`): handles legacy integer `type` field via `LEGACY_TYPE_IDS` (`nodeRegistry.cpp:29`) → stable string `typeId`. Unknown ids become **placeholder specs** via `findOrCreatePlaceholder` (`nodeRegistry.cpp:324`) so the node + its data are preserved rather than dropped (`nodeRegistry.cpp:140-141`). Restored links are force-created past the type filter (`graph.cpp:173`) so a retype doesn't drop a saved link. Link waypoints restored (`graph.cpp:176-186`).

**Node registry & specs** — `src/project/graph/nodeRegistry.{cpp,h}`, `nodes/{nodeSpec,scriptNode,baseNode}.h`, `jsNodeHost.{cpp,h}`.
- `NodeSpec` (`nodes/nodeSpec.h:48`) fully describes a node type: stable string `id` (e.g. `"core.wait"`), display `name` (with icon glyph), `category`, color, rounding, `entry` flag (start node emitted first), `inputs`/`outputs` (`PinDef{name, value, valueType, defNum}`, `nodeSpec.h:39`), `props` (`PropDef{key, label, type, defaults, enumOptions, width, hideIfInputConnected, compact}`, `nodeSpec.h:23`), and function hooks `build` (emit C++ logic), `value` (pull-based value expression), `title`, `drawExtra`, `syncPins`, `prepareBuild`.
- `ScriptNode` (`nodes/scriptNode.h:16`) is the *single concrete node class* — every node type is a `ScriptNode` parameterized by a `NodeSpec*`. All editable state lives in a `nlohmann::json props` bag (`scriptNode.h:20`). `build()`/`value()`/`prepareBuild()` delegate to the spec's hooks.
- `Base` (`nodes/baseNode.h:159`) is the abstract `ImFlow::BaseNode` subclass with per-pin value-type tracking (`inTypes`/`outTypes`), `valueInputTypes()`, `firstValueOutType()`, pin-type lookup by pointer, and the `serialize/deserialize/build/value/prepareBuild` virtuals.
- `BuildCtx` (`baseNode.h:18`) is the codegen context passed to every `build`/`value` call: `source` (accumulating C++), `vars` (graph-level `VarDef{type,name,value}`), `includes`, `outUUIDs`/`inValUUIDs`/`inValTypes`/`inValFallbacks` (the live link topology + per-pin types + inline-field literals), `flowEnd` (what to emit at a dead end — `return;` or yield+goto-Start for repeatable), and the resolvers `valueResolver`/`valueTypeResolver`/`varLValue`/`varTypeOf` set up by `Graph::build`. Helper methods: `localConst/localVar/setVar/incrVar/globalVar/declareVar/jump/line/include`. `inputExpr(i, fallback)` (`baseNode.h:60`) resolves value input `i`: if connected, calls `valueResolver` and `convertExpr` to cast; if not, returns the inline literal or a typed zero.
- **Native specs** (`nodeRegistry.cpp:76-205`): only four are defined in C++ — `core.varGet`, `core.varSet` (with Set/Add/Subtract enum op), `core.switchCase` (dynamic number of case outputs), `core.note` (a draggable resizable text annotation).
- **JS-defined specs**: the rest. `Js::init()` boots `quickjs-ng` and evaluates `data/nodes/_prelude.js` (`jsNodeHost.h:14`). `Js::loadSpecs(out, userDir)` loads `data/nodes/builtin/*.js` plus `<project>/nodes/*.js` and turns them into `NodeSpec`s (`nodeRegistry.cpp:218-221`). The builtin JS files in `data/nodes/builtin/` are: `debug.js`, `flow.js`, `object.js`, `value.js`. The complete set of JS-defined node ids (from grepping `id:` in those files): `core.start, core.wait, core.waitFrame, core.repeat, core.func, core.ifElse, core.compare, core.value, core.valueFloat, core.valueUInt, core.valueVec3, core.valueQuat, core.constRad, core.negate, core.vnegate, core.vnorm, core.vlen, core.vdot, core.vcross, core.vdist, core.vlerp, core.vcomp, core.vecSwap, core.ease, core.mapRange, core.fmod, core.onExtremum, core.quatAxisAngle, core.quatLerp, core.quatRotAxisZYX, core.objDel, core.objEvent, core.objGetPos, core.objGetRot, core.objSetPos, core.objSetRot, core.objSetRotEuler, core.objSetRotEulerVec, core.objOrigPos, core.objOrigRot, core.objRef, core.sceneLoad, core.arg, core.deltaTime`. Plus the four C++ native ones (`varGet`/`varSet`/`switchCase`/`note`) and the legacy integer types listed in `LEGACY_TYPE_IDS` (`nodeRegistry.cpp:29`): `start, wait, objDel, objEvent, compare, value, repeat, func, ifElse, sceneLoad, arg, switchCase, note, objRef`.
- **Hot reload**: `pollUserNodeReload()` (`nodeRegistry.cpp:294`) checks mtimes of `<project>/nodes/*.js` every frame (called from `NodeEditor::draw`, `nodeEditor.cpp:225`, but *skipped during a build* because the build reads specs from a worker thread — `nodeEditor.cpp:224`) and calls `reloadSpecs` if any changed. `reloadSpecs` (`nodeRegistry.cpp:285`) re-runs `buildDesired` (native + JS) and `ingest`s the result: existing ids are updated *in place* so raw `NodeSpec*` held by live nodes stay valid (`nodeRegistry.cpp:233-236`); vanished ids become `missing=true` placeholders with nulled build/value (`nodeRegistry.cpp:237-242`). **GOTCHA:** specs are stored in `unique_ptr` precisely to keep addresses stable across reloads (`nodeRegistry.cpp:208-209`) — never hold a `NodeSpec` by value.
- **Value types** (`src/project/graph/valueTypes.h`): registry of value-pin data types (id, name, cType, defaultLiteral, color, size) populated from `data/nodes/_types.js`. `canConnect(from, to)` and `convertExpr(from, to, expr)` drive type-coercion of links. `LOGIC_TYPE = "logic"` is the sentinel for flow pins. `byteSizeOf`/`cTypeOf` feed the per-instance variable blob layout.

**Graph → C++ compilation** — `src/project/graph/graph.cpp:279` (`Graph::build`) and `src/build/nodeGraphBuilder.cpp`.
- `Build::buildNodeGraphAssets` (`nodeGraphBuilder.cpp:31`) iterates all `NODE_GRAPH`-type assets, deserializes each into a temporary `Graph`, allocates a `Utils::BinaryFile binFile` and a `std::string sourceCode`, calls `graph.build(binFile, sourceCode, uuid)`, and writes both the generated `.cpp` (`<project>/src/p64/<hexuuid>.cpp`) and a binary header (`<project>/<asset.outPath>`) — but only if their content changed (`nodeGraphBuilder.cpp:60-65`). It also pushes the uuid into `sceneCtx.graphFunctions` (line 47) and the out-path into `sceneCtx.files` (line 46). Node graphs are **always regenerated** (comment at `nodeGraphBuilder.cpp:49`: "output also depends on node definitions + codegen") even if the `.p64graph` is unchanged — but the file write is gated by content equality afterward.
- `Graph::build` (`graph.cpp:279`) is the codegen core:
  1. Writes the binary header: `uint64 uuid`, `uint16 stackSize=4096`, `uint16 padding`, `uint32 varBlobBytes` (`graph.cpp:287-291`). **GOTCHA:** `stackSize` is a hardcoded magic 4096 — no per-graph stack analysis.
  2. Collects all live links into `nodeOutgoingMap` (uuid → vector of output-pin-index → dst uuid) and `nodeIngoingValMap` (uuid → vector of input-pin-index → src uuid), resizing and zero-filling (`graph.cpp:301-334`).
  3. Builds the variable-layout closure: `varLValue(name)` returns `(*((cType*)((uint8_t*)inst->vars + offset)))` (`graph.cpp:343-348`). `varTypeOf(name)` returns the type id.
  4. Orders nodes with the entry node (Start) first (`graph.cpp:356-368`).
  5. Compacts ingoing value links to value-pin order per node (`graph.cpp:371-385`).
  6. Sets up **back-propagation value resolution** (`graph.cpp:396-418`): `resolveValue(valUuid)` recurses into a node's `value()` with that node's input context swapped in, with a cycle guard (`visited` set, `graph.cpp:402`). Returns the inline expression, or `res_<uuid>` as the fallback named after the node's persisted result slot. `valueTypeResolver` returns the producer's first value-output type (`graph.cpp:421-424`).
  7. `prepareBuild` pass: lets Set/Get-Var nodes resolve dynamic pin types from graph variables before codegen (`graph.cpp:428`).
  8. `flowEnd` = repeatable ? `coro_yield(); inst->time += ...; goto NODE_<startUuid>;` : `return;` (`graph.cpp:432-435`).
  9. **Codegen loop** (`graph.cpp:443-462`): for each node, emits `NODE_<hexuuid>: // <name>` label, opens a block, calls `node->build(nodeCtx)`, then either `ctx.jump(0)` (if it has outputs) or `ctx.line(flowEnd)` (if it doesn't). The generated `goto`s target other `NODE_<uuid>` labels.
  10. Emits the final source: base includes (`<script/nodeGraph.h>`, `<scene/object.h>`, `<scene/scene.h>`, `<vi/swapChain.h>`, `<lib/logger.h>`, `graph.cpp:464-468`), node-requested includes, wraps everything in `namespace P64::NodeGraph::G<hexuuid> { void run(void* arg) { Instance* inst = ...; <global vars> <codegen body> } }` (`graph.cpp:477-490`). **GOTCHA:** the codegen is `goto`-based coroutines using labels named `NODE_<hexuuid>` — this requires the runtime `nodeGraph.h` to support this style, and any node uuid collision would produce a duplicate label (no check). **GOTCHA:** the `flowEnd` for repeatable graphs uses `inst->time += P64::VI::SwapChain::getDeltaTime();` (`graph.cpp:434`) — a hardcoded dependency on the VI swapchain header being included (it is, line 466).
- The generated `.cpp` is then compiled by the N64 toolchain alongside user scripts (see §4) and the binary header is packed into the ROM filesystem as the node-graph asset's runtime data, loaded by the engine's `script/nodeGraph.h` runtime.

---

## 2. Runtime architecture (N64 engine)

All paths in this section are under `n64/engine/`.

### 2.1 Build target & engine structure

**The `n64/CMakeLists.txt` does NOT build the real ROM.** It is explicitly a dummy file for CLion/IDE indexing (header comment at `n64/CMakeLists.txt:1-8`). The real build is `n64/engine/Makefile`:
- `include`s `$(N64_INST)/include/n64.mk` and `t3d.mk` (libdragon + tiny3d makefiles).
- Flags: `-std=gnu++20 -fno-exceptions -Os -Iinclude` plus a strict `-Werror` warning set (`n64/engine/Makefile:9-15`).
- **Builds a static library, `build/engine.a`**, not a ROM: `all` target is `$(BUILD_DIR)/$(PROJECT_NAME).a` produced by `$(N64_LD) -r -o …` (a relocatable link of all `.o` + the RSP ucodes, lines 22-35).
- Also assembles custom RSP microcode objects: `renderer/hdr/rsp_hdr.o`, `renderer/bigtex/applyTexture.o`, `renderer/bigtex/rsp_bigtex.o` (lines 25-29, 45-52). These are hand-written `.S` ucodes (e.g. `n64/engine/src/renderer/bigtex/rsp_bigtex.S`, `…/rsp_hdr.S`) plus an `.rspl` link script.

**GOTCHA:** `n64/engine/Makefile:11` wildcards `src/collision/shapes/*.cpp` but no such directory exists on disk — the shape `.cpp` files live at `n64/engine/src/collision/*.cpp`. Dead glob; harmless but misleading.

**GOTCHA:** The dummy CMake uses C++23 (`n64/CMakeLists.txt:16`) while the real Makefile uses `gnu++20` (`n64/engine/Makefile:9`). IDE-only, but any feature check in the IDE can disagree with the actual ROM build.

A game links: `engine.a` + user `src/user/*.cpp` + generated `src/p64/*.cpp`, packed via libdragon's `n64.mk` into a `.z64`.

**Public API surface** — `n64/engine/include/` (this is exactly what Doxygen scans, `docs/Doxyfile:8-9`). 9 subdirectories, 49 headers:

- `scene/` — `scene.h` (`P64::Scene`), `sceneManager.h`, `object.h` (`P64::Object`), `objectFlags.h`, `event.h`, `componentTable.h`, `camera.h`, `lighting.h`, `globalState.h`, plus per-component headers under `scene/components/` (animModel, audio2d, camera, charBody, code, collBody, collMesh, constraint, culling, light, model, nodeGraph).
- `renderer/` — `pipeline.h`, `pipelineHDRBloom.h`, `pipelineBigTex.h`, `drawLayer.h`, `material.h`, `hdr/postProcess.h`, `bigtex/textures.h` + `bigtex/uvTexture.h`, `particles/ptxSystem.h` + `particles/ptxSprites.h`.
- `collision/` — 24 headers (see §2.5).
- `audio/` — `audioManager.h`.
- `assets/` — `assetManager.h`, `assetTypes.h`.
- `script/` — `userScript.h`, `scriptTable.h`, `globalScript.h`, `nodeGraph.h`.
- `vi/` — `swapChain.h`.
- `lib/` — `math.h`, `types.h`, `memory.h`, `matrixManager.h`, `logger.h`, `fifo.h`, `ringBuffer.h`, `mips.h`.
- `debug/` — `debugDraw.h`, `debugMenu.h`, `menu.h`.

### 2.2 Scene & object model (runtime)

**Scene** (`scene/scene.h`, `src/scene/scene.cpp`): `P64::Scene` owns `std::vector<Object*> objects`, `std::array<Object*,128> idLookup` for O(1) lookup of the first 128 ids (falling back to linear scan, `scene.cpp:478-493`), cameras, a render pipeline, lighting (double: `lighting` + `lightingTemp` for overrides), and a double-buffered event queue `eventQueue[2]` with `eventQueueIdx` flip (`scene.cpp:378-400`).

**Object layout** (`scene/object.h`): an `Object` is a *single heap allocation* containing the base struct + an inline `CompRef[]` table + an 8-byte-aligned component data blob. `getCompRefs()`/`getCompData()` reach past the struct by raw pointer arithmetic (lines 65-76). Components are NOT polymorphic — they are POD-ish structs registered in `COMP_TABLE` by integer ID, located in the object via `CompRef{type,flags,offset}`. `getComponent<T>()` scans refs for `T::ID` (lines 85-94). This is a flat, cache-friendly, no-vtable ECS-ish design.

**Runtime vs editor component systems — totally different:**
- Editor: `Project::Component::Entry` with `shared_ptr<void> data`, `CompInfo` with `FuncCompDraw/FuncCompBuild/FuncCompSerial` etc. (`src/project/component/components.h`), keyed by `int id` + `uint64_t uuid`, glm types, JSON-serialized.
- Runtime: `P64::ComponentDef` with raw function pointers `update/unscaledUpdate/fixedUpdate/draw/onEvent/onColl/initDel/getAllocSize`, keyed by `uint8_t ID`, packed bytes. The runtime table is a fixed `constexpr`-initialized array of 17 slots filled via the `SET_COMP` macro + `HAS_FUNC_TPL` SFINAE detection that nulls-out callbacks a component does not define.

**Component IDs (runtime)** (`scene/components/*.h`):
| ID | Component | Header |
|---|---|---|
| 0 | Code (user script) | `code.h` |
| 1 | Model (static) | `model.h` |
| 2 | Light | `light.h` |
| 3 | Camera | `camera.h` |
| 4 | Collision-Mesh | `collMesh.h` |
| 5 | Collider | `collBody.h` |
| 6 | Audio (2D) | `audio2d.h` |
| 7 | Constraint | `constraint.h` |
| 8 | Culling | `culling.h` |
| 9 | Node Graph | `nodeGraph.h` |
| 10 | Model (animated) | `animModel.h` |
| 11 | Rigid-Body | `rigidBody.h` |
| 12 | Character-Body | `charBody.h` |
| 13 | UI Document | `ui.h` |
| 14 | Audio (3D) | `audio3d.h` |
| 15 | Player Spawn | `playerSpawn.h` |
| 16 | Blob Shadow | `blobShadow.h` |

**GOTCHA:** There are *two* `nodeGraph.h` headers — `n64/engine/include/scene/components/nodeGraph.h` (the runtime component) and `n64/engine/include/script/nodeGraph.h` (the script runtime) — easy to confuse.

**Object lifecycle / state machine** (`objectFlags.h`, `scene.cpp`): flags track self/parent active+hidden separately; `ACTIVE = SELF_ACTIVE|PARENTS_ACTIVE`. `setEnabled`/`setVisible` set `PENDING_ACTIVE_CHG`; `updateChildObjectStates` (`scene.cpp:495-522`) propagates parent state down the hierarchy and emits ENABLE/DISABLE events. Deletion is deferred via `pendingObjDelete` (`scene.cpp:277-289`).

### 2.3 Main loop & update order

`n64/engine/src/main.cpp:106-119`:
```
for(;;) { SceneManager::run(); VI::SwapChain::drain(); SceneManager::unload(); Mem::freeDepthBuffer(); MatrixManager::reset(); }
```

`SceneManager::run` (`src/scene/sceneManager.cpp:36-49`) fires `SCENE_PRE_LOAD`, constructs `Scene`, fires `SCENE_POST_LOAD`, then loops `currScene->update(getDeltaTime())` until the scene id changes / forceReload.

`Scene::update` (`scene.cpp:149-293`), per frame:
1. accumulator += deltaTime; joypad_poll; reset metrics; AudioManager::update; lighting.reset; pick camMain.
2. `SCENE_UPDATE` global hook (`scene.cpp:168`).
3. Spawn pending prefab objects (lines 171-203) — prefab data is prefixed with child count, ids assigned as a contiguous block from `nextId` (`scene.cpp:446-471`).
4. `runPendingComponentInit` (deferred from scene load so parent active state is known first).
5. `updateChildObjectStates` if flagged.
6. `runPendingEvents` (flipped double-buffer).
7. **Fixed-step physics loop**: while accumulator ≥ fixedDt (clamped to `MAX_PHYSICS_STEPS=5`, line 39), call each enabled object's `fixedUpdate` then `Coll::collisionSceneGetInstance()->step()` (lines 231-249). `fixedDt = 1/physicsTickRate` (default 50 Hz, line 223).
8. Optional render interpolation of rigid-body transforms (`applyRenderInterpolation`, lines 251-255, 402-425) — extrapolates pos/rot by remaining accumulator fraction, restored after draw.
9. **Variable update**: per-object `update(dt)` (lines 257-269).
10. Cameras update.
11. Deferred deletes flushed.
12. `VI::SwapChain::nextFrame()` (line 292) — hands the finished frame to the VI.

`Scene::draw` (`scene.cpp:295-376`) is called from inside the pipeline's draw pass (see §2.4): `SCENE_PRE_DRAW` → `renderPipeline->preDraw()` → `DrawLayer::draw(0)` → for each camera: attach, lighting.apply, push 3D layers, `SCENE_PRE_DRAW_3D`, **per-object per-component `draw`** (skipping culled/hidden), reset `IS_CULLED`, `SCENE_POST_DRAW_3D`, pop → `DrawLayer::use2D` + `SCENE_DRAW_2D` → `renderPipeline->draw()` → restore interpolated transforms.

### 2.4 Render loop

**Entry to a frame** is `VI::SwapChain::nextFrame()` (`src/vi/swapChain.cpp:119-166`). It blocks until a framebuffer is free (`fbFreeCount` and `blockNewFrame`), picks the free index, computes a smoothed delta-time from a 6-sample `RingBuffer` (clamped to 1/5 s, line 147), then calls `drawTask(&frameBuffers[freeIdx], freeIdx, renderPassDone)`. `renderPassDone` (line 63) pushes the index into a FIFO for the VBlank handler.

The **draw task** is set by each pipeline in its `init()`. Default (`src/renderer/pipelineDefault.cpp:37-46`):
```
rdpq_attach(surf, surfDepth); scene.draw(getDeltaTime()); Debug::Overlay::draw(surf); rdpq_detach_cb(done, fbIndex);
```
So `scene.draw` is invoked *inside* the RDP command stream for one of the 3 rotating buffers. HDR-Bloom and BigTex do the same but with their own pre/post processing (`pipelineHDRBloom.cpp:47-56`, `pipelineBigTex.cpp:55-62`).

**VI swapchain** (`vi/swapChain.h`/`.cpp`): triple-buffered (`FB_COUNT=3`, line 13). A VBlank interrupt handler `onVIFrameReady` (line 38) pops the next finished buffer from `fbIdxForVI` FIFO and calls `vi_show` — this is the async "VI chases the RDP" design. `init` (line 73) primes the state machine; `start` (line 185) shows the first frame; `drain` (line 168) waits via `RSP_WAIT_LOOP` until only the VI holds a buffer (used between scenes). **GOTCHA:** 200 ms RSP-timeout escape hatch that forces a free buffer (lines 132-137) — a fallback for RSP hangs, not normal flow; if hit it logs an error and may show a torn frame.

**Three render pipelines** selected by `SceneConf::Pipeline` in `Scene::Scene` (`scene.cpp:78-84`):
- **Default** (`pipeline.h:34`, `pipelineDefault.cpp`): RGBA16 or RGBA32 (`FLAG_SCR_32BIT`) color Fbs, per-frame depth buffer allocated via `Mem::allocDepthBuffer`. `preDraw` sets standard rdpq mode + optional depth/color clear. `draw` = `DrawLayer::draw3D/drawPtx/draw2D/nextFrame`.
- **HDR+Bloom** (`pipelineHDRBloom.h`/`.cpp`): **fixed 320×240 RGBA16 only** (asserts at lines 34-36). Uses a custom RSP ucode `RspHDR::init/destroy` (`src/renderer/hdr/rspHDR.cpp` + `rsp_hdr.S`/`rsp_hdr.rspl`). `PostProcess` (`renderer/hdr/postProcess.h`) keeps HDR + blur A/B surfaces; `preDraw` calls `postProc[frameIdx].beginFrame()`, `draw` calls `endFrame` then `applyEffects(*fb)` to produce the bloom composite, then `draw2D`. Ping-pongs `frameIdx` across `BUFF_COUNT=3` so post-processing of frame N-1 happens concurrently with rendering frame N. Config: `blurSteps=4, hdrFactor=2.0, bloomThreshold=0.2` (`pipelineHDRBloom.cpp:20-26`).
- **BigTex** (`pipelineBigTex.h`/`.cpp`): also **320×240 RGBA16 only**. A custom RSP ucode (`rsp_bigtex.S` + `applyTexture.S` hand-written ASM) plus CPU-side `BigTex_applyTexture` (declared `extern "C"` at `pipelineBigTex.cpp:16-19`) to composite. Renders geometry into a UV-index buffer (`fbs.uv[frameIdx]`) + shade buffer, then `draw()` blends slices (`SHADE_BLEND_SLICES=16`) back into the color fb. Has 3 draw modes (DEF/UV/MAT) and triple-buffers UV/shade/color (`frameIdx = (frameIdx+1)%3`). Supports textures larger than 4 KB TMEM by streaming through `BigTex::Textures textures{18}`. **GOTCHA:** asserts that `FLAG_CLR_COLOR` is NOT set (line 76) — BigTex can't clear color.

**Materials/textures/meshes at runtime:**
- Models are libdragon `T3DModel*` loaded by `AssetManager` (type `MODEL_3D` → `t3d_model_load`, `assetManager.cpp:89`). `Comp::Model::draw` draws mesh indices with an embedded `MaterialInstance`.
- `Renderer::Material` (`renderer/material.h`) is the **baked, immutable** material: a `flagsData` uint32 packs AA/filter/Z-read/Z-write/persp/dither plus per-feature enable bits (`FLAG_TEX0/TEX1/CC/BLENDER/K4K5/PRIMLOD/PRIM/ENV/T3D_VERT_FX…`). The actual CC/blender/prim/env/tile data trails in `char data[]`. `begin/end` push/pop rdpq state.
- `Renderer::MaterialInstance` is the **per-object mutable** overlay: prim/env/fresnel colors + up to 8 texture `Placeholder` slots, each rebuilding an `rspq_block_t` on `update()`. Placeholders must be declared in the editor (baked into `setMask`) or `getPlaceholder` returns nullptr.
- Fixed-point model matrices are pool-allocated via `MatrixManager` (`lib/matrixManager.h`) with `RingMat4FP` triple-buffering so the RSP reads a stable matrix while the CPU prepares the next frame.

### 2.5 Collision & physics

Located under `n64/engine/include/collision/` (24 headers) and `n64/engine/src/collision/` (18 `.cpp`). Author tag on most files: Kevin Reier (Byterset).

**Architecture / scene:** `P64::Coll::CollisionScene` (`collision/collisionScene.h`) is a singleton via `collisionSceneGetInstance()` (line 197). It tracks `std::vector<RigidBody*>`, `std::vector<Collider*>`, `std::vector<MeshCollider*>`, a `std::deque<ContactConstraint>` cache + lookup map, and **two dynamic AABB trees** (broadphase): `colliderAABBTree` and `meshColliderAABBTree` (lines 149-150). `step()` runs the full solver pipeline; private methods list the phases (lines 185-194): `detectAllContacts`, `preSolveContacts`, `warmStart`, `solveVelocityConstraints`, `solvePositionConstraints`, `detectSweptCollisions` (CCD), `updateSleepStates`, `updateMeshColliderWorldStates`. Tunables in `scene.cpp:118-126` come from `SceneConf`: gravity, `fixedDt` (default 1/50), velocity/position solver iterations (defaults 8/7, `collisionScene.h:29-30`), `visualUnitsPerMeter` (`gfxScale`). Bullet-style warm starting (`WARM_STARTING_FACTOR=0.85`, line 31) and split-impulse push velocities (`rigidBody.h:214-218`).

**Broadphase:** `AABBTree` (`collision/aabbTree.h`) — a dynamic BVH with `NodeProxy=int16_t`, fattened AABBs (`AABB_DISPLACEMENT_MULTIPLIER=10`), `queryBounds/queryPoint/queryRay`, `makeNodePairKey` for stable pair ids.

**Narrowphase:** GJK + EPA.
- `gjk.h` — `GjkSupportFunction = void(*)(const void*, const fm_vec3_t&, fm_vec3_t&)`, `Simplex` (tetrahedron, max 4 points), `gjkCheckForOverlap` returns bool + optional separating axis.
- `epa.h` — `EpaResult{contactA,contactB,normal,penetration}`, `epaSolve` expands the GJK simplex to find MTV.
- `collide.h` — `collideDetectObjectToObject`, `collideDetectObjectToMesh`, `collideDetectObjectToTriangle`, `collideCacheContactConstraint`.
- `contact.h` — `ContactPoint`, `ContactConstraint`, `ContactConstraintKey` + hash (ColliderPair / ColliderMesh / ColliderMeshTriangle). `MAX_CONTACT_POINTS_PER_PAIR=3`.

**Shape types** (`collision/types.h` ShapeType enum + `collision/shapes.h`): **Sphere, Capsule, Box (OBB), Cone, Cylinder, Pyramid**. Each `*Shape` provides `support(dir)` (for GJK), `boundingBox(rot)`, `inertiaTensor(mass)`. `Collider` (`collision/colliderShape.h`) is a union of all six, plus owner ptr, parent offset, bounce, friction, read/write masks, trigger flag, cached world AABB/rotation matrices, and `syncOwnerTransform`/`syncWorldState`/`syncFromRigidBody`.

**RigidBody** (`collision/rigidBody.h`): full rigid body — position/rotation, linear+angular velocity, acceleration+torque accumulators, mass/inverseMass, inertia tensors (local + world), constraint flags (FreezePosX/Y/Z/RotX/Y/Z), timeScale, gravityScale, angular damping, kinematic + sleeping state (`SLEEP_STEPS=120`, thresholds in lines 27-37), split-impulse push velocities, island/wake machinery. Methods: integrate velocity/position/rotation, apply forces/impulses/torque, `getVelocityAtPoint`, constraint projections.

**Mesh colliders** (`collision/meshCollider.h`): concave triangle meshes with their *own* per-mesh AABB tree over triangles; `createFromRawData` (from a built collision asset) / `create` (manual verts+tris); local↔world transforms; `queryTriangleNodes`. Each `MeshTriangle` carries a GJK support function. This is the static-world collider (no rigid body needed).

**Queries exposed publicly:**
- `CollisionScene::raycast(Raycast&, RaycastHit&)` (`collisionScene.h:102`). `Raycast` (`raycast.h`) has origin/dir/invDir/maxDistance + `RaycastColliderTypeFlags` (MESH_COLLIDERS / COLLIDER_BODIES / ALL) + readMask + interactTrigger. `RaycastHit{point,normal,distance,hitObjectId,didHit}`. Constants `RAYCAST_MAX_COLLIDER_TESTS=50`, `RAYCAST_MAX_TRIANGLE_TESTS=30`.
- `CollisionScene::capsuleSweep(center,axisUp,radius,innerHalfHeight,displacement,collTypes,readMask,hit,ignoreOwner)` (line 117) → `CapsuleSweepHit{normal,point,t,depth,didHit}`.
- `CollisionScene::sphereSweep(center,radius,displacement,…)` (line 129) → `SphereSweepHit`.

**CharacterBody controller** (`collision/characterBody.h`): a kinematic capsule controller, *not* a rigid body. `Settings`: up, centerOffset, gravity, maxFallSpeed, floorMaxAngle (45°), stepHeight (auto stair-climb by shrinking capsule bottom), floorSnapDistance, radius, height, collTypes, maxSlides, readMask, followFloor. Public API: `configure`, `inputVelocity` (set by user), `getVelocity`/`setVelocity`, `isOnFloor`/`isOnSteepSurface`/`floorNormal`/`getFootPos`/`floorObjectId`/`wasMovedByFloor`, `setUp`/`setCenterOffset`, `teleport(pos,resetForces)`, **`moveAndSlide(dt)`** (the main movement solver: gravity + sweep + slide + floor snap + writes back to `Object::pos`), `debugDraw`. Uses `Attach` (`collision/attach.h`) to track the contact point on a moving mesh so the character is carried by platforms (followFloor). Wrapped as component `Comp::CharBody` (ID 12). Real usage example: `n64/examples/char_body/src/user/Controller.cpp` — sets `body.inputVelocity`, jumps via `body.setVelocity`, calls `body.moveAndSlide(dt)`, reads `isOnFloor`/`isOnSteepSurface`, toggles planet gravity via `body.setUp`, teleports on fall (line 143).

**Collision events to scripts:** `CollisionScene::dispatchCollisionCallbacks` builds a `CollEvent{selfCollider,hitCollider,selfMeshCollider,hitMeshCollider,selfRigidBody,hitRigidBody,contactCount,contacts,otherObject}` and `Scene::onObjectCollision` (`scene.cpp:436-444`) dispatches it into the object's components' `onColl` (`scene.cpp:49-60`). **GOTCHA:** `CharacterBody` deliberately produces no collision events — `floorObjectId()` is provided instead so platforms can react (`characterBody.h:97-103`).

### 2.6 Audio

`n64/engine/include/audio/audioManager.h` + `src/audio/audioManager.cpp` (+ private `audioManagerPrivate.h`).
- Backed by libdragon's `audio_init(freq,3)` + `mixer_init(CHANNEL_COUNT)` (`audioManager.cpp:84-85`). **32 mixer channels** (`CHANNEL_COUNT=32`, line 14).
- `init(freq)` (`audioManager.cpp:72-89`): only re-initializes if `freq` changed. Frequency comes from `SceneConf::audioFreq` (`scene.cpp:74`), so each scene can set its own mix rate.
- Slot model: `std::array<Slot,32>`; each `Slot` is a union of `wav64_t*`/`xm64player_t*` with volume/speed/uuid/isXM. `getFreeSlots(count)` finds `count` consecutive free slots (multi-channel wav needs N consecutive slots, lines 47-59).
- `play2D(wav64_t*)` plays a WAV on a free slot via `wav64_play`; `play2D(xm64player_t*)` plays XM music via `xm64player_play` reserving N channels; `play2D(assetId)` resolves through `AssetManager::getByIndex` (inline in header, lines 57-59). Returns `Audio::Handle{slot,uuid}`.
- `Audio::Handle` (4 bytes): `stop`, `setVolume`, `setSpeed` (WAV only; warns for XM, line 220), `isDone`. UUID guards against stale handles.
- `update()` (`audioManager.cpp:91-120`): `mixer_try_play`, per-slot volume apply + stop-on-finish.
- `setMasterVolume`, `stopAll`, `Metrics` (bitmasks of allocated/playing channels, used by the debug overlay `ovlAudio.cpp`).
- Component: `Comp::Audio2D` (ID 6) auto-plays wav/xm with LOOP/AUTO_PLAY flags.

Formats supported (via asset handlers in `assetManager.cpp:84-95`): **WAV64** (AUDIO type, `wav64_load`), **XM64** music (MUSIC_XM type, `xm64player_open`). No direct MP3 decode at runtime — `.mp3` files are converted to XM64 at build time by `src/build/audioBuilder.cpp`.

**GOTCHA:** `AudioManager::destroy()` exists in the `.cpp` (line 122) but is **not** declared in the public header. The public API has no teardown; audio is torn down implicitly on `mixer_close` frequency change.

### 2.7 Asset / memory management

**Global asset manager:** `P64::AssetManager` (`assets/assetManager.h` / `src/assets/assetManager.cpp`) — a single process-wide table. `init()` (line 101) loads `rom:/p64/a` (the asset table, baked by the editor) and fixes up path pointers. The table is `AssetTable{count; AssetEntry entries[]}` where each `AssetEntry` packs a `path` pointer and a `data` pointer whose **top nibble is the type and top 4 bits of the next byte are flags** (lines 27-45) — a tagged-pointer trick relying on N64 pointers fitting in 24 bits (`0x00FFFFFF` mask, line 37). **GOTCHA:** assumes all asset allocations live in the low 16 MB; on N64 with standard memory this holds, but it's a hard implicit constraint.

`getByIndex(idx)` lazy-loads: looks up the entry, if pointer null calls the type's `LoadFunc`, stores the pointer, returns it (`0x80000000`-OR'd to make it cached/uncached — line 147). Per-type handlers (`assetManager.cpp:84-95`):
- UNKNOWN/PREFAB → `asset_load` + `free`
- IMAGE → `sprite_load`/`sprite_free`
- AUDIO → `wav64_load`/`wav64_close`
- FONT → `rdpq_font_load`/`rdpq_font_free`
- MODEL_3D → `t3d_model_load`/`t3d_model_free`
- CODE_OBJ / CODE_GLOBAL → null (no load; these are compiled-in C++)
- NODE_GRAPH → `P64::NodeGraph::load` (patches the first slot with the C function pointer matched by UUID, `src/script/nodeGraph.cpp:29-36`)
- MUSIC_XM → `xm64player_open` (heap-allocs the player) / close+delete

`freeAll()` (line 113) iterates and frees everything except entries flagged `FLAG_KEEP_LOADED`. **Called automatically in `Scene::~Scene`** (`scene.cpp:143`) — so all asset pointers are invalidated every scene transition (documented in the header, line 23). `AssetRef<T>` (`assetManager.h:47-64`) is a lazy wrapper storing either an index (<0xFFFF) or a resolved pointer, used in components to defer loads. `PrefabRef` is just an index.

**Project config & fonts** (`main.cpp:78-91`): `rom:/p64/conf` is loaded as a `ProjectConf{sceneIdOnBoot, sceneIdOnReset, autoLoadFonts[16]}`; fonts whose slot isn't 0xFFFF are auto-loaded and registered with `rdpq_text_register_font`.

**Scene binary loading** (`src/scene/sceneLoader.cpp`): scenes live at DFS path `rom:/p64/sNNNN_` where NNNN is the zero-padded scene id (`updateScenePath`, lines 41-46). Sub-files by suffix: `_` = config (SceneConf), `_o` = objects. `loadObject` (line 67) reads packed `ObjectEntry{flags,id,group,pos,scale,packedRot}`, pre-scans components to size the allocation (`getAllocSize` per component), `memalign(8, allocSize)`, zero-fills (hw_memset for ≥16 bytes), placement-`new`s the `Object`, fills `CompRef[]` from the stream (compId + argSize in 4-byte units), and either calls `initDel` immediately or defers it (`deferComponentInit=true` is used at scene load so parent active state can be resolved first, `sceneLoader.cpp:143-150` + `scene.cpp:179-226`). An `EVENT_TYPE_READY` is queued for every loaded object (`sceneLoader.cpp:161`). Quaternions are packed as a 32-bit value (`Math::unpackQuat`, line 125).

**Memory management:**
- `P64::Mem` (`lib/memory.h`): a single lazily-allocated depth buffer (`allocDepthBuffer` reuses/sizes; `freeDepthBuffer` called per scene in `main.cpp:117`). `getHeapDiff()` snapshots the libdragon heap to detect leaks (called every main-loop iteration, `main.cpp:108-111`, logs a warning on non-zero diff). `StaticMem` reports text/data/bss sizes via `__text_start/end` etc. linker symbols.
- `MatrixManager` (`lib/matrixManager.h`): a pool of `T3DMat4FP` fixed-point matrices for the RSP, with `RingMat4FP` triple-buffering so the CPU never overwrites a matrix the RSP is still reading. `reset()` called per scene (`main.cpp:118`).
- Object memory: `memalign(8,…)` + manual `~Object()` + `free` (`scene.cpp:136-139`, `284-287`); `malloc_usable_size` tracks `memObjects` for the debug overlay. Comment at `sceneLoader.cpp:106` marks `@TODO: custom allocator`.
- BigTex has its own memory manager (`src/renderer/bigtex/memory.cpp`/`.h`) for the large texture pool and UV/shade framebuffers; HDR pipeline allocates HDR/blur surfaces in `PostProcess`.

**No explicit TMEM manager** in the engine sources — TMEM is driven by tiny3d/rdpq. The BigTex subsystem is the engine's answer to the 4 KB TMEM limit: it streams >4 KB textures by rendering UV indices then compositing in slices via custom RSP/CPU code. **GOTCHA:** BigTex asserts no `FLAG_CLR_COLOR` (can't clear) and is fixed 320×240; HDR-Bloom is also fixed 320×240 and RGBA16-only — these are ucode-imposed limits the editor must enforce upstream.

### 2.8 Script callbacks

Two script systems, both code-generated by the editor:

**(a) Per-object scripts (`Code` component, ID 0)** — A user script is a `src/user/*.cpp` defining functions inside a namespace named after the script's UUID hex, e.g. `namespace P64::Script::CB7F8F3EFD4E4EBF { … }` (`n64/tests/test_obj_states/src/user/ObjCapture.cpp:5`). It uses the `P64_DATA(...)` macro (`script/userScript.h:18-21`) to declare a `Data` struct of per-instance fields (which the editor exposes via `[[P64::Name]]` attributes; supported editor-settable types listed in `ObjCapture.cpp:9-17`). The editor's `src/build/scriptBuilder.cpp` parses each script (via `Utils::CPP::hasFunction`, lines 27-35) to detect which callbacks exist, then emits:
- forward declarations `namespace <UUID> { struct Data; extern uint16_t DATA_SIZE; void init/destroy/update/fixedUpdate/draw/onEvent/onCollision(...); }`
- a `ScriptEntry` row with function pointers cast to the `Func*` typedefs (only the detected ones).

These rows fill `P64::Script::getCodeByIndex/getCodeSizeByIndex` (`script/scriptTable.h:31-33`) in the generated `src/p64/scriptTable.cpp`. At runtime, `Comp::Code::initDelete` (`scene/components/code.h:43-70`) looks up `Script::getCodeByIndex(initData[0])`, copies the editor-baked `Data` defaults (`memcpy(dataPtr+sizeof(Code), &initData[2], dataSize)`), computes the `usedFunctions` bitmask, and calls `script->init`. The per-frame dispatch is in `Scene::update`/`draw`/`runPendingEvents`/`onObjectCollision` via `COMP_TABLE[compRefs[i].type].update/draw/onEvent/onColl` (`scene.cpp:233-269, 295-376, 378-400, 49-60`), which for a Code component calls `Comp::Code::update` etc. (`code.h:72-100`), each guarded by the `usedFunctions` bitmask so absent callbacks are a single branch, not an indirect call.

**Event callbacks available to a Code script** (signatures in `scriptTable.h:14-28`):
- `init(Object&, Data*)` and `destroy(Object&, Data*)` — lifecycle.
- `update(Object&, Data*, float)` — variable per-frame.
- `fixedUpdate(Object&, Data*, float)` — fixed physics step (called inside the accumulator loop, `scene.cpp:231-249`).
- `draw(Object&, Data*, float)` — inside the 3D pass per camera.
- `onEvent(Object&, Data*, const ObjectEvent&)` — receives ENABLE/DISABLE/READY built-ins and any custom event via `Scene::sendEvent`. READY is queued at load (`sceneLoader.cpp:161`).
- `onCollision(Object&, Data*, const Coll::CollEvent&)` — from `Scene::onObjectCollision`.

**(b) Global scripts (`GlobalScript` hooks)** — A user `src/user/globalSetup.cpp` defines functions inside a UUID namespace under `P64::GlobalScript::<UUID>`, named exactly after the `HookType` enum (`script/globalScript.h:11-32`): `onGameInit`, `onScenePreLoad`, `onScenePostLoad`, `onScenePreUnload`, `onScenePostUnload`, `onSceneUpdate`, `onScenePreDraw`, `onScenePreDraw3D`, `onScenePostDraw3D`, `onSceneDraw2D`. The editor generates a dispatcher `GlobalScript::callHooks` that calls the matching function for each registered global script. `callHooks` is invoked at the precise points in `main.cpp:97` (GAME_INIT), `sceneManager.cpp:38/43/53/55` (load/unload), `scene.cpp:168` (UPDATE), `scene.cpp:299/319/345/358` (PRE_DRAW / PRE_DRAW_3D / POST_DRAW_3D / DRAW_2D). Example: `n64/examples/jam25/src/user/globalSetup.cpp` implements most hooks under namespace `P64::GlobalScript::C4F4D286D6CBAAAA`.

**(c) NodeGraph scripts (visual scripting)** — `Comp::NodeGraph` (ID 9) wraps a `NodeGraph::Instance` (`script/nodeGraph.h`) which runs a coroutine (`coro_create/coro_resume/coro_destroy`) produced from a `.p64graph` asset. The graph's bytecode is patched at load time (`src/script/nodeGraph.cpp:29-36`) to bind its first slot to a C `GraphFunc` looked up by UUID via `Script::getGraphFuncByUUID`. Custom JS nodes are the modern extension mechanism (the `registerFunction` C-bind is `[[deprecated]]`, `nodeGraph.h:52`). `Comp::NodeGraph::run(arg0,arg1)` starts it; `update` resumes the coroutine each frame until it finishes (`components/nodeGraph.h:66-72`).

**GOTCHA:** Script namespaces are keyed by **64-bit UUID hex strings**, not human names. The editor (`src/utils/codeParser.cpp`) extracts these; if two scripts ever collide UUIDs the generated `scriptTable.cpp` will have ambiguous symbols. The `P64_DATA` macro `static_assert(sizeof(Data) < 0xFFFF)` (`userScript.h:19`) caps per-instance data at 64 KB-1 because `DATA_SIZE` is `uint16_t`.

**GOTCHA:** `Comp::Code` stores a raw `Script::ScriptEntry*` (`code.h:26`) resolved at init from `getCodeByIndex`. If the asset table's script index ordering ever drifts from the generated `scriptTable.cpp` ordering, the wrong script runs on an object. The editor's `scriptBuilder.cpp` is responsible for keeping these in sync.

### 2.9 Examples & tests

`n64/examples/` has 6 projects; `n64/tests/` has 1. Each is a **runnable .z64 ROM** (same structure: `Makefile.custom`, `project.p64proj`, `assets/`, `data/scenes/<id>/scene.json`, `src/user/*.cpp`, generated `src/p64/`).

- `n64/examples/empty/` — minimal baseline. Assets: a box (`box.glb`), `crate32.png`, font conf. One scene. No user scripts beyond what's generated. Demonstrates the bare project skeleton / build pipeline.
- `n64/examples/baked_light/` — baked lighting showcase. User scripts: `DebugCam.cpp`, `Light.cpp`. Two scenes. Assets include `glass_reflection_a.i8.png` (env/reflection), brick/rock/snow textures, `.glb` scenes with baked lightmaps.
- `n64/examples/bigtex/` — BigTex pipeline demo. User script: `DebugCam.cpp`. One scene. Assets include `marble_bust_01_4k.glb` (a high-res bust that won't fit TMEM normally), 6 cube-map faces, `skybox.glb`. Demonstrates `BIG_TEX_256` pipeline streaming large textures via the custom RSP ucode.
- `n64/examples/char_body/` — CharacterBody controller demo. User scripts: `Controller.cpp`, `DebugCam.cpp`, `Platform.cpp`. Two scenes. `Controller.cpp` is the reference CharacterBody usage: `moveAndSlide`, jump with coyote time, planet gravity (dynamic `setUp`), moving-platform follow, debug overlay, camera orbit.
- `n64/examples/material_test/` — material system demo. User scripts: `DebugCam.cpp`, `Flame.cpp`, `Rot.cpp`, `WaterFX.cpp`. Two scenes. Demonstrates `Renderer::MaterialInstance` placeholders, UV generation, animated water/flame, env reflection, prefabs.
- `n64/examples/jam25/` — the largest, a real game jam entry. Complete 3D platformer. 11 scenes. ~20 user scripts: `Player`, `Coin`, `Goal`, `ObjBot`, `ObjHead`, `ObjVoid`, `LoadingZone`, `Seesaw`, `RotAnim`, `TestRot`, `TitleScreen`, `TitleCard`, `Credits`, `HUD`, `MiniMap`, `Particles`, `SkyBox`, `BootChecks`, `BootLogos`, `DebugCam`, plus a `systems/` subfolder and a `nodes/` folder with JS node-graph nodes. Uses global scripts, prefabs, `.p64graph` visual scripts, XM music, large SFX set. Demonstrates essentially every engine feature together.
- `n64/tests/test_obj_states/` — automated self-checking test ROM. User scripts: `TestSetup.cpp` (under `P64::GlobalScript::C98127B5B02279B8`) and `ObjCapture.cpp` (under `P64::Script::CB7F8F3EFD4E4EBF`). 4 scenes. `ObjCapture` records every INIT/DESTROY/UPDATE/FIXED_UPDATE/DRAW/READY/ENABLE/DISABLE event with frame, objId, parentId, enabled flag. `TestSetup` defines a vector of `TestDef{name, sceneId, fnUpdate, fnTest}` covering object state-machine cases. Each test runs N frames then compares captured events against expected. **GOTCHA:** tests run on-device only; no host-side test runner aggregates results. `test_obj_states` self-reports via `debugf`/onscreen text. This is the conformance test for the runtime object state-machine / event ordering — it documents the exact expected ordering (e.g. DESTROY suppresses a same-frame DISABLE/ENABLE event; READY fires on frame 1 before the first UPDATE/DRAW).

---

## 3. Asset pipeline

### 3.1 Project file format

**Format:** JSON file named `project.p64proj` (mimetype `application/x-pyrite64-project`, `src/mimetype.xml:1-8`). The `.p64proj` is the *only* project-file; everything else lives in subdirs.

**Read/write:**
- Struct `Project::Project::ProjectConf` — `src/project/project.h:53-74`.
- Serialize: `src/project/project.cpp:125-147` (`ProjectConf::serialize`) via `Utils::JSON::Builder`.
- Deserialize: `src/project/project.cpp:149-165` (`Project::deserialize`).
- Load + self-repair: `Project::Project` ctor `src/project/project.cpp:167-247` — reads JSON, creates required dirs (`data/scenes`, `assets/p64`, `src/p64`, `src/user`), writes `.gitignore` from `data/build/baseGitignore`, writes `Makefile.custom` from `data/build/baseMakefile.custom`, copies `assets/p64/font.ia4.png` from `data/build/assets/font.ia4.png`. Compares `editorVersion` to `PYRITE_VERSION`; older → forces clean build (`project.cpp:212-220`). **GOTCHA:** opening a project can silently delete your `build/` and `engine/build/` if the editor version bumped, even if you had local changes there.
- Save: `Project::save()` `project.cpp:258-263` → `saveConfig()` (writes `.p64proj`), then `assets.save()` and `scenes.save()`.

**Project config JSON keys** (from `project.cpp:125-147`): `name`, `romName`, `pathEmu`, `pathN64Inst`, `editorVersion`, `romHeader` (object: `category`, `region`, `saveType`, `regionFree`, `rtc`, `controllers[4]`), `metadata` (object: `enabled`, `langs[]` of MetaLang with `lang`,`name`,`author`,`releaseDate`,`osiLicense`,`website`,`shortDesc`,`longDesc`,`ageRating`,`screenshots[]`,`boxFront/Back/Top/Bottom/Left/Right`,`cartFront/Back`), `sceneIdOnBoot`, `sceneIdOnReset`, `sceneIdLastOpened`, `debugMenu`, `assetExclusions` (array of assets-relative slash-aware globs), `collLayer0..7`.

`assetExclusions` is the project-wide alternative to one `"exclude": true` sidecar per file. `*` and `?` stay within one path segment, `**` crosses directories, and a pattern without `/` matches basenames anywhere. Absolute paths and `.`/`..`/empty segments are invalid. The native asset manager stores every matching pattern on an entry; `AssetManagerEntry::isExcluded()` combines project matches with the sidecar flag. All native builders and the headless inventory/validation/build plan consume that effective state. The Project Settings GUI authors these patterns, and `bf64 asset exclusion list/add/remove` provides the atomic headless surface.

**Project subdirs** (created in ctor, `project.cpp:178-186`):
- `data/scenes/` — scene dirs named by integer id, each with `scene.json`
- `assets/` — imported source assets (PNG, WAV/MP3, XM, GLB/glTF, TTF, `.prefab`, `.p64graph`); each asset may have a sibling `<asset>.conf` JSON
- `assets/p64/` — engine-bundled assets (font)
- `src/user/` — user C++ scripts (`.cpp`)
- `src/p64/` — *generated* tables (`scriptTable.cpp`, `globalScriptTable.cpp`, `assetTable.h`, `sceneTable.h/.cpp`, per-graph `<uuid>.cpp`)
- `filesystem/` — *generated* converted ROM assets (`.sprite`, `.wav64`, `.xm64`, `.t3dm`, `.font64`, `.pf`, `.pg`, `.bci`) + `filesystem/p64/` runtime bins (`a`, `conf`, `fileList.txt`)
- `build/` — *generated* make build objects
- `engine/` — synced copy of `n64/engine` (see `copyChangedEngineFiles`, `project.cpp:29-59`)
- `metadata/` — *generated* ROM metadata (INI + copied box/cart images); gitignored (`project.cpp:191-204`)
- `nodes/` — optional user node definitions (`<project>/nodes/*.js`, loaded in ctor `project.cpp:229`)

**File extensions the editor reads/writes** (from `buildAssetEntry`, `src/project/assetManager.cpp:101-185`):

| Extension | FileType | Output ext | Converter |
|---|---|---|---|
| `.png` | IMAGE | `.sprite` | `mksprite` (libdragon) |
| `.bci.png` | IMAGE | `.bci` | internal `BCI::convertPNG` (`src/build/tools/bci.cpp`) |
| `.wav` / `.mp3` | AUDIO | `.wav64` | `audioconv64` |
| `.xm` | MUSIC_XM | `.xm64` | `audioconv64` |
| `.glb` / `.gltf` | MODEL_3D | `.t3dm` | `T3DM::writeT3DM` + `mkasset` |
| `.ttf` | FONT | `.font64` | `mkfont` |
| `.prefab` | PREFAB | `.pf` | internal prefab builder |
| `.p64graph` | NODE_GRAPH | `.pg` | internal `nodeGraphBuilder` |
| `.cpp` (in `src/user/`) | CODE_OBJ / CODE_GLOBAL | (compiled) | gcc via makefile |

Plus sidecar `<asset>.conf` JSON (written/read by `AssetConf::serialize`/`deserialize`, `assetManager.cpp:81-99`, `229-244`). Project file `.p64proj`, scenes `scene.json`, generated `.h/.cpp/.mk/.ini/.txt/.z64`.

**Sidecar defaults:** `AssetConf::deserialize` and the headless asset view now normalize every editor-known field. Missing, null, or wrongly typed fields receive the same defaults (`baseScale=16`, numeric zeroes, false booleans, empty data) without rewriting the source sidecar. `asset show`/validation report which fields were defaulted, so a minimal `{"exclude":true}` sidecar is safe in both CLI and editor builds.

**GOTCHA:** Project creation (`globalActions.cpp:106-146`) copies `n64/examples/empty` recursively then deletes `Makefile`/`build`/`filesystem`/`p64_project.z64`. The template's `.p64proj` is patched with the user's `name`/`rom`. No validation that `n64/examples/empty` exists — if the submodule isn't checked out, creation silently copies nothing meaningful.

### 3.2 Scene serialization

**Format:** JSON. Each scene is a *directory* `data/scenes/<id>/scene.json` (id is an integer string). Enumerated by `SceneManager::reload` `src/project/scene/sceneManager.cpp:24-68`. Loaded by `SceneManager::loadScene` `sceneManager.cpp:131-141`.

**Top-level schema** (`Scene::serialize`/`deserialize`, `src/project/scene/scene.cpp:388-491`):
```text
{
  "conf": { /* SceneConf */ },
  "graph": { /* Object tree, root named "Scene" */ }
}
```
Serialized with `doc.dump(minify ? -1 : 2)` (`scene.cpp:392`) — pretty-printed by default. **GOTCHA:** the field is named `graph` but it is the *object tree*, not a node graph — confusing naming.

**SceneConf fields** (`src/project/scene/scene.h:29-54`): `name` (default "New Scene"), `fbWidth` (320), `fbHeight` (240), `fbFormat` (0=RGBA16, 1=RGBA32), `clearColor` (vec4), `doClearColor`, `doClearDepth`, `renderPipeline` (0=Default, 1=HDR-Bloom, 2=HiRes-Tex 256x), `frameLimit`, `filter`, `audioFreq` (32000), `physicsTickRate` (50), `gravity` (vec3, default {0,-9.81,0}), `visualUnitsPerMeter` (100), `velocitySolverIterations` (7), `positionSolverIterations` (6), `interpolatePhysicsTransforms` (true), `layers3D[]`, `layersPtx[]`, `layers2D[]` (each `LayerConf`: `name`, `depthCompare`, `depthWrite`, `blender`, `fog`, `fogColorMode`, `fogColor` (vec4), `fogMin`, `fogMax`, `lightMode`). If `layers3D` empty, `resetLayers()` (`scene.cpp:395-425`) seeds default Opaque/Transp/PTX/2D layers using libdragon `RDPQ_BLENDER_*` constants.

**Object tree (the "graph" key):** `Object` struct in `src/project/scene/object.h:24-132`. Serialized by `serializeObj` `object.cpp:19-59`:
```text
{
  "name": "...", "uuid": <u32>, "proportionalScale": bool, "selectable": bool, "enabled": bool,
  "uuidPrefab": <u64>,
  "pos": [x,y,z], "rot": [x,y,z,w], "scale": [x,y,z],
  "propOverrides": { "<keyInt>": <GenericValue> },
  "components": [ { "id": int, "uuid": u64, "name": str, "data": {...} } ],
  "children": [ ...recursive... ]
}
```
Deserialized by `Object::deserialize` `object.cpp:105-172`. Note: `uuid` is a **32-bit** hash for scene objects; prefab UUIDs are 64-bit. A legacy `"id"` field may be present but is intentionally ignored (`object.cpp:109-110`); runtime ids are build-time only (`object.h:31-33`, assigned in `Scene::assignRuntimeIds` `scene.cpp:493-514`, max 65535).

**Components:** `Component::Entry` (`components.h`): `id` (int index into `Component::TABLE`), `uuid` (u64), `name`, `data` (shared_ptr<void>). The `TABLE` maps stable ids 0-16 to 17 component types, ending with Player Spawn at id 15 and Blob Shadow at id 16. Each `CompInfo` has `funcSerialize`/`funcDeserialize` that produce/consume the `data` JSON object. **GOTCHA:** the `id` is a plain integer that must stay stable — adding or reordering component types breaks all saved scenes. The `constexpr TABLE` order is the canonical id assignment.

**Headless mutation:** `tools/bf64.py` exposes scene lifecycle, object-tree, component, and attachment commands over this same JSON contract. Proposed documents are validated before same-directory atomic replacement. Scene deletion is transactional across the scene directory and `project.p64proj`, with automatic rollback when final project validation or I/O fails. Generated object UUIDs are 32-bit; component UUIDs are 64-bit, matching the editor model.

**Prefab system** (`src/project/scene/prefab.h/.cpp`): a `Prefab` is just `PROP_U32(uuid) + Object obj`, serialized as JSON, saved to `<project>/assets/<sanitizedName>.prefab` (`scene.cpp:285`). `Scene::createPrefabFromObject` (`scene.cpp:244`) **rebases child transforms to be relative to their parent** (`scene.cpp:256-275`) because the engine has no runtime transform hierarchy — this is critical and the comment at `scene.cpp:252` explains why. `Scene::unpackPrefabInstance` (`scene.cpp:312`) materializes a prefab instance into real editable objects with baked world transforms. `Scene::addPrefabInstance` (`scene.cpp:140`) creates a thin instance with transform overrides pre-added.

**Property / override system** — `src/utils/prop.h`. The heart of the prefab-override cascade.
- `Property<T>` (`prop.h:271`) has a `name`, `id` (CRC64 of name, `prop.h:281`), `value`. `resolve(overrides, *isOverride)` (`prop.h:288`) walks the `PropScope::stack` of override layers (outermost first), looking up `PropScope::combine(layer.pathHash, id)`; if not found, falls back to the bare `overrides[id]`; else returns `value`. **GOTCHA:** the cascade is ambient via a `thread_local std::vector<Layer> PropScope::stack` (`prop.h:140`) — property resolution is *not* reentrant across objects; the RAII guards `Path` / `PrefabLayer` / `Dispatch` / `ResetScope` (`prop.h:181-268`) maintain it. The comment at `prop.h:124-128` explicitly lists the four walkers that must stay in sync: `sceneBuilder::writeObject`, `objectInspector`, `viewport3D renderNestedPrefab / resolveNestedTarget`, `sceneGraph drawPrefabDefNode`. **GOTCHA:** `Path` and `PrefabLayer` are explicitly non-copyable/non-movable (`prop.h:186-189, 225-228`) because their destructors unwind state — putting them in a `vector` by value and letting it reallocate runs a moved-from destructor and corrupts the path hash.
- `GenericValue` (`prop.h:18`) is a tagged-union of all supported property types with stable integer type IDs (`prop.h:42-53`); the comment at `prop.h:41` says "do NOT change those IDs or any saved prefabs/scenes will break!"
- The `PROP_*` macros (`prop.h:352-363`) declare a `Property<T>` whose `id` is `crc64(#name)` at construction.

**GOTCHA:** `propOverrides` keys are `uint64_t` derived from `PropScope::combine(pathHash, prop.id)` for nested prefab overrides (`object.h:67-90`) — the override map is keyed by integers, serialized as string keys in JSON (`object.cpp:36-39`, `127-133`), so any change to the hash-combine function silently breaks all saved overrides.

### 3.3 GLTF / fast64 import

**Importer:** the glTF/GLB parser lives in the vendored **tiny3d** submodule (`vendored/tiny3d/tools/gltf_importer/`). It is **not checked out in this workspace** (`vendored/tiny3d` is empty), but is referenced extensively. CMake builds it inline (`CMakeLists.txt:77-98`): `parser.cpp`, `writer.cpp`, `parser/materialParser.cpp`, `parser/boneParser.cpp`, `parser/nodeParser.cpp`, `parser/animParser.cpp`, `optimizer/meshOptimizer.cpp`, `optimizer/meshBVH.cpp`, `converter/meshConverter.cpp`, `converter/animConverter.cpp`, plus bundled `lodepng.cpp`, `meshopt/*`, `tristrip/*`, and `cgltf.h` (a single-header glTF library by jkuhlmann — that's the glTF parser lib).

**Library:** `cgltf` (c glTF library) for raw parsing, plus tiny3d's own material/animation converters. **No nlohmann json is used for glTF** — cgltf parses the binary/JSON container directly.

**Entry point:** `T3DM::parseGLTF(path, config)` — called in `AssetManager::reloadEntry` (`assetManager.cpp:304-322`) and in `buildT3DMAssets` (`t3dmBuilder.cpp:222-243`). Header referenced as `tiny3d/tools/gltf_importer/src/parser.h`.

**Config** (`T3DM::Config`, inferred from usage): `globalScale` (= `baseScale`, default 16), `animSampleRate` (60), `createBVH` (= `gltfBVH` conf flag), `verbose`, `assetPath` ("assets/"), `assetPathFull` (abs path), `projectPath`, `getMaterialInfo` callback (reads saved material tex sizes/filter from conf), `materialWriter` callback (build-time, `t3dmBuilder.cpp:234-241`).

**fast64 material handling:** fast64 (the Blender glTF exporter for N64) emits material-library nodes named `fast64_f3d_material_library*`. These are explicitly skipped in collision building (`collisionBuilder.cpp:84`). fast64 glTF materials carry RDP extensions (color combiner, other-mode, prim/env colors, textures) which tiny3d's `materialParser.cpp` reads into `T3DM::Material` structs. `Project::Assets::Material::fromT3D` (`material.cpp:150-244`) maps the T3DM material to engine material: color combiner (`cc`), `drawFlags`, `vertexFx`, fog mode → `fogToAlpha`, alpha compare, filter, prim/env colors, and two textures (`tex0`/`tex1`) with offset/scale/repeat/mirror from the T3D UV wrap/clamp/mirror flags. The conf's `data.materials` map (keyed by material name) overrides/edits these per-material.

**What import produces:** the source `.glb`/`.gltf` is **kept as-is** in `assets/`. At build time `buildT3DMAssets` (`t3dmBuilder.cpp:205-275`) calls `T3DM::writeT3DM(config, t3dm, t3dmPath)` to produce a `.t3dm` binary in `filesystem/`, then runs `mkasset -c <compr>` to compress it. The `.t3dm` is the converted N64 mesh format. In-editor, `AssetManager::reloadEntry` (`assetManager.cpp:295-343`) parses the glb into `entry.model.t3dm` and builds a `Renderer::N64Mesh` via `N64Mesh::fromT3DM` for viewport preview. Animation data is parsed by `animParser.cpp` and used by `renderer/animation.cpp`.

**Texture dependencies:** glTF materials reference texture *paths* (resolved against `assetPath`); `Material::fromT3D` calls `assets.getByPath(mat.texPath)` to bind the texture to its PNG asset UUID. So glTF textures must already exist as PNG assets in the project. **GOTCHA:** if `getByPath` fails (texture not in `assets/`), `tex.set.value` stays false — the material silently loses its texture binding with no warning (`material.cpp:174-181`).

**GOTCHA:** `reloadEntry` for `MODEL_3D` wraps the parse in try/catch and only logs (`assetManager.cpp:339-341`); a broken glb produces an empty model with no editor-visible error beyond the log.

### 3.4 Texture pipeline

**Editor preview loading:** `Renderer::Texture` (`src/renderer/texture.cpp:14-107`) uses **SDL_image** (`IMG_Load` / `IMG_LoadSizedSVG_IO` for SVG). Converts to `SDL_PIXELFORMAT_BGRA32`. Supports mono (I4/I8) mode: copies R channel into alpha (`texture.cpp:29-45`). Creates an SDL_GPU texture + uploads. PNG, plus anything SDL_image supports. Notably the editor does **not** do N64 format conversion for preview — it just shows the source.

**Input formats accepted (build):** `.png` (IMAGE), special-cased `.bci.png` → BCI_256 format (`assetManager.cpp:110-116`, `165-169`).

**N64 output formats** (`src/utils/textureFormats.h:9-24`): `AUTO`, `RGBA32`, `RGBA16`, `CI8`, `CI4`, `I8`, `I4`, `IA16`, `IA8`, `IA4`, `IHQ`, `SHQ`, `ZBUF`, `BCI_256`. Mono = I8/I4 (`textureFormats.h:49-51`).

**Conversion:** `Build::buildTextureAssets` (`src/build/textureBuilder.cpp:17-54`):
- For BCI_256: internal `BCI::convertPNG` (`src/build/tools/bci.cpp`) — a custom 4x4-block 4-color palette compressor (k-means clustering, `bci.cpp:42-60`), outputs a `.bci` file.
- For all others: shells out to libdragon's **`mksprite`** (`<N64_INST>/bin/mksprite`) with `-c <compression>` and optionally `-f <format>` from `TEX_TYPES[]`. Output is `.sprite`.

**TMEM fitting:** not done in the editor per-texture; TMEM fitting is implicit in libdragon's `mksprite`/sprite format and in tiny3d's material texture tiling (the `texSize`, `offset`, `scale`, `repeat` fields on `MaterialTex`, `material.h:23-49`, built in `material.cpp:50-81` with `offset*64`, `repeat*16`, signed scale). The material `build` writes per-tile S/T wrap/mirror/scale.

**Big-texture (256x256) streaming path:** a **scene-level render pipeline option**, not a per-texture flag. `SceneConf::renderPipeline` value 2 = "HiRes-Tex (256x)" (`sceneInspector.cpp:22`, `41-49` forces 320x240 RGBA16 when set). The runtime engine implements it under `n64/engine/src/renderer/bigtex/`. This is distinct from BCI_256 (a compressed still-image format). The editor doesn't generate bigtex data; it's a runtime mode the engine enters.

**GOTCHA:** `buildTextureAssets` (`textureBuilder.cpp:34-35`) computes `compr = compression - 1; if compr<0 compr=1` — i.e. `ComprTypes::DEFAULT` (0) becomes compression level 1, and there's a `@TODO` to pull a real default. So the "DEFAULT" enum value is **not** actually default-aware; it hardcodes level 1.

**GOTCHA:** `BCI::convertPNG` uses `rand()` for palette init (`bci.cpp:46`) — output is **non-deterministic** across builds, which can cause subtly different `.bci` outputs and break content-addressable caching.

### 3.5 Material system

Two distinct concepts:

**(a) Material** (`src/project/assets/material.h:51-99`, `.cpp`): the **asset-level** material definition, owned by a 3D model asset. One per glTF material name, stored in `Model3D::materials` map (`model3d.h:15`). Serialized into the **model asset's conf** under `data.materials[<name>]`. Fields: render-mode flags (`cc`/`blender`/`aa`/`fog`/`dither`/`filter`/`zmode`/`zprim`/`zdelta`/`persp`/`alphaComp` each with a `*Set` bool), two textures `tex0`/`tex1` (`MaterialTex`), T3D settings (`vertexFX`, `drawFlags`, `fogToAlpha`), color values (`k4k5`, `primLod`, `primColor`, `envColor`). Built to binary in `matWriter` (`t3dmBuilder.cpp:20-156`) producing a flag word + conditional fields, then inlined into the `.t3dm`.

`MaterialTex` (`material.h:23-49`): `set`, `texUUID`, `texSize` (ivec2), `dynType` (NONE/TILE/FULL), `dynPlaceholder`, `offset`, `scale`, `repeat`, `mirrorS/T`. `DYN_TYPE_TILE`/`FULL` mark textures as dynamically swappable at runtime via material instances. `MAX_PLACEHOLDERS=8` (`material.h:27`); `t3dmBuilder.cpp:36-44` drops placeholders past this limit and logs an error to prevent runtime corruption.

**(b) MaterialInstance** (`src/project/component/shared/materialInstance.h:25-51`, `.cpp`): a **per-object component override** living on the Model component (`compModel.cpp:36`). Holds an array of 8 `MaterialTex` slots (`texSlots`), plus per-object depth/prim/env/lighting/fresnel overrides. Serialized as the component's `material` sub-object. Built to binary in `MaterialInstance::build` (`materialInstance.cpp:49-90`) writing a `setMask` u16, flags, RGBA colors, then per-set-slot texture blocks.

**fast64 → engine mapping:** `Material::fromT3D` (`material.cpp:150-244`) as described in §3.3. The `AssetConf::data.materials` JSON holds per-material overrides that, if present for a material name, are deserialized into `Material` (`assetManager.cpp:324-331`); otherwise `fromT3D` generates defaults from the glTF. The `modelEditor.cpp` UI edits these and writes back to `conf.data.materials`.

**Material serialization locations:**
- Asset material: in `<asset>.glb.conf` → `data.materials[<name>]` (AssetConf serialize, `assetManager.cpp:229-244`, the `data` field).
- Per-object material instance: in the scene `scene.json` object component `data.material`.

**Runtime resolution:** `N64Mesh::draw` (`n64Mesh.cpp:86-205`) — for each part, looks up `model->materials[part.materialName]`, then if the material's tex is `DYN_TYPE_FULL` it pulls from `matInstance->texSlots[slotIdx]`; if `DYN_TYPE_TILE` it overrides offset only. `N64Material::convert` (`n64/n64Material.h`, `.cpp`) translates engine material → `UniformN64Material` GPU uniform.

**GOTCHA:** `Material::deserialize` (`material.cpp:142-143`) reads `k4k5Set` **before** `k4k5`, but `serialize` (`material.cpp:104`) writes them in the opposite conceptual order. Works because `readProp` is key-based, but order-dependent readers would break.

### 3.6 Audio assets

**Components:** `Component::Audio2D` (`src/project/component/types/compAudio2d.cpp`) stores `{audioUUID, volume, loop, autoPlay}` and supports WAV or XM. `Component::Audio3D` (`compAudio3d.cpp`, stable id 14) stores WAV UUID, source volume, pitch, loop/auto-play, min/max distance, and rolloff. Both resolve UUID → asset index at build time; Audio3D rejects tracker music and writes its spatial settings plus Q4.12 pitch into the runtime init block.

**Import/store:** source `.wav`/`.mp3` → AUDIO, `.xm` → MUSIC_XM. `Build::buildAudioAssets` (`src/build/audioBuilder.cpp:14-64`) shells out to libdragon's **`audioconv64`** (`<N64_INST>/bin/audioconv64`). Audio flags: `--wav-mono`, `--wav-resample <rate>`, `--wav-compress <level>` (only applied to AUDIO, not MUSIC_XM). Output `.wav64` (audio) / `.xm64` (music).

**Formats:** input WAV/MP3/XM; output WAV64 (libdragon's compressed wav format, supports vadpcm/opus) and XM64. Opus (`wavCompression==3`) triggers `needsOpus` in `buildGlobalScripts` which injects `wav64_init_compression(3)` into the game-init hook (`scriptBuilder.cpp:145-156`).

**Runtime spatialization:** `audio/spatialAudio.cpp` is dependency-light math for distance attenuation and equal-power stereo pan. `AudioManager::play3D` marks a WAV slot group as spatial; handles can move it, replace settings, or set a clamped `0.125x..8x` pitch without restarting. `Scene::update` uses the first camera as listener, and `Comp::Audio3D` follows its object's world position. The manager applies handle/master-volume/pitch changes across every channel occupied by a multi-channel WAV and treats default/stale handles as inert.

**GOTCHA:** `audioconv64` is invoked with the same flags for both AUDIO types but the wav-* flags are only added when `asset.type == AUDIO` (`audioBuilder.cpp:33-43`); an `.mp3` typed as AUDIO will pass `--wav-*` flags to `audioconv64` which may or may not accept them for mp3 input — undocumented.

### 3.7 Node-graph assets

**Format:** JSON. `.p64graph` files (asset), built to `.pg` binary + `<uuid>.cpp` source. On-disk schema (`Graph::deserialize`/`serialize`, `src/project/graph/graph.cpp:110-262`):
```text
{
  "repeatable": bool,
  "view": [scrollX, scrollY, scale],
  "variables": [ {"name": str, "type": "i32|u32|f32|vec3|quat|objref"} ],
  "nodes": [ {"uuid": u64, "typeId": "core.start", "pos": [x,y], /* props */ } ],
  "links": [ {"src": u64, "srcPort": int, "dst": u64, "dstPort": int, "points": [[x,y]...]} ],
  "groups": [ {"title": str, "pos": [x,y], "size": [w,h]} ]
}
```
New graph created with `{"nodes": [], "links": []}` (`assetManager.cpp:818`). Legacy graphs used integer `"type"` instead of `"typeId"`, mapped via `LEGACY_TYPE_IDS[14]` (`nodeRegistry.cpp:29-33`).

**Node definitions in `data/nodes/` are JavaScript** (not JSON), executed by an embedded **QuickJS** (`vendored/quickjs-ng`, `jsNodeHost.cpp:13`). Loader: `data/nodes/_icons.js` (MDI glyph table), `data/nodes/_prelude.js` (the node-definition API), `data/nodes/_types.js` (value-type table + conversions), then `data/nodes/builtin/*.js`. User nodes from `<project>/nodes/*.js` are layered on top (`jsNodeHost.cpp:479-488`, polled for reload in `nodeRegistry.cpp:294-309`).

**Node categories** (from `data/nodes/builtin/*.js` `category:` fields): `Flow`, `Object`, `Scene`, `Value`, `Math`, `Vector Math`, `Quat Math`, `Logic`, `Easing`, `Wave`, `Debug`, plus native `Variables` (varGet/varSet) and `Other` (Note) from `nodeRegistry.cpp:79-204`.

**Compilation to C++:** `Build::buildNodeGraphAssets` (`src/build/nodeGraphBuilder.cpp:31-67`). See §1.7 for the codegen details.

### 3.8 Scripts

**`data/scripts/`** contains **templates**, not user scripts:
- `defaultObject.cpp` — template for new object scripts (`assetManager.cpp:249` loads it; `createScript` `assetManager.cpp:761-809` substitutes `__UUID__`). Defines namespace `P64::Script::__UUID__` with `P64_DATA(...)` struct and lifecycle funcs.
- `defaultGlobal.cpp` — template for global scripts.
- `scriptTable.cpp` — generated-table **template** with placeholders `__CODE_ENTRIES__`, `__CODE_SIZE_ENTRIES__`, `__CODE_DECL__`, `__GRAPH_SWITCH_CASE__`, `__GRAPH_DEF__` (`data/scripts/scriptTable.cpp:9-49`).
- `globalScriptTable.cpp` — global-hook template with `__CODE_DECL__`, `__CODE_HOOKS__`.
- `assetTable.h` / `sceneTable.h` — templates with `{{ASSET_MAP}}` / `{{SCENE_MAP}}` / `{{SCENE_COUNT}}`, substituted in `projectBuilder.cpp:176-203`. Define `operator""_asset`, `operator""_prefab`, `operator""_scene` consteval lookups.
- `mingw_create_env.sh` — Windows toolchain bootstrap (builds/installs tiny3d gltf_importer).

**How user scripts are discovered & compiled:** the editor scans `src/user/**/*.cpp` (`assetManager.cpp:388-402`). Each `.cpp` is parsed by `buildCodeEntry` (`assetManager.cpp:187-226`): looks for `::Script::` (object script) or `::GlobalScript::` (global script) marker, extracts a 16-hex-char UUID from the namespace name, and parses the `P64_DATA(...)` struct via `Utils::CPP::parseDataStruct` (`src/utils/codeParser.cpp:112-184`) to expose its fields in the inspector.

UUID format: 16 hex chars, first char forced to `'C'` to avoid leading digits in a C++ namespace name (`assetManager.cpp:793`).

`parseDataStruct` regex-parses `P64_DATA(...)` body for `[[attr]] type name;` fields (`codeParser.cpp:121-176`). Supported types: `uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/float/char[]/AssetRef<sprite_t>/ObjectRef/PrefabRef` (`codeParser.cpp:18-31`). The `[[P64::Bitmask("0=Fire,1=Water")]]` attribute is pre-parsed into bit/name pairs for unsigned ints (`codeParser.cpp:60-73`, `152-157`).

`hasFunction` (`codeParser.cpp:186-195`) checks whether a given lifecycle function exists (used by `scriptBuilder.cpp:39-45` to conditionally emit table entries).

At build time `buildScripts` (`scriptBuilder.cpp:17-94`) generates `src/p64/scriptTable.cpp` with one `ScriptEntry` per object script (function pointers to `init/destroy/update/fixedUpdate/draw/onEvent/onCollision` based on which exist) + a `codeSizeTable[]` of `DATA_SIZE` + graph decls. `buildGlobalScripts` (`scriptBuilder.cpp:96-182`) generates `src/p64/globalScriptTable.cpp` dispatching hook enums to user functions, plus injects opus-init and debug-menu hotkey.

The generated `scriptTable.cpp` + user `src/user/*.cpp` + `src/p64/*.cpp` are compiled by the libdragon makefile (`data/build/baseMakefile.mk:22-24`): `src = $(wildcard src/*.cpp) $(wildcard src/p64/*.cpp) $(wildcard src/user/*.cpp)` plus per-subdir `USER_CODE_DIRS` rules (`projectBuilder.cpp:140-144`).

**GOTCHA:** `codeParser.cpp` strips comments with two regex passes then field-regexes — it will **misparse fields with `//` inside string literals** or `]]` inside attribute args. The `hasFunction` check strips all whitespace then string-matches `retType+name+(` — a return type like `const void*` or `std::void` won't match `void`.

**GOTCHA:** Script UUIDs are extracted by string offset (`uuidPos += 10` for `::Script::`, `+= 16` for `::GlobalScript::`, `assetManager.cpp:199-203`) — fragile if the namespace is formatted differently (e.g. `::Script ::` with space).

### 3.9 Themes & fonts

**Themes** live in `data/themes/*.json` (`dark.json`, `dark-blue.json`, `darl-warm.json` [sic — typo in filename], `highcontrast.json`, `light.json`, `retro-95.json`). Format (from `dark.json` + `theme.cpp:38-71`):
```text
{
  "name": "Display Name",
  "colors": { "<ImGuiColName>": [r,g,b,a 0..1] },
  "style": { "WindowRounding": float, "FrameRounding": float, "WindowPadding": [x,y], "ItemSpacing": [x,y] },
  "custom": { "<key>": [r,g,b,a] },
  "font": "<filename>.ttf",
  "fontPixel": bool
}
```
Color names must exactly match `ImGui::GetStyleColorName(i)` (`theme.cpp:31-35`). Loaded by `ImGui::Theme::setTheme` (`theme.cpp:160-170`). `getThemes` (`theme.cpp:193-211`) enumerates the dir.

**Fonts in `data/`:** `Altinn-DINExp.ttf` (default UI font), `GoogleSansCode.ttf` (mono font), `materialdesignicons-webfont.ttf` (icon font, merged into UI font), `W95F.otf` (for retro-95 theme). Engine font asset lives at `data/build/assets/font.ia4.png` (copied into every project's `assets/p64/font.ia4.png`).

**GOTCHA:** Theme JSON keys use ImGui color names (e.g. `"TabSelectedOverline"`) which are **version-dependent** — a theme written for one ImGui version may fail to apply colors on another. The match is by string, silently skipping unknown names (`theme.cpp:34` returns -1, skipped at line 45).

**GOTCHA:** `darl-warm.json` is a typo for "dark-warm" — it ships in the release as-is.

---

## 4. Build system

### 4.1 Toolchain

`src/utils/toolchain.cpp`/`.h`. `ctx.toolchain.scan()` (`main.cpp:158`) probes for the libdragon/gcc-mips toolchain. On Windows, the toolchain is auto-installed (the launcher's "Install Toolchain" button, `toolchainOverlay.cpp`). The supported headless Linux path is `bf64 toolchain detect/install` followed by transactional `doctor --fix`, which persists `pathN64Inst` and `.bf64/env.sh`. The headed editor itself still expects `N64_INST` or `pathN64Inst` on Linux/macOS. **GOTCHA:** launching an editor build with both empty still reaches `make` with an empty toolchain path (`projectBuilder.cpp:62-68); run strict `bf64 doctor` first to get an actionable preflight instead of the resulting missing-tool errors. Windows falls back to `/pyrite64-sdk` (`projectBuilder.cpp:70-74`).

### 4.2 Build flow

`Build::buildProject` (`src/build/projectBuilder.cpp:56-262`):

1. Load project; resolve `N64_INST` from conf or env (`projectBuilder.cpp:62-87`).
2. Create `filesystem/p64/` dir. Register every non-excluded asset in `sceneCtx.assetList` + `assetFileMap` (`projectBuilder.cpp:99-111`, `addAsset` `39-54`).
3. Detect asset-list changes vs `filesystem/p64/fileList.txt`; if changed, wipe `.t3dm`/`.pf` + `filesystem/p64/` + code build (`projectBuilder.cpp:113-137`).
4. Build node graphs → `src/p64/<uuid>.cpp` + `filesystem/.../<name>.pg` (`buildNodeGraphAssets`).
5. Build scripts → `src/p64/scriptTable.cpp`, `src/p64/globalScriptTable.cpp` (`buildScripts`/`buildGlobalScripts`).
6. Build scenes → binary scene/object files; generate `src/p64/sceneTable.h` + `.cpp` (`projectBuilder.cpp:156-188`, `buildScene`).
7. Build assets in order: 3D Model (`t3dmBuilder`), Font, Texture, Audio, UI, **Prefab last** (`projectBuilder.cpp`, `uiBuilder.cpp`). Each writes into `filesystem/`.
8. Generate `src/p64/assetTable.h` from `assetFileMap` (`projectBuilder.cpp:199-203`).
9. Write asset table binary `filesystem/p64/a` (`projectBuilder.cpp:206-218`): u32 count, then per-asset (offset, type+flags packed), then concatenated `romPath` strings.
10. Generate `Makefile` from `data/build/baseMakefile.mk` substituting `{{N64_INST}}`, `{{ROM_NAME}}`, `{{PROJECT_NAME}}`, `{{ASSET_LIST}}`, `{{USER_CODE_DIRS}}`, `{{ROM_HEADER_FLAGS}}`, `{{P64_SELF_PATH}}`, `{{PROJECT_SELF_PATH}}` (`projectBuilder.cpp:225-240`).
11. Write `filesystem/p64/conf` (u32 sceneIdOnBoot, u32 sceneIdOnReset, u16 autoLoadFontUUIDs[16]) (`projectBuilder.cpp:242-251`).
12. Run `make -C "<path>" -j8` (`projectBuilder.cpp:254`).

### 4.3 Intermediate & final outputs

All under project dir:
- `filesystem/` — converted assets (`.sprite`, `.wav64`, `.xm64`, `.t3dm`, `.font64`, `.ui64`, `.pf`, `.pg`, `.bci`) + `.sdata` sidecars (from t3dm, collected `t3dmBuilder.cpp:258-272`)
- `filesystem/p64/a` — asset table binary
- `filesystem/p64/conf` — runtime boot config
- `filesystem/p64/fileList.txt` — asset-list cache for change detection
- `src/p64/scriptTable.cpp`, `globalScriptTable.cpp`, `sceneTable.h`, `sceneTable.cpp`, `assetTable.h`, `<graphUUID>.cpp` — generated C++
- `Makefile` — generated from template + `Makefile.custom` (user-kept)
- `build/` — make object files (`.o`, `.d`, `.elf`, `.dfs`)
- `engine/build/engine.a` — engine static lib (built by sub-make, `baseMakefile.mk:32-34`)
- `metadata/` — ROM metadata (`metadata.ini` + copied `img_<uuid>.png/jpg`, `description[_lang].txt`, `romMetaBuilder.cpp:104-113`)
- `.gitignore` — includes `metadata` entry (`project.cpp:191-204`)

**Final ROM:** `<romName>.z64` in the project root (cleaned before build, `globalActions.cpp:157-158`; removed on `clean`, `projectBuilder.cpp:269`). Format is standard N64 `.z64` (big-endian, libdragon-generated via `n64.mk` makefile include, `baseMakefile.mk:13`). ROM header flags come from `buildRomHeaderFlags` (`romMetaBuilder.cpp:85-117`): `N64_ROM_CATEGORY`, `N64_ROM_REGION`, `N64_ROM_SAVETYPE`, `N64_ROM_REGIONFREE`, `N64_ROM_RTC`, `N64_ROM_CONTROLLER1..4`, and `N64_ROM_METADATA` pointing at `metadata/metadata.ini`.

### 4.4 Clean

`cleanProject` (`projectBuilder.cpp:264-285`): removes `.z64`, optionally `filesystem/`, `build/`, `engine/build/`, `engine/`. The Makefile's `clean` target calls back into the editor binary: `{{P64_SELF_PATH}} --cli --cmd clean {{PROJECT_SELF_PATH}}` (`baseMakefile.mk:64-65`).

**GOTCHA:** The Makefile `clean` invokes the editor binary with `--cli --cmd clean` — so the **editor executable must be on PATH / locatable** for `make clean` to work, and re-enters the `Project` ctor which triggers engine-file sync and a possible forced clean (`project.cpp:212-220`) — recursive clean risk if versions mismatch.

**GOTCHA:** `assetBuildNeeded` (`projectBuilder.cpp:288-297`) compares file mtimes with `ageSrc < ageDst` → skip. On filesystems with coarse mtime granularity (or clock skew between source and build dirs on different mounts), this can **skip needed rebuilds** or rebuild spuriously.

---

## 5. UI focus-area architecture

`.bfui` is a versioned JSON asset recognized as `FileType::UI_DOCUMENT`. `Build::buildUIAssets` resolves image/font UUID or project-path references, validates stable CRC32 element IDs, and emits a big-endian `.ui64` header, fixed 64-byte element table, and deduplicated string table. Runtime loading uses asset type 10 and the normal raw `asset_load`/`free` handler.

The editor's `UIEditor` is opened from **Focus → UI**, the asset browser, or the asset inspector. It edits the same JSON consumed by `bf64 ui`; there is no hidden editor-only document model.

Scene component id 13 is `UI Document`. Runtime `Comp::UI` owns mutable element/input state and exposes stable-ID setters/getters, including `setValue` for ProgressBar fill state, `reserveText` for steady-state formatted updates, and visibility-triggered reflow. Progress bars keep `value/max` in component state and apply the first matching authored absolute color threshold. `ui/layout.cpp` calculates anchors and simple container flow using fixed scratch storage; hidden direct children collapse. `ComponentDef::draw2D` is dispatched once after all camera passes, preventing one UI document from being drawn once per camera. Controller interactions return through `EVENT_TYPE_UI_ACTIVATE`, `EVENT_TYPE_UI_CHANGE`, and `EVENT_TYPE_UI_SUBMIT`, with the element CRC32 in `ObjectEvent::value`.

`ui/dialogue.cpp` provides a renderer/input-independent `DialogueRunner`. It retains a caller-owned line array, reveals complete UTF-8 code points at per-line/default rates, waits for manual `advance()` or a configured hold, and emits lifecycle callbacks. `Comp::UI::bindDialogue` adapts its text sink to two stable element IDs; the runner can also be host-tested without libdragon.

Font references currently require existing auto-load slots 1–15. Asset pointers still follow normal scene lifetime rules; UI component pointers and `getText()` results must not be retained across scene transitions.

`debug/profiler.cpp` implements the `bf64.runtime-profile` v1 target protocol. A build-time request is appended to `filesystem/p64/conf`; the runtime discards the configured warm-up, samples at most 2048 frames, instruments post-culling T3D object submissions, heap/top-down allocations, and mixer voices, then emits one JSON line. The Python `run --profile` process reader enables Ares homebrew mode, combines that record with host artifact sizes and emulator metadata, and atomically writes `bf64.profile`.

`save/saveManager.cpp` is the public cartridge persistence layer. Each logical slot owns two aligned physical banks containing a 24-byte versioned header and fixed-capacity payload. Writes fill an inactive bank in `writing` state and commit it with a final 8-byte update; reads choose the newest valid generation by header/payload CRC, fall back to a valid peer on corruption, and can migrate/rewrite old schemas. Erase commits a tombstone so an older bank cannot reappear. Backends are EEPROM 4K/16K and FlashRAM; `save/flashramDriver.c` is a BF64-prefixed adaptation of libdragon PR #925 so the feature does not depend on an unreleased SDK API.

`renderer/chunkMesh.cpp` provides fixed-capacity runtime geometry with one canonical copy and configurable uncached frame-buffer copies. Dirty bits are per chunk and per render buffer, topology is shared across uniform batches (at most 70 vertices each), optional world-space AABBs feed tiny3d frustum tests, and metrics expose allocation bytes, copy count, culling, draw batches, and submitted triangles.

---

## 6. Gotchas index (cross-cutting)

The most important fragile/surprising things, gathered in one place for quick scanning:

- **Two-binary split with silent drift** (§0): editor and runtime have independent Object/Component models. Drift is silent until the ROM misbehaves. Three manual relative includes are the only ABI bridge.
- **CMake dummies** (§0, §2.1): `n64/CMakeLists.txt` and `n64/examples/*/CMakeLists.txt` are IDE-only; editing them does nothing to the ROM.
- **CWD rewritten at boot** (§1.1): editor CWD is the app resource dir; project paths are absolute. Code assuming project CWD is wrong.
- **`forceVSync` overrides user preference** (§1.1): on hardware without immediate present, the VSync toggle does nothing.
- **Wayland ignores window position** (§1.1): stores `sessionID` instead.
- **Launcher rejects spaces in paths, drop-file bypasses** (§1.4): `.p64proj` dropped from OS with spaces in path bypasses the no-spaces check.
- **Undo is whole-scene-snapshot, not per-scene** (§1.5): scene switching clears undo history.
- **`PROJECT_BUILD` blocks while emulator runs** (§1.5): closing the emulator is the only way to clear "running" state.
- **`PROJECT_CREATE` doesn't auto-open** (§1.5): user must open from recents.
- **ImGui internal API usage** (§1.3): `helper.h` includes `imgui_internal.h`; ImGui upgrades can break `makeTabVisible` and `DockTabItemRect` reads.
- **`ImTable::add` crashes on `%` in label** (§1.3): `ImGui::Text("%s", name.c_str())` — fine for constants, risky for user-supplied names.
- **Theme fonts load relative to rewritten CWD** (§1.3): moving the binary breaks theming silently.
- **Node-graph dirty tracking is dual** (§1.7): `NodeEditor` flag + asset-manager flag must stay consistent.
- **Specs stored in `unique_ptr` for address stability** (§1.7): never hold a `NodeSpec` by value.
- **Codegen is `goto`-based with `NODE_<uuid>` labels** (§1.7): node uuid collision produces a duplicate label (no check).
- **`stackSize=4096` hardcoded** (§1.7): no per-graph stack analysis.
- **Editor never calls runtime code** (§0, §2.1): only reads 3 headers to stay ABI-compatible with baked blobs.
- **`AssetEntry` packs type+flags into pointer high bits** (§2.7): assumes asset pointers fit in 24 bits — hard N64-RAM assumption.
- **All asset pointers invalidated on scene change** (§2.7): `Scene::~Scene` → `AssetManager::freeAll`. Keeping an asset pointer across a scene load is a use-after-free.
- **HDR-Bloom and BigTex hard-locked to 320×240 RGBA16** (§2.4): BigTex additionally cannot clear color. Ucode-imposed; editor must enforce.
- **`VI::SwapChain` 200ms RSP-timeout escape hatch** (§2.4): fallback for RSP hangs; may show a torn frame.
- **Script identity by 64-bit UUID namespace** (§2.8): `P64_DATA` size capped at 65535 bytes by `static_assert`.
- **`Comp::Code` script-index ordering** (§2.8): editor must keep `src/p64/scriptTable.cpp` ordering consistent with asset table.
- **`AudioManager::destroy()` not in public header** (§2.6): no public teardown.
- **`NodeGraph::registerFunction` deprecated** (§2.8): custom JS nodes are the supported path.
- **Tests run on-device only** (§2.9): no host-side test runner aggregates results.
- **`Component::TABLE` id stability** (§3.2): adding/reordering component types breaks all saved scenes.
- **`propOverrides` keys are hash-combined** (§3.2): changing the combine function silently breaks all saved overrides.
- **`PropScope::stack` is `thread_local`** (§3.2): property resolution is not reentrant across objects.
- **glTF textures must pre-exist as PNG assets** (§3.3): silent texture binding loss if `getByPath` fails.
- **Broken glb → empty model, only logged** (§3.3): no editor-visible error beyond the log.
- **`ComprTypes::DEFAULT` hardcodes level 1** (§3.4): not actually default-aware.
- **`BCI::convertPNG` non-deterministic** (§3.4): uses `rand()` for palette init.
- **`audioconv64` flags applied to mp3** (§3.6): undocumented whether mp3 input accepts `--wav-*` flags.
- **`codeParser.cpp` misparses `//` in strings** (§3.8): two-regex comment strip; `hasFunction` won't match `const void*` return type.
- **Script UUID extracted by string offset** (§3.8): fragile if namespace formatted differently.
- **Theme JSON keys are ImGui-version-dependent** (§3.9): unknown names silently skipped.
- **`darl-warm.json` typo ships as-is** (§3.9).
- **Toolchain path empty → cryptic make errors** (§4.1): no clear "SDK not configured" message on non-Windows.
- **`make clean` re-enters editor** (§4.4): recursive clean risk if versions mismatch.
- **Mtime-based asset build skip** (§4.4): coarse mtime granularity or clock skew can skip needed rebuilds.
- **Two parallel UUID systems** (§3): scene objects use 32-bit UUIDs; assets/prefabs/components use 64-bit. Mixing them in lookups is a class of bugs.
- **RigidBody duplicate guard hardcoded to id 11** (§3.2): `addComponent` magic number; CharBody (id 12) has no such guard — inconsistent.
- **`BinaryFile` writes big-endian via `std::byteswap`** (§3): assumes little-endian host; no endianness check.
