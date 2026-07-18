---
name: New Feature
about: Suggest a net-new capability that doesn't exist today
title: "[FEATURE] "
labels: enhancement
assignees: ''

---

Please first search through existing issues and PRs before suggesting a feature!

## User Story

As a **<kind of contributor/user>**, I want **<new capability>** so that **<benefit>**.

> Examples of `<kind of contributor/user>`: BF64 contributor, N64 homebrew developer, agent driving the CLI, editor user, skills maintainer.

## What's new

A clear, concise description of the new capability and how someone would use it. If it's a new `./bf64` subcommand, a new skills sibling, a new node-graph node type, or a new runtime engine API, describe the shape it would take.

## Why

Why this feature matters. If it unblocks a class of games, a new agent workflow, or a kind of contribution that isn't possible today, say so.

## Acceptance Criteria

Write each criterion so a human (or agent) can verify it by running a command, inspecting an output, or performing a check — not by subjective judgment.

- [ ] A testable, observable condition.
- [ ] Another testable condition.
- [ ] ...

## Does this touch the shared core?

If the feature modifies `src/`, `n64/engine/include/`, `CMakeLists.txt`, `CMakePresets.json`, `vendored/`, or the shared Sphinx toolchain under `docs/`, it touches the **shared core** and will need a row in [`docs/docs/agent/DIVERGENCE.md`](../../docs/docs/agent/DIVERGENCE.md) §4 before the PR merges. Check one:

- [ ] No — this lives in the agent-only layer (`skills/`, `tools/bf64.py`, `docs/docs/agent/`, `docs/docs/n64/`, `docs/docs/project/`, `.claude-plugin/`, `.cursor-plugin/`).
- [ ] Yes — I'll add a `DIVERGENCE.md` §4 row in the PR.
- [ ] Not sure — needs discussion.

## Additional context

Screenshots, related issues, upstream PRs, or anything else relevant.