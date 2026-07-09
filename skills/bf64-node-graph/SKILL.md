---
name: bf64-node-graph
description: Use when working with BF64 visual scripting, node graph assets, node specs, variables, links, generated C++ code, or graph build/debug failures.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: scripting
  target_version: "BF64"
---

# BF64 Node Graphs

Use this for visual scripting assets and node-spec authoring.

## Quick Start

```bash
./bf64 asset ls --project <project> --json
./bf64 asset show <node-graph-or-asset-name> --project <project> --json
./bf64 build --project <project> --json
```

## Mental Model

- `.p64graph` stores graph JSON: view, variables, nodes, links, and groups.
- Native specs live in C++; most node specs come from JS under `data/nodes/builtin/*.js` plus project `nodes/*.js`.
- `Project::Graph::Graph::build` emits generated C++ and a binary header for the ROM.
- Generated graph C++ is written under project `src/p64/<uuid>.cpp`; do not edit it by hand.
- Value pins are typed by BF64's graph value-type registry and converted during codegen.

## Workflow

1. Inspect assets and graph sidecars before editing.
2. If adding node behavior, edit node spec sources, not generated C++.
3. Keep node ids stable; missing ids become placeholders so saved graphs preserve data.
4. Build dry-run, then real build, to force graph regeneration.
5. When debugging runtime graph behavior, inspect generated C++ as evidence but fix the source node or graph asset.

## Reference

- See [REFERENCE.md](REFERENCE.md) for node spec shape, generated-code model, and a safe debug loop.

## Grounding

- `docs/docs/agent/ARCHITECTURE.md` section 1.7.
- `docs/docs/agent/CODEMAP.md` entries for `src/project/graph/*`, `data/nodes/*`, and `src/build/nodeGraphBuilder.cpp`.
- `docs/docs/agent/AGENTIC_SURFACE.md` known limits for node-graph validation.

## Common Agent Mistakes

- Editing generated `src/p64/*.cpp` and losing the fix on the next build.
- Renaming node ids without a compatibility plan.
- Ignoring placeholder nodes after a spec disappears.
- Creating cycles in value resolution and assuming flow wiring alone prevents them.
