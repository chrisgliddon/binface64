#!/usr/bin/env python3
"""Smoke-check the BF64 skills package as an installable artifact."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
README = SKILLS / "README.md"


def fail(message: str) -> None:
    raise RuntimeError(message)


def skill_dirs() -> list[Path]:
    return sorted(path for path in SKILLS.iterdir() if path.is_dir() and not path.name.startswith("_"))


def check_lint() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lint-skills.py"), "--strict"],
        cwd=ROOT,
        check=True,
    )


def check_plugin(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("skills") != "./skills":
        fail(f"{path}: skills must be ./skills")
    if not data.get("name", "").endswith("-skills"):
        fail(f"{path}: plugin name should end with -skills")


def markdown_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [match.group(1) for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text)]


def check_local_links(path: Path) -> None:
    for target in markdown_links(path):
        if "://" in target or target.startswith("#"):
            continue
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        resolved = (path.parent / path_part).resolve()
        if not resolved.exists():
            fail(f"{path.relative_to(ROOT)} link target missing: {target}")


def check_readme_links() -> None:
    linked_skills: set[str] = set()

    for target in markdown_links(README):
        if "://" in target or target.startswith("#"):
            continue
        path_part = target.split("#", 1)[0]
        resolved = (README.parent / path_part).resolve()
        if not resolved.exists():
            fail(f"README link target missing: {target}")
        if path_part.endswith("/SKILL.md"):
            linked_skills.add(Path(path_part).parent.name)

    actual = {path.name for path in skill_dirs()}
    missing = actual - linked_skills
    extra = linked_skills - actual
    if missing:
        fail(f"README does not link skills: {sorted(missing)}")
    if extra:
        fail(f"README links unknown skills: {sorted(extra)}")


def check_router_links() -> None:
    router = SKILLS / "bf64" / "SKILL.md"
    text = router.read_text(encoding="utf-8")
    actual = {path.name for path in skill_dirs()}
    for name in sorted(actual - {"bf64"}):
        if f"`{name}`" not in text:
            fail(f"router does not mention skill {name}")


def check_all_markdown_links() -> None:
    for path in sorted(SKILLS.rglob("*.md")):
        check_local_links(path)


def check_temp_install() -> None:
    with tempfile.TemporaryDirectory(prefix="bf64-skills-") as tmp:
        target_root = Path(tmp) / "skills"
        shutil.copytree(SKILLS, target_root)
        for source in skill_dirs():
            installed = target_root / source.name / "SKILL.md"
            if not installed.exists():
                fail(f"installed skill missing {installed}")
            first_line = installed.read_text(encoding="utf-8").splitlines()[0].strip()
            if first_line != "---":
                fail(f"installed skill lacks frontmatter: {installed}")


def main() -> int:
    try:
        check_lint()
        check_plugin(ROOT / ".claude-plugin" / "plugin.json")
        check_plugin(ROOT / ".cursor-plugin" / "plugin.json")
        check_readme_links()
        check_router_links()
        check_all_markdown_links()
        check_temp_install()
    except Exception as exc:  # noqa: BLE001 - command-line smoke check
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("OK: skills package smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
