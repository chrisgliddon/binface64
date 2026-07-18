---
name: Improvement
about: Suggest a change to something that already exists — faster, clearer, more ergonomic, or more correct
title: "[IMPROVEMENT] "
labels: enhancement
assignees: ''

---

Please first search through existing issues and PRs before suggesting an improvement!

## User Story

As a **<kind of contributor/user>**, I want **<change to an existing thing>** so that **<benefit>**.

> Examples of `<kind of contributor/user>`: BF64 contributor, N64 homebrew developer, agent driving the CLI, editor user, skills maintainer.

## What's being improved

A clear, concise description of the existing behavior and the change you're proposing. Link to the file, command, or doc section if you can.

## Why

Why this improvement matters. If it unblocks a workflow, fixes a paper cut, or makes agent/human pairing smoother, say so.

## Acceptance Criteria

Write each criterion so a human (or agent) can verify it by running a command, inspecting an output, or performing a check — not by subjective judgment.

- [ ] A testable, observable condition.
- [ ] Another testable condition.
- [ ] ...

## Does this touch the shared core?

If the improvement modifies `src/`, `n64/engine/include/`, `CMakeLists.txt`, `CMakePresets.json`, `vendored/`, or the shared Sphinx toolchain under `docs/`, it touches the **shared core** and will need a row in [`docs/docs/agent/DIVERGENCE.md`](../../docs/docs/agent/DIVERGENCE.md) §4 before the PR merges. Check one:

- [ ] No — this lives in the agent-only layer (`skills/`, `tools/bf64.py`, `docs/docs/agent/`, `docs/docs/n64/`, `docs/docs/project/`, `.claude-plugin/`, `.cursor-plugin/`).
- [ ] Yes — I'll add a `DIVERGENCE.md` §4 row in the PR.
- [ ] Not sure — needs discussion.

## Additional context

Screenshots, related issues, upstream PRs, or anything else relevant.