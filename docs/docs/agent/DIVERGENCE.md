# Upstream Relationship & Divergence Policy

**Fork:** Binface64 (BF64) ← `HailToDodongo/pyrite64`
**Maintained by:** Chris Gliddon
**Last reviewed:** 2026-07-06
**Review cadence:** Each BF64 phase boundary, or whenever upstream cuts a tagged release, whichever comes first.

---

## 1. Purpose

This document is the single source of truth for *how Binface64 relates to upstream Pyrite64*. It records:

1. What we learned about upstream's posture toward AI-assisted contributions (and the absence of any stated posture).
2. The three-part fork strategy BF64 adopts as a result.
3. A living classification of every BF64 change as **mergeable upstream**, **BF64-only**, or **conditional** — so future agent sessions don't have to re-derive the policy each time.
4. The mechanical rebase hygiene rules that keep the mergeable subset actually mergeable.

Every BF64 contributor (human or agent) is expected to read this before touching shared-core files. Agents especially: this is the file that tells you *whether the change you're about to make belongs in the fork at all, or should be extracted as an upstream PR instead*.

---

## 2. What we know about upstream's posture

As of Pyrite64 v0.7.0 (July 2026), based on a review of the upstream repo, its issue tracker (21 open / 12 sampled closed), PR history (144 closed), README, PR template, issue templates, FAQ, changelog, and full source tree:

### 2.1 No stated position on AI / agents

- **Zero mentions** of "AI", "LLM", "agent", "MCP", "Copilot", or "machine learning" anywhere in upstream's own artifacts (README, PR template, both issue templates, FAQ, changelog, breaking-changes, C++ source, docs). The maintainer has neither invited nor prohibited AI-assisted contributions.
- The only "agent/MCP/LLM" hits in our local grep are inside BF64's own `docs/docs/project/` files — i.e., us, not them.
- No `CONTRIBUTING.md`, no `CODE_OF_CONDUCT`, no AI-usage policy file exists in the upstream tree.

### 2.2 Governance signals (all point to a single cautious maintainer)

- **Issue creation is restricted.** Outsiders cannot open issues; only `HailToDodongo` does. The `New issue` button on the tracker reads *"Issue creation is restricted in this repository."*
- **No Discussions tab** (the URL 404s). All off-tracker communication is funneled to the N64Brew Discord (`https://discord.gg/WqFgNWf`).
- **The PR template warns large features will likely be rejected** and asks contributors to pre-discuss in Discord or open a draft first. Verbatim:
  > "Submitting new features or larger changes have a good chance of not being merged and/or resulting in conflicts. If you plan on working on something that isn't a small change, please talk about it first in the discord / create an issue or draft."
- **Ownership is concentrated.** Every architectural PR in the recent history (node-graph rewrite #256, character body #247, multiple viewports #264, editor themes #261, prefabs #268, ROM metadata editor #259) is authored by `HailToDodongo`. Outside contributors land focused slices: viewport lock mode, scene-graph search filter, swept-sphere function, drag-and-drop script components, typo fixes. The maintainer reserves the engine's shape to himself.
- **Project phase is explicitly early.** README warning: *"still in early development… features are going to be missing… breaking API changes are to be expected."* v0.7.0 alone reworked the material system and collision/physics. This is a fast-moving target, not a stable platform.

### 2.3 Legal posture

- **MIT licensed.** No clause prohibits AI-generated contributions; no "AI training data" carve-out; no extra restrictions on games built with the engine. Legally, an agent-driven fork is unambiguous.
- **The maintainer's silent non-stance is a soft opening, not a wall.** Nothing blocks AI-assisted PRs; external contributions are welcomed when small, focused, and pre-discussed. The block is on *architectural surprise*, not on *AI as such*.

---

## 3. Fork strategy

BF64 adopts a three-part posture toward upstream. Every later section of this document is operational guidance for one of these three parts.

### 3.1 Diverge freely on the agent surface

The following BF64-only layer lives in directories upstream does not have and will not touch. Here we move fast, break things, and feel no obligation to keep upstream mergeable:

- `/skills/` — the agent constraints library (Phases 3–4)
- `mcp/` — the BF64 MCP server (Phase 6)
- `cli/` — the `bf64` headless agent-first CLI (Phase 5), *except* thin shims that call existing engine code
- `extensions/` — the extension host + reference extensions (Phase 7)
- `docs/docs/agent/` — this directory: ARCHITECTURE, CODEMAP, HANDOFF, DIVERGENCE, and per-issue notes
- `docs/docs/n64/` — the N64 hardware/asset compendium (Phases 1–2)
- `docs/docs/project/` — BF64 planning docs (gap analysis, phased plan)
- `AGENTS.md` / `CLAUDE.md` — repo-root agent onboarding (Phase 8)
- `examples/` — agent-built micro-game(s) (Phase 9)

These are the **raison d'être** of BF64. Upstream will never adopt them; that's fine and by design.

### 3.2 Stay rebaseable on the shared core

The following are upstream-owned surfaces. We modify them as little as possible, and when we must, we isolate the change so periodic `git merge upstream/main` stays tractable:

- `src/` — editor and runtime C++ (the bulk of the engine)
- `n64/engine/include/` — public engine API headers (the surface the C++ API docs are generated from)
- `CMakeLists.txt`, `CMakePresets.json` — build system
- `vendored/` — git submodules (libdragon, tiny3d, SDL, imgui, etc.); we pin versions, upstream bumps them
- `docs/conf.py`, `docs/Doxyfile`, `docs/_apigen.py`, `docs/Makefile`, `docs/build_and_serve.sh` — the Sphinx toolchain (shared with upstream; see §6 for the BF64 docs-tree divergence)
- `docs/docs/manual/`, `docs/docs/dev/`, `docs/docs/version/`, `docs/docs/faq` — existing user-facing docs
- `data/`, `packaging/`, `scripts/`, `tools/`, `.github/` — ancillary

**Rule:** a change to any of the above must be justifiable as either (a) a bug fix or small standalone improvement that could become an upstream PR, or (b) a strictly additive, isolated hook (e.g., a new `#ifdef BF64_AGENT`-guarded extension point) that won't conflict with upstream's direction. If you can't satisfy (a) or (b), stop and propose an alternative to the agent-surface layer instead.

### 3.3 Contribute back opportunistically, not strategically

We do not attempt to upstream the agent layer. We do watch for incidental wins:

- **When BF64 work surfaces an upstream bug** (e.g., a crash found during Phase 0 recon, a build break on a platform upstream claims to support), the fix is extracted as a standalone PR, pre-discussed on Discord per the PR template, and submitted upstream. The BF64 commit message credits upstream if the fix is later merged either direction.
- **When BF64 adds a small, human-useful, standalone feature** that matches upstream's visible roadmap (editor polish, a new CLI flag the maintainer might want, a docs improvement), the same path applies.
- **We never upstream anything agent-architectural** (MCP, skills, extension host, agent CLI) unless the maintainer explicitly asks. The silent non-stance in §2.1 means we don't presume alignment.

---

## 4. Change classification (living table)

Every BF64 change to the shared core (§3.2) gets a row here before the PR is merged into BF64. Agent-only-layer changes (§3.1) don't need rows — they're assumed BF64-only. New rows go at the top.

| Date | Change | Files | Classification | Upstream PR? | Notes |
|---|---|---|---|---|---|
| 2026-07-18 | README rewrite + `Readme.md` → `README.md` rename, `LICENSE` second copyright line, `CONTRIBUTING.md`, three issue templates, PR template update | `Readme.md`→`README.md`, `LICENSE`, `CONTRIBUTING.md` (new), `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md`, `docs/docs/agent/DIVERGENCE.md` (this row + §7 reference fix) | BF64-only / conditional | No | README rewrite keeps upstream's "© 2025-2026 - Max Bebök (HailToDodongo)" line and the "does NOT use any proprietary N64 SDKs" notice verbatim per §7; BF64 credits added below. `LICENSE` adds a second copyright line (additive). `CONTRIBUTING.md` and the issue/PR templates are new BF64-only files. The `Readme.md`→`README.md` rename is a shared-core filename change; if upstream ever renames too, resolve in favor of upstream's casing. |
| 2026-07-12 | Complete BF64 shippability tranche (UI flow, typed/XM-safe audio and pitch, cartridge saves, profiling, procedural chunks) | `n64/engine/*`, UI/audio editor builders, `tools/bf64.py` | BF64-only / conditional | No | Additive runtime APIs and isolated editor fields; candidate bug fixes can be split out later. FlashRAM driver is prefixed to avoid colliding when libdragon PR #925 lands. |
| 2026-07-12 | Normalize incomplete asset sidecars and prune excluded outputs | `tools/bf64.py`, `src/build/projectBuilder.cpp` | mergeable upstream | Not opened | Standalone correctness fixes; stale T3DM stream cleanup is narrowly ownership-scoped. |
| 2026-07-12 | Linux editor/native/MIPS regression gates | `.github/workflows/editor.yml`, `tests/` | BF64-only | No | Exercises the shared editor CLI against BF64 contracts without changing upstream release behavior. |
| 2026-07-06 | Add BF64 project section to Sphinx docs | `docs/docs/project.rst`, `docs/docs/project/*.md`, `docs/index.rst` (+1 line) | BF64-only (additive, upstream has no equivalent section) | No | Lives in a section upstream doesn't have; the `index.rst` toctree line is the only shared-file edit and is strictly additive |
| 2026-07-06 | Add this DIVERGENCE.md + `agent/` section | `docs/docs/agent/DIVERGENCE.md`, `docs/docs/agent.rst`, `docs/index.rst` (+1 line) | BF64-only (additive) | No | Same pattern as the project section |

**Classification values:**
- **mergeable upstream** — small, standalone, matches upstream's roadmap. Open a Discord thread → draft PR → submit. Add a row here tracking the upstream PR number.
- **BF64-only** — lives in an upstream-absent directory, or is additive and isolated. No upstream obligation.
- **conditional** — could be mergeable *if* refactored to drop BF64-specific dependencies. Note the refactor scope in `Notes`.

---

## 5. Rebase hygiene rules

These rules exist so §3.2's "stay rebaseable" promise is actually kept. Agents must follow them when editing shared-core files.

1. **Prefer additive edits over in-place rewrites.** A new file, a new function, a new `#ifdef BF64_AGENT` block — all merge cleanly. Rewriting an existing function does not.
2. **Guard BF64-only code in shared files.** Any inline BF64 code that must live in an upstream file (e.g., a hook in `src/editor/...`) is wrapped:
   ```cpp
   #ifdef BF64_AGENT
   // BF64-only: <one-line reason>
   <code>
   #endif
   ```
   Define `BF64_AGENT` in `CMakeLists.txt` at the BF64 target level only. This keeps the diff visible, removable, and conflict-free on rebase.
3. **Never reorder unrelated upstream code.** If you touch a function for a BF64 hook, don't reformat its neighbors. Reformat noise is the #1 cause of painful rebases against a fast-moving upstream.
4. **Pin submodules; let upstream bump them.** `vendored/*` versions are set by upstream. If BF64 needs a different libdragon/tiny3d pin (e.g., for an extension hook), record the pin and the reason in row §4, and re-pull upstream's pin at each merge.
5. **Run `git merge upstream/main` at every tagged upstream release.** Do not let the fork drift more than one tag behind. Resolve conflicts in shared-core files immediately; agent-layer files should not conflict. If they do, that's a §4 row (the upstream release grew a new file where we had one — coordinate).
6. **Keep `docs/` shared-core diffs to toctree additions only.** The Sphinx tree is upstream-owned. BF64 adds *sections* (`docs/docs/project/`, `docs/docs/agent/`, `docs/docs/n64/`) and *one toctree line each* in `docs/index.rst`. We do not modify `conf.py`, `Doxyfile`, `_apigen.py`, the manual, or the dev/version sections. See §6.
7. **Commit messages on shared-core files use upstream's style.** Conventional-commits prefix (`feat:`, `fix:`, `docs:`, `chg:`) matching what upstream actually uses. BF64-only files may use a `docs(agent):` / `feat(mcp):` prefix; those commits are squashed if ever upstreamed.

---

## 6. Documentation tree: the one allowed divergence in `docs/`

`docs/` is upstream-owned, but BF64 needs new doc sections. The compromise, locked in here:

```
docs/
├── index.rst                     # shared — BF64 adds one toctree line per new section
├── conf.py, Doxyfile, _apigen.py, Makefile, build_and_serve.sh, requirements.txt  # shared, untouched by BF64
├── _static/                      # shared, untouched (upstream's images/fonts)
├── docs/                         # the Sphinx content tree (shared structure)
│   ├── manual/                   # shared, untouched by BF64
│   ├── dev/                      # shared, untouched by BF64
│   ├── version/                  # shared, untouched by BF64
│   ├── faq.md                    # shared, untouched by BF64
│   ├── project/                  # BF64-only — planning docs (gap analysis, phased plan)
│   │   ├── gap-analysis.md
│   │   └── phased-plan.md
│   ├── project.rst               # BF64-only — toctree for project/
│   ├── agent/                    # BF64-only — this directory (ARCHITECTURE, CODEMAP, HANDOFF, DIVERGENCE, …)
│   │   └── DIVERGENCE.md          # (this file)
│   ├── agent.rst                 # BF64-only — toctree for agent/
│   ├── n64/                      # BF64-only — N64 hardware/asset compendium (Phases 1–2)
│   └── n64.rst                   # BF64-only — toctree for n64/
└── _build/, .venv/               # gitignored
```

**Rules:**
- New BF64 section = new subdirectory under `docs/docs/` + a matching `docs/docs/<section>.rst` toctree + **one line** added to `docs/index.rst`'s root toctree. No other shared file is touched.
- We do not modify `docs/conf.py` to add Hugo, frontmatter, or alternative builders. The Sphinx/MyST/Breathe toolchain stays as upstream built it. (This is why we declined the original Hugo-migration idea: it would have diverged `conf.py`, `Makefile`, `build_and_serve.sh`, and `requirements.txt` simultaneously — exactly the shared-core rebase pain §5 exists to prevent.)
- BF64 docs are plain MyST markdown with `#` h1 titles and no frontmatter, matching the convention of every existing `.md` file in the tree. GFM tables, fenced code, and relative links all render as-is.
- The C++ API reference (auto-generated by `Doxyfile` + `_apigen.py` from `n64/engine/include/`) remains upstream's. BF64 does not add or modify API pages. If BF64 adds new public engine headers (e.g., for the extension host), those go through §5's `#ifdef BF64_AGENT` rule in shared headers, and a §4 row decides whether the API page generator should pick them up upstream.

---

## 7. Attribution

- Upstream Pyrite64 credits stay intact in `README.md`, `LICENSE`, and the docs footer. BF64's README rewrite (Phase 8) keeps the "© 2025-2026 - Max Bebök (HailToDodoko)" line and the "Pyrite64 does NOT use any proprietary N64 SDKs" notice verbatim.
- BF64 adds its own credits block *below* upstream's, never replacing it.
- Games built *with* BF64 inherit upstream's no-restriction license policy; we add the same no-restriction notice for BF64 itself.
- When BF64 work is upstreamed (§3.3), the upstream PR credits BF64 by name in the PR description. The maintainer is free to credit or not in the merge commit; we don't insist.

---

## 8. When this policy changes

- **Upstream posts an AI stance** (issue, Discord announcement, README update, blog): revisit §2.1 and §3.3 within one BF64 phase. If the stance is permissive, consider widening what we upstream. If restrictive, narrow further.
- **Upstream cuts a release** with a breaking change that touches BF64's shared-core surface: this doc gets a §4 row recording the rebase, and §5 rule 5 fires.
- **BF64 completes a phase** that adds a new top-level directory (e.g., `mcp/` in Phase 6): add it to the §3.1 list and create a matching entry in `docs/docs/<section>.rst` per §6.
- **A BF64 change is upstreamed and merged**: update the §4 row's `Upstream PR?` column with the PR number and mark `Classification` as `mergeable upstream (merged)`.
