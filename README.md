# Binface64

<p align="center">
<img src="./data/img/titleLogo.png" width="400">
</p>

<p align="center">
An agentic fork of <a href="https://github.com/HailToDodongo/pyrite64">Pyrite64</a> — an N64 game-engine and editor using <a href="https://github.com/DragonMinded/libdragon">Libdragon</a> and <a href="https://github.com/HailToDodongo/tiny3d">tiny3d</a>.
</p>

> Note: This project does NOT use any proprietary N64 SDKs or libraries.

## Why Binface64

The Nintendo 64 was, in our view, a letdown — underserved by great third-party games and left behind far too early by the industry. We think the system deserved more, and we'd like to see more *new, great* games made for it.

Binface64 exists because so much software development is now agent-centric. LLM-driven workflows can carry the tedious, mechanical parts of N64 homebrew — toolchain setup, asset validation, constraint checking, build/run loops, audit trails — and leave humans free to make the creative and design calls. We see an agent-first fork of an already-capable engine as the best foot forward toward a steady stream of new N64 titles.

## What Binface64 adds

Binface64 (BF64) inherits the Pyrite64 editor and runtime unchanged in spirit and adds an **agent surface** on top of it — a machine-facing layer that humans driving LLMs/agents can use without scraping prose or inferring GUI behavior:

- **`./bf64` headless CLI** (`tools/bf64.py`) — project creation, asset import/validation, scene/prefab/node-graph mutation, build/run/profile, toolchain setup, and a local operation history. Every command speaks stable JSON with rule ids, fixes, and source citations.
- **`skills/` library** — a router plus narrow sibling skills covering N64 constraints, the CLI, scenes, rendering, collision, asset import, models, textures, audio, UI, concept art, game-design budgets, and QA. Installable into Claude Code, Cursor, OpenAI Codex, and OpenCode. See [`skills/README.md`](skills/README.md).
- **`docs/docs/n64/` constraints compendium** — human-readable N64 hardware/asset docs backed by `limits.json`, the machine-readable source for validators and future MCP tools.
- **`docs/docs/agent/`** — the agentic surface contract, architecture, codemap, handoff, and the upstream relationship & divergence policy.
- **`.bf64/operations.jsonl`** — a local, gitignored audit trail written by commands that support `--record`, so later humans and agents can reconstruct what happened.
- **Plugin manifests** for Claude Code (`.claude-plugin/`) and Cursor (`.cursor-plugin/`).

## What Binface64 inherits

The editor, the runtime engine, the libdragon + tiny3d pipeline, and the "no proprietary N64 SDKs" stance all come from upstream Pyrite64 by Max Bebök (HailToDodongo). We stay rebaseable against upstream's shared core and contribute incidental bug fixes back when they're standalone. The full fork strategy — what we diverge on, what we keep mergeable, and what we upstream — is recorded in [`docs/docs/agent/DIVERGENCE.md`](docs/docs/agent/DIVERGENCE.md).

> [!WARNING]
> This project is still in early development, so features are going to be missing.<br>
> Documentation is also still a work in progress, and breaking API changes are to be expected.

## Quick start

### Build the editor

Binface64 uses CMake presets. From the repo root:

```sh
cmake --preset linux-release      # or: windows-gcc-release / macos-release
cmake --build --preset linux-release
```

The built editor binary lands in the repo root as `pyrite64` (or `pyrite64.exe` on Windows). The project focuses on real hardware, so accurate emulation is required to run/test games on PC — [Ares (v147 or newer)](https://ares-emu.net/) and [gopher64](https://github.com/gopher64/gopher64) are accurate enough.

### Use the headless CLI

```sh
./bf64 doctor --json                       # check your local agent/tooling environment
./bf64 constraints list --json            # list N64/BF64 constraint topics
./bf64 new ./projects/agent_game --name "Agent Game" --json
./bf64 project status --project ./projects/agent_game --json
./bf64 build --project ./projects/agent_game --json
./bf64 run --build --project ./projects/agent_game --json
```

Every command accepts `--json` and most accept `--record` to append to `.bf64/operations.jsonl`. See [`docs/docs/agent/AGENTIC_SURFACE.md`](docs/docs/agent/AGENTIC_SURFACE.md) for the full contract.

### Install the skills

Copy or symlink `skills/` into your agent's skills directory. See [`skills/README.md`](skills/README.md) for per-agent setup. Start with the [`bf64`](skills/bf64/SKILL.md) router and [`n64-constraints`](skills/n64-constraints/SKILL.md).

## Documentation

- **Hosted docs:** https://hailtododongo.github.io/pyrite64/ (upstream; BF64-only sections are served from the same Sphinx tree)
- **Agentic surface:** [`docs/docs/agent/AGENTIC_SURFACE.md`](docs/docs/agent/AGENTIC_SURFACE.md)
- **Fork strategy:** [`docs/docs/agent/DIVERGENCE.md`](docs/docs/agent/DIVERGENCE.md)
- **N64 constraints:** [`docs/docs/n64/`](docs/docs/n64/) and [`docs/docs/n64/limits.json`](docs/docs/n64/limits.json)
- **Contributing:** [`CONTRIBUTING.md`](CONTRIBUTING.md)

The source for the docs lives in this repo under `/docs`.

## Links

For anything N64 homebrew related, checkout the N64Brew discord: https://discord.gg/WqFgNWf

## Acknowledgments

Binface64 would not be possible without the work of many people. We're grateful to every project below, and to everyone building for the N64 in 2026.

**Upstream engine — Pyrite64** © 2025-2026 Max Bebök (HailToDodongo): the editor, runtime, and the libdragon/tiny3d game pipeline BF64 is built on. Please consider crediting Pyrite64 with a logo and/or name in your credits and/or boot logo sequence.

**N64 toolchain & rendering:**
- [libdragon](https://github.com/DragonMinded/libdragon) — DragonMinded's open N64 SDK
- [tiny3d](https://github.com/HailToDodongo/tiny3d) — HailToDodongo's 3D graphics library for the N64

**Editor dependencies:**
- [SDL3](https://github.com/libsdl-org/SDL), [SDL_image](https://github.com/libsdl-org/SDL_image), and [SDL_shadercross](https://github.com/libsdl-org/SDL_shadercross) — libsdl-org
- [Dear ImGui](https://github.com/ocornut/imgui) — ocornut
- [ImGuizmo](https://github.com/CedricGuillemet/ImGuizmo) — CedricGuillemet
- [ImNodeFlow](https://github.com/CedricGuillemet/ImGuizmo) — node-graph editor for ImGui
- [glm](https://github.com/g-truc/glm) — g-truc's OpenGL mathematics
- [quickjs-ng](https://github.com/quickjs-ng/quickjs) — the embedded JavaScript engine for node-graph scripts
- [tiny-regex-c](https://github.com/kokke/tiny-regex-c) — kokke's small regex engine
- [SHA256](https://github.com/System-Glitch/SHA256) — System-Glitch's C++ SHA-256

**Asset authoring:**
- [fast64](https://github.com/Fast-64/fast64) — Fast-64's Blender addon, the source of BF64's Fast64 material support
- [Blender](https://www.blender.org/) — for 3D model authoring and GLTF export

**Accurate emulators (required for PC testing):**
- [Ares](https://ares-emu.net/) — accurate N64 emulation (v147 or newer)
- [gopher64](https://github.com/gopher64/gopher64) — fast, accurate N64 emulator

**Community:**
- [N64Brew Discord](https://discord.gg/WqFgNWf) — the home of modern N64 homebrew

## Credits & License

© 2025-2026 Max Bebök (HailToDodongo) — Pyrite64, the upstream engine and editor.<br>
© 2025-2026 Chris Gliddon — Binface64, the agentic surface and everything BF64-only.

Binface64 is licensed under the MIT License, see the [LICENSE](LICENSE) file for more information.<br>
Licenses for external libraries used in the editor can be found in their respective directory under `/vendored`.

Binface64 does NOT force any restrictions or licenses on games made with it.<br>
Binface64 does NOT claim any copyright or force licenses for assets / source-code generated by the editor or the BF64 CLI.

While not required, please consider crediting Binface64 (and Pyrite64) with a logo and/or name in your credits and/or boot logo sequence.