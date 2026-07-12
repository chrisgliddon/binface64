---
name: bf64-scenes
description: Use when inspecting or reasoning about BF64 scenes, objects, components, prefabs, scene JSON, scene validation, or editor/runtime serialization boundaries.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: scenes
  target_version: "BF64"
---

# BF64 Scenes

Use this when working with scene structure or object/component composition.

## Quick Start

```bash
./bf64 scene ls --project <project> --json
./bf64 scene show <scene-id> --project <project> --json
./bf64 scene validate --project <project> --json
./bf64 scene create Gameplay --project <project> --json
./bf64 scene object add 1 --name Player --project <project> --json
./bf64 scene component add 1 Player camera --project <project> --json
./bf64 scene attach model 1 Player assets/player.glb --project <project> --json
./bf64 prefab create actors/player --project <project> --json
./bf64 prefab attach model actors/player Player assets/player.glb --project <project> --json
./bf64 project status --project <project> --json
```

## Mental Model

- Editor scene data lives under `data/scenes/<id>/scene.json`.
- Editor objects are `Project::Object` trees with editor-side components and JSON serialization.
- Runtime objects are packed `P64::Object` allocations with `CompRef[]` and component data blobs.
- Prefabs are source assets; runtime prefab binaries are generated during build.
- The editor and runtime do not call each other; they communicate through baked files.
- Script namespace identifiers are exactly 16 hex characters with `C` as the first character; that `C` is part of the UUID stored by a Code component.

## Workflow

1. Inspect scene inventory with `scene ls`, then inspect the target scene with `scene show`.
2. Validate structure before making claims about boot/reset scene references, duplicate UUIDs, component ids, render pipeline constraints, or object count.
3. Use `scene create/duplicate/rename/delete`, `scene object add/update/remove/reparent`, `scene component add/update/remove`, and `scene attach`; do not raw-edit scene JSON.
4. Use the matching `prefab create/duplicate/rename/delete`, `prefab object`, `prefab component`, and `prefab attach` commands for prefab documents and sidecar pairs.
5. After asset or component changes, run the relevant validation and `project status`.
6. If runtime behavior differs from scene JSON, inspect the build pipeline and generated assets, not just editor data.

## Grounding

- `docs/docs/agent/ARCHITECTURE.md` sections 1.4, 2.2, and 3.
- `docs/docs/agent/CODEMAP.md` sections `src/project/scene`, `src/project/component`, and `src/build/sceneBuilder.cpp`.
- `docs/docs/agent/AGENTIC_SURFACE.md` scene validator contract.

## Common Agent Mistakes

- Confusing editor component IDs/data with runtime packed component structs.
- Editing `filesystem/` outputs instead of source scene, prefab, or asset files.
- Raw-editing scene JSON instead of using atomic, validated mutation commands.
- Moving or replacing a prefab without its `.conf` sidecar instead of using pair-safe CLI operations.
- Forgetting that build-time baking can change the runtime representation.
