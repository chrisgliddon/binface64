# Codemap

**Scope:** annotated directory map of the Binface64 repo. What lives where, entry points, key classes/files, serialization formats. Read alongside `ARCHITECTURE.md` (which explains *how* things work) — this doc tells you *where* to find them.
**Last reviewed:** 2026-07-06 (Pyrite64 v0.7.0-era, upstream commit `104a2d2`)
**Audience:** LLM agents in later BF64 sessions. Cite file paths so you can jump straight to code.

---

## 0. Top-level layout

```
binface64/
├── CMakeLists.txt          # 407 lines — editor build (host gcc, SDL3/ImGui)
├── CMakePresets.json        # 142 lines — build presets
├── Readme.md                # upstream Pyrite64 README (BF64 rewrite is Phase 8)
├── LICENSE                  # MIT
├── .gitmodules              # 11 submodules (SDL, ImGui, libdragon, tiny3d, …)
├── .github/                 # issue/PR templates, CI workflows
├── .gitignore, .gitattributes, .editorconfig
├── data/                    # editor-bundled resources (themes, fonts, node defs, templates)
├── docs/                    # Sphinx docs (this file lives under docs/docs/agent/)
├── n64/                     # N64 runtime + examples + tests (the .z64 side)
├── packaging/               # packaging scripts
├── scripts/                 # repo-level scripts (build_appimage.sh)
├── src/                     # editor (host app)
├── tools/                   # node tooling (createDebugFont.mjs + npm)
└── vendored/                # git submodules (SDL, ImGui, libdragon, tiny3d, glm, …)
```

---

## 1. `src/` — the editor

Host SDL3 + ImGui + glm + quickjs-ng app. Built by root `CMakeLists.txt` as `pyrite64`.

### 1.1 Entry points

| File | Role |
|---|---|
| `src/main.cpp:154` (`main`) | Editor boot + main loop. See ARCHITECTURE §1.1–§1.2. |
| `src/cli.cpp:26` (`CLI::run`) | CLI dispatcher. `--cli --cmd build <path>` / `--cmd clean`. Returns `GUI`/`SUCCESS`/`ERROR`. |
| `src/cli.h` | CLI enum + `getProjectPath` accessor. |
| `src/context.h` | Global `Context ctx` — the single shared state: `project`, `editorScene`, `scene`, `gpu`, `window`, `toolchain`, `prefs`, `thumbnails`, `clipboard`, `futureBuildRun`, `forceVSync`, `wantsProjectClose`. `deferAction` (line 81) for post-GPU-submit lambdas. `isBuildOrRunning` (line 89). |

### 1.2 `src/editor/`

| Path | Role |
|---|---|
| `src/editor/window.{cpp,h}` | `Editor::Window` — thin SDL window wrapper, geometry persistence to `editor.json`, Wayland handling. |
| `src/editor/actions.{cpp,h}` | `Editor::Actions` — typed callback registry (`PROJECT_OPEN`, `PROJECT_BUILD`, etc.), 255-slot array indexed by enum. `init`/`registerAction`/`call`. |
| `src/editor/globalActions.cpp:42` (`initGlobalActions`) | Registers the built-in actions (OPEN/CLOSE/CREATE/CLEAN/BUILD/ASSETS_RELOAD/COPY/PASTE). |
| `src/editor/keymap.{cpp,h}` | Keybind storage + serialization. |
| `src/editor/preferences.{cpp,h}` | `Editor::Prefs` — user prefs (keymap, recentProjects, theme, fpsLimit, useVSync). Persisted to `<appData>/editor.json`. |
| `src/editor/undoRedo.{cpp,h}` | `Editor::UndoRedo::History` — whole-scene-snapshot undo, 100-entry stack. See ARCHITECTURE §1.5. |
| `src/editor/selectionUtils.{cpp,h}` | Selection helpers (prefab-aware). |
| `src/editor/transformUtils.{cpp,h}` | Transform/gizmo math. |
| `src/editor/thumbnailCache.{cpp,h}` | Asset thumbnail generation/caching. |

### 1.3 `src/editor/imgui/` — custom ImGui wrapper

| File | Role |
|---|---|
| `helper.h`/`helper.cpp` | 1021-line property-table abstraction (`ImTable::*`), prefab-override machinery, searchable combos, drag-drop, `IconButton`/`HelpIcon`/`rotationInput`/`makeTabVisible`. Includes `imgui_internal.h`. |
| `theme.h`/`theme.cpp` | JSON theme loader (`data/themes/*.json`), 12-step zoom, `_px` literal, font loading. |
| `notification.h`/`notification.cpp` | Toast notifications (`INFO`/`SUCCESS`/`ERROR`) + transient center-screen `showAction`. |

### 1.4 `src/editor/pages/` — editor screens & panels

