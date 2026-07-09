---
name: bf64
description: Use when starting any BF64, Binface64, Pyrite64, or N64 game-development task and you need the right sibling skill, current source pins, CLI commands, or project workflow.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "1"
  area: router
  target_version: "BF64"
---

# BF64 Router

Read this first for Binface64 work. BF64 is an agentic fork of Pyrite64: a hosted editor plus N64 runtime built on libdragon and tiny3d.

## Version Pins

- BF64 CLI surface: `tools/bf64.py`, `CLI_VERSION = "0.9.0"`.
- Constraint schema: `docs/docs/n64/limits.json`, `schema_version = 1`.
- tiny3d source pin: `bdcd946`.
- libdragon source pin: `b1011fe31`.
- Current source-of-truth docs: `docs/docs/agent/AGENTIC_SURFACE.md`, `ARCHITECTURE.md`, `CODEMAP.md`, and `docs/docs/n64/*`.

If a local checkout disagrees with these pins, inspect the repo before applying this collection.

## Route By Task

| Task | Skill |
|---|---|
| Hardware, memory, ROM, display, emulator, asset budgets | `n64-constraints` |
| Headless commands, JSON contracts, validation, import, build, run, history | `bf64-cli` |
| New project, toolchain, build/run loop, starter layout | `bf64-project-setup` |
| Scenes, object/component graph, prefabs, serialization | `bf64-scenes` |
| Visual scripting and generated node-graph C++ | `bf64-node-graph` |
| Runtime C++ scripts and public engine APIs | `bf64-cpp-scripting` |
| tiny3d rendering, materials, lighting, HDR, BigTex | `bf64-rendering` |
| Physics, collision bodies, character movement, raycasts | `bf64-collision` |
| Importing files into projects with sidecars and validation | `bf64-asset-import` |
| 3D models, glTF, Fast64, animation, skinning | `n64-models` |
| Textures, palettes, TMEM, sprites, BigTex | `n64-textures` |
| Fonts, HUDs, 2D sprites, readable UI/text | `n64-2d-ui-text` |
| SFX, WAV64, XM64, music budgets | `n64-audio-assets` |
| Image-generation prompts and low-poly visual references | `n64-concept-art` |
| Turning game ideas into feasible N64 scope | `n64-game-design-budgets` |
| Validation, emulator runs, logs, screenshots, hardware QA | `bf64-qa-debugging` |

## Cardinal Rules

1. Query BF64's structured surface first: `./bf64 project status --project <project> --json`.
2. Use `./bf64 validate`, `./bf64 import`, and `./bf64 asset validate-all` before touching build outputs.
3. Treat `docs/docs/n64/limits.json` as the machine-readable constraint source.
4. Do not teach agents to edit generated files under `filesystem/`, `build/`, or `src/p64/`.
5. Headed editor, headless CLI, and future MCP tools should share the same constraints.

## Common Agent Mistakes

- Applying generic N64 advice without checking BF64's current validator and docs.
- Assuming Pyrite64 editor CMake files build ROMs; ROM builds use libdragon/tiny3d Makefiles.
- Raw-editing scene JSON as the long-term mutation API instead of using supported CLI/editor surfaces.
- Reporting "works" without a JSON validation, build, run, or captured error/log artifact.
