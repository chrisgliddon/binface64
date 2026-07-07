# Binface64 (BF64) — Phased Build Plan

**Repo:** https://github.com/chrisgliddon/binface64 (fork of HailToDodongo/pyrite64)
**Stack:** C++ editor, libdragon + tiny3d runtime, CMake, fast64/GLTF asset pipeline
**Goal:** Turn Pyrite64 into the first *agent-centric* N64 game engine — usable by LLMs via MCP, CLI, and an Extensions scripting system, with a `/skills` folder that encodes N64 hardware truth so agents ship real, working ROMs.

**The vision (thread this through everything):** The N64 was a very powerful machine undermined by expensive cartridge hardware and poor developer experience. BF64 imagines an alternate timeline where great new games keep shipping on legacy consoles with strong nostalgic attach rates — starting with the N64. The cartridge cost problem is gone (flash carts, emulation, small-batch manufacturing); BF64's job is to kill the DX problem.

---

## How this plan is organized

- Each phase is scoped to fit comfortably inside a **single <500K token context window session** (target ~250–400K working tokens including file reads, tool output, and generation). Phases that risk blowing the budget are split.
- Each phase produces **durable artifacts in the repo** (docs, skills, code) so the next session can cold-start by reading them — no reliance on conversation memory.
- Every phase ends with a **HANDOFF.md update** (`docs/agent/HANDOFF.md`): what was done, what's next, known issues. This is the session-to-session baton.
- Kickoff prompts are written to be pasted into a fresh Claude Code / agent session with the repo cloned.

**Phase order rationale:** Research first (Phases 0–2) because everything downstream — skills, MCP tool descriptions, CLI validation, CONTRIBUTING schemas — needs authoritative N64 constraints baked in. Skills next (3–4) because they're pure docs with huge leverage. Then machine interfaces (5–7), then community/contribution scaffolding (8), then dogfooding (9).

---

## Phase 0 — Codebase Reconnaissance & Architecture Map

**Session budget:** ~300K tokens (heavy file reading, light writing)
**Outputs:**
- `docs/agent/ARCHITECTURE.md` — editor architecture, runtime architecture, asset pipeline flow, node-graph scripting system, build system
- `docs/agent/CODEMAP.md` — annotated directory map: what lives where, entry points, key classes, where scenes/objects/components are serialized, project file formats
- `docs/agent/HANDOFF.md` — initialized
- `docs/agent/DIVERGENCE.md` — policy for tracking BF64 divergence from upstream Pyrite64 (how we stay mergeable vs. where we intentionally fork)

**Why first:** Pyrite64 has ~618 commits of existing design decisions. Agents can't extend what they can't see. This phase converts implicit knowledge in C++ into explicit docs every later session reads instead of re-crawling the tree.

**Kickoff prompt:**

```
You are working in the Binface64 repo (github.com/chrisgliddon/binface64), a fork of
Pyrite64 (an N64 game engine + editor built on libdragon and tiny3d). Our mission:
extend it into an agent-centric engine (MCP + CLI + Extensions + /skills).

This session is PHASE 0: Codebase Reconnaissance. Do NOT write feature code.

Tasks:
1. Crawl the repo: /src (editor, C++), /n64 (runtime), /tools, /scripts, /data,
   /vendored, /docs, CMakeLists.txt, CMakePresets.json, .gitmodules.
2. Produce docs/agent/ARCHITECTURE.md covering:
   - Editor architecture: UI framework, project model, scene representation,
     how the node-graph scripting works, how the editor invokes the toolchain.
   - Runtime architecture: scene management, object/component model, render loop
     (tiny3d), collision, audio, asset/memory management and cleanup.
   - Asset pipeline: GLTF/fast64 import path, texture conversion, how assets are
     packed into the ROM, intermediate file formats.
   - Build system: how a project becomes a .z64 ROM; toolchain install flow;
     what's Windows-specific vs cross-platform.
3. Produce docs/agent/CODEMAP.md: a directory-by-directory annotated map with
   entry points, key classes/files, and serialization formats (list every file
   format the editor reads/writes, with location of the parser/writer code).
4. Produce docs/agent/DIVERGENCE.md: a short policy doc for tracking our fork's
   divergence from upstream pyrite64 (naming: keep Pyrite64 credits intact per
   MIT license; BF64 changes live in clearly-marked areas where possible).
5. Create docs/agent/HANDOFF.md with: phase status table (Phases 0-9), what this
   session completed, open questions, and instructions for the next session.

Constraints:
- Cite file paths and line-ish locations in the docs so future agents can jump
  straight to code.
- Flag anything undocumented, surprising, or fragile in a "Gotchas" section.
- Where behavior is unclear from reading, say so explicitly — do not guess.
Commit with message "docs(agent): phase 0 architecture map".
```

---

## Phase 1 — N64 Hardware & Systems Research Compendium

**Session budget:** ~350K tokens (web research + synthesis)
**Outputs:**
- `docs/n64/hardware.md` — CPU (VR4300), RCP (RSP + RDP), RDRAM (4MB / 8MB Expansion Pak), TMEM (4KB), cart bus, DMA behavior, real-world bandwidth constraints
- `docs/n64/performance-budgets.md` — practical frame budgets: triangle counts, fill rate, RSP microcode limits, what tiny3d achieves vs. stock microcode
- `docs/n64/libdragon-tiny3d.md` — what libdragon and tiny3d actually provide, their constraints and idioms, versions vendored in BF64
- `docs/n64/display-and-video.md` — resolutions, framebuffer formats, VI filtering, NTSC/PAL, HDR+bloom and big-texture techniques Pyrite64 already supports
- `docs/n64/audio.md` — mixer channels, sample rates, memory cost of audio, formats libdragon supports
- `docs/n64/emulation-and-hardware-testing.md` — Ares (v147+), gopher64, flashcarts, why accuracy matters, test matrix

**Why:** This becomes the ground-truth layer that skills (Phase 3–4), MCP tool docs, and CLI validators all cite. Numbers must be sourced from libdragon/tiny3d docs and the homebrew community (N64brew wiki), not folklore.

**Kickoff prompt:**

```
You are in the Binface64 repo. Read docs/agent/HANDOFF.md and docs/agent/ARCHITECTURE.md
first for context. This session is PHASE 1: N64 Hardware Research Compendium.

Mission: produce authoritative, number-dense reference docs in docs/n64/ that all
future skills, MCP tools, and validators will cite. Audience: LLM agents building
games. Optimize for precision and retrievability, not prose.

Research sources (in priority order):
1. The vendored libdragon and tiny3d source/docs in this repo (ground truth for
   what BF64 can actually do).
2. libdragon docs (libdragon.dev), tiny3d README/docs (github.com/HailToDodongo/tiny3d).
3. N64brew wiki (n64brew.dev) for hardware specs: VR4300, RSP, RDP, RDRAM timing,
   TMEM, VI, AI, PI.
4. Pyrite64 docs (hailtododongo.github.io/pyrite64) and FAQ.

Write these files (each with a "Hard limits" table up top and "Practical budgets"
section with real-world numbers, citing sources inline as URLs):
- docs/n64/hardware.md
- docs/n64/performance-budgets.md   (tris/frame at 30fps vs 60fps with tiny3d,
  fill-rate limits, 1-cycle vs 2-cycle mode costs, RDRAM bandwidth contention)
- docs/n64/libdragon-tiny3d.md      (APIs BF64's runtime uses, version pins,
  idioms, known footguns)
- docs/n64/display-and-video.md
- docs/n64/audio.md
- docs/n64/emulation-and-hardware-testing.md

Rules:
- Distinguish HARD hardware limits (TMEM = 4KB, RDRAM = 4/8MB) from SOFT practical
  budgets (recommended tri counts), and label which is which.
- Where sources disagree, note the disagreement and pick the conservative number.
- Every doc ends with "Implications for BF64 agents" — 5-10 bullet rules of thumb.
Update docs/agent/HANDOFF.md. Commit: "docs(n64): phase 1 hardware compendium".
```

---

## Phase 2 — Asset Requirements & Limitations Research

**Session budget:** ~350K tokens
**Outputs:**
- `docs/n64/textures.md` — every texture format (RGBA16/32, CI4/CI8, IA4/8/16, I4/I8), TMEM fitting math, mipmaps, palettes, big-texture streaming technique
- `docs/n64/models-and-meshes.md` — vertex budgets, GLTF→fast64→tiny3d pipeline, material system, skinning/animation limits, what fast64 materials map to
- `docs/n64/audio-assets.md` — format conversion, sample-rate/memory tradeoff tables, music (sequenced vs streamed) guidance
- `docs/n64/rom-budgets.md` — cart sizes (4–64MB), compression, asset packing in BF64, how to budget a whole game
- `docs/n64/asset-checklist.md` — one-page pre-flight checklist an agent runs before importing any asset

**Why split from Phase 1:** Asset constraints are the #1 way an LLM will produce broken N64 content (a 1024×1024 PNG is normal everywhere except here). This deserves its own dense session, and it directly feeds the asset skills and the CLI's `validate` command.

**Kickoff prompt:**

```
You are in the Binface64 repo. Read docs/agent/HANDOFF.md, docs/agent/ARCHITECTURE.md,
and the docs/n64/ compendium from Phase 1. This session is PHASE 2: Asset
Requirements & Limitations.

Mission: document exactly what assets are valid for BF64/N64, in a form an agent
can use as a pre-flight validator. Ground everything in (a) the actual asset
pipeline code in this repo (find the texture converter, GLTF importer, and ROM
packer — CODEMAP.md tells you where), and (b) libdragon/tiny3d/fast64 docs.

Write:
- docs/n64/textures.md — all N64 texture formats with bits-per-texel, max
  dimensions that fit in 4KB TMEM per format (include the actual math and a
  lookup table), palette rules for CI formats, mipmap cost, and when to use
  Pyrite64's big-texture (256x256) streaming path.
- docs/n64/models-and-meshes.md — the GLTF (Blender + fast64) import path in
  this engine: supported material features, vertex/tri budgets per object and
  per scene, skinning & animation support and costs, UV/normal requirements,
  common Blender export mistakes.
- docs/n64/audio-assets.md — accepted input formats, conversion pipeline,
  memory/quality tradeoff tables (sample rate x mono/stereo x seconds = KB),
  music strategy guidance.
- docs/n64/rom-budgets.md — ROM size targets, what the packer does, compression,
  a worked example budget for a small 3D game (textures/models/audio/code).
- docs/n64/asset-checklist.md — a single-page checklist with PASS/FAIL rules an
  agent can apply to any asset before import. Make every rule mechanical and
  checkable (numbers, not vibes).

Rules: distinguish engine-enforced limits (cite the enforcing code path) from
hardware limits from best-practice budgets. Update HANDOFF.md.
Commit: "docs(n64): phase 2 asset requirements".
```

---

## Phase 3 — `/skills` Scaffold + Core Engine Skills

**Session budget:** ~300K tokens
**Outputs:**
- `/skills/README.md` — index, philosophy, versioning policy (pinned to BF64 + tiny3d + libdragon versions, mirroring bevy-skills' pin-to-version approach)
- `/skills/_TEMPLATE/SKILL.md` — canonical skill format
- Core skills, each a folder with `SKILL.md` (+ `examples/` where useful):
  - `bf64-project-setup` — create/open a project, toolchain install, build a ROM, run in Ares/gopher64
  - `bf64-scenes` — scene creation, object/component model, serialization format
  - `bf64-node-graph` — the visual scripting system: node types, wiring, patterns
  - `bf64-rendering` — tiny3d usage through BF64: materials, lighting, HDR/bloom, big textures
  - `bf64-collision` — collision setup and queries
  - `bf64-audio` — playing music/SFX, memory management
  - `n64-constraints` — a "read this first" skill distilling Phases 1–2 into agent rules

**Format reference:** Styled after `chrisgliddon/bevy-skills` and official PixiJS skills — one directory per skill, front-matter with name/description/version pins, task-oriented sections, correct-vs-wrong code pairs, and explicit "hardware constraint" callouts unique to N64.

**Kickoff prompt:**

```
You are in the Binface64 repo. Read docs/agent/HANDOFF.md, then ARCHITECTURE.md,
CODEMAP.md, and skim all of docs/n64/. This session is PHASE 3: /skills scaffold
and core engine skills.

Model the skills folder after github.com/chrisgliddon/bevy-skills and the official
PixiJS skills: one folder per skill containing SKILL.md with YAML front-matter
(name, description with explicit trigger phrases, version pins), task-oriented
sections, and minimal-but-runnable code examples. Fetch bevy-skills' README and
one or two of its SKILL.md files to match structure and tone.

Create:
1. /skills/README.md — index of all skills, the format spec, versioning policy
   (every skill pins BF64 commit/tag + tiny3d + libdragon versions), and guidance
   for agents on which skill to load for which task.
2. /skills/_TEMPLATE/SKILL.md — the canonical template. Must include a mandatory
   "N64 Constraints" section slot — this is what makes these different from
   desktop-engine skills.
3. Core skills (folder + SKILL.md each):
   - n64-constraints: distill docs/n64/ into the rules an agent MUST internalize
     (TMEM math, RDRAM budget, tri budgets, ROM budget). This is the "read first".
   - bf64-project-setup: new project, toolchain, build .z64, run in Ares/gopher64,
     verify output. Include the exact commands from the repo's build system.
   - bf64-scenes: scene/object/component model, the on-disk serialization format
     (document real fields from the code — cite file paths).
   - bf64-node-graph: node-graph scripting — enumerate actual node types from the
     source, show 3 worked patterns (trigger->action, timer, state toggle).
   - bf64-rendering: materials/fast64 mapping, lighting, HDR+bloom, big-texture
     mode — each with when-to-use and cost callouts.
   - bf64-collision and bf64-audio: same treatment.

Rules:
- Every code sample must reflect the REAL current APIs in this repo — verify
  against source before writing. Never invent API names.
- Every skill ends with "Common agent mistakes" (wrong vs right).
- Keep each SKILL.md under ~500 lines; link to docs/n64/ instead of duplicating.
Update HANDOFF.md. Commit: "feat(skills): phase 3 core skills".
```

---

## Phase 4 — Asset & Content Pipeline Skills

**Session budget:** ~300K tokens
**Outputs:** `/skills/` additions:
- `n64-textures` — format selection decision tree, TMEM fitting, palette workflows, conversion commands
- `n64-models` — Blender/fast64 → GLTF → BF64 workflow, budget-aware modeling rules, animation
- `n64-audio-assets` — asset prep and conversion
- `bf64-asset-import` — the engine's import UI/CLI path, global asset management, memory cleanup behavior
- `n64-game-design-budgets` — designing *within* the machine: scene scoping, streaming/scene-splitting patterns, a worked "small complete game" budget
- Update `/skills/README.md` index

**Kickoff prompt:**

```
You are in the Binface64 repo. Read docs/agent/HANDOFF.md, /skills/README.md and
/skills/_TEMPLATE/SKILL.md (follow that format exactly), and all of docs/n64/
from Phase 2. This session is PHASE 4: asset & content pipeline skills.

Create these skills (folder + SKILL.md each), grounded in the repo's actual asset
pipeline code and the docs/n64/ research:
- n64-textures: a decision tree ("what format for this texture?"), TMEM fitting
  tables per format, CI palette workflow, exact conversion tool invocations used
  by this engine, and the big-texture path. Include 5+ wrong-vs-right examples
  (e.g. "1024x1024 RGBA32 PNG" -> what to do instead).
- n64-models: Blender + fast64 authoring rules for BF64: poly budgets by object
  class (hero character / prop / environment chunk), material setup that maps
  cleanly to tiny3d, GLTF export settings, animation constraints, common import
  failures and their error messages.
- n64-audio-assets: input formats, conversion, the memory math from
  docs/n64/audio-assets.md turned into prescriptive rules.
- bf64-asset-import: how assets enter a BF64 project (editor and any scriptable
  path), the global asset manager and automatic memory cleanup semantics, how to
  verify an asset made it into the ROM.
- n64-game-design-budgets: scoping a game to the hardware — scene-splitting
  patterns, a fully worked budget for a small complete 3D game, and red flags
  that a design won't fit.

Update /skills/README.md index. Verify every command and API against the repo.
Update HANDOFF.md. Commit: "feat(skills): phase 4 asset pipeline skills".
```

---

## Phase 5 — BF64 CLI (Headless, Agent-First)

**Session budget:** ~400K tokens (this is real code)
**Outputs:**
- `cli/` — a `bf64` command-line tool (language chosen in-session based on what the repo supports best; likely C++ sharing editor code, or a thin tool wrapping existing scripts)
- Commands (v1): `bf64 new`, `bf64 build`, `bf64 run` (launch Ares/gopher64), `bf64 validate <asset>` (enforces `docs/n64/asset-checklist.md` mechanically), `bf64 import <asset>`, `bf64 scene ls/show` (read scene files), `bf64 doctor` (toolchain check)
- `--json` output mode on every command (agents parse this)
- `docs/cli.md` + `/skills/bf64-cli/SKILL.md`
- CI workflow that builds a sample project headlessly

**Design principles:** Every editor capability that matters for shipping should eventually be reachable headlessly; deterministic exit codes; machine-readable errors that *name the violated constraint and the fix* ("texture.png: 64KB exceeds TMEM 4KB as RGBA16; use CI4 at 64×64 or enable big-texture streaming").

**Kickoff prompt:**

```
You are in the Binface64 repo. Read docs/agent/HANDOFF.md, ARCHITECTURE.md,
CODEMAP.md, docs/n64/asset-checklist.md, and /skills/bf64-project-setup/SKILL.md.
This session is PHASE 5: build the bf64 CLI.

Goal: a headless, agent-first CLI so LLMs can drive the full loop —
create project -> import assets -> edit scenes (read-only for now) -> build ROM
-> run in emulator — without the GUI.

1. First, write cli/DESIGN.md: pick implementation language/approach based on
   what the repo makes easiest (reusing editor project/serialization code in C++
   vs wrapping scripts). Justify briefly, then proceed — don't stall on it.
2. Implement v1 commands:
   - bf64 doctor          (toolchain/emulator presence check, actionable fixes)
   - bf64 new <name>      (scaffold a project)
   - bf64 build           (project -> .z64, surface toolchain errors cleanly)
   - bf64 run [--emu ares|gopher64]
   - bf64 validate <path> (mechanically enforce docs/n64/asset-checklist.md:
     texture format/size/TMEM fit, model budgets, audio memory. Errors must name
     the violated constraint AND the fix.)
   - bf64 import <path>   (run the engine's asset import headlessly)
   - bf64 scene ls / bf64 scene show <scene> (read + pretty-print scene files)
3. Every command supports --json (stable schema, documented). Deterministic exit
   codes: 0 ok, 1 user/asset error, 2 environment error, 3 internal.
4. Write docs/cli.md and /skills/bf64-cli/SKILL.md (template format).
5. Add a GitHub Actions workflow that runs bf64 new + build on a sample project
   headlessly (or, if toolchain-in-CI is too heavy this session, doctor +
   validate against test fixtures — note the follow-up in HANDOFF.md).

Keep scope tight: read/build/validate this session; scene MUTATION lands with
Extensions in Phase 7. Update HANDOFF.md.
Commit in logical chunks, prefix "feat(cli):".
```

---

## Phase 6 — MCP Server

**Session budget:** ~400K tokens
**Outputs:**
- `mcp/` — a BF64 MCP server exposing the CLI's capabilities as tools, plus knowledge tools
- Tools (v1): `bf64_project_status`, `bf64_build`, `bf64_run`, `bf64_validate_asset`, `bf64_import_asset`, `bf64_list_scenes`, `bf64_read_scene`, `bf64_query_constraints` (structured lookups into docs/n64 — TMEM math, budget tables), `bf64_list_skills` / `bf64_read_skill`
- Tool descriptions written *for models*: constraints and units in the description, examples in the schema
- `docs/mcp.md`, `/skills/bf64-mcp/SKILL.md`, config snippets for Claude Code / Claude Desktop

**Kickoff prompt:**

```
You are in the Binface64 repo. Read docs/agent/HANDOFF.md, cli/DESIGN.md,
docs/cli.md, and /skills/README.md. This session is PHASE 6: the BF64 MCP server.

Build an MCP server in mcp/ that makes BF64 first-class for LLM agents. It should
wrap the bf64 CLI (shell out to it; do not duplicate logic) and add knowledge
tools over docs/n64 and /skills.

1. Read the MCP builder best practices (use the mcp-builder skill if available;
   otherwise modelcontextprotocol.io docs). Choose TypeScript or Python SDK —
   whichever gives the cleanest stdio server; justify in mcp/DESIGN.md.
2. Tools (v1), all returning structured content:
   - bf64_project_status, bf64_build, bf64_run
   - bf64_validate_asset, bf64_import_asset
   - bf64_list_scenes, bf64_read_scene
   - bf64_query_constraints: parameterized lookups — e.g.
     {question:"max_texture_size", format:"CI4"} -> {width:..., height:...,
     tmem_bytes:..., source:"docs/n64/textures.md"}. Back it with a small
     structured data file generated from docs/n64 tables (checked into repo).
   - bf64_list_skills / bf64_read_skill
3. Write tool descriptions FOR MODELS: put units, hard limits, and one worked
   example in each description. Error messages must be actionable and name the
   constraint violated.
4. docs/mcp.md: install + config for Claude Code and Claude Desktop (mcp.json
   snippets), tool reference, a worked agent transcript example.
5. /skills/bf64-mcp/SKILL.md in template format.
6. Basic tests: server boots, tools list, validate_asset round-trips on fixtures.

Update HANDOFF.md. Commit prefix "feat(mcp):".
```

---

## Phase 7 — Extensions System (Scripting the Engine/Editor)

**Session budget:** ~400K tokens (the hardest engineering phase; may split into 7a design / 7b implementation if the session runs hot)
**Outputs:**
- `docs/extensions/DESIGN.md` — extension model decided against the real codebase: likely a JS/TS extension host in the editor (the repo already has ~11% JavaScript) + manifest format, with hooks for: asset pipeline steps, scene mutation, custom node-graph nodes, editor commands, build steps
- `extensions/` — extension host + API + 2–3 reference extensions (e.g., a scene-mutation extension that finally gives the CLI/MCP **write** access to scenes; an asset post-processor; a custom node pack)
- `bf64 ext` CLI subcommands + MCP tools for running extension commands
- `/skills/bf64-extensions/SKILL.md`

**Why Extensions unlock agent write-access:** Rather than hand-coding scene mutation into the CLI, the extension API becomes *the* programmable surface — agents script the engine the same way human power-users do. CLI/MCP scene-write tools become thin callers of a first-party extension.

**Kickoff prompt:**

```
You are in the Binface64 repo. Read docs/agent/HANDOFF.md, ARCHITECTURE.md (esp.
editor architecture + serialization formats), cli/DESIGN.md, and mcp/DESIGN.md.
This session is PHASE 7: the Extensions system.

Goal: a scripting/extension API so both humans and agents can programmatically
drive the engine/editor — including SCENE MUTATION, which CLI/MCP currently lack.

1. Write docs/extensions/DESIGN.md first, grounded in the actual codebase:
   - Extension host choice (the editor already contains JavaScript — investigate
     what runtime/UI layer that is and whether it can host extensions; otherwise
     evaluate embedding QuickJS/duktape vs a headless out-of-process model that
     manipulates project files directly through a supported API).
   - Manifest format (extension.json: name, version, permissions, entry points).
   - Hook surface v1: (a) editor/headless commands, (b) scene read/write API over
     the real serialization format, (c) asset pipeline pre/post steps,
     (d) custom node-graph node registration, (e) build hooks.
   - Safety: extensions declare permissions; scene writes go through a validating
     API (schema-checked against the engine's format) — never raw file pokes.
2. Implement the host + API for hooks (a) and (b) at minimum; (c)-(e) as stubs
   with tracked TODOs if the session budget demands.
3. Ship reference extensions in extensions/:
   - scene-tools: add/remove/modify objects and components in a scene, headlessly.
   - asset-post: example asset pipeline step.
4. Wire through: `bf64 ext run <ext> <command> [--json]` and an MCP tool
   bf64_run_extension. Scene mutation via MCP now works through scene-tools.
5. /skills/bf64-extensions/SKILL.md: how to write an extension, full API
   reference, wrong-vs-right examples.

If scope forces a split, land DESIGN.md + scene read/write API + scene-tools
first — that's the agent-critical path. Update HANDOFF.md.
Commit prefix "feat(ext):".
```

---

## Phase 8 — CONTRIBUTING.md, Vision, and LLM-Friendly Repo Surface

**Session budget:** ~250K tokens
**Outputs:**
- `CONTRIBUTING.md` — vision-led, LLM-friendly, with XML-structured contribution schemas
- `README.md` rewrite for BF64 (keeping Pyrite64 credits/lineage prominent, per MIT + courtesy)
- `AGENTS.md` / `CLAUDE.md` — repo-root agent onboarding: read order (HANDOFF → ARCHITECTURE → skills index), conventions, build/test commands
- GitHub issue templates mirroring the XML schemas
- `docs/agent/HANDOFF.md` finalized into a living roadmap

**Kickoff prompt:**

```
You are in the Binface64 repo. Read docs/agent/HANDOFF.md and skim /skills/README.md,
docs/cli.md, docs/mcp.md, docs/extensions/DESIGN.md. This session is PHASE 8:
contribution & vision surface.

1. Write CONTRIBUTING.md with these sections:

   A. VISION (lead with it): The N64 was a very powerful machine undermined by
      expensive cartridge hardware and poor developer experience. BF64 imagines
      an alternate timeline where great NEW games ship on legacy consoles that
      already enjoy strong nostalgic attach rates — starting with the N64. The
      cart-cost problem is solved (flashcarts, emulators, small-batch carts);
      BF64 exists to solve the DX problem, for humans AND for AI agents. Write
      this in an inspiring but concrete voice (2-4 paragraphs, no marketing fluff).

   B. HOW AGENTS CONTRIBUTE: read order (AGENTS.md -> docs/agent/ -> /skills),
      build/test commands, commit conventions, divergence policy vs upstream
      Pyrite64 (link docs/agent/DIVERGENCE.md), and the rule that all N64
      technical claims must cite docs/n64/.

   C. XML CONTRIBUTION SCHEMAS — provide a fenced codeblock schema for each
      contribution type, designed so an LLM can fill it deterministically:

      <bug_report> with children: <title>, <environment> (os, bf64_version/commit,
      toolchain, emulator+version or hardware+flashcart), <steps_to_reproduce>
      (numbered <step> elements), <expected_result>, <actual_result>,
      <reproducibility percent="..."/> (with guidance: run it N times, report
      the %), <artifacts> (logs, ROM hash, scene file), <suspected_area> optional.

      <feature_improvement> with: <title>, <current_behavior>, <proposed_behavior>,
      <motivation>, <affected_surface> (editor|runtime|cli|mcp|extensions|skills|docs),
      <breaking_change true|false>, <alternatives_considered>.

      <new_feature> written as a user story: <title>, <user_story> ("As a ___,
      I want ___, so that ___"), <acceptance_criteria> (multiple <criterion>
      elements, each independently verifiable), <n64_constraints_impact>
      (must reference docs/n64/ where relevant), <affected_surface>, <out_of_scope>.

      Include one fully worked example of each schema.

   D. SKILL CONTRIBUTIONS: pointer to /skills/_TEMPLATE and quality bar
      (verified APIs, wrong-vs-right pairs, version pins).

2. Create matching GitHub issue templates in .github/ISSUE_TEMPLATE/ whose bodies
   are the XML schemas in codeblocks.
3. Write AGENTS.md (and symlink/duplicate as CLAUDE.md) at repo root: 1-page
   onboarding for agent sessions.
4. Rewrite README.md for Binface64: what BF64 adds (skills/CLI/MCP/extensions),
   the vision paragraph, quickstart for humans and for agents, and a prominent
   credits section for Pyrite64 (Max Bebök / HailToDodongo), libdragon, tiny3d,
   and fast64. Keep the MIT license notices intact.
5. Finalize docs/agent/HANDOFF.md into a living ROADMAP with Phase 9 queued.

Commit prefix "docs(contrib):".
```

---

## Phase 9 — Dogfood: Ship a Micro-Game Agentically, Then Harden

**Session budget:** ~400K tokens
**Outputs:**
- `examples/first-light/` (or similar) — a tiny but *complete* 3D game (one mechanic, 2–3 scenes, title screen, win state) built **only** through the agent surface: skills + CLI + MCP + extensions. No GUI allowed except to verify.
- A friction log → converted into fixes: skill corrections, better CLI/MCP error messages, missing extension hooks
- Updated skills with lessons learned; ROM tested in Ares + gopher64 (and hardware notes if available)
- Blog-style `docs/postmortem-first-light.md` — doubles as marketing for the vision

**Why this phase matters most:** The whole thesis is "an agent can ship an N64 game." This is the falsifiable test, and every failure becomes a repo improvement.

**Kickoff prompt:**

```
You are in the Binface64 repo. Read AGENTS.md and follow its read order. This
session is PHASE 9: dogfood the entire agent surface by building a micro-game.

Rules of engagement:
- You may ONLY use the documented agent surface: /skills, the bf64 CLI, the MCP
  tools, and the Extensions API. Do not open the GUI editor except to visually
  verify results. If something is impossible through the agent surface, that is
  a FINDING — log it, work around it if possible, continue.
- Keep a running FRICTION.md log: every incorrect skill claim, every unclear
  error, every missing capability, with severity (blocker/major/minor).

Build examples/first-light/: a complete micro-game —
- One core mechanic (e.g., collect N glowing orbs before a timer ends), 2-3 small
  scenes, a title screen, a win/lose state, at least one sound effect and one
  music track, all assets validated by `bf64 validate` before import.
- Must build to a .z64 and run correctly in Ares (v147+) and gopher64.
- Must respect the worked budget format from /skills/n64-game-design-budgets —
  write the budget FIRST, then build to it.

Then harden:
1. Triage FRICTION.md. Fix all blockers and majors this session: correct skills,
   improve CLI/MCP error messages, add missing extension commands. Minors become
   XML-formatted issues per CONTRIBUTING.md (file them in .github or as issue
   drafts in docs/agent/issues/).
2. Write docs/postmortem-first-light.md: what an agent shipping an N64 game
   actually looked like — honest about friction, concrete about fixes. This doc
   carries the project vision; make it worth reading.
3. Update HANDOFF.md/ROADMAP with the post-1.0 queue (e.g., scene mutation gaps,
   CI ROM builds, more skills, hardware test matrix).

Commit in logical chunks; the game itself under "feat(examples):".
```

---

## Session budget summary

| Phase | Focus | Est. tokens | Type |
|---|---|---|---|
| 0 | Codebase recon & architecture map | ~300K | Read-heavy |
| 1 | N64 hardware research compendium | ~350K | Research |
| 2 | Asset requirements & limitations | ~350K | Research |
| 3 | Skills scaffold + core engine skills | ~300K | Docs |
| 4 | Asset & content pipeline skills | ~300K | Docs |
| 5 | `bf64` CLI | ~400K | Code |
| 6 | MCP server | ~400K | Code |
| 7 | Extensions system | ~400K (splittable 7a/7b) | Code |
| 8 | CONTRIBUTING.md, vision, agent onboarding | ~250K | Docs |
| 9 | Dogfood micro-game + hardening | ~400K | Everything |

**Cross-session invariants:**
- `docs/agent/HANDOFF.md` is always updated before a session ends — it's the only memory.
- All N64 technical claims cite `docs/n64/`; all API claims are verified against source.
- Upstream Pyrite64 credits stay intact; divergence is tracked in `docs/agent/DIVERGENCE.md`.
- Every new capability ships with a matching skill in `/skills`.