| File | Role |
|---|---|
| `launcher.{cpp,h}` | Home screen when no project open. Recent-projects carousel, Create/Open/Toolchain cards. |
| `editorScene.{cpp,h}` | Main editor host: dockspace, multi-viewport, menu bar, status bar, per-project window persistence. |
| `parts/viewport3D.{cpp,h}` | 3D scene preview, camera, gizmos, picking. Registers render callbacks on `Renderer::Scene`. |
| `parts/sceneGraph.{cpp,h}` | Object tree / outliner. |
| `parts/sceneInspector.{cpp,h}` | Scene-level settings (framebuffer, physics, layers). |
| `parts/layerInspector.{cpp,h}` | Per-layer render config. |
| `parts/assetsBrowser.{cpp,h}` | File browser with tabs. |
| `parts/assetInspector.{cpp,h}` | Per-asset import settings. |
| `parts/objectInspector.{cpp,h}` | Object transform + component list + per-component UI (delegates to `Component::TABLE[id].funcDraw`). |
| `parts/logWindow.{cpp,h}` | Tail of `Utils::Logger`. |
| `parts/memoryDashboard.{cpp,h}` | Cart size estimate, asset breakdown. |
| `parts/nodeEditor.{cpp,h}` | Node-graph canvas (one per open `.p64graph`). See ARCHITECTURE §1.7. |
| `parts/assets/modelEditor.{cpp,h}` | 3D model preview/edit. |
| `parts/assets/matInstanceEditor.{cpp,h}` | Material-instance editor. |
| `parts/assets/textureEditor.{cpp,h}` | Texture editor. |
| `parts/preferenceOverlay.{cpp,h}` | Preferences modal. |
| `parts/projectSettings.{cpp,h}` | Project settings modal. |
| `parts/createProjectOverlay.{cpp,h}` | Create-project modal (drawn by launcher). |
| `parts/toolchainOverlay.{cpp,h}` | Toolchain install modal (drawn by launcher). |

### 1.5 `src/project/` — the project model (editor-side)

| Path | Role | Serialization |
|---|---|---|
| `project/project.{cpp,h}` | `Project::Project` + `ProjectConf`. Load/save the `.p64proj` JSON, create directory skeleton, version-gated auto-clean, engine-file sync. | `.p64proj` (JSON via `Utils::JSON::Builder`) |
| `project/scene/sceneManager.{cpp,h}` | `SceneManager` — scans `data/scenes/`, load/add/remove/duplicate scenes. | dir tree `data/scenes/<id>/` |
| `project/scene/scene.{cpp,h}` | `Project::Scene` + `SceneConf`. The editor's view of a scene. | `data/scenes/<id>/scene.json` (JSON, `{"conf":..., "graph":<object tree>}`) |
| `project/scene/object.{cpp,h}` | `Project::Object` — scene-graph node (`shared_ptr` tree, `Component::Entry` vector, `Property<glm::vec3/quat/vec3>` transforms, `propOverrides` map). | JSON inside `scene.json`'s `graph` |
| `project/scene/prefab.{cpp,h}` | `Prefab` = `PROP_U32(uuid) + Object`. Create/unpack/add instance. Rebases child transforms to parent-relative on creation. | `assets/<sanitizedName>.prefab` (JSON) |
| `project/assetManager.{cpp,h}` | `AssetManager` — bucketed by `FileType`, `AssetManagerEntry` per asset, hot-reload watcher, dirty tracking. | `<asset>.conf` sidecar JSON per asset |
| `project/assets/material.{cpp,h}` | Asset-level `Material` (per glTF material name). `fromT3D` maps tiny3d → engine. | inside model asset's `conf.data.materials[<name>]` |
| `project/assets/model3d.{cpp,h}` | `Model3D` (parsed T3DMData + materials map). | — |
| `project/component/components.{cpp,h}` | `Component::TABLE` — 13-entry `constexpr` array of `CompInfo` (function pointers for draw/build/serialize). `Component::Entry` = `{id, uuid, name, shared_ptr<void> data}`. | per-component `funcSerialize` JSON |
| `project/component/types/comp*.cpp` | The 13 component implementations (Code, Model, Light, Camera, CollMesh, CollBody, Audio2D, Constraint, Culling, NodeGraph, AnimModel, RigidBody, CharBody). | each has `funcSerialize`/`funcDeserialize` |
| `project/component/shared/materialInstance.{cpp,h}` | Per-object `MaterialInstance` (8 texture slots + color overrides). | scene `scene.json` component `data.material` |
| `project/component/shared/meshFilter.{cpp,h}` | Mesh-subset filter. | scene component `data.meshFilter` |
| `project/graph/graph.{cpp,h}` | `Project::Graph::Graph` — wraps `ImFlow::ImNodeFlow` + variables + build helpers. `build()` is the codegen core. | `.p64graph` (JSON) |
| `project/graph/nodeRegistry.{cpp,h}` | Native + JS node spec registry, hot reload, legacy id mapping, placeholder creation. | — |
| `project/graph/nodes/nodeSpec.h` | `NodeSpec` — full node-type descriptor. |
| `project/graph/nodes/scriptNode.h` | `ScriptNode` — the single concrete node class, parameterized by `NodeSpec*`. |
| `project/graph/nodes/baseNode.h` | `Base` — abstract `ImFlow::BaseNode` subclass + `BuildCtx` codegen context. |
| `project/graph/jsNodeHost.{cpp,h}` | QuickJS host: `Js::init`, `Js::loadSpecs`, eval of `_prelude.js`/`_types.js`/`builtin/*.js`/user `nodes/*.js`. |
| `project/graph/valueTypes.h` | Value-type registry (`canConnect`, `convertExpr`, `LOGIC_TYPE`). |

### 1.6 `src/renderer/` — editor-side GPU (preview, not the N64 renderer)

| File | Role |
|---|---|
| `scene.{cpp,h}` | `Renderer::Scene` — GPU render manager (3 shader/pipeline pairs: n64/lines/sprites), callback maps for render/copy/postrender passes, single `draw()` submit point. Lights vector. **Not** the editor's scene model. |
| `object.{cpp,h}` | `Renderer::Object` — preview object. |
| `camera.{cpp,h}` | `Renderer::Camera` — preview camera. |
| `framebuffer.{cpp,h}` | GPU framebuffer helpers. |
| `mesh.{cpp,h}` / `n64Mesh.{cpp,h}` / `n64/` | Host mesh representation; `N64Mesh::fromT3DM` builds preview from parsed glTF. |
| `texture.{cpp,h}` | `Renderer::Texture` — SDL_image-loaded preview texture (PNG/SVG). No N64 format conversion here. |
| `material.cpp` | Engine-material preview mapping. |
| `animation.{cpp,h}` / `skeleton.{cpp,h}` | Preview animation/skeleton. |
| `pipeline.{cpp,h}` / `shader.cpp` / `vertBuffer.{cpp,h}` / `vertex.h` / `uniforms.h` / `storageBuffer.{cpp,h}` | GPU pipeline plumbing. |

### 1.7 `src/utils/` — shared editor utilities

| File | Role |
|---|---|
| `binaryFile.h` | `Utils::BinaryFile` — big-endian binary writer (via `std::byteswap`, assumes little-endian host). |
| `codeParser.{cpp,h}` | `Utils::CPP::parseDataStruct` / `hasFunction` — regex-parse `P64_DATA(...)` struct fields + lifecycle func detection. Used by `scriptBuilder`. |
| `colors.h` | Color constants. |
| `container.h` | Container helpers. |
| `filePicker.{cpp,h}` | Native file dialog wrapper (SDL_dialog). `poll()` called from main loop. |
| `fs.{cpp,h}` | Filesystem helpers (path manipulation). |
| `hash.{cpp,h}` | SHA256 wrapper (for UUIDs). |
| `json.h` / `jsonBuilder.h` | nlohmann/json wrapper + builder. |
| `logger.{cpp,h}` | `Utils::Logger` — log buffer (tailed by `LogWindow`). |
| `meshGen.{cpp,h}` | Procedural mesh helpers (gizmos, debug shapes). |
| `network.{cpp,h}` | HTTP/S fetch helper (used by updater). |
| `proc.{cpp,h}` | `Utils::Proc` — process spawn, `getAppResourcePath`, `getAppDataPath`. |
| `prop.h` | `Property<T>` + `PropScope` + `GenericValue` — the prefab-override cascade. See ARCHITECTURE §3.2. |
| `ringBuffer.h` | Ring buffer container. |
| `string.h` | String helpers. |
| `textureFormats.h` | `TextureFormat` enum (AUTO/RGBA32/RGBA16/CI8/CI4/I8/I4/IA16/IA8/IA4/IHQ/SHQ/ZBUF/BCI_256). |
| `time.{cpp,h}` | Time helpers. |
| `toolchain.{cpp,h}` | `Utils::Toolchain` — scan for libdragon/gcc-mips, install on Windows. |
| `updater.{cpp,h}` | `Utils::Updater::getNewerVersion` — version-check fetch. |

### 1.8 `src/build/` — the build pipeline (editor → ROM)

| File | Role |
|---|---|
| `projectBuilder.cpp:56` (`buildProject`) | The orchestrator. See ARCHITECTURE §4.2. |
| `sceneBuilder.cpp` | Scene → binary (`rom:/p64/sNNNN_` + `_o` object blob). |
| `scriptBuilder.cpp:17` (`buildScripts`) / `:96` (`buildGlobalScripts`) | Generates `src/p64/scriptTable.cpp` + `globalScriptTable.cpp`. |
| `nodeGraphBuilder.cpp:31` (`buildNodeGraphAssets`) | `.p64graph` → `.cpp` + `.pg` binary. |
| `t3dmBuilder.cpp:205` (`buildT3DMAssets`) | `.glb` → `.t3dm` via tiny3d importer. |
| `textureBuilder.cpp:17` (`buildTextureAssets`) | `.png` → `.sprite` via `mksprite` / `.bci` via internal `BCI::convertPNG`. |
| `audioBuilder.cpp:14` (`buildAudioAssets`) | `.wav/.mp3/.xm` → `.wav64`/`.xm64` via `audioconv64`. |
| `collisionBuilder.cpp` | Collision-mesh → binary. Skips `fast64_f3d_material_library*` nodes (line 84). |
| `prefabBuilder.cpp` | Prefab → `.pf` binary. |
| `tools/bci.cpp` | `BCI::convertPNG` — 4x4-block 4-color palette compressor (k-means, non-deterministic via `rand()`). |
| `romMetaBuilder.{cpp,h}` | ROM metadata: `buildRomHeaderFlags` + `metadata.ini` + image copies. |

### 1.9 `src/shader/` — editor preview shaders

| File | Role |
|---|---|
| `build.sh` | Shader build script. |
| `*.glsl` (`n64.frag/vert`, `lines.frag/vert`, `sprites.frag/vert`, `ubo.glsl`, `utils.glsl`) | Editor preview shaders (SDL_GPU SPIR-V/MSL/DXIL). |
| `defines.h` | Shader preprocessor defines. |

### 1.10 `src/n64/`

| File | Role |
|---|---|
| `ccMapping.{cpp,h}` | Color-combiner mapping helpers. |
| `libdragon.h` | libdragon header shim for host parsing. |

---

## 2. `n64/` — the N64 runtime + games

### 2.1 `n64/engine/` — the engine (linked into every game ROM)

**Build:** `n64/engine/Makefile` (NOT `n64/CMakeLists.txt`, which is an IDE dummy). Builds `build/engine.a` static lib via gcc-mips / libdragon `n64.mk` + `t3d.mk`. C++20, `-fno-exceptions -Os -Werror`. Also assembles custom RSP ucodes (`renderer/hdr/rsp_hdr.S`, `renderer/bigtex/rsp_bigtex.S`, `renderer/bigtex/applyTexture.S`).

#### `n64/engine/include/` — public API surface (79 headers, Doxygen-scanned)

| Subdir | Headers | Role |
|---|---|---|
| `scene/` | `scene.h`, `sceneManager.h`, `object.h`, `objectFlags.h`, `event.h`, `componentTable.h`, `camera.h`, `lighting.h`, `globalState.h`, and `components/*` | Scene mgmt, object/component model, events, 17 stable-id components including UI, Audio3D, Player Spawn, and Blob Shadow. |
| `input/` | `input.h` | Four fixed-port input snapshots, action/axis routing, consumption, and timed rumble. |
| `multiplayer/` | `session.h`, `viewports.h`, `spawns.h`, `groupCamera.h` | Persistent match state, split layouts, deterministic spawn selection, and shared-camera framing. |
| `renderer/` | `pipeline.h`, `pipelineHDRBloom.h`, `pipelineBigTex.h`, `drawLayer.h`, `material.h`, `chunkMesh.h`, `hdr/postProcess.h`, `bigtex/textures.h`, `bigtex/uvTexture.h`, `particles/ptxSystem.h`, `particles/ptxSprites.h` | 3 render pipelines, materials, triple-buffered procedural chunks, big-texture streaming, particles. |
| `collision/` | 24 headers (`collisionScene.h`, `aabbTree.h`, `aabb.h`, `gjk.h`, `epa.h`, `collide.h`, `contact.h`, `colliderShape.h`, `rigidBody.h`, `meshCollider.h`, `characterBody.h`, `attach.h`, `raycast.h`, `capsuleSweep.h`, `sphereSweep.h`, `shapes.h`, `types.h`, `vecMath.h`, `matrix3x3.h`, `gfxScale.h`, `contactUtils.h`, `fmMath.h`, `fmCollision.h`, `fmTypes.h`) | Physics & collision: AABB-tree broadphase, GJK/EPA narrowphase, 6 shapes, RigidBody, MeshCollider, CharacterBody, raycast/sweep queries. |
| `audio/` | `audioManager.h`, `spatialAudio.h` | 32-channel WAV64/XM64 mixer, handles/listener, 2D and positional playback math. |
| `ui/` | `documentFormat.h`, `layout.h`, `dialogue.h` | Compiled `.ui64` ABI, allocation-free flow layout, and input-agnostic typewriter/dialogue sequencing. |
| `save/` | `saveManager.h`, `flashramDriver.h` | Redundant checksummed EEPROM/FlashRAM slots, migrations, erase, and cartridge driver. |
| `assets/` | `assetManager.h`, `assetTypes.h` | Global asset table, lazy `AssetRef<T>`, `PrefabRef`. |
| `script/` | `userScript.h`, `scriptTable.h`, `globalScript.h`, `nodeGraph.h` | User script binding (`P64_DATA` macro, `ScriptEntry` table, global hooks, node-graph coroutine). |
| `vi/` | `swapChain.h` | Triple-buffered VI swapchain. |
| `lib/` | `math.h`, `types.h`, `memory.h`, `matrixManager.h`, `logger.h`, `fifo.h`, `ringBuffer.h`, `mips.h` | Math, memory, logging, containers, MIPS helpers, user-literals (`_crc32`/`_hash`/`_crc64`/`_square`/`_s`/`_ms`/`_deg`/`_rad`). |
| `debug/` | `debugDraw.h`, `debugMenu.h`, `menu.h` | Debug overlays + menu builder. |

#### `n64/engine/src/` — engine implementation

Mirrors the include tree: `scene/`, `renderer/` (with `hdr/`, `bigtex/`, `particles/`), `collision/`, `audio/`, `assets/`, `script/`, `save/`, `ui/`, `vi/`, `lib/`, `debug/`. Entry point: `main.cpp:106` (the runtime main loop — see ARCHITECTURE §2.3).

#### Key runtime files

| File | Role |
|---|---|
| `src/main.cpp:106` | Runtime main loop: `for(;;){ SceneManager::run(); VI::SwapChain::drain(); SceneManager::unload(); Mem::freeDepthBuffer(); MatrixManager::reset(); }`. Loads `rom:/p64/conf`, registers fonts, GAME_INIT hook. |
| `src/scene/scene.cpp` | `P64::Scene::update`/`draw`/`addObject`/`removeObject`/`sendEvent`/`onObjectCollision`. The per-frame logic + render dispatch. |
| `src/scene/sceneManager.cpp` | `SceneManager::run`/`load`/`reload`/`getCurrent`. Fires global hooks around load/unload. |
| `src/scene/sceneLoader.cpp` | Binary scene loader. `rom:/p64/sNNNN_` (config) + `_o` (objects). `memalign(8,...)` single-alloc Object + CompRef[] + data blob. Deferred `initDel`. READY event queue. |
| `src/scene/componentTable.cpp` | `COMP_TABLE[17]` — runtime component registry via `SET_COMP` + `HAS_FUNC_TPL` SFINAE. |
| `src/vi/swapChain.cpp` | Triple-buffered VI. VBlank handler, 200ms RSP-timeout escape hatch (lines 132-137). |
| `src/renderer/pipelineDefault.cpp` / `pipelineHDRBloom.cpp` / `pipelineBigTex.cpp` | The 3 pipelines. HDR/BigTex assert 320×240 RGBA16. |
| `src/renderer/bigtex/*` | BigTex streaming: `textures.cpp` (18-texture pool), `uvTexture.cpp`, `memory.cpp` (own allocator), `applyTexture.S` + `rsp_bigtex.S` (RSP ucode). |
| `src/renderer/hdr/*` | HDR+Bloom: `rspHDR.cpp` + `rsp_hdr.S`/`rsp_hdr.rspl` (RSP ucode), `postProcess.cpp`. |
| `src/collision/collisionScene.cpp` | `CollisionScene::step` — full solver pipeline (detect → preSolve → warmStart → solveVelocity → solvePosition → sweptCCD → sleep → meshWorldStates). |
| `src/audio/audioManager.cpp` | 32-channel mixer, `play2D`/`play3D`, listener updates, and movable `Audio::Handle`. |
| `src/save/{saveManager.cpp,flashramDriver.c}` | EEPROM/FlashRAM redundant-bank transaction, prefixed cartridge driver, CRC/generation validation, tombstones, and schema migrations. |
| `src/renderer/chunkMesh.cpp` | Per-buffer dirty chunk copies, shared topology, AABB/visibility culling, draw and allocation telemetry. |
| `src/ui/layout.cpp` | Fixed-scratch anchored and horizontal/vertical flow layout with hidden-child collapse. |
| `src/ui/dialogue.cpp` | UTF-8-safe typewriter timing, manual/timed line progression, and text/event callbacks. |
| `src/assets/assetManager.cpp` | Global asset table init/load/freeAll. Tagged-pointer trick (type+flags in high bits). |
| `src/script/nodeGraph.cpp` | `NodeGraph::load` — patches bytecode first slot with C `GraphFunc` by UUID. |

### 2.2 `n64/examples/` — runnable example games

Each is a full project (`.p64proj`, `Makefile.custom`, `assets/`, `data/scenes/<id>/scene.json`, `src/user/*.cpp`).

| Dir | What it demonstrates |
|---|---|
| `empty/` | Minimal baseline — bare project skeleton / build pipeline. |
| `baked_light/` | Baked lighting, ambient/dir/point lights, Default pipeline. |
| `bigtex/` | BigTex 256×256 streaming pipeline, high-res bust + cubemap skybox. |
| `char_body/` | CharacterBody controller — `moveAndSlide`, jump, planet gravity (`setUp`), moving platforms. Reference: `src/user/Controller.cpp`. |
| `material_test/` | Material instances, placeholders, UV gen, animated water/flame, env reflection, prefabs. |
| `jam25/` | Complete 3D platformer game-jam entry. 11 scenes, ~20 scripts, global hooks, prefabs, node graphs, XM music. Demonstrates every engine feature. |

### 2.3 `n64/tests/`

| Dir | Role |
|---|---|
| `test_obj_states/` | Self-checking test ROM. `ObjCapture.cpp` records object lifecycle events; `TestSetup.cpp` runs scripted test sequences comparing captured vs expected events. **Runs on-device only** — reports via `debugf`/onscreen. The conformance test for runtime object state-machine / event ordering. |

### 2.4 `n64/CMakeLists.txt` — IDE DUMMY

Header comment says so verbatim. Uses host gcc + C++23. Never invoked by real toolchain. **Do not edit expecting ROM changes.**

---

