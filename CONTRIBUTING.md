# Contributing to Binface64

Thanks for wanting to contribute to Binface64 (BF64). This project exists because we believe the N64 was underserved by great third-party games and we'd like to see more new, great games made for the system — and because so much development is now agent-centric, we see an agent-first fork of an already-capable engine as the best foot forward.

**Contributions from humans driving LLMs and agents are explicitly welcome here.** If you pair with an AI assistant to write code, validate assets, build ROMs, or debug — great. We do the same. The guidance below applies whether you're solo or paired.

## Before you start

Please read these three files first:

1. [`README.md`](README.md) — what BF64 is and what it adds over upstream Pyrite64.
2. [`docs/docs/agent/DIVERGENCE.md`](docs/docs/agent/DIVERGENCE.md) — the fork strategy. In particular, §3 distinguishes the **agent-only layer** (diverge freely) from the **shared core** (stay rebaseable against upstream). Every change to the shared core needs a row in §4's living table.
3. [`docs/docs/agent/AGENTIC_SURFACE.md`](docs/docs/agent/AGENTIC_SURFACE.md) — the machine-facing contract the `./bf64` CLI, validators, and audit trail implement.

If you're pairing with an LLM, also read [`skills/README.md`](skills/README.md) and install the `skills/` package into your agent. The [`bf64`](skills/bf64/SKILL.md) router is the entry point.

## Setup

### Build the editor

```sh
cmake --preset linux-release      # or: windows-gcc-release / macos-release
cmake --build --preset linux-release
```

The built editor binary lands in the repo root as `pyrite64` (or `pyrite64.exe` on Windows).

### Run the tests

```sh
python3 -m pytest tests/
```

The `tests/` directory covers the `./bf64` CLI contract, the editor CLI, multiplayer, native audio, chunk meshes, save data, UI layout, and N64 integration. If you're adding or changing CLI behavior, the matching test file is the source of truth for the JSON contract.

### Install the skills (optional, but recommended)

Copy or symlink `skills/` into your agent's skills directory. See [`skills/README.md`](skills/README.md) for per-agent setup (Claude Code, Cursor, OpenAI Codex, OpenCode).

## Working with LLMs and agents

BF64 is built to be driven by humans *with* agents, not by agents alone. A few rules keep that pairing productive:

1. **Start from structured state, not prose.** Before proposing changes, run `./bf64 project status --project <project> --json`. It combines project config, scene validation, asset inventory, toolchain checks, and suggested next actions. Don't guess — query.
2. **Use the supported mutation surfaces.** Don't raw-edit scene JSON, prefab JSON, or node-graph JSON. Use `./bf64 scene ...`, `./bf64 prefab ...`, and `./bf64 node-graph ...`. These validate before commit, write atomically, and produce stable JSON.
3. **Leave an audit trail.** Pass `--record` to commands that support it. The resulting `.bf64/operations.jsonl` entries let the next human or agent reconstruct what happened.
4. **Treat `docs/docs/n64/limits.json` as the constraint source.** If an agent's advice disagrees with `limits.json`, `limits.json` wins. If `limits.json` is wrong, fix it in the same change as the validator that reads it.
5. **Report evidence, not vibes.** "It works" isn't a result. A passing `./bf64 validate`, a green `./bf64 build`, a captured emulator log, or a screenshot is.

## Where your change belongs

From [`DIVERGENCE.md`](docs/docs/agent/DIVERGENCE.md) §3:

### Agent-only layer — diverge freely

These directories are upstream-absent. Move fast, break things, no upstream obligation:

- `skills/` — the agent constraints library
- `tools/bf64.py`, `bf64` — the headless agent-first CLI
- `docs/docs/agent/` — architecture, codemap, handoff, divergence, agentic surface
- `docs/docs/n64/` — the N64 hardware/asset compendium and `limits.json`
- `docs/docs/project/` — BF64 planning docs
- `.claude-plugin/`, `.cursor-plugin/` — plugin manifests
- `.bf64/` — local operation history (gitignored)

### Shared core — stay rebaseable

These are upstream-owned. Modify as little as possible, and when you must, isolate the change:

- `src/` — editor and runtime C++
- `n64/engine/include/` — public engine API headers
- `CMakeLists.txt`, `CMakePresets.json` — build system
- `vendored/` — git submodules (libdragon, tiny3d, SDL, imgui, etc.); we pin versions, upstream bumps them
- `docs/conf.py`, `docs/Doxyfile`, `docs/_apigen.py`, `docs/Makefile`, `docs/build_and_serve.sh` — the Sphinx toolchain
- `docs/docs/manual/`, `docs/docs/dev/`, `docs/docs/version/`, `docs/docs/faq.md` — existing user-facing docs
- `data/`, `packaging/`, `scripts/`, `.github/` — ancillary

**Rule:** a change to the shared core must be justifiable as either (a) a bug fix or small standalone improvement that could become an upstream PR, or (b) a strictly additive, isolated hook (e.g., a new `#ifdef BF64_AGENT`-guarded extension point) that won't conflict with upstream's direction. If you can't satisfy (a) or (b), stop and propose an alternative in the agent-only layer instead.

See [`DIVERGENCE.md`](docs/docs/agent/DIVERGENCE.md) §5 for the full rebase hygiene rules (additive edits, `#ifdef BF64_AGENT` guards, no unrelated reformatting, pinned submodules, conventional-commits style on shared-core files).

## Issues

We use three issue types. Please pick the one that matches what you're reporting. Search existing issues and PRs before opening a new one.

### Bug

Something BF64 does is wrong, crashes, or behaves incorrectly. Use the **Bug report** template. It asks for:

- **Expected Result** — what you thought would happen.
- **Actual Result** — what actually happened.
- **Steps to Reproduce** — the smallest sequence that triggers it.
- **Reproducibility %** — how often it happens (e.g., 100%, ~50%, once). If it's intermittent, say so.
- **Platform(s) Tested On** — OS, BF64/Pyrite64 version, emulator (Ares, gopher64, real hardware), and any relevant toolchain details.

If you have screenshots, emulator logs, or a `.bf64/operations.jsonl` excerpt, attach them.

### Improvement

A change to something that already exists — making it faster, clearer, more ergonomic, or more correct without adding a net-new capability. Use the **Improvement** template. It takes the form of a **user story** with **acceptance criteria**:

> **User Story:** As a `<kind of contributor/user>`, I want `<change>` so that `<benefit>`.
>
> **Acceptance Criteria:**
> - [ ] A testable, observable condition.
> - [ ] Another testable condition.
> - [ ] ...

Acceptance criteria should be written so that a human (or agent) can verify each one by running a command, inspecting an output, or performing a check — not by subjective judgment.

### New Feature

A net-new capability that doesn't exist today. Use the **New Feature** template. It also takes the form of a **user story** with **acceptance criteria**, scoped for the new surface rather than a change to an existing one.

> **User Story:** As a `<kind of contributor/user>`, I want `<new capability>` so that `<benefit>`.
>
> **Acceptance Criteria:**
> - [ ] A testable, observable condition.
> - [ ] Another testable condition.
> - [ ] ...

If the feature touches the shared core, note that in the issue — it'll need a [`DIVERGENCE.md`](docs/docs/agent/DIVERGENCE.md) §4 row before the PR merges.

## Pull requests

PRs are welcome. A few expectations:

- **Small and focused.** One PR per change. If you're planning something that isn't a small change, please talk about it first — open an issue or a draft PR, or raise it in the [N64Brew Discord](https://discord.gg/WqFgNWf). This mirrors upstream Pyrite64's PR template posture: large features have a good chance of not being merged if they land without pre-discussion.
- **Shared-core changes need a `DIVERGENCE.md` §4 row.** Add it in the same PR, at the top of the living table, with the correct classification (`mergeable upstream`, `BF64-only`, or `conditional`).
- **Commit messages** on shared-core files use upstream's conventional-commits style (`feat:`, `fix:`, `docs:`, `chg:`). Agent-only-layer files may use a `docs(agent):` / `feat(mcp):` / `feat(cli):` prefix.
- **Tests.** If you change CLI behavior, validator output, or a JSON contract, update the matching `tests/` file in the same PR. Run `python3 -m pytest tests/` before pushing.
- **Lint the skills.** If you touch `skills/`, run `python3 scripts/lint-skills.py` and `python3 scripts/check-skills-package.py` before pushing.
- **Don't reorder unrelated upstream code** in shared-core files. Reformat noise is the #1 cause of painful rebases against a fast-moving upstream.

## Contributing back upstream

We do not strategically upstream the agent layer. We do watch for incidental wins — when BF64 work surfaces an upstream bug or a small, human-useful, standalone feature that matches upstream's visible roadmap, the fix is extracted as a standalone PR, pre-discussed on Discord per the PR template, and submitted upstream. See [`DIVERGENCE.md`](docs/docs/agent/DIVERGENCE.md) §3.3 for the full policy.

## Questions

If anything here is unclear, the best places to ask are:

- A GitHub issue (use the most relevant of the three templates).
- The [N64Brew Discord](https://discord.gg/WqFgNWf) for N64-homebrew questions in general.

Thanks for helping make the N64 the system it should have been.