---
name: bf64-asset-import
description: Use when importing, validating, replacing, or inspecting BF64 project assets, sidecar `.conf` files, output paths, dry runs, and asset inventory.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: assets
  target_version: "BF64"
---

# BF64 Asset Import

Use this when moving a source asset into a BF64 project.

## Quick Start

```bash
./bf64 validate ./crate.ci4.png --texture-format CI4 --json
./bf64 import ./crate.ci4.png --project <project> --dest textures/crate.ci4.png --dry-run --json
./bf64 import ./crate.ci4.png --project <project> --dest textures/crate.ci4.png --record --json
./bf64 asset show assets/textures/crate.ci4.png --project <project> --json
./bf64 asset validate-all --project <project> --json
./bf64 asset validate-all --project <project> --include-excluded --json
./bf64 asset exclusion add 'reference/**' --project <project> --json
```

## Supported Imports

Current BF64 imports: `.png`, `.glb`, `.gltf`, `.wav`, `.mp3`, `.xm`, and `.ttf`.

The import command copies the asset under `assets/`, writes a `.conf` sidecar with a new UUID, removes stale generated output when overwriting, and records artifacts when `--record` is used.

## Workflow

1. Validate the source file with explicit role/format when possible.
2. Dry-run import to verify destination, sidecar, and issues.
3. Use `--force` only for an intentional overwrite.
4. Run `asset show` on the imported asset.
5. Run `asset validate-all` before build.
6. Use sidecar `exclude: true` for isolated files and project-level `asset exclusion` globs for draft/reference trees. Normal validation and builds omit both; `--include-excluded` performs a complete source audit.
7. Let the build pipeline generate `.sprite`, `.bci`, `.t3dm`, `.wav64`, `.xm64`, and font outputs.

## Grounding

- `docs/docs/agent/AGENTIC_SURFACE.md` import and asset inventory contract.
- `docs/docs/n64/asset-checklist.md`
- `docs/docs/n64/limits.json`
- `docs/docs/agent/CODEMAP.md` `src/build/*Builder.cpp` entries.

## Common Agent Mistakes

- Copying files into `assets/` without creating or validating sidecar `.conf`.
- Skipping `--dry-run` when destination paths are uncertain.
- Committing generated outputs instead of source assets unless the project explicitly requires them.
- Importing unsupported source formats and assuming the editor will convert them.
