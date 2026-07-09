---
name: bf64-qa-debugging
description: Use when validating, debugging, or proving BF64 behavior with CLI checks, builds, emulator runs, logs, screenshots, hardware tests, or regression evidence.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: qa
  target_version: "BF64"
---

# BF64 QA Debugging

Use this when the question is "does it actually work?"

## Quick Start

```bash
./bf64 project status --project <project> --json
./bf64 asset validate-all --project <project> --json
./bf64 build --project <project> --json
./bf64 build --execute --project <project> --pyrite64-binary ./pyrite64 --record --json
./bf64 run --project <project> --emulator ares --record --json
```

## Evidence Ladder

1. Static checks: JSON validity, `./bf64 validate`, `asset validate-all`, `scene validate`.
2. Build plan: dry-run `build` with artifact expectations.
3. Real build: `build --execute` with stdout/stderr tails and ROM artifact.
4. Emulator run: Ares first, gopher64 for fast iteration.
5. Runtime evidence: ISViewer/debug log, screenshots, visible behavior notes.
6. Hardware pass when release-readiness or timing-sensitive behavior matters.

## Debug Workflow

1. Reproduce with the smallest project/scene/asset set.
2. Capture command, exit code, JSON issues, logs, and artifact paths.
3. Fix source files, not generated outputs.
4. Re-run the same command to prove the issue changed.
5. Add or update automated validation when the bug is structurally detectable.

## Reference

- See [REFERENCE.md](REFERENCE.md) for evidence bundles, failure triage, and QA automation gaps.

## Grounding

- `docs/docs/agent/AGENTIC_SURFACE.md`
- `docs/docs/n64/emulation-and-hardware-testing.md`
- `docs/docs/n64/asset-checklist.md`
- `docs/docs/agent/ARCHITECTURE.md` build/run and runtime logging notes.

## Common Agent Mistakes

- Reporting success from a dry-run build.
- Using inaccurate emulators as acceptance evidence.
- Losing the failing command/log while iterating.
- Fixing generated files and then watching the build overwrite the fix.
