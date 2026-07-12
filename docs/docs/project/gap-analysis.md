# Binface64 Gap Analysis: Upstream Baseline and BF64 Status

**Pyrite64 (upstream) vs. N64 hardware capability vs. the engine feature set behind Super Mario 64 & Ocarina of Time**

Prepared for the Binface64 project · Historical baseline: Pyrite64 v0.6.0 (v0.7.0 in development) · BF64 status reviewed July 2026

---

## 1. Purpose & Method

This document answers one question: **what would an engine need to provide for a team (or an agent) to ship a game of the caliber of Super Mario 64 or Ocarina of Time — and how much of that does Pyrite64 already provide?**

Sources used:
- Pyrite64 README, full documentation tree (components, C++ API namespaces, editor windows), FAQ, and v0.1.0–v0.7.0 changelog (hailtododongo.github.io/pyrite64)
- libdragon and tiny3d capabilities (the SDK layer Pyrite64 sits on)
- Known technical architecture of SM64 (1996) and OoT (1998) from decompilation-era documentation and N64 homebrew community knowledge

**Confidence legend** — used throughout, because "not in the docs" ≠ "not in the code":

| Mark | Meaning |
|---|---|
| ✅ Present | Documented feature with a component/API/editor surface |
| 🟡 Partial | Exists but limited, code-only, or requires C++ workarounds |
| ❌ Absent | No trace in docs, changelog, or API reference; FAQ may explicitly deny it |
| ❓ Unverified | Not documented; may exist in code or in libdragon/tiny3d underneath — **confirm during BF64 Phase 0 code recon** |

## Current BF64 delta

The comparison tables below intentionally preserve the reviewed **upstream Pyrite64 v0.6 baseline**. They are no longer the current BF64 feature inventory. BF64 has since closed the first shippability tranche:

| Original gap | Current BF64 implementation |
|---|---|
| 2D UI/HUD, images, text, input | Versioned `.bfui` assets; dedicated GUI and CLI; Container/Image/Text/Button/TextInput/ProgressBar runtime; stable IDs, focus, mutable values, and collapsible horizontal/vertical flow |
| Dialogue/typewriter | Input-agnostic `P64::UI::DialogueRunner` with UTF-8-safe reveal, manual/timed progression, events, and direct `.bfui` binding |
| Save data | Public redundant/checksummed EEPROM 4K/16K and FlashRAM slot service with generations, corruption fallback, erase tombstones, migrations, and Ares two-boot probes |
| Positional audio | `Audio3D` editor/runtime component and `AudioManager::play3D`, with camera listener, distance rolloff, equal-power stereo pan, movable handles, and WAV pitch control |
| Procedural geometry | Triple-buffered `Renderer::ChunkMesh` with per-chunk dirty copies, vertex-color updates, visibility/AABB culling, and memory/triangle telemetry |
| Headless content mutation | Atomic, validated scene, prefab, and node-graph lifecycle/object/component mutation with dry-run, JSON, recording, stable UUIDs, and rollback |
| Production focus areas | Shared GUI/CLI areas for UI, Music, SFX, 3D Environment, 3D Avatars, and Cutscenes |
| Runtime evidence | Bounded structured profiling plus machine-readable frame/render/memory/audio/artifact metrics |
| Linux setup | Toolchain detection/install and atomic `doctor --fix` for project-local SDK configuration |

Remaining rows such as room streaming, dynamic music direction, shadows, camera behaviors, LOD, authored branching/localization, and game-state flow are still useful backlog. Read any “Absent” UI/save/Audio3D or headless-mutation row below as an upstream finding superseded by this table.

---

## 2. What Pyrite64 Already Has (v0.6.0 inventory)

**Editor:** 3D viewport (multi-select, orbit/focus, gizmos), scene hierarchy graph, object/scene/layer/asset inspectors, asset browser, log window, **ROM size dashboard**, node-graph editor, model editor, launcher with automatic toolchain install (Windows), macOS/Metal and Linux support, configurable keymaps, window layout persistence.

**Runtime components:** Model (static), Model (animated — skeletal via tiny3d), Light, Camera, Culling, Collision-Mesh, Collider, Rigid-Body, Character-Body, Constraint, Audio (2D), Code (C++), Node-Graph.

**Collision & physics (surprisingly deep):** AABB-tree broadphase, GJK/EPA narrowphase, shape library (box, sphere, capsule, cylinder, cone, pyramid), mesh colliders, raycasts, sphere/capsule sweeps, contact constraints, rigid bodies, a dedicated character body controller, and constraints.

**Rendering:** tiny3d pipeline with three render pipelines — Default, **HDR+Bloom**, and **BigTex (256×256 texture streaming)** — plus a material system with material instances, draw layers, a particle/sprite system (PTX), fast64 material import from Blender GLTF, and a debug overlay.

**Engine services:** scene manager, global asset manager with automatic memory cleanup, prefabs with parameters, object lifecycle/event queue, global scripts, matrix manager, static memory allocator, VI swapchain, logging, debug menu.

**Audio:** mixer with configurable frequency (default 32 kHz), Opus-compressed audio working (v0.3.0), Audio2D component, AudioManager/Handle API.

**Pipeline & tooling:** GLTF import, on-demand collision mesh generation, duplicate-UUID and missing-model validation, auto-save before build & run, a basic **CLI** (build, clean), open-source IPL3 — no proprietary SDK anywhere; ROMs run on real hardware and accurate emulators (Ares v147+, gopher64).

---

## 3. Where Pyrite64 Already *Exceeds* Retail-Era Engines

Worth stating before listing gaps, because it's the foundation of the BF64 thesis:

| Capability | Pyrite64 | Retail 1996–2000 |
|---|---|---|
| Texture size | 256×256 big-texture streaming path | Effectively 32×64 / 64×64-class tiles constrained by 4KB TMEM; large surfaces done by tiling |
| Post-processing | HDR + bloom pipeline | Essentially none; VI filter tricks at best |
| Physics | General-purpose GJK/EPA rigid bodies, sweeps, constraints | Bespoke per-game collision (SM64's floor/wall/ceiling tri checks; OoT's bgcheck) — no general physics |
| Microcode/throughput | tiny3d (modern RSP microcode, outperforms F3DEX2-class throughput) | SGI F3D/F3DEX/F3DZEX microcodes |
| Tooling | Live visual editor, ROM size dashboard, prefabs, instant emulator loop | Text pipelines, NINGEN/proprietary SGI workstations, multi-minute burns to dev carts |
| Legal | 100% open source, sellable output | Proprietary Nintendo SDK, licensed devs only |

The gap analysis below is therefore *not* "Pyrite64 is behind 1998" — it's ahead in rendering and physics, and behind in **shippable-game systems** (UI, save, audio direction, streaming, game framework).

---

## 4. Benchmark: What SM64 and OoT Demanded From Their Engines

### Super Mario 64 (1996) — engine-level requirements
- Whole-course loading (no streaming), ~4MB RDRAM budget
- Skeletal character animation with per-part display lists; distance LOD on select objects
- **Blob/projected drop shadows** (critical for platforming depth perception)
- Camera as a first-class *system* (Lakitu: modes, collision-aware, player-relative)
- Analog-stick character controller with slopes, walls, ceilings, water volumes
- **Sequenced music** (sample-bank + score) with dynamic layering and environmental filtering (muffled underwater)
- Positional/3D sound effects
- HUD (counters, glyph font), dialog boxes with a text/glyph system
- **EEPROM saves** (4 kbit)
- Particles, water rendering, warp/transition system, demo playback

### Ocarina of Time (1998) — engine-level requirements (superset of SM64's)
- **Scene → room streaming from cartridge** (rooms swapped in a double-buffered RAM segment while the scene persists) — the single most important technique for making a "big" N64 game fit in 4MB
- **Actor overlay system**: gameplay code for entities loaded/unloaded from ROM at runtime — code itself was streamed, not just assets
- Environment system: **day/night cycle with interpolated ambient/diffuse/fog lighting per time-of-day**, per-room environment settings
- Skeletal animation with **animation blending/interpolation** and flex (skinned) skeletons; **LOD meshes** on characters
- Dynamic **projected shadows**, per-room **audio reverb/echo**, positional 3D audio
- **Dynamic sequenced music**: transitions, stingers, interactive layering (plus the ocarina itself — runtime note synthesis)
- Camera system with behaviors, rail/fixed modes, **Z-targeting** support, and a **spline-driven cutscene system**
- Text/dialogue engine: variable-width font, control codes (color, icons, pauses, choices), localization
- Path/waypoint system for NPCs and platforms; water volumes with distinct physics; minimap + HUD framework
- **SRAM saves** with multiple slots and checksums
- (Majora's Mask, same engine, added Expansion Pak-mandatory 8MB usage — the ceiling case)

**Also relevant to "top N64 games" generally:** 4-controller local multiplayer (Mario Kart 64, GoldenEye, Smash), Rumble Pak, Controller Pak saves — the N64's social identity.

---

## 5. Gap Matrix

### 5.1 Rendering & Graphics

| Capability | SM64 | OoT | Pyrite64 v0.6 | Status |
|---|---|---|---|---|
| Static & skeletal models | ✔ | ✔ | Model + AnimModel components | ✅ Present |
| Animation blending/crossfade | partial | ✔ | tiny3d supports blending; no documented component-level control | ❓ Unverified — verify AnimModel API in Phase 0 |
| LOD (distance-based mesh swap) | partial | ✔ | Not documented | ❌ Absent |
| Drop/projected shadows | ✔ (blob) | ✔ (projected) | Not documented | ❌ Absent — high impact for 3D platformers |
| Fog | ✔ | ✔ (per-room, animated) | tiny3d supports fog; fast64 materials carry fog settings | ❓ Unverified at engine/editor level |
| Environment/reflection mapping | ✘ | partial (spherical env-map effects) | Not documented | ❌ Absent |
| Particles | ✔ | ✔ | PTX sprite/particle system | ✅ Present |
| Post-processing (HDR/bloom) | ✘ | ✘ | HDRBloom pipeline | ✅ **Exceeds retail** |
| Big textures | ✘ | ✘ | 256×256 BigTex pipeline | ✅ **Exceeds retail** |
| Draw layers / transparency ordering | ✔ | ✔ | DrawLayer system | ✅ Present |
| Culling | ✔ | ✔ (room-based) | Culling component | ✅ Present (object-level; room-level see 5.4) |
| Skinned "flex" meshes | ✘ | ✔ | tiny3d supports skinning | ❓ Unverified through the editor pipeline |

### 5.2 Audio

| Capability | SM64 | OoT | Pyrite64 v0.6 | Status |
|---|---|---|---|---|
| SFX playback (2D) | ✔ | ✔ | Audio2D component, Opus support | ✅ Present |
| **Positional 3D audio** (pan/attenuate by distance) | ✔ | ✔ | Only Audio2D documented — no Audio3D component exists | ❌ Absent — glaring for a 3D engine |
| Sequenced/tracker music (small footprint, dynamic) | ✔ | ✔ | libdragon supports XM/YM modules underneath; no documented music component or editor surface | 🟡 Partial — SDK capability without engine surface |
| Dynamic music (layers, transitions, stingers) | ✔ | ✔ | Nothing documented | ❌ Absent |
| Environmental DSP (reverb/echo per area, underwater filter) | ✔ | ✔ | Nothing documented | ❌ Absent |
| Streamed music (Opus) | ✘ | ✘ | Working since v0.3 | ✅ Exceeds retail (with ROM-size tradeoff) |

### 5.3 Gameplay Framework & UI

| Capability | SM64 | OoT | Pyrite64 v0.6 | Status |
|---|---|---|---|---|
| Character controller | ✔ | ✔ | CharacterBody (capsule sweeps, slopes) | ✅ Present |
| Camera *behaviors* (follow modes, collision-aware, targeting, rails) | ✔ | ✔ | Camera component exists; behaviors are DIY C++ | 🟡 Partial |
| **2D / HUD / UI system** | ✔ | ✔ | FAQ: "2D support is WIP and currently done in code" | ❌ Absent (explicitly) |
| **Text/font/dialogue engine** (control codes, choices, localization) | ✔ | ✔ | Nothing documented | ❌ Absent |
| Menus & game-state flow (title → game → pause) | ✔ | ✔ | Scene switching exists; no state/menu framework | 🟡 Partial |
| **Save system** (EEPROM/SRAM/FlashRAM + Controller Pak) | ✔ EEPROM | ✔ SRAM | Nothing documented; libdragon provides the primitives | ❌ Absent — a game you can't save isn't shippable |
| Cutscene system (camera splines, timed events) | partial | ✔ | Node-graph can sequence events | 🟡 Partial — no camera-spline/timeline tooling |
| Path/spline/waypoint system | partial | ✔ | Nothing documented | ❌ Absent |
| Day/night & environment interpolation | ✘ | ✔ | Lights are scriptable in C++; no time-of-day system | ❌ Absent |
| Water/area volumes (swim physics, triggers) | ✔ | ✔ | Trigger volumes achievable via colliders + events | 🟡 Partial |
| Visual gameplay scripting | n/a | n/a | FAQ: node-graph is *only* event sequences; **C++ required** | 🟡 Partial — the core DX gap BF64's whole thesis targets |

### 5.4 Memory, Streaming & Scale

| Capability | SM64 | OoT | Pyrite64 v0.6 | Status |
|---|---|---|---|---|
| Scene loading with asset lifetime management | ✔ | ✔ | SceneManager + AssetManager w/ auto cleanup | ✅ Present |
| **Sub-scene (room) streaming** | ✘ | ✔ | Scenes appear to be atomic load units | ❌ Absent — the ceiling on world size |
| Code overlays (stream gameplay code like OoT actors) | ✘ | ✔ | Not documented (libdragon has overlay/USO support underneath) | ❓ Unverified |
| Expansion Pak (8MB) detection/usage | ✘ | optional | Not documented | ❓ Unverified |
| ROM budget visibility | n/a | n/a | ROM size dashboard | ✅ Present — great foundation for `bf64 validate` |

### 5.5 Input & Peripherals

| Capability | Top games | Pyrite64 v0.6 | Status |
|---|---|---|---|
| Controller 1 (stick + buttons) | ✔ | Working (via libdragon joypad) | ✅ Present |
| **4-controller multiplayer** | MK64, GoldenEye, Smash | No documented multi-player abstractions | ❓ Unverified — libdragon supports 4 ports; engine surface unknown |
| Rumble Pak | ✔ (post-StarFox) | Not documented (libdragon supports it) | ❓ Unverified |
| Controller Pak saves | ✔ | Not documented | ❌ Absent |
| Transfer Pak | niche | Not documented | ❌ Absent (low priority) |

### 5.6 Developer & Agent Experience (the BF64-specific lens)

| Capability | Pyrite64 v0.6 | Status |
|---|---|---|
| Visual editor | Yes, mature and multiplatform | ✅ Present |
| CLI | Exists — build/clean only | 🟡 Partial — no validate/import/inspect, no `--json` |
| Headless scene read/write | No | ❌ Absent |
| MCP / agent interface | No | ❌ Absent (BF64 raison d'être) |
| Extension/plugin system | No — Custom Graph Nodes only | 🟡 Partial |
| Machine-readable error output | No | ❌ Absent |
| Asset pre-flight validation | Partial (UUID/missing-model checks) | 🟡 Partial |

---

## 6. Prioritized Gaps for Binface64

Ranked by **(shippability impact × frequency of need)**, mapped to the BF64 phased plan. P0 = you can't ship a "top game"-class title without it.

### P0 — Blocks any complete game
1. ✅ **Save system core delivered in BF64:** EEPROM 4K/16K redundant slots, checksums, migrations, and persistence testing. SRAM/FlashRAM and Controller Pak remain later extensions.
2. 🟡 **UI/HUD + text/typewriter core delivered in BF64:** authored documents, runtime images/text/input/buttons/meters, and dialogue sequencing are present. Localization, branching choices, and inline control codes remain.
3. ✅ **Positional 3D audio delivered in BF64:** editor component plus runtime pan/attenuation and moving-source controls.
4. ⬜ **Game-state/menu flow framework remains:** title → gameplay → pause → game over, built on existing scene management.

### P1 — Separates "demo" from "Ocarina-class"
5. **Room/sub-scene streaming** — OoT's defining trick; determines whether BF64 games are SM64-sized courses or OoT-sized worlds. Verify AssetManager's granularity in Phase 0 before designing.
6. **Dynamic music system** — sequenced (XM/YM via libdragon) with layers/transitions/stingers, plus environmental DSP (reverb, underwater filter). Streamed Opus alone eats ROM budget fast.
7. **Shadows** (blob first, projected later) — cheap, and platforming legibility depends on it.
8. **Camera behavior library** — follow/orbit/rail/fixed modes with collision avoidance and target-lock support, as data-configurable components rather than bespoke C++.
9. **LOD support** in the model pipeline (author LOD levels in Blender, distance-swap at runtime).
10. **Path/spline system** — NPCs, platforms, and cutscene cameras all want it; one system serves three needs.
11. **Cutscene timeline** — extend the node-graph with camera splines + timed tracks.

### P2 — Polish, reach, and the "alternate timeline" flex
12. **Day/night & environment interpolation system** (time-of-day lighting/fog keyframes).
13. **4-player input abstraction + Rumble Pak** — the N64's social soul; also a marketing-grade differentiator for new releases.
14. **Expansion Pak awareness** (detect 8MB, expose the budget to the ROM dashboard and `bf64 validate`).
15. **Animation blending controls** surfaced in AnimModel (if verification shows they're not already exposed).
16. **Environment mapping / fake reflections**, **code overlays** for very large games, **Controller Pak** saves.

### Agent-surface status
- ✅ CLI expansion with stable `--json`, validation, build/run/profile, focus areas, and operation history
- ✅ Supported scene, prefab, node-graph, asset-exclusion, and project mutation surfaces
- ✅ Skills encoding the reviewed constraints and current workflows
- ⬜ MCP server remains a separate integration layer over the CLI contracts
- ⬜ A general third-party Extensions/plugin ABI remains separate from the supported headless mutation work

**Current disposition:** the core of the proposed Phase 7.5 shippability tranche is implemented. Dogfooding should now concentrate on game-state flow and the remaining authoring depth instead of rebuilding save/UI/Audio3D primitives game-side.

---

## 7. Non-Gaps (things NOT worth building)

- **PC export** — FAQ says N64-only; agreed. The constraint *is* the product.
- **Modding existing ROMs** — out of scope and legally fraught; BF64 is for new games.
- **Inaccurate-emulator support** (Project64 etc.) — hardware accuracy is the quality bar; don't chase broken targets.
- **General visual programming to replace C++ entirely** — the BF64 answer to "poor DX" is agents writing the C++ (plus Extensions), not reinventing Blueprints on a 93.75MHz CPU.
- **Matching OoT's actor overlay system on day one** — modern 64MB flashcart-era ROM budgets and 8MB Expansion Pak targeting reduce (but don't eliminate) the pressure that forced it in 1998.

---

## 8. Open Questions → Phase 0 Verification Checklist

Carry these into the BF64 Phase 0 code recon; each flips an ❓ above to ✅/❌:

1. Does `AnimModel` expose animation blending/crossfade and multiple simultaneous animations?
2. Is fog configurable per-scene/per-material through the editor, or only via fast64 material import?
3. What is the actual granularity of `AssetManager` load/unload — could room streaming be built on it without redesign?
4. Does the runtime detect/use Expansion Pak RAM (8MB) anywhere?
5. **Resolved in BF64:** joypad was already runtime-facing; BF64 now wraps EEPROM 4K/16K. Rumble, SRAM/FlashRAM, and Controller Pak remain unsurfaced.
6. Is skinned-mesh (flex) import supported end-to-end through the GLTF pipeline?
7. Does the PTX system support world-space 3D particles or screen-space sprites only?
8. **Resolved in BF64:** `./bf64` now covers constraints, toolchain, project, import/assets, exclusions, scenes, prefabs, node graphs, UI/focus areas, build/run/profile, and history.
9. **Resolved for playback/import:** XM is imported and built to XM64 through Audio2D; dynamic layers/transitions/stingers remain absent.
10. **Resolved in BF64:** `.bfui` supplies the authored 2D document/editor/builder/runtime surface described in the status table.

---

## 9. Bottom Line

Upstream Pyrite64 is a **rendering- and physics-forward** engine that already beats 1996–2000 retail technology in several dimensions (HDR, big textures, general physics, tooling). The original review correctly identified its missing game-shipping layer. BF64 now supplies the first core pieces—save data, authored UI/text/input/meters, dialogue sequencing, positional audio, structured profiling, and supported headless production workflows—while music direction, streaming, shadows, camera/game-state frameworks, and richer authored narrative systems remain meaningful product gaps.

That leaves BF64 in a more useful dogfooding position: agents can build against stable shippability primitives and use real ROM/Ares evidence to discover the next gaps, rather than reproducing foundational UI/save/audio services inside every game.
