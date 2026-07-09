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
./bf64 project status --project <project> --json
```

## Mental Model

- Editor scene data lives under `data/scenes/<id>/scene.json`.
- Editor objects are `Project::Object` trees with editor-side components and JSON serialization.
- Runtime objects are packed `P64::Object` allocations with `CompRef[]` and component data blobs.
- Prefabs are source assets; runtime prefab binaries are generated during build.
- The editor and runtime do not call each other; they communicate through baked files.

## Workflow

1. Inspect scene inventory with `scene ls`, then inspect the target scene with `scene show`.
2. Validate structure before making claims about boot/reset scene references, duplicate UUIDs, component ids, render pipeline constraints, or object count.
3. For scene changes, prefer editor-supported actions or future BF64 scene APIs; raw JSON editing is a last resort and must be validated.
4. After asset or component changes, run `scene validate` and `project status`.
5. If runtime behavior differs from scene JSON, inspect the build pipeline and generated assets, not just editor data.

## Grounding

- `docs/docs/agent/ARCHITECTURE.md` sections 1.4, 2.2, and 3.
- `docs/docs/agent/CODEMAP.md` sections `src/project/scene`, `src/project/component`, and `src/build/sceneBuilder.cpp`.
- `docs/docs/agent/AGENTIC_SURFACE.md` scene validator contract.

## Common Agent Mistakes

- Confusing editor component IDs/data with runtime packed component structs.
- Editing `filesystem/` outputs instead of source scene, prefab, or asset files.
- Assuming scene JSON mutation is safe without validator and build confirmation.
- Forgetting that build-time baking can change the runtime representation.
