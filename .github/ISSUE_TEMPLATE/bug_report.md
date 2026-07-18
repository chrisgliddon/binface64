---
name: Bug report
about: Report something Binface64 does incorrectly, crashes, or behaves unexpectedly
title: "[BUG] "
labels: bug
assignees: ''

---

Please first search through existing issues and PRs before submitting a bug!

## Which part of the project is affected?

Pick one or more:

- [ ] Headless `./bf64` CLI (e.g., JSON output, validation, build/run, history)
- [ ] Editor (e.g., UI issues, button not working, viewport)
- [ ] N64 / Runtime code (e.g., ROM crashes, rendering, audio, collision)
- [ ] Skills package (e.g., router, sibling skill, plugin manifest)
- [ ] Documentation (e.g., `docs/docs/n64/`, `docs/docs/agent/`, README)
- [ ] Toolchain manager / installation
- [ ] Other

## Expected Result

What you thought would happen. Be specific — include the exact command, action, or output you expected.

## Actual Result

What actually happened. Include the full error message, JSON output (if you ran with `--json`), or a description of the wrong behavior. If the CLI exited non-zero, paste the `issues` array from the JSON output.

## Steps to Reproduce

The smallest sequence that triggers the bug. Number each step.

1.
2.
3.

If you can reproduce it with a single `./bf64 ... --json` command, paste that command here. If you used `--record`, paste the matching `.bf64/operations.jsonl` entry if you have it.

## Reproducibility %

How often does this happen with the steps above?

- [ ] 100% (always)
- [ ] ~75%
- [ ] ~50%
- [ ] ~25%
- [ ] Once (hasn't repeated)

If it's intermittent, describe what seems to vary between runs.

## Platform(s) Tested On

- **OS:** (e.g., Windows 11, Linux — Ubuntu 24.04, macOS 14)
- **Binface64 / Pyrite64 version:** (e.g., 0.8.0, latest `main`)
- **How the game/output was run:** (e.g., real N64 with flashcart, Ares v147, gopher64)
- **Toolchain:** (e.g., libdragon pin `b1011fe31`, tiny3d pin `bdcd946`, N/A)

## Screenshots / Logs

If applicable, add screenshots, emulator logs, or excerpts from `.bf64/operations.jsonl` to help explain the problem.