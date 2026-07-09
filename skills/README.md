# Binface64 Skills

AI agent skills for **BF64 / Binface64**, an agentic fork of Pyrite64 for Nintendo 64 game development. The skills are designed for headed and headless collaboration: an agent should be able to create projects, validate assets, write runtime code, build ROMs, reason about N64 budgets, and hand a human clear evidence instead of guesses.

The package follows the `bevy-skills` shape: one router skill, narrow sibling skills, installable plugin metadata, and deterministic linting.

## Install

| Agent | Skill directory | Setup |
|---|---|---|
| Claude Code | `~/.claude/skills/` | Copy or symlink `skills/`; plugin manifest lives in `.claude-plugin/`. |
| Cursor | `~/.cursor/skills/` | Copy or symlink `skills/`; plugin manifest lives in `.cursor-plugin/`. |
| OpenAI Codex | `~/.codex/skills/` | Copy or symlink `skills/`. |
| OpenCode | `~/.config/opencode/skills/` or `~/.claude/skills/` | Copy or symlink `skills/`. |

## Where To Start

1. [`bf64`](bf64/SKILL.md) - router, source pins, task-to-skill map.
2. [`n64-constraints`](n64-constraints/SKILL.md) - hardware, ROM, memory, asset, emulator constraints.
3. [`bf64-cli`](bf64-cli/SKILL.md) - headless commands for validation, import, build, run, status, and history.

## Skills

| Skill | Trigger |
|---|---|
| [`bf64`](bf64/SKILL.md) | Router for any BF64 / Binface64 / Pyrite64 N64 game development task. |
| [`n64-constraints`](n64-constraints/SKILL.md) | N64 hardware limits, budgets, ROM/RDRAM/TMEM/RSP/RDP, emulator accuracy. |
| [`bf64-cli`](bf64-cli/SKILL.md) | `./bf64` commands, JSON output, validation, import, build, run, operation history. |
| [`bf64-project-setup`](bf64-project-setup/SKILL.md) | Create/open projects, toolchain checks, build/run loop, starter project layout. |
| [`bf64-scenes`](bf64-scenes/SKILL.md) | Scene files, objects, components, prefabs, serialization, scene validation. |
| [`bf64-node-graph`](bf64-node-graph/SKILL.md) | Visual scripting, node graph JSON, JS node specs, generated C++ coroutine code. |
| [`bf64-cpp-scripting`](bf64-cpp-scripting/SKILL.md) | Runtime C++ scripts, `P64_DATA`, component APIs, ROM build constraints. |
| [`bf64-rendering`](bf64-rendering/SKILL.md) | tiny3d/BF64 rendering, materials, lighting, draw layers, HDR/bloom, BigTex. |
| [`bf64-collision`](bf64-collision/SKILL.md) | Collision components, rigid bodies, character body, raycasts, contact debugging. |
| [`bf64-asset-import`](bf64-asset-import/SKILL.md) | Importing and validating project assets through the headless BF64 CLI. |
| [`n64-models`](n64-models/SKILL.md) | 3D model budgets, glTF/Fast64/tiny3d pipeline, animation and skinning limits. |
| [`n64-textures`](n64-textures/SKILL.md) | Texture formats, CI palettes, TMEM, sprite conversion, BigTex constraints. |
| [`n64-2d-ui-text`](n64-2d-ui-text/SKILL.md) | Fonts, HUDs, sprites, text readability, 2D UI art under N64 limits. |
| [`n64-audio-assets`](n64-audio-assets/SKILL.md) | WAV64/XM64, SFX, music, sample rates, channel budgets, conversion checks. |
| [`n64-concept-art`](n64-concept-art/SKILL.md) | N64-style concept prompts, hero poses, turnarounds, texture reference sheets. |
| [`n64-game-design-budgets`](n64-game-design-budgets/SKILL.md) | Translate design ideas into feasible actor, memory, ROM, render, and audio budgets. |
| [`bf64-qa-debugging`](bf64-qa-debugging/SKILL.md) | Validate/build/run/debug loops, emulator choices, logs, screenshots, hardware matrix. |

## Version Policy

These skills are pinned to the current BF64 agentic surface and the reviewed N64 reference docs:

- BF64 CLI surface: `tools/bf64.py`, `CLI_VERSION = "0.9.0"`
- N64 limits schema: `docs/docs/n64/limits.json`, `schema_version = 1`
- tiny3d source pin: `bdcd946`
- libdragon source pin: `b1011fe31`

When BF64 changes CLI contracts, asset validators, engine APIs, or source pins, update the router skill, impacted sibling skills, and this README in the same change.

## Editing

Run:

```bash
python3 scripts/lint-skills.py
python3 scripts/check-skills-package.py
```

Rules:

1. Every skill directory is `skills/<name>/SKILL.md`.
2. Frontmatter `name` equals the directory name.
3. Descriptions start with `Use when` and contain `BF64`.
4. Every skill has `## Common Agent Mistakes`.
5. Hardware and asset facts point back to `docs/docs/n64/*` or `docs/docs/n64/limits.json`.
