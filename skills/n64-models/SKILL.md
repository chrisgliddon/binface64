---
name: n64-models
description: Use when creating, importing, validating, or optimizing BF64 3D models, glTF/Fast64 exports, tiny3d assets, skeletons, or animations.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: models
  target_version: "BF64"
---

# N64 Models

Use this for 3D assets before they become BF64 runtime `.t3dm` outputs.

## Quick Start

```bash
./bf64 constraints model --json
./bf64 validate ./asset.glb --json
./bf64 import ./asset.glb --project <project> --dest models/asset.glb --dry-run --json
```

## Hard Checks

- Model source must be `.glb` or `.gltf`.
- BF64 validates total vertices and indices against 65535 each.
- tiny3d's RSP vertex cache target is 70 vertices per load.
- Animation targets are translation, rotation, and scale.
- Multiple skin weights are discarded; design for one effective bone influence.
- Fast64 material extras are expected for reliable import.

## Workflow

1. Model for silhouette and gameplay readability first, then reduce geometry.
2. Keep collision mesh simpler than render mesh.
3. Export with Fast64-compatible material data.
4. Validate source file before import.
5. Import with `--dry-run`, then real import.
6. Build the ROM to let tiny3d importer and BF64 builder prove the asset.

## Grounding

- `docs/docs/n64/models-and-meshes.md`
- `docs/docs/n64/performance-budgets.md`
- `docs/docs/n64/asset-checklist.md`
- `docs/docs/n64/limits.json`

## Common Agent Mistakes

- Treating glTF PBR materials as if BF64 imports all of them.
- Relying on smooth high-poly shapes that will not survive N64 budgets.
- Assuming multi-weight skinning behaves like modern engines.
- Accepting a model after JSON validation without a real build when importer edge cases matter.