## 3. `data/` — editor-bundled resources

| Path | Role | Format |
|---|---|---|
| `data/themes/*.json` | Editor themes (`dark`, `dark-blue`, `darl-warm` [sic], `highcontrast`, `light`, `retro-95`). | JSON (colors/style/custom/font/fontPixel) |
| `data/Altinn-DINExp.ttf` | Default UI font. | TTF |
| `data/GoogleSansCode.ttf` | Mono font. | TTF |
| `data/materialdesignicons-webfont.ttf` | Icon font (merged into UI font). | TTF |
| `data/W95F.otf` | retro-95 theme font. | OTF |
| `data/icon.ico` | App icon. | ICO |
| `data/nodes/_icons.js` | MDI glyph table for node icons. | JS |
| `data/nodes/_prelude.js` | Node-definition API (`node()`, `valueType()`, `convert()`, `logicIn/Out`, `valueIn/Out`, prop constructors, `__describe`/`__invoke_build`/`__invoke_value`). | JS |
| `data/nodes/_types.js` | Value-type table + conversions. | JS |
| `data/nodes/builtin/{debug,flow,object,value}.js` | Built-in node specs (~44 node ids). | JS |
| `data/scripts/defaultObject.cpp` | Template for new object scripts (substitutes `__UUID__`). | C++ template |
| `data/scripts/defaultGlobal.cpp` | Template for new global scripts. | C++ template |
| `data/scripts/scriptTable.cpp` | Generated-table template (placeholders `__CODE_ENTRIES__` etc.). | C++ template |
| `data/scripts/globalScriptTable.cpp` | Global-hook template (`__CODE_DECL__`/`__CODE_HOOKS__`). | C++ template |
| `data/scripts/assetTable.h` / `sceneTable.h` | Asset/scene table templates (`{{ASSET_MAP}}` etc.), define `operator""_asset`/`_prefab`/`_scene` consteval. | C++ template |
| `data/scripts/mingw_create_env.sh` | Windows toolchain bootstrap. | shell |
| `data/build/baseMakefile.mk` | Per-game Makefile template (substituted by `projectBuilder.cpp:225-240`). | makefile template |
| `data/build/baseMakefile.custom` | User-kept `Makefile.custom` template. | makefile |
| `data/build/baseGitignore` | Project `.gitignore` template (appends `metadata`). | gitignore |
| `data/build/assets/font.ia4.png` | Engine font asset (copied into every project's `assets/p64/`). | PNG (IA4) |
| `data/shader/` | Engine shader sources. | various |
| `data/img/` | Editor UI images (title logo, window icon, splash). | PNG/JPG |
| `data/materialdesignicons-webfont.ttf` | MDI icon font. | TTF |

---

## 4. `docs/` — Sphinx documentation

| Path | Role |
|---|---|
| `index.rst` | Root toctree (faq, manual, dev, version, project, agent). | rST |
| `conf.py` | Sphinx config (furo theme, myst-parser, breathe). | Python |
| `Doxyfile` | Doxygen config — `INPUT = ../n64/engine/include`, XML output for Breathe. | Doxygen |
| `_apigen.py` | Custom Doxygen-XML → rST generator (replaces Exhale). | Python |
| `Makefile` | `make html` (Sphinx). | make |
| `build_and_serve.sh` | Fast/full build + watch + http server. | shell |
| `requirements.txt` | Sphinx + furo + myst-parser + breathe. | pip |
| `docs/faq.md` | FAQ. | MyST |
| `docs/manual/` | User manual (install, launcher, intro, assets, editor, script, cli). Mix of `.rst` (toctrees) + `.md` (MyST body). | rST + MyST |
| `docs/dev/` | Developer manual (`build.rst`). | rST |
| `docs/version/` | Changelog + breaking changes. | MyST |
| `docs/project/` | **BF64-only** — gap-analysis.md, phased-plan.md. | MyST |
| `docs/agent/` | **BF64-only** — this file, ARCHITECTURE.md, HANDOFF.md, DIVERGENCE.md. | MyST |
| `docs/n64/` | **BF64-only** (Phase 1–2, not yet created) — N64 hardware/asset compendium. | MyST (planned) |
| `_static/` | Images, fonts, videos referenced by docs. | binary |

**GOTCHA:** BF64 doc sections (`project/`, `agent/`, `n64/`) follow the convention: new subdirectory under `docs/docs/` + matching `docs/docs/<section>.rst` toctree + one line in `docs/index.rst`. No other shared file modified. See DIVERGENCE.md §6.

---

## 5. `vendored/` — git submodules (11)

| Submodule | Path | Upstream | Role |
|---|---|---|---|
| SDL | `vendored/SDL` | libsdl-org/SDL | Window, GPU device, dialogs, process spawn (SDL3). |
| ImGui | `vendored/imgui` | ocornut/imgui | UI (docking branch, SDL3 GPU backend). |
| SDL_image | `vendored/SDL_image` | libsdl-org/SDL_image | Image loading (window icon, asset preview). |
| SDL_shadercross | `vendored/SDL_shadercross` | libsdl-org/SDL_shadercross | Runtime shader cross-compilation (gated `HAS_SHADER_CROSS`). |
| ImGuizmo | `vendored/ImGuizmo` | CedricGuillemet/ImGuizmo | 3D transform gizmos. |
| ImViewGuizmo | `vendored/ImViewGuizmo` | (vendored) | View-cube / navigation gizmo. |
| ImNodeFlow | `vendored/ImNodeFlow` | (vendored) | Node-graph canvas (`ImFlow::ImNodeFlow`). |
| glm | `vendored/glm` | g-truc/glm | Math (editor side). |
| tiny3d | `vendored/tiny3d` | HailToDodongo/tiny3d | N64 3D library + glTF importer (`tools/gltf_importer/`). |
| libdragon | `vendored/libdragon` | DragonMinded/libdragon | N64 SDK (headers at build time, `n64.mk`/`t3d.mk`). |
| quickjs-ng | `vendored/quickjs-ng` | quickjs-ng/quickjs | JS runtime for node-graph script definitions. |
| SHA256 | `vendored/SHA256` | System-Glitch/SHA256 | UUID hashing. |
| tiny-regex-c | `vendored/tiny-regex-c` | kokke/tiny-regex-c | Regex (used by codeParser). |

**GOTCHA:** submodules are not checked out in this workspace — recon relied on call sites and CMake lists. Run `git submodule update --init --recursive` for full source.

---

## 6. `.github/`

| Path | Role |
|---|---|
| `pull_request_template.md` | Warns large PRs likely won't merge; asks to pre-discuss on Discord. |
| `ISSUE_TEMPLATE/bug_report.md` | Bug report template (system, steps, screenshots). |
| `ISSUE_TEMPLATE/feature-request---suggestion.md` | Feature request template. |
| `workflows/` | CI workflows. |

**GOTCHA:** Upstream issue creation is restricted — outsiders can't open issues. See DIVERGENCE.md §2.2.

---

## 7. `tools/` and `scripts/` and `packaging/`

| Path | Role |
|---|---|
| `tools/createDebugFont.mjs` | Node script to generate the debug font PNG. |
| `tools/package.json` / `package-lock.json` | Node deps for the above. |
| `scripts/build_appimage.sh` | Linux AppImage build script. |
| `packaging/` | Packaging assets/scripts. |

---

## 8. Serialization formats index (quick reference)

Every file format the editor reads/writes, with the parser/writer location:

| Format | Direction | Files | Parser / Writer |
|---|---|---|---|
| `.p64proj` (JSON) | R/W | project root | `Project::deserialize` (`project.cpp:149`) / `ProjectConf::serialize` (`project.cpp:125`) |
| `scene.json` (JSON) | R/W | `data/scenes/<id>/` | `Scene::deserialize` (`scene.cpp:429`) / `Scene::serialize` (`scene.cpp:388`) |
| `<asset>.conf` (JSON) | R/W | alongside asset | `AssetConf::deserialize` (`assetManager.cpp:229`) / `AssetConf::serialize` (`assetManager.cpp:81`) |
| `<asset>.glb.conf` → `data.materials` (JSON) | R/W | alongside `.glb` | `Material::deserialize` / serialize (via `AssetConf.data`) |
| `.prefab` (JSON) | R/W | `assets/` | `Prefab` serialize/deserialize (`scene.cpp:285`) |
| `.p64graph` (JSON) | R/W | `assets/` | `Graph::deserialize` (`graph.cpp:110`) / `Graph::serialize` (`graph.cpp:202`) |
| `.png` | R | `assets/` | SDL_image (`texture.cpp`) / `mksprite` (build) |
| `.bci.png` | R | `assets/` | `BCI::convertPNG` (`bci.cpp`) |
| `.glb` / `.gltf` | R | `assets/` | `T3DM::parseGLTF` (tiny3d `cgltf`) |
| `.wav` / `.mp3` / `.xm` | R | `assets/` | `audioconv64` (build) |
| `.ttf` | R | `assets/` | `mkfont` (build) |
| `.cpp` (user scripts) | R | `src/user/` | `Utils::CPP::parseDataStruct` / `hasFunction` (`codeParser.cpp`) |
| `nodes/*.js` | R | project `nodes/` | `Js::loadSpecs` (`jsNodeHost.cpp`) |
| `data/nodes/*.js` | R | app resources | `Js::loadSpecs` (`jsNodeHost.cpp`) |
| `data/themes/*.json` | R | app resources | `ImGui::Theme::applyThemeJson` (`theme.cpp:38`) |
| `editor.json` (JSON) | R/W | app data dir | `Window::loadState`/`saveState` (`window.cpp`) + `Prefs::load`/`save` |
| `editorScene.json` (JSON) | R/W | app data dir | `Editor::Scene` window persistence (`editorScene.cpp:89-101`) |
| `.sprite` (binary) | W | `filesystem/` | `mksprite` (build) |
| `.bci` (binary) | W | `filesystem/` | `BCI::convertPNG` (build) |
| `.t3dm` (binary) | W | `filesystem/` | `T3DM::writeT3DM` (build) |
| `.wav64` / `.xm64` (binary) | W | `filesystem/` | `audioconv64` (build) |
| `.font64` (binary) | W | `filesystem/` | `mkfont` (build) |
| `.pf` (binary) | W | `filesystem/` | `prefabBuilder.cpp` (build) |
| `.pg` (binary) | W | `filesystem/` | `nodeGraphBuilder.cpp` (build) |
| `src/p64/scriptTable.cpp` (C++) | W | project `src/p64/` | `buildScripts` (`scriptBuilder.cpp:17`) |
| `src/p64/globalScriptTable.cpp` (C++) | W | project `src/p64/` | `buildGlobalScripts` (`scriptBuilder.cpp:96`) |
| `src/p64/sceneTable.{h,cpp}` (C++) | W | project `src/p64/` | `projectBuilder.cpp:156-188` |
| `src/p64/assetTable.h` (C++) | W | project `src/p64/` | `projectBuilder.cpp:199-203` |
| `src/p64/<graphUUID>.cpp` (C++) | W | project `src/p64/` | `buildNodeGraphAssets` (`nodeGraphBuilder.cpp:31`) |
| `Makefile` | W | project root | `projectBuilder.cpp:225-240` from `data/build/baseMakefile.mk` |
| `Makefile.custom` | W | project root | `data/build/baseMakefile.custom` (copied once) |
| `.gitignore` | W | project root | `data/build/baseGitignore` (copied once) |
| `filesystem/p64/a` (binary) | W | `filesystem/p64/` | `projectBuilder.cpp:206-218` |
| `filesystem/p64/conf` (binary) | W | `filesystem/p64/` | `projectBuilder.cpp:242-251` |
| `filesystem/p64/fileList.txt` | W | `filesystem/p64/` | `projectBuilder.cpp` (asset-list cache) |
| `metadata.ini` + `img_*.{png,jpg}` + `description[_lang].txt` | W | `metadata/` | `romMetaBuilder.cpp:104-113` |
| `.z64` (binary) | W | project root | `make` via libdragon `n64.mk` |
| `rom:/p64/sNNNN_` (binary, in-ROM) | W | packed into `.z64` | `sceneBuilder.cpp` |
| `rom:/p64/sNNNN_o` (binary, in-ROM) | W | packed into `.z64` | `sceneBuilder.cpp` (objects) |
| `rom:/p64/a` (binary, in-ROM) | W | packed into `.z64` | `projectBuilder.cpp:206-218` |
| `rom:/p64/conf` (binary, in-ROM) | W | packed into `.z64` | `projectBuilder.cpp:242-251` |

---

## 9. Entry points index (quick reference)

| What | Where |
|---|---|
| Editor `main` | `src/main.cpp:154` |
| Editor CLI dispatch | `src/cli.cpp:26` |
| Editor global context | `src/context.h` (`ctx`) |
| Editor action registry | `src/editor/actions.cpp:13` (`actionCallbacks[0xFF]`) |
| Editor global actions | `src/editor/globalActions.cpp:42` (`initGlobalActions`) |
| Editor main loop | `src/main.cpp:304-492` |
| Editor undo system | `src/editor/undoRedo.cpp:64` (`History::begin`) |
| Project load | `src/project/project.cpp:167` (`Project::Project` ctor) |
| Project save | `src/project/project.cpp:258` (`Project::save`) |
| Scene load (editor) | `src/project/scene/sceneManager.cpp:131` (`SceneManager::loadScene`) |
| Scene serialize | `src/project/scene/scene.cpp:388` (`Scene::serialize`) |
| Object serialize | `src/project/scene/object.cpp:19` (`serializeObj`) |
| Asset load | `src/project/assetManager.cpp:167` (`Project` ctor) → `reload` |
| Asset build entry | `src/project/assetManager.cpp:187` (`buildCodeEntry`) / per-type builders in `src/build/` |
| Build orchestrator | `src/build/projectBuilder.cpp:56` (`buildProject`) |
| Runtime main loop | `n64/engine/src/main.cpp:106` |
| Runtime scene update | `n64/engine/src/scene/scene.cpp:149` (`Scene::update`) |
| Runtime scene draw | `n64/engine/src/scene/scene.cpp:295` (`Scene::draw`) |
| Runtime scene load (binary) | `n64/engine/src/scene/sceneLoader.cpp:67` (`loadObject`) |
| Runtime asset init | `n64/engine/src/assets/assetManager.cpp:101` (`AssetManager::init`) |
| Runtime physics step | `n64/engine/src/collision/collisionScene.cpp` (`CollisionScene::step`) |
| Runtime audio update | `n64/engine/src/audio/audioManager.cpp:91` (`AudioManager::update`) |
| Node-graph codegen | `src/project/graph/graph.cpp:279` (`Graph::build`) |
| Node-graph spec loader | `src/project/graph/jsNodeHost.cpp` (`Js::loadSpecs`) |
| Script table gen | `src/build/scriptBuilder.cpp:17` (`buildScripts`) |
| Theme loader | `src/editor/imgui/theme.cpp:38` (`applyThemeJson`) |
