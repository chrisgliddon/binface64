#!/usr/bin/env python3
"""Lint BF64 agent skills.

The linter intentionally uses only the Python standard library so it can run in
fresh checkouts and agent sandboxes without dependency setup.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata"}
REQUIRED_KEYS = {"name", "description"}
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
MAX_SKILL_LINES = 150
REQUIRED_VERSION_TOKEN = "BF64"


@dataclass
class LintResult:
    path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_frontmatter(text: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, ["frontmatter must start with `---` on the first line"]

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, ["frontmatter missing closing `---`"]

    result: dict[str, Any] = {}
    current_key: str | None = None
    nested: dict[str, str] = {}

    def flush_nested() -> None:
        nonlocal current_key, nested
        if current_key is not None and nested:
            result[current_key] = nested
        current_key = None
        nested = {}

    for line_no, raw in enumerate(lines[1:end], start=2):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  ") and current_key is not None:
            sub = line.strip()
            if ":" not in sub:
                errors.append(f"line {line_no}: nested entry without colon: {sub!r}")
                continue
            key, _, value = sub.partition(":")
            nested[key.strip()] = value.strip().strip('"').strip("'")
            continue
        flush_nested()
        if ":" not in line:
            errors.append(f"line {line_no}: top-level entry without colon: {line!r}")
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value:
            result[key] = value.strip('"').strip("'")
        else:
            current_key = key
            nested = {}
    flush_nested()
    return result, errors


def lint_skill(path: Path) -> LintResult:
    result = LintResult(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    frontmatter, parse_errors = parse_frontmatter(text)
    result.errors.extend(parse_errors)
    if not frontmatter:
        return result

    extra = set(frontmatter) - ALLOWED_KEYS
    if extra:
        result.errors.append(f"unknown frontmatter keys: {sorted(extra)}")
    missing = REQUIRED_KEYS - set(frontmatter)
    if missing:
        result.errors.append(f"missing required keys: {sorted(missing)}")

    name = frontmatter.get("name")
    if isinstance(name, str):
        if not NAME_RE.match(name):
            result.errors.append(f"name {name!r} must match {NAME_RE.pattern}")
        if len(name) > MAX_NAME_LEN:
            result.errors.append(f"name length {len(name)} > {MAX_NAME_LEN}")
        if name != path.parent.name:
            result.errors.append(f"name {name!r} does not match directory {path.parent.name!r}")

    description = frontmatter.get("description")
    if isinstance(description, str):
        if not (1 <= len(description) <= MAX_DESCRIPTION_LEN):
            result.errors.append(f"description length {len(description)} outside 1..{MAX_DESCRIPTION_LEN}")
        if not description.startswith("Use when"):
            result.errors.append("description must start with `Use when`")
        metadata = frontmatter.get("metadata")
        expected_pin = metadata.get("target_version") if isinstance(metadata, dict) else REQUIRED_VERSION_TOKEN
        if not isinstance(expected_pin, str) or not expected_pin:
            expected_pin = REQUIRED_VERSION_TOKEN
        if expected_pin not in description:
            result.errors.append(f"description must contain literal {expected_pin!r}")

    metadata = frontmatter.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        result.errors.append("metadata must be a nested mapping")

    if len(lines) > MAX_SKILL_LINES:
        result.warnings.append(f"skill is {len(lines)} lines; prefer <= {MAX_SKILL_LINES}")
    if "## Common Agent Mistakes" not in text:
        result.errors.append("missing `## Common Agent Mistakes` section")
    if "docs/docs/" not in text and path.parent.name != "bf64":
        result.warnings.append("no docs/docs source reference found")

    return result


def skill_paths(args: list[str]) -> list[Path]:
    if args:
        return [Path(arg) for arg in args]
    paths = []
    for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
        if path.parent.name.startswith("_"):
            continue
        paths.append(path)
    return paths


def lint_plugin(path: Path) -> LintResult:
    result = LintResult(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported to caller
        result.errors.append(f"invalid JSON: {exc}")
        return result
    for key in ("name", "version", "description", "skills"):
        if key not in data:
            result.errors.append(f"missing key {key!r}")
    if data.get("skills") != "./skills":
        result.errors.append("skills must be `./skills`")
    return result


def main(argv: list[str]) -> int:
    strict = False
    args: list[str] = []
    for item in argv:
        if item == "--strict":
            strict = True
        else:
            args.append(item)

    results = [lint_skill(path) for path in skill_paths(args)]
    if not args:
        for plugin in (ROOT / ".claude-plugin" / "plugin.json", ROOT / ".cursor-plugin" / "plugin.json"):
            results.append(lint_plugin(plugin))

    failed = False
    warned = False
    for result in results:
        rel = result.path.relative_to(ROOT) if result.path.is_absolute() and ROOT in result.path.parents else result.path
        for error in result.errors:
            failed = True
            print(f"ERROR {rel}: {error}")
        for warning in result.warnings:
            warned = True
            print(f"WARN  {rel}: {warning}")

    if failed or (strict and warned):
        return 1
    print(f"OK: linted {len(results)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
