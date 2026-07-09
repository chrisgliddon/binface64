---
name: bf64-cpp-scripting
description: Use when writing BF64 runtime C++ scripts, user components, `P64_DATA` structs, lifecycle hooks, or code that compiles into the N64 ROM.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: scripting
  target_version: "BF64"
---

# BF64 C++ Scripting

Use this when code will run on the N64 runtime, not only in the host editor.

## Quick Start

```bash
./bf64 project status --project <project> --json
./bf64 build --project <project> --json
./bf64 build --execute --project <project> --pyrite64-binary ./pyrite64 --json
```

## Runtime Rules

- Game code is compiled by the N64 toolchain with the engine, generated `src/p64/*.cpp`, and user `src/user/*.cpp`.
- The real ROM build uses libdragon/tiny3d Makefiles, not `n64/CMakeLists.txt`.
- Runtime code uses `gnu++20`, `-fno-exceptions`, `-Os`, and strict warnings.
- Public runtime APIs live under `n64/engine/include/`.
- `P64_DATA(...)` structs are parsed by BF64's script builder; keep data fields simple and serializable.

## Workflow

1. Read the relevant runtime header under `n64/engine/include/` before writing a call.
2. Keep hot-path code allocation-light and deterministic; systems run on real hardware budgets.
3. Use BF64 scene/component APIs rather than editor-only types.
4. Build dry-run to inspect expected generated files, then execute a real ROM build.
5. Run in Ares/gopher64 and inspect debug output for runtime failures.

## Examples

- See [EXAMPLES.md](EXAMPLES.md) for `P64_DATA`, runtime UI drawing, and audio-handle patterns grounded in current example games.

## Grounding

- `docs/docs/agent/ARCHITECTURE.md` sections 2 and 4.
- `docs/docs/agent/CODEMAP.md` sections `n64/engine/include`, `src/build/scriptBuilder.cpp`, and runtime main loop.
- `docs/docs/n64/libdragon-tiny3d.md`.

## Common Agent Mistakes

- Including host editor headers in N64 runtime code.
- Using C++ exceptions or desktop assumptions in ROM code.
- Editing IDE dummy CMake files expecting a ROM build change.
- Forgetting generated `src/p64` code is build output, not source of truth.
