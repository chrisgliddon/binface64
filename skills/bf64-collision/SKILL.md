---
name: bf64-collision
description: Use when implementing or debugging BF64 collision, rigid bodies, character bodies, collision meshes, raycasts, sweeps, contacts, or movement behavior.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: collision
  target_version: "BF64"
---

# BF64 Collision

Use this for runtime physics and collision behavior.

## Quick Start

```bash
./bf64 scene validate --project <project> --json
./bf64 project status --project <project> --json
./bf64 build --project <project> --json
```

## Mental Model

- Editor collision components are serialized and baked into runtime component data.
- Runtime collision code lives under `n64/engine/include/collision` and `n64/engine/src/collision`.
- BF64 has collision bodies, collision meshes, rigid bodies, and character-body style movement.
- Runtime queries include raycasts and sweeps; use engine APIs instead of reimplementing math in game scripts.
- Collision meshes and model meshes are related but not interchangeable decisions; validate build outputs.

## Workflow

1. Validate the scene before debugging behavior; malformed components can look like physics bugs.
2. Identify the intended shape/body type and check the runtime header for available fields/functions.
3. Keep collision meshes low-detail and gameplay-shaped, not render-mesh exact.
4. Rebuild and run in emulator; inspect logs for component init/delete or heap warnings.
5. Use debug drawing/logging when available, then remove or gate debug output.

## Examples

- See [EXAMPLES.md](EXAMPLES.md) for `CharBody::moveAndSlide`, floor raycasts, and collision event patterns from current examples.

## Grounding

- `docs/docs/agent/ARCHITECTURE.md` runtime scene/object/component sections.
- `docs/docs/agent/CODEMAP.md` collision headers and component map.
- `docs/docs/n64/performance-budgets.md` for CPU/RSP/RDP budget context.

## Common Agent Mistakes

- Using visual mesh complexity as collision mesh complexity.
- Debugging runtime motion while only inspecting editor-side component data.
- Forgetting fixed/update ordering and per-frame hardware costs.
- Adding custom collision math when BF64 already exposes tested runtime primitives.
