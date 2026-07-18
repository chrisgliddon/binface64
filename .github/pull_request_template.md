# Please read before submitting!

PRs are welcome. A few expectations:

- **Small and focused.** One PR per change. If you're planning something that isn't a small change, please talk about it first — open an issue or a draft PR, or raise it in the [N64Brew Discord](https://discord.gg/WqFgNWf). Large features have a good chance of not being merged if they land without pre-discussion.
- **Pick the right layer.** See [`docs/docs/agent/DIVERGENCE.md`](../docs/docs/agent/DIVERGENCE.md) §3. Agent-only-layer changes (`skills/`, `tools/bf64.py`, `docs/docs/agent/`, `docs/docs/n64/`) diverge freely. Shared-core changes (`src/`, `n64/engine/include/`, `CMakeLists.txt`, `vendored/`, the Sphinx toolchain) must stay rebaseable — prefer additive edits, guard BF64-only code with `#ifdef BF64_AGENT`, and don't reorder unrelated upstream code.
- **Shared-core changes need a `DIVERGENCE.md` §4 row.** Add it in this PR, at the top of the living table, with the correct classification (`mergeable upstream`, `BF64-only`, or `conditional`).
- **Tests.** If you change CLI behavior, validator output, or a JSON contract, update the matching `tests/` file in this PR. Run `python3 -m pytest tests/` before pushing.
- **Lint the skills.** If you touch `skills/`, run `python3 scripts/lint-skills.py` and `python3 scripts/check-skills-package.py` before pushing.
- **Commit messages** on shared-core files use upstream's conventional-commits style (`feat:`, `fix:`, `docs:`, `chg:`). Agent-only-layer files may use a `docs(agent):` / `feat(mcp):` / `feat(cli):` prefix.

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the full guide.