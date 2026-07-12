#!/usr/bin/env python3
"""Agent-first BF64 utility surface.

This is a lightweight, no-dependency bridge for agents before the formal BF64
CLI/MCP phases land. It exposes machine-readable N64 constraints and a focused
asset validator backed by docs/docs/n64/limits.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import queue
import re
import signal
import shlex
import shutil
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from tools.bf64_ui import (
    default_ui_document,
    load_focus_catalog,
    validate_ui_document,
)


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
LIMITS_PATH = REPO_ROOT / "docs" / "docs" / "n64" / "limits.json"
FOCUS_AREAS_PATH = REPO_ROOT / "data" / "focus-areas.json"
DEFAULT_HISTORY_PATH = REPO_ROOT / ".bf64" / "operations.jsonl"
PROJECT_FILENAME = "project.p64proj"
EMPTY_PROJECT_TEMPLATE = REPO_ROOT / "n64" / "examples" / "empty"
CLI_VERSION = "0.18.0"
HISTORY_SCHEMA_VERSION = 2
PROFILE_SCHEMA_VERSION = 1
PROFILE_MARKER = "BF64_PROFILE_JSON:"
VALIDATABLE_ASSET_KINDS = {"texture", "model", "audio", "font", "ui", "prefab", "node_graph"}
IMPORTABLE_ASSET_KINDS = {"texture", "model", "audio", "font"}
PROJECT_ASSET_KINDS = ("texture", "model", "audio", "font", "ui", "prefab", "node_graph", "unknown")
NODE_GRAPH_VARIABLE_TYPES = {"i32", "u32", "f32", "vec3", "quat", "objref"}
PYRITE_BINARY_NAMES = ("pyrite64", "pyrite64.exe")
BUILD_TOOLCHAIN_FILES = (
    ("mips64-elf-gcc", "bin/mips64-elf-gcc"),
    ("n64.mk", "include/n64.mk"),
    ("t3d.mk", "include/t3d.mk"),
    ("mkasset", "bin/mkasset"),
    ("mksprite", "bin/mksprite"),
    ("audioconv64", "bin/audioconv64"),
    ("mkfont", "bin/mkfont"),
    ("mkdfs", "bin/mkdfs"),
    ("n64tool", "bin/n64tool"),
)
ASSET_CONF_DEFAULTS: dict[str, Any] = {
    "uuid": 0,
    "format": 0,
    "baseScale": 16,
    "compression": 0,
    "gltfBVH": False,
    "wavForceMono": False,
    "wavResampleRate": 0,
    "wavCompression": 0,
    "fontId": 0,
    "fontCharset": "",
    "exclude": False,
    "data": {},
}
ASSET_CONF_BOOL_FIELDS = {"gltfBVH", "wavForceMono", "exclude"}
ASSET_CONF_SIGNED_FIELDS = {"format", "baseScale", "compression", "wavCompression"}
ASSET_CONF_UNSIGNED_FIELDS = {"wavResampleRate", "fontId"}

COMPONENT_NAMES = (
    "Code",
    "Model (Static)",
    "Light",
    "Camera",
    "Collision-Mesh",
    "Collider",
    "Audio (2D)",
    "Constraint",
    "Culling",
    "Node Graph",
    "Model (Animated)",
    "Rigid-Body",
    "Character-Body",
    "UI Document",
    "Audio (3D)",
)
COMPONENT_ALIASES = {
    "code": 0,
    "script": 0,
    "model": 1,
    "staticmodel": 1,
    "modelstatic": 1,
    "light": 2,
    "camera": 3,
    "collisionmesh": 4,
    "collmesh": 4,
    "collider": 5,
    "collisionbody": 5,
    "audiostream": 6,
    "audio2d": 6,
    "audio": 6,
    "constraint": 7,
    "culling": 8,
    "nodegraph": 9,
    "animatedmodel": 10,
    "modelanimated": 10,
    "rigidbody": 11,
    "characterbody": 12,
    "charbody": 12,
    "uidocument": 13,
    "ui": 13,
    "audio3d": 14,
    "positionalaudio": 14,
    "spatialaudio": 14,
}
COMPONENT_ASSET_FIELDS = {
    1: ("model", "model"),
    4: ("modelUUID", "model"),
    6: ("audioUUID", "audio"),
    9: ("asset", "node_graph"),
    10: ("model", "model"),
    13: ("document", "ui"),
    14: ("audioUUID", "audio"),
}


def load_limits() -> dict[str, Any]:
    with LIMITS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def issue(
    severity: str,
    rule: str,
    message: str,
    fix: str = "",
    source: str = "",
) -> dict[str, str]:
    out = {"severity": severity, "rule": rule, "message": message}
    if fix:
        out["fix"] = fix
    if source:
        out["source"] = source
    return out


def has_errors(issues: list[dict[str, str]]) -> bool:
    return any(i.get("severity") == "error" for i in issues)


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def output_result(data: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return

    status = "OK" if data.get("ok") else "FAILED"
    target = data.get("path") or data.get("topic") or data.get("command", "")
    print(f"{status}: {target}")
    for item in data.get("issues", []):
        prefix = item.get("severity", "info").upper()
        rule = item.get("rule", "")
        msg = item.get("message", "")
        print(f"{prefix} {rule}: {msg}")
        if item.get("fix"):
            print(f"  fix: {item['fix']}")


def load_conf(asset_path: Path, explicit_conf: str | None) -> tuple[dict[str, Any], str | None]:
    conf_path = Path(explicit_conf) if explicit_conf else Path(str(asset_path) + ".conf")
    if not conf_path.exists():
        return {}, None
    try:
        return json.loads(conf_path.read_text(encoding="utf-8")), str(conf_path)
    except Exception as exc:  # noqa: BLE001 - surfaced as a validation issue
        return {"__parse_error__": str(exc)}, str(conf_path)


def normalize_asset_conf(conf: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return the non-mutating editor-compatible view of an asset sidecar."""
    if "__parse_error__" in conf:
        return dict(conf), []

    normalized = dict(conf)
    defaulted: list[str] = []
    for key, fallback in ASSET_CONF_DEFAULTS.items():
        value = normalized.get(key)
        valid = value is not None
        if key == "uuid":
            valid = type(value) is int and 0 <= value <= 0xFFFFFFFFFFFFFFFF
        elif key in ASSET_CONF_BOOL_FIELDS:
            valid = type(value) is bool
        elif key in ASSET_CONF_SIGNED_FIELDS:
            valid = type(value) is int and -0x80000000 <= value <= 0x7FFFFFFF
        elif key in ASSET_CONF_UNSIGNED_FIELDS:
            valid = type(value) is int and 0 <= value <= 0xFFFFFFFF
        elif key == "fontCharset":
            valid = isinstance(value, str)
        elif key == "data":
            valid = isinstance(value, dict)
        if valid:
            continue
        normalized[key] = dict(fallback) if isinstance(fallback, dict) else fallback
        defaulted.append(key)
    return normalized, defaulted


def read_png_info(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        sig = fh.read(8)
        if sig != b"\x89PNG\r\n\x1a\n":
            raise ValueError("not a PNG file")
        length, chunk = struct.unpack(">I4s", fh.read(8))
        if chunk != b"IHDR" or length < 13:
            raise ValueError("PNG missing IHDR chunk")
        ihdr = fh.read(13)
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "compression": compression,
        "filter": filter_method,
        "interlace": interlace,
    }


def parse_texture_format(value: Any, limits: dict[str, Any]) -> tuple[str, int] | None:
    ids = limits["texture"]["format_ids"]
    by_id = {int(v): k for k, v in ids.items()}
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            num = int(raw)
            return (by_id[num], num) if num in by_id else None
        normalized = raw.upper().replace("-", "_").replace(" ", "_")
        if normalized == "BCI":
            normalized = "BCI_256"
        if normalized in ids:
            return normalized, int(ids[normalized])
        return None
    if isinstance(value, (int, float)):
        num = int(value)
        return (by_id[num], num) if num in by_id else None
    return None


def infer_texture_format_from_name(path: Path, limits: dict[str, Any]) -> tuple[str, int] | None:
    name = path.name.lower()
    for token, fmt in (
        (".bci.png", "BCI_256"),
        (".rgba32.", "RGBA32"),
        (".rgba16.", "RGBA16"),
        (".ci8.", "CI8"),
        (".ci4.", "CI4"),
        (".ia16.", "IA16"),
        (".ia8.", "IA8"),
        (".ia4.", "IA4"),
        (".i8.", "I8"),
        (".i4.", "I4"),
    ):
        if token in name:
            return fmt, int(limits["texture"]["format_ids"][fmt])
    return None


def pipeline_id(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip().lower()
    if raw in {"0", "default"}:
        return 0
    if raw in {"1", "hdr", "hdr+bloom", "hdr_bloom"}:
        return 1
    if raw in {"2", "bigtex", "big_tex"}:
        return 2
    raise ValueError(f"unknown scene pipeline: {value}")


def read_json_file(path: Path) -> dict[str, Any] | list[Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def resolve_project(project_arg: str | None) -> tuple[Path | None, Path | None, dict[str, Any] | None, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    raw = Path(project_arg or ".")
    config_path = raw if raw.suffix == ".p64proj" else raw / PROJECT_FILENAME

    if not config_path.exists():
        issues.append(
            issue(
                "error",
                "PROJECT",
                f"Could not find {PROJECT_FILENAME} at {config_path}.",
                "Pass --project <project-dir> or --project <path/to/project.p64proj>.",
                "docs/docs/agent/ARCHITECTURE.md#31-project-format",
            )
        )
        return None, None, None, issues

    try:
        config = read_json_file(config_path)
    except Exception as exc:  # noqa: BLE001
        issues.append(issue("error", "PROJECT", f"Could not parse project JSON: {exc}", "Fix project.p64proj JSON."))
        return config_path.parent, config_path, None, issues

    if not isinstance(config, dict):
        issues.append(issue("error", "PROJECT", "project.p64proj must contain a JSON object."))
        return config_path.parent, config_path, None, issues

    return config_path.parent, config_path, config, issues


def project_summary(project_root: Path, config_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(project_root),
        "config_path": str(config_path),
        "name": config.get("name", "New Project"),
        "romName": config.get("romName", "pyrite64"),
        "editorVersion": config.get("editorVersion", ""),
        "sceneIdOnBoot": config.get("sceneIdOnBoot", 1),
        "sceneIdOnReset": config.get("sceneIdOnReset", 1),
        "sceneIdLastOpened": config.get("sceneIdLastOpened", 1),
        "assetExclusions": config.get("assetExclusions", []),
    }


def normalize_asset_exclusion_pattern(value: Any) -> tuple[str | None, str | None]:
    """Return a canonical assets-relative glob and an error message, if any."""
    if not isinstance(value, str):
        return None, "Asset exclusion patterns must be strings."

    pattern = value.strip().replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    if pattern.startswith("assets/"):
        pattern = pattern[len("assets/") :]

    if not pattern:
        return None, "Asset exclusion patterns cannot be empty."
    if pattern.startswith("/") or re.match(r"^[A-Za-z]:/", pattern):
        return None, f"Asset exclusion pattern must be relative to assets/: {value!r}."
    if "\x00" in pattern:
        return None, "Asset exclusion patterns cannot contain NUL characters."

    parts = pattern.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None, f"Asset exclusion pattern cannot contain empty, '.' or '..' segments: {value!r}."
    return pattern, None


def configured_asset_exclusion_patterns(config: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (configured spelling, canonical pattern) pairs, ignoring invalid entries."""
    raw_patterns = config.get("assetExclusions", [])
    if not isinstance(raw_patterns, list):
        return []
    patterns: list[tuple[str, str]] = []
    for raw in raw_patterns:
        normalized, error = normalize_asset_exclusion_pattern(raw)
        if normalized is not None and error is None:
            patterns.append((str(raw), normalized))
    return patterns


def asset_glob_regex(pattern: str) -> re.Pattern[str]:
    """Compile BF64's slash-aware glob syntax (`*`, `?`, and recursive `**`)."""
    regex = ""
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    regex += "(?:.*/)?"
                    index += 1
                else:
                    regex += ".*"
                continue
            regex += "[^/]*"
        elif char == "?":
            regex += "[^/]"
        else:
            regex += re.escape(char)
        index += 1
    return re.compile(f"^{regex}$")


def matching_asset_exclusion_patterns(
    asset_path: str,
    patterns: list[tuple[str, str]],
) -> list[str]:
    rel_path = asset_path.replace("\\", "/").removeprefix("assets/")
    basename = rel_path.rsplit("/", 1)[-1]
    matches: list[str] = []
    for configured, pattern in patterns:
        candidate = rel_path if "/" in pattern else basename
        if asset_glob_regex(pattern).fullmatch(candidate):
            matches.append(configured)
    return matches


def load_asset_exclusion_patterns(project_root: Path) -> list[tuple[str, str]]:
    try:
        config = read_json_file(project_root / PROJECT_FILENAME)
    except Exception:  # noqa: BLE001 - project validation reports malformed config
        return []
    return configured_asset_exclusion_patterns(config) if isinstance(config, dict) else []


def iter_scene_files(project_root: Path) -> tuple[list[tuple[int, Path]], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    scenes_root = project_root / "data" / "scenes"
    if not scenes_root.exists():
        issues.append(
            issue(
                "error",
                "PROJECT",
                f"Scene directory does not exist: {scenes_root}.",
                "Open/save the project in BF64 or create data/scenes/<id>/scene.json.",
                "docs/docs/agent/ARCHITECTURE.md#31-project-format",
            )
        )
        return [], issues

    scenes: list[tuple[int, Path]] = []
    for entry in scenes_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            scene_id = int(entry.name)
        except ValueError:
            continue
        scenes.append((scene_id, entry / "scene.json"))
    scenes.sort(key=lambda item: item[0])
    return scenes, issues


def component_name_list(components: list[Any]) -> list[str]:
    names: list[str] = []
    for comp in components:
        if isinstance(comp, dict):
            names.append(str(comp.get("name") or f"component:{comp.get('id', '?')}"))
    return names


def collect_object_stats(graph: Any, max_component_id: int) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
    issues: list[dict[str, str]] = []
    tree: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        "object_count": 0,
        "component_count": 0,
        "max_depth": 0,
        "component_ids": {},
        "duplicate_object_uuids": [],
        "duplicate_component_uuids": [],
    }
    seen_uuids: set[int] = set()
    seen_component_uuids: set[int] = set()

    if not isinstance(graph, dict):
        return stats, [issue("error", "SCENE", "Scene graph must be a JSON object.")], tree

    children = graph.get("children", [])
    if not isinstance(children, list):
        return stats, [issue("error", "SCENE", "Scene graph children must be a JSON array.")], tree

    def visit(obj: Any, depth: int, path: str) -> dict[str, Any] | None:
        if not isinstance(obj, dict):
            issues.append(issue("error", "SCENE", f"{path} must be a JSON object."))
            return None

        stats["object_count"] += 1
        stats["max_depth"] = max(int(stats["max_depth"]), depth)
        name = str(obj.get("name") or "(unnamed)")
        uuid = obj.get("uuid")
        if not isinstance(uuid, int):
            issues.append(issue("error", "SCENE", f"{path} object '{name}' is missing an integer uuid."))
        elif uuid in seen_uuids:
            stats["duplicate_object_uuids"].append(uuid)
            issues.append(issue("error", "SCENE", f"Duplicate scene object uuid {uuid}."))
        else:
            seen_uuids.add(uuid)

        components = obj.get("components", [])
        if not isinstance(components, list):
            issues.append(issue("error", "SCENE", f"{path} object '{name}' components must be an array."))
            components = []
        rigid_body_count = 0
        for comp in components:
            stats["component_count"] += 1
            if not isinstance(comp, dict):
                issues.append(issue("error", "SCENE", f"{path} object '{name}' has a non-object component."))
                continue
            comp_id = comp.get("id")
            if not isinstance(comp_id, int) or comp_id < 0 or comp_id > max_component_id:
                issues.append(
                    issue(
                        "error",
                        "SCENE",
                        f"{path} object '{name}' has invalid component id {comp_id}.",
                        f"Use a component id in the editor/runtime registry range 0..{max_component_id}.",
                        "docs/docs/agent/CODEMAP.md#component-system",
                    )
                )
            else:
                key = str(comp_id)
                stats["component_ids"][key] = int(stats["component_ids"].get(key, 0)) + 1
                if comp_id == 11:
                    rigid_body_count += 1

            component_uuid = comp.get("uuid")
            if not isinstance(component_uuid, int) or component_uuid <= 0 or component_uuid > 0xFFFFFFFFFFFFFFFF:
                issues.append(
                    issue(
                        "error",
                        "SCENE_COMPONENT_UUID",
                        f"{path} object '{name}' has an invalid component uuid {component_uuid}.",
                        "Use a persistent integer UUID in the range 1..0xFFFFFFFFFFFFFFFF.",
                    )
                )
            elif component_uuid in seen_component_uuids:
                stats["duplicate_component_uuids"].append(component_uuid)
                issues.append(
                    issue(
                        "error",
                        "SCENE_COMPONENT_UUID",
                        f"Duplicate scene component uuid {component_uuid}.",
                        "Regenerate one component UUID through the supported scene mutation API.",
                    )
                )
            else:
                seen_component_uuids.add(component_uuid)

            if not isinstance(comp.get("name"), str) or not str(comp.get("name", "")).strip():
                issues.append(issue("error", "SCENE_COMPONENT_NAME", f"{path} object '{name}' has a component without a name."))
            if not isinstance(comp.get("data"), dict):
                issues.append(
                    issue(
                        "error",
                        "SCENE_COMPONENT_DATA",
                        f"{path} object '{name}' component {component_uuid} data must be a JSON object.",
                    )
                )
            elif comp_id == 14:
                data = comp["data"]
                audio_uuid = data.get("audioUUID")
                if not isinstance(audio_uuid, int) or audio_uuid <= 0:
                    issues.append(
                        issue(
                            "error",
                            "SCENE_AUDIO3D_ASSET",
                            f"{path} object '{name}' Audio (3D) component needs a positive audioUUID.",
                        )
                    )
                numeric = {
                    key: data.get(key, 1.0) if key == "pitch" else data.get(key)
                    for key in ("volume", "minDistance", "maxDistance", "rolloff", "pitch")
                }
                if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in numeric.values()):
                    issues.append(
                        issue(
                            "error",
                            "SCENE_AUDIO3D_RANGE",
                            f"{path} object '{name}' Audio (3D) volume/distances/rolloff/pitch must be numeric.",
                        )
                    )
                else:
                    if not 0.0 <= float(numeric["volume"]) <= 1.0:
                        issues.append(issue("error", "SCENE_AUDIO3D_RANGE", "Audio (3D) volume must be in 0..1."))
                    if float(numeric["minDistance"]) < 0.0:
                        issues.append(issue("error", "SCENE_AUDIO3D_RANGE", "Audio (3D) minDistance cannot be negative."))
                    if float(numeric["maxDistance"]) <= float(numeric["minDistance"]):
                        issues.append(issue("error", "SCENE_AUDIO3D_RANGE", "Audio (3D) maxDistance must exceed minDistance."))
                    if float(numeric["rolloff"]) <= 0.0:
                        issues.append(issue("error", "SCENE_AUDIO3D_RANGE", "Audio (3D) rolloff must be positive."))
                    if not 0.125 <= float(numeric["pitch"]) <= 8.0:
                        issues.append(issue("error", "SCENE_AUDIO3D_RANGE", "Audio (3D) pitch must be in 0.125..8."))
        if rigid_body_count > 1:
            issues.append(
                issue(
                    "error",
                    "SCENE_COMPONENT_DUPLICATE",
                    f"{path} object '{name}' has {rigid_body_count} Rigid-Body components; only one is supported.",
                )
            )

        node = {
            "name": name,
            "uuid": uuid,
            "components": component_name_list(components),
            "children": [],
        }

        child_list = obj.get("children", [])
        if not isinstance(child_list, list):
            issues.append(issue("error", "SCENE", f"{path} object '{name}' children must be an array."))
            child_list = []
        for idx, child in enumerate(child_list):
            child_node = visit(child, depth + 1, f"{path}.children[{idx}]")
            if child_node:
                node["children"].append(child_node)
        return node

    for idx, child in enumerate(children):
        node = visit(child, 1, f"graph.children[{idx}]")
        if node:
            tree.append(node)

    return stats, issues, tree


def validate_scene_doc(scene_path: Path, scene_id: int | None, doc: Any, limits: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if not isinstance(doc, dict):
        return {
            "ok": False,
            "path": str(scene_path),
            "kind": "scene",
            "metadata": {"scene_id": scene_id},
            "issues": [issue("error", "SCENE", "scene.json must contain a JSON object.")],
        }

    conf = doc.get("conf", {})
    if not isinstance(conf, dict):
        conf = {}
        issues.append(issue("error", "SCENE", "scene.json conf must be a JSON object."))

    graph = doc.get("graph")
    if graph is None:
        graph = {}
        issues.append(issue("error", "SCENE", "scene.json is missing graph object."))

    stats, graph_issues, tree = collect_object_stats(graph, int(limits["engine"]["max_component_id"]))
    issues.extend(graph_issues)

    max_objects = int(limits["scene"]["max_objects"])
    if int(stats["object_count"]) > max_objects:
        issues.append(
            issue(
                "error",
                "S6",
                f"Scene has {stats['object_count']} objects, exceeding the {max_objects} runtime id budget.",
                "Split the scene or delete/merge objects.",
                "docs/docs/n64/asset-checklist.md#scenes--prefabs-project-internal-assets",
            )
        )

    pipeline = optional_int(conf.get("renderPipeline")) or 0
    pipelines = limits["scene"]["pipelines"]
    pipe_conf = pipelines.get(str(pipeline))
    if pipe_conf is None:
        issues.append(
            issue(
                "error",
                "S1",
                f"Unknown renderPipeline {conf.get('renderPipeline')}.",
                "Use 0 (Default), 1 (HDR+Bloom), or 2 (BigTex).",
                "docs/docs/n64/asset-checklist.md#scenes--prefabs-project-internal-assets",
            )
        )
        pipe_name = "Unknown"
    else:
        pipe_name = str(pipe_conf["name"])
        fb_width = optional_int(conf.get("fbWidth")) or 320
        fb_height = optional_int(conf.get("fbHeight")) or 240
        fb_format = optional_int(conf.get("fbFormat")) or 0

        if "fb_width" in pipe_conf and fb_width != int(pipe_conf["fb_width"]):
            issues.append(issue("error", "S1", f"{pipe_name} requires fbWidth {pipe_conf['fb_width']}; got {fb_width}."))
        if "fb_height" in pipe_conf and fb_height != int(pipe_conf["fb_height"]):
            issues.append(issue("error", "S1", f"{pipe_name} requires fbHeight {pipe_conf['fb_height']}; got {fb_height}."))
        if "fb_format" in pipe_conf and fb_format != int(pipe_conf["fb_format"]):
            issues.append(issue("error", "S2", f"{pipe_name} requires fbFormat {pipe_conf['fb_format']}; got {fb_format}."))
        if "fb_formats" in pipe_conf and fb_format not in {int(v) for v in pipe_conf["fb_formats"]}:
            issues.append(issue("error", "S2", f"{pipe_name} requires fbFormat in {pipe_conf['fb_formats']}; got {fb_format}."))
        if pipeline == 2 and conf.get("doClearColor", True) is not False:
            issues.append(
                issue(
                    "error",
                    "S3",
                    "BigTex scenes must set doClearColor false.",
                    "Disable clear color or switch to Default/HDR+Bloom.",
                    "docs/docs/n64/asset-checklist.md#scenes--prefabs-project-internal-assets",
                )
            )

    audio_freq = optional_int(conf.get("audioFreq")) or 32000
    if audio_freq not in {32000, 44100, 48000}:
        issues.append(
            issue(
                "warning",
                "S4",
                f"audioFreq {audio_freq} is unusual; BF64 docs recommend 32000, 44100, or 48000.",
                "Use 32000 unless the project has a specific audio reason.",
                "docs/docs/n64/asset-checklist.md#scenes--prefabs-project-internal-assets",
            )
        )

    metadata = {
        "scene_id": scene_id,
        "name": conf.get("name") or str(scene_id or scene_path.parent.name),
        "renderPipeline": pipeline,
        "renderPipelineName": pipe_name,
        "fbWidth": optional_int(conf.get("fbWidth")) or 320,
        "fbHeight": optional_int(conf.get("fbHeight")) or 240,
        "fbFormat": optional_int(conf.get("fbFormat")) or 0,
        "audioFreq": audio_freq,
        **stats,
    }

    return {
        "ok": not has_errors(issues),
        "path": str(scene_path),
        "kind": "scene",
        "metadata": metadata,
        "tree": tree,
        "issues": issues,
    }


def load_scene_summary(scene_id: int, scene_path: Path, limits: dict[str, Any]) -> dict[str, Any]:
    if not scene_path.exists():
        return {
            "ok": False,
            "path": str(scene_path),
            "kind": "scene",
            "metadata": {"scene_id": scene_id, "name": str(scene_id)},
            "tree": [],
            "issues": [issue("error", "SCENE", f"Scene file does not exist: {scene_path}.")],
        }
    try:
        doc = read_json_file(scene_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "path": str(scene_path),
            "kind": "scene",
            "metadata": {"scene_id": scene_id, "name": str(scene_id)},
            "tree": [],
            "issues": [issue("error", "SCENE", f"Could not parse scene JSON: {exc}", "Fix scene.json JSON.")],
        }
    return validate_scene_doc(scene_path, scene_id, doc, limits)


def list_scene_summaries(project_root: Path, limits: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    scene_files, issues = iter_scene_files(project_root)
    return [load_scene_summary(scene_id, path, limits) for scene_id, path in scene_files], issues


def find_scene(project_root: Path, scene_ref: str, limits: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, str]]]:
    summaries, issues = list_scene_summaries(project_root, limits)
    if scene_ref.isdigit():
        scene_id = int(scene_ref)
        for summary in summaries:
            if summary["metadata"].get("scene_id") == scene_id:
                try:
                    return summary, read_json_file(Path(summary["path"])), issues
                except Exception as exc:  # noqa: BLE001
                    issues.append(issue("error", "SCENE", f"Could not read scene {scene_ref}: {exc}"))
                    return summary, None, issues

    for summary in summaries:
        if str(summary["metadata"].get("name", "")).lower() == scene_ref.lower():
            try:
                return summary, read_json_file(Path(summary["path"])), issues
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "SCENE", f"Could not read scene {scene_ref}: {exc}"))
                return summary, None, issues

    issues.append(
        issue(
            "error",
            "SCENE",
            f"Could not find scene '{scene_ref}'.",
            "Use `bf64 scene ls --project <project>` to list available scene ids and names.",
        )
    )
    return None, None, issues


def validate_project_file(path: Path, limits: dict[str, Any]) -> dict[str, Any]:
    project_root, config_path, config, issues = resolve_project(str(path))
    if project_root is None or config_path is None or config is None:
        return {"ok": False, "path": str(path), "kind": "project", "metadata": {}, "scenes": [], "issues": issues}

    raw_exclusions = config.get("assetExclusions", [])
    if not isinstance(raw_exclusions, list):
        issues.append(
            issue(
                "error",
                "PROJECT_ASSET_EXCLUSIONS",
                "assetExclusions must be an array of assets-relative glob strings.",
                "Use patterns such as reference/** or models/draft/**.",
            )
        )
    else:
        for index, raw_pattern in enumerate(raw_exclusions):
            _normalized, error = normalize_asset_exclusion_pattern(raw_pattern)
            if error:
                issues.append(
                    issue(
                        "error",
                        "PROJECT_ASSET_EXCLUSIONS",
                        f"assetExclusions[{index}]: {error}",
                        "Use a relative pattern under assets/ without empty, '.' or '..' path segments.",
                    )
                )

    scenes, scene_dir_issues = list_scene_summaries(project_root, limits)
    issues.extend(scene_dir_issues)
    scene_ids = {s["metadata"].get("scene_id") for s in scenes}
    for key in ("sceneIdOnBoot", "sceneIdOnReset", "sceneIdLastOpened"):
        value = config.get(key, 1)
        if value not in scene_ids:
            issues.append(
                issue(
                    "error",
                    "PROJECT",
                    f"{key} points to missing scene id {value}.",
                    "Create that scene or update project.p64proj to an existing scene id.",
                    "docs/docs/agent/ARCHITECTURE.md#31-project-format",
                )
            )

    for scene in scenes:
        issues.extend(
            issue(
                item["severity"],
                item["rule"],
                f"Scene {scene['metadata'].get('scene_id')}: {item['message']}",
                item.get("fix", ""),
                item.get("source", ""),
            )
            for item in scene.get("issues", [])
        )

    return {
        "ok": not has_errors(issues),
        "path": str(config_path),
        "kind": "project",
        "metadata": project_summary(project_root, config_path, config),
        "scene_count": len(scenes),
        "scenes": [
            {
                "id": s["metadata"].get("scene_id"),
                "name": s["metadata"].get("name"),
                "path": s["path"],
                "ok": s["ok"],
                "object_count": s["metadata"].get("object_count", 0),
                "component_count": s["metadata"].get("component_count", 0),
                "issues": s.get("issues", []),
            }
            for s in scenes
        ],
        "issues": issues,
    }


def validate_scene_file(path: Path, limits: dict[str, Any]) -> dict[str, Any]:
    try:
        doc = read_json_file(path)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "path": str(path),
            "kind": "scene",
            "metadata": {},
            "issues": [issue("error", "SCENE", f"Could not parse scene JSON: {exc}", "Fix scene.json JSON.")],
        }
    scene_id = optional_int(path.parent.name)
    return validate_scene_doc(path, scene_id, doc, limits)


def validate_prefab_file(
    path: Path,
    limits: dict[str, Any],
    conf: dict[str, Any] | None = None,
    conf_path: str | None = None,
    document: Any | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if document is None:
        try:
            doc = read_json_file(path)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "path": str(path),
                "kind": "prefab",
                "metadata": {"conf": conf_path},
                "issues": [issue("error", "PREFAB_JSON", f"Could not parse prefab JSON: {exc}.")],
            }
    else:
        doc = document

    if not isinstance(doc, dict):
        return {
            "ok": False,
            "path": str(path),
            "kind": "prefab",
            "metadata": {"conf": conf_path},
            "issues": [issue("error", "PREFAB", "Prefab must contain a JSON object.")],
        }

    prefab_uuid = doc.get("uuid")
    if not isinstance(prefab_uuid, int) or prefab_uuid <= 0 or prefab_uuid > 0xFFFFFFFF:
        issues.append(
            issue(
                "error",
                "PREFAB_UUID",
                f"Prefab uuid must be a persistent integer in 1..0xFFFFFFFF; got {prefab_uuid}.",
            )
        )
    if conf is not None:
        conf_uuid = conf.get("uuid")
        if isinstance(prefab_uuid, int) and conf_uuid != prefab_uuid:
            issues.append(
                issue(
                    "error",
                    "PREFAB_UUID",
                    f"Prefab uuid {prefab_uuid} does not match sidecar uuid {conf_uuid}.",
                    "Regenerate or update the sidecar so both UUIDs match.",
                )
            )

    root = doc.get("obj")
    if not isinstance(root, dict):
        issues.append(issue("error", "PREFAB_OBJECT", "Prefab is missing its root obj object."))
        stats = {"object_count": 0, "component_count": 0, "max_depth": 0}
        tree: list[dict[str, Any]] = []
    else:
        stats, object_issues, tree = collect_object_stats(
            {"children": [root]},
            int(limits["engine"]["max_component_id"]),
        )
        for item in object_issues:
            mapped = dict(item)
            mapped["message"] = str(mapped.get("message", "")).replace("scene ", "prefab ").replace("Scene ", "Prefab ")
            rule = str(mapped.get("rule", ""))
            if rule == "SCENE_COMPONENT_UUID":
                mapped["rule"] = "PREFAB_COMPONENT_UUID"
            elif rule.startswith("SCENE_"):
                mapped["rule"] = "PREFAB_" + rule.removeprefix("SCENE_")
            elif rule == "SCENE":
                mapped["rule"] = "PREFAB_OBJECT"
            issues.append(mapped)

        if root.get("uuidPrefab", 0) not in {0, None}:
            issues.append(issue("error", "PREFAB_OBJECT", "Prefab root obj must use uuidPrefab 0."))
        max_objects = int(limits["scene"]["max_objects"])
        if int(stats.get("object_count", 0)) > max_objects:
            issues.append(
                issue(
                    "error",
                    "PREFAB_OBJECT_LIMIT",
                    f"Prefab has {stats['object_count']} objects, exceeding the {max_objects} runtime id budget.",
                )
            )

    metadata = {
        "conf": conf_path,
        "uuid": prefab_uuid,
        "name": root.get("name") if isinstance(root, dict) else None,
        "object_count": int(stats.get("object_count", 0)),
        "component_count": int(stats.get("component_count", 0)),
        "max_depth": int(stats.get("max_depth", 0)),
        "tree": tree,
    }
    return {"ok": not has_errors(issues), "path": str(path), "kind": "prefab", "metadata": metadata, "issues": issues}


def known_node_graph_type_ids(project_root: Path | None) -> set[str]:
    roots = [REPO_ROOT / "data" / "nodes", REPO_ROOT / "src" / "project" / "graph"]
    if project_root is not None:
        roots.append(project_root / "nodes")
    ids: set[str] = set()
    patterns = (
        re.compile(r"\bid\s*:\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"\.id\s*=\s*['\"]([^'\"]+)['\"]"),
    )
    for root in roots:
        if not root.exists():
            continue
        paths = [root] if root.is_file() else root.rglob("*")
        for source in paths:
            if not source.is_file() or source.suffix.lower() not in {".js", ".cpp"}:
                continue
            try:
                text = source.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in patterns:
                ids.update(pattern.findall(text))
    return ids


def validate_node_graph_file(
    path: Path,
    project_root: Path | None = None,
    conf_path: str | None = None,
    document: Any | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if document is None:
        try:
            doc = read_json_file(path)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "path": str(path),
                "kind": "node_graph",
                "metadata": {"conf": conf_path},
                "issues": [issue("error", "NODE_GRAPH_JSON", f"Could not parse node graph JSON: {exc}.")],
            }
    else:
        doc = document
    if not isinstance(doc, dict):
        return {
            "ok": False,
            "path": str(path),
            "kind": "node_graph",
            "metadata": {"conf": conf_path},
            "issues": [issue("error", "NODE_GRAPH", "Node graph must contain a JSON object.")],
        }

    repeatable = doc.get("repeatable", False)
    if not isinstance(repeatable, bool):
        issues.append(issue("error", "NODE_GRAPH", "repeatable must be boolean."))
    view = doc.get("view", [0.0, 0.0, 1.0])
    if not isinstance(view, list) or len(view) != 3 or any(not isinstance(value, (int, float)) for value in view):
        issues.append(issue("error", "NODE_GRAPH_VIEW", "view must be [scrollX, scrollY, scale]."))
    elif float(view[2]) <= 0:
        issues.append(issue("error", "NODE_GRAPH_VIEW", "view scale must be greater than zero."))

    variables = doc.get("variables", [])
    variable_names: set[str] = set()
    if not isinstance(variables, list):
        issues.append(issue("error", "NODE_GRAPH_VARIABLE", "variables must be an array."))
        variables = []
    for index, variable in enumerate(variables):
        if not isinstance(variable, dict):
            issues.append(issue("error", "NODE_GRAPH_VARIABLE", f"variables[{index}] must be an object."))
            continue
        name = variable.get("name")
        value_type = variable.get("type", "i32")
        if not isinstance(name, str) or not name.strip():
            issues.append(issue("error", "NODE_GRAPH_VARIABLE", f"variables[{index}] requires a non-empty name."))
        elif name in variable_names:
            issues.append(issue("error", "NODE_GRAPH_VARIABLE", f"Duplicate variable name: {name}."))
        else:
            variable_names.add(name)
        if value_type not in NODE_GRAPH_VARIABLE_TYPES:
            issues.append(
                issue(
                    "error",
                    "NODE_GRAPH_VARIABLE",
                    f"Variable {name or index} uses unknown type {value_type}; expected one of {sorted(NODE_GRAPH_VARIABLE_TYPES)}.",
                )
            )

    nodes = doc.get("nodes", [])
    node_ids: set[int] = set()
    start_count = 0
    object_ref_slots: set[int] = set()
    known_types = known_node_graph_type_ids(project_root)
    if not isinstance(nodes, list):
        issues.append(issue("error", "NODE_GRAPH_NODE", "nodes must be an array."))
        nodes = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            issues.append(issue("error", "NODE_GRAPH_NODE", f"nodes[{index}] must be an object."))
            continue
        node_uuid = node.get("uuid")
        if not isinstance(node_uuid, int) or node_uuid <= 0 or node_uuid > 0xFFFFFFFFFFFFFFFF:
            issues.append(issue("error", "NODE_GRAPH_NODE", f"nodes[{index}] has invalid uuid {node_uuid}."))
        elif node_uuid in node_ids:
            issues.append(issue("error", "NODE_GRAPH_NODE", f"Duplicate node uuid {node_uuid}."))
        else:
            node_ids.add(node_uuid)
        type_id = node.get("typeId")
        legacy_type = node.get("type")
        if not isinstance(type_id, str) or not type_id.strip():
            if not isinstance(legacy_type, int) or legacy_type < 0:
                issues.append(issue("error", "NODE_GRAPH_TYPE", f"nodes[{index}] requires typeId or a legacy type index."))
        else:
            if type_id == "core.start":
                start_count += 1
            if type_id not in known_types:
                issues.append(
                    issue(
                        "warning",
                        "NODE_GRAPH_TYPE",
                        f"Node type {type_id} is not registered by BF64 or this project's nodes/*.js.",
                        "Install/restore its node definition before building; the editor preserves it as a placeholder.",
                    )
                )
            if type_id in {"core.varGet", "core.varSet"} and node.get("var") not in variable_names:
                issues.append(issue("error", "NODE_GRAPH_VARIABLE", f"Node {node_uuid} references missing variable {node.get('var')!r}."))
        pos = node.get("pos")
        if not isinstance(pos, list) or len(pos) != 2 or any(not isinstance(value, (int, float)) for value in pos):
            issues.append(issue("error", "NODE_GRAPH_NODE", f"nodes[{index}] pos must contain two numbers."))
        if "objRefSlot" in node:
            slot = node.get("objRefSlot")
            if not isinstance(slot, int) or slot < 0 or slot > 0xFFFF or slot in object_ref_slots:
                issues.append(issue("error", "NODE_GRAPH_OBJECT_REF", f"Node {node_uuid} has invalid/duplicate objRefSlot {slot}."))
            else:
                object_ref_slots.add(slot)

    links = doc.get("links", [])
    seen_links: set[tuple[int, int, int, int]] = set()
    if not isinstance(links, list):
        issues.append(issue("error", "NODE_GRAPH_LINK", "links must be an array."))
        links = []
    for index, link in enumerate(links):
        if not isinstance(link, dict):
            issues.append(issue("error", "NODE_GRAPH_LINK", f"links[{index}] must be an object."))
            continue
        src, dst = link.get("src"), link.get("dst")
        src_port, dst_port = link.get("srcPort", 0), link.get("dstPort", 0)
        if src not in node_ids or dst not in node_ids:
            issues.append(issue("error", "NODE_GRAPH_LINK", f"links[{index}] references missing node(s): {src} -> {dst}."))
        if not isinstance(src_port, int) or src_port < 0 or not isinstance(dst_port, int) or dst_port < 0:
            issues.append(issue("error", "NODE_GRAPH_LINK", f"links[{index}] ports must be non-negative integers."))
        if all(isinstance(value, int) for value in (src, src_port, dst, dst_port)):
            key = (src, src_port, dst, dst_port)
            if key in seen_links:
                issues.append(issue("error", "NODE_GRAPH_LINK", f"Duplicate link {key}."))
            seen_links.add(key)
        points = link.get("points", [])
        if not isinstance(points, list) or any(
            not isinstance(point, list)
            or len(point) != 2
            or any(not isinstance(value, (int, float)) for value in point)
            for point in points
        ):
            issues.append(issue("error", "NODE_GRAPH_LINK", f"links[{index}] points must be [x, y] pairs."))

    groups = doc.get("groups", [])
    if not isinstance(groups, list):
        issues.append(issue("error", "NODE_GRAPH_GROUP", "groups must be an array."))
        groups = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            issues.append(issue("error", "NODE_GRAPH_GROUP", f"groups[{index}] must be an object."))
            continue
        for key in ("pos", "size"):
            value = group.get(key)
            if not isinstance(value, list) or len(value) != 2 or any(not isinstance(item, (int, float)) for item in value):
                issues.append(issue("error", "NODE_GRAPH_GROUP", f"groups[{index}].{key} must contain two numbers."))
        if not isinstance(group.get("title", ""), str):
            issues.append(issue("error", "NODE_GRAPH_GROUP", f"groups[{index}].title must be a string."))

    if nodes and start_count == 0:
        issues.append(issue("warning", "NODE_GRAPH_START", "Graph has no core.start node; auto-run has no logic entry point."))
    if start_count > 1:
        issues.append(issue("warning", "NODE_GRAPH_START", f"Graph has {start_count} core.start nodes."))

    metadata = {
        "conf": conf_path,
        "repeatable": repeatable,
        "node_count": len(nodes),
        "link_count": len(links),
        "variable_count": len(variables),
        "group_count": len(groups),
        "start_node_count": start_count,
    }
    return {"ok": not has_errors(issues), "path": str(path), "kind": "node_graph", "metadata": metadata, "issues": issues}


def validate_texture(
    path: Path,
    conf: dict[str, Any],
    conf_path: str | None,
    args: argparse.Namespace,
    limits: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    metadata: dict[str, Any] = {"conf": conf_path}
    ext = path.suffix.lower()

    if ext != ".png":
        issues.append(
            issue(
                "error",
                "T1",
                f"BF64 image assets must be .png, got {ext or '(no extension)'}.",
                "Convert the image to PNG before importing.",
                "docs/docs/n64/asset-checklist.md#textures-png",
            )
        )
        return {"ok": False, "path": str(path), "kind": "texture", "metadata": metadata, "issues": issues}

    try:
        png = read_png_info(path)
        metadata.update(png)
    except Exception as exc:  # noqa: BLE001
        issues.append(issue("error", "T1", f"Could not read PNG header: {exc}", "Re-export a valid PNG."))
        return {"ok": False, "path": str(path), "kind": "texture", "metadata": metadata, "issues": issues}

    if "__parse_error__" in conf:
        issues.append(issue("error", "CONF", f"Could not parse conf JSON: {conf['__parse_error__']}"))

    explicit_format = args.texture_format if args.texture_format is not None else conf.get("format")
    fmt = parse_texture_format(explicit_format, limits)
    inferred = infer_texture_format_from_name(path, limits)
    if fmt is None:
        if explicit_format is not None:
            allowed = ", ".join(sorted(limits["texture"]["format_ids"].keys()))
            issues.append(
                issue(
                    "error",
                    "T4",
                    f"Unknown texture format '{explicit_format}'.",
                    f"Use one of: {allowed}.",
                    "docs/docs/n64/textures.md#2-texture-format-map",
                )
            )
        fmt = inferred or ("RGBA16", int(limits["texture"]["format_ids"]["RGBA16"]))
        if inferred is None and explicit_format is None:
            issues.append(
                issue(
                    "warning",
                    "T4",
                    "Texture format is AUTO or unknown; validator is using RGBA16 as a conservative TMEM check.",
                    "Pass --texture-format or use a format suffix such as .ci4.png when you need exact validation.",
                    "docs/docs/n64/textures.md#24-auto-autodetection-mkspritec344-369",
                )
            )
    elif fmt[0] == "AUTO":
        fmt = inferred or ("RGBA16", int(limits["texture"]["format_ids"]["RGBA16"]))
        if inferred is None:
            issues.append(
                issue(
                    "warning",
                    "T4",
                    "Texture format is AUTO; exact mksprite palette downgrades require running mksprite.",
                    "Use --texture-format for a strict preflight check.",
                    "docs/docs/n64/textures.md#24-auto-autodetection-mkspritec344-369",
                )
            )

    fmt_name, fmt_id = fmt
    metadata["format"] = fmt_name
    metadata["format_id"] = fmt_id

    compression = conf.get("compression")
    compression_id = optional_int(compression)
    if compression is not None and (compression_id is None or compression_id not in {0, 1, 2, 3}):
        issues.append(
            issue(
                "error",
                "T8",
                f"compression must be 0, 1, 2, or 3; got {compression}.",
                "Set compression to 0 (default), 1 (LZ4), 2 (APLib), or 3 (Shrinkler).",
                "docs/docs/n64/asset-checklist.md#textures-png",
            )
        )

    width = int(metadata["width"])
    height = int(metadata["height"])
    try:
        scene_pipeline = pipeline_id(args.scene_pipeline)
    except ValueError as exc:
        scene_pipeline = None
        issues.append(issue("error", "S1", str(exc), "Use --scene-pipeline default, hdr, bigtex, 0, 1, or 2."))
    metadata["scene_pipeline"] = scene_pipeline

    if fmt_name == "BCI_256" or path.name.lower().endswith(".bci.png"):
        bci = limits["texture"]["formats"]["BCI_256"]
        metadata["estimated_rom_bytes"] = (width // 4) * (height // 4) * bci["bytes_per_block_4x4"]
        if width != bci["bf64_required_width"] or height != bci["bf64_required_height"]:
            issues.append(
                issue(
                    "error",
                    "T5",
                    f"BF64 BigTex BCI textures must be exactly 256x256; got {width}x{height}.",
                    "Resize to 256x256 or do not use the .bci.png extension.",
                    "docs/docs/n64/asset-checklist.md#textures-png",
                )
            )
        if width % 4 != 0 or height % 4 != 0:
            issues.append(issue("error", "T5", "BCI dimensions must be multiples of 4."))
        if scene_pipeline is None:
            issues.append(
                issue(
                    "warning",
                    "T6",
                    "Scene pipeline was not supplied; cannot prove this BCI texture is used only in BigTex.",
                    "Pass --scene-pipeline bigtex when validating a BigTex scene asset.",
                    "docs/docs/n64/textures.md#73-when-to-use-bigtex",
                )
            )
        elif scene_pipeline != 2:
            issues.append(
                issue(
                    "error",
                    "T6",
                    ".bci.png textures only work with scene renderPipeline 2 (BigTex).",
                    "Set the scene to BigTex or convert this texture to a normal sprite format.",
                    "docs/docs/n64/asset-checklist.md#textures-png",
                )
            )
    else:
        if width > 256 or height > 256:
            issues.append(
                issue(
                    "error",
                    "T9",
                    f"Non-BigTex texture dimensions must not exceed 256x256; got {width}x{height}.",
                    "Use BigTex for 256x256 large textures or reduce dimensions to fit TMEM.",
                    "docs/docs/n64/asset-checklist.md#textures-png",
                )
            )
        fmt_limits = limits["texture"]["formats"].get(fmt_name)
        if fmt_limits and "max_texels" in fmt_limits:
            texels = width * height
            metadata["texels"] = texels
            metadata["max_texels"] = fmt_limits["max_texels"]
            metadata["estimated_rom_bytes"] = estimate_texture_bytes(width, height, fmt_name, limits)
            if texels > int(fmt_limits["max_texels"]):
                severity = "error" if explicit_format not in (None, 0, "0", "AUTO", "auto") else "warning"
                issues.append(
                    issue(
                        severity,
                        "T3",
                        f"{fmt_name} texture is {texels} texels, exceeding the {fmt_limits['max_texels']} texel TMEM budget.",
                        "Choose CI4/CI8/I4/I8 when appropriate, reduce dimensions, or use BigTex.",
                        "docs/docs/n64/textures.md#32-max-texture-dimensions-that-fit-tmem",
                    )
                )

    return {
        "ok": not has_errors(issues),
        "path": str(path),
        "kind": "texture",
        "metadata": metadata,
        "issues": issues,
    }


def estimate_texture_bytes(width: int, height: int, fmt_name: str, limits: dict[str, Any]) -> int:
    if fmt_name == "BCI_256":
        return (width // 4) * (height // 4) * limits["texture"]["formats"]["BCI_256"]["bytes_per_block_4x4"]
    fmt = limits["texture"]["formats"].get(fmt_name, {})
    bpt = float(fmt.get("bytes_per_texel", 2))
    palette = 0
    if fmt_name == "CI8":
        palette = 512
    elif fmt_name == "CI4":
        palette = 32
    return int((width * height * bpt) + palette)


def read_gltf_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".gltf":
        return json.loads(path.read_text(encoding="utf-8"))

    with path.open("rb") as fh:
        header = fh.read(12)
        if len(header) != 12:
            raise ValueError("GLB header is truncated")
        magic, version, _length = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2:
            raise ValueError("not a GLB v2 file")
        chunk_header = fh.read(8)
        if len(chunk_header) != 8:
            raise ValueError("GLB JSON chunk header is truncated")
        chunk_len, chunk_type = struct.unpack("<I4s", chunk_header)
        if chunk_type != b"JSON":
            raise ValueError("first GLB chunk is not JSON")
        raw = fh.read(chunk_len)
    return json.loads(raw.decode("utf-8"))


def validate_model(
    path: Path,
    conf: dict[str, Any],
    conf_path: str | None,
    _args: argparse.Namespace,
    limits: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    metadata: dict[str, Any] = {"conf": conf_path}
    if path.suffix.lower() not in set(limits["model"]["accepted_extensions"]):
        issues.append(
            issue(
                "error",
                "M1",
                f"BF64 model assets must be .glb or .gltf, got {path.suffix or '(no extension)'}.",
                "Export the model as glTF/GLB with Fast64 custom properties.",
            )
        )
        return {"ok": False, "path": str(path), "kind": "model", "metadata": metadata, "issues": issues}

    try:
        doc = read_gltf_json(path)
    except Exception as exc:  # noqa: BLE001
        issues.append(issue("error", "M1", f"Could not parse glTF/GLB JSON: {exc}", "Re-export a valid glTF/GLB."))
        return {"ok": False, "path": str(path), "kind": "model", "metadata": metadata, "issues": issues}

    accessors = doc.get("accessors") or []
    vertex_count = 0
    index_count = 0
    has_weights = False
    for mesh in doc.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            attrs = prim.get("attributes") or {}
            pos_idx = attrs.get("POSITION")
            if isinstance(pos_idx, int) and pos_idx < len(accessors):
                count = int(accessors[pos_idx].get("count") or 0)
                vertex_count += count
                if prim.get("indices") is None:
                    index_count += count
            idx_idx = prim.get("indices")
            if isinstance(idx_idx, int) and idx_idx < len(accessors):
                index_count += int(accessors[idx_idx].get("count") or 0)
            if "WEIGHTS_0" in attrs or "JOINTS_1" in attrs or "WEIGHTS_1" in attrs:
                has_weights = True

    metadata["vertex_count"] = vertex_count
    metadata["index_count"] = index_count
    if vertex_count > int(limits["model"]["max_vertices_per_file"]):
        issues.append(
            issue(
                "error",
                "M4",
                f"Model has {vertex_count} vertices, exceeding the 65535 per-file cap.",
                "Split the model into multiple GLB files.",
                "docs/docs/n64/models-and-meshes.md#hard-limits",
            )
        )
    if index_count > int(limits["model"]["max_indices_per_file"]):
        issues.append(
            issue(
                "error",
                "M4",
                f"Model has {index_count} indices, exceeding the 65535 per-file cap.",
                "Split the model into multiple GLB files.",
                "docs/docs/n64/models-and-meshes.md#hard-limits",
            )
        )
    if has_weights:
        issues.append(
            issue(
                "warning",
                "M5",
                "Model includes skin weights; BF64/tiny3d keeps only one bone influence per vertex.",
                "Use rigid skinning or verify deformation after import.",
                "docs/docs/n64/models-and-meshes.md#31-skinning-one-bone-per-vertex",
            )
        )

    materials = doc.get("materials") or []
    missing_fast64 = []
    for idx, mat in enumerate(materials):
        extras = mat.get("extras") or {}
        if "f3d_mat" not in extras:
            missing_fast64.append(mat.get("name") or f"material[{idx}]")
    metadata["material_count"] = len(materials)
    if materials and missing_fast64:
        issues.append(
            issue(
                "error",
                "M3",
                f"{len(missing_fast64)} material(s) are missing Fast64 f3d_mat extras: {', '.join(missing_fast64[:5])}.",
                "Export from Blender with Fast64 material custom properties enabled.",
                "docs/docs/n64/models-and-meshes.md#52-material-data-source-fast64-f3d_mat-extras",
            )
        )

    allowed_targets = set(limits["model"]["allowed_animation_targets"])
    max_seconds = 0.0
    bad_targets: list[str] = []
    non_linear = False
    for anim in doc.get("animations") or []:
        samplers = anim.get("samplers") or []
        for sampler in samplers:
            if sampler.get("interpolation") in {"STEP", "CUBICSPLINE"}:
                non_linear = True
            input_idx = sampler.get("input")
            if isinstance(input_idx, int) and input_idx < len(accessors):
                mx = accessors[input_idx].get("max")
                if isinstance(mx, list) and mx:
                    try:
                        max_seconds = max(max_seconds, float(mx[0]))
                    except (TypeError, ValueError):
                        pass
        for channel in anim.get("channels") or []:
            target = (channel.get("target") or {}).get("path")
            if target and target not in allowed_targets:
                bad_targets.append(str(target))
    metadata["max_animation_seconds"] = max_seconds
    if max_seconds > float(limits["model"]["max_animation_seconds"]):
        issues.append(
            issue(
                "error",
                "M8",
                f"Animation duration is {max_seconds:.2f}s, exceeding the {limits['model']['max_animation_seconds']:.2f}s u16 tick cap.",
                "Split or shorten the clip.",
                "docs/docs/n64/models-and-meshes.md#64-timing-keyframes-and-sdata-streaming",
            )
        )
    if doc.get("animations"):
        issues.append(
            issue(
                "info",
                "M8",
                "Validator cannot prove optimized retained keyframe gaps stay below 32768 ticks without running the tiny3d importer.",
                "Run a real build after this preflight; importer asserts are still the source of truth.",
            )
        )
    if bad_targets:
        issues.append(
            issue(
                "error",
                "M7",
                f"Unsupported animation target(s): {', '.join(sorted(set(bad_targets)))}.",
                "Use only translation, rotation, and scale channels.",
                "docs/docs/n64/asset-checklist.md#models-glb--gltf",
            )
        )
    if non_linear:
        issues.append(
            issue(
                "warning",
                "M7",
                "STEP or CUBICSPLINE interpolation is present; tiny3d importer resamples as linear/slerp.",
                "Bake animation at 60 Hz if exact interpolation matters.",
                "docs/docs/n64/models-and-meshes.md#63-interpolation-is-ignored",
            )
        )

    return {"ok": not has_errors(issues), "path": str(path), "kind": "model", "metadata": metadata, "issues": issues}


def read_wav_info(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        if fh.read(4) != b"RIFF":
            raise ValueError("missing RIFF header")
        fh.read(4)
        if fh.read(4) != b"WAVE":
            raise ValueError("missing WAVE header")
        fmt: dict[str, Any] = {}
        data_bytes = 0
        while True:
            hdr = fh.read(8)
            if len(hdr) < 8:
                break
            chunk_id, size = struct.unpack("<4sI", hdr)
            payload = fh.read(size)
            if size % 2:
                fh.read(1)
            if chunk_id == b"fmt " and len(payload) >= 16:
                audio_fmt, channels, sample_rate, byte_rate, _align, bits = struct.unpack("<HHIIHH", payload[:16])
                fmt = {
                    "audio_format": audio_fmt,
                    "channels": channels,
                    "sample_rate": sample_rate,
                    "byte_rate": byte_rate,
                    "bits_per_sample": bits,
                }
            elif chunk_id == b"data":
                data_bytes += size
    if not fmt:
        raise ValueError("missing fmt chunk")
    fmt["data_bytes"] = data_bytes
    if fmt.get("byte_rate"):
        fmt["duration_seconds"] = data_bytes / fmt["byte_rate"]
    return fmt


def read_xm_channels(path: Path) -> int | None:
    with path.open("rb") as fh:
        data = fh.read(80)
    if len(data) < 70 or not data.startswith(b"Extended Module: "):
        return None
    return struct.unpack("<H", data[68:70])[0]


def validate_audio(
    path: Path,
    conf: dict[str, Any],
    conf_path: str | None,
    args: argparse.Namespace,
    limits: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    metadata: dict[str, Any] = {"conf": conf_path}
    ext = path.suffix.lower()
    accepted = set(limits["audio"]["editor_accepted_extensions"])
    if ext not in accepted:
        if ext in set(limits["audio"]["manual_only_extensions"]):
            issues.append(
                issue(
                    "error",
                    "A1",
                    f"{ext} can be converted manually but BF64 editor does not classify it as an audio asset.",
                    "Use .wav, .mp3, or .xm for BF64 editor import, or invoke audioconv64 manually.",
                    "docs/docs/n64/audio-assets.md#12-bf64-editor-asset-classification",
                )
            )
        else:
            issues.append(
                issue(
                    "error",
                    "A1",
                    f"BF64 editor audio assets must be .wav, .mp3, or .xm; got {ext or '(no extension)'}.",
                    "Convert to WAV/MP3 or use XM for tracker music.",
                    "docs/docs/n64/asset-checklist.md#audio-wav--mp3--xm",
                )
            )

    wav_compression = conf.get("wavCompression")
    wav_compression_id = optional_int(wav_compression)
    if wav_compression is not None and (wav_compression_id is None or wav_compression_id not in {0, 1, 3}):
        issues.append(
            issue(
                "error",
                "A2",
                f"wavCompression must be 0, 1, or 3; got {wav_compression}.",
                "Use 1 for VADPCM, 3 for long Opus audio, or 0 for raw PCM.",
                "docs/docs/n64/audio-assets.md#61-wav-compress-values",
            )
        )

    resample_raw = conf.get("wavResampleRate")
    resample = optional_int(resample_raw) or 0
    metadata["wavResampleRate"] = resample
    if resample_raw is not None and optional_int(resample_raw) is None:
        issues.append(
            issue(
                "error",
                "A3",
                f"wavResampleRate must be an integer sample rate; got {resample_raw}.",
                "Use 0, 8000, 11025, 16000, 22050, 32000, 44100, or 48000.",
                "docs/docs/n64/audio-assets.md#41-resample-rates",
            )
        )
    if resample > int(limits["audio"]["wav_resample_cli_max"]):
        issues.append(issue("error", "A3", f"wavResampleRate {resample} exceeds audioconv64 max 48000."))
    elif resample == 48000:
        issues.append(
            issue(
                "warning",
                "A3",
                "48000 Hz is accepted by audioconv64 but not offered by the BF64 UI dropdown.",
                "Use 48000 only when intentionally targeting Opus.",
                "docs/docs/n64/audio-assets.md#41-resample-rates",
            )
        )

    if wav_compression_id == 3 and resample not in {0, 48000}:
        issues.append(
            issue(
                "warning",
                "A4",
                "Opus forces 48000 Hz internally; non-48000 wavResampleRate is repurposed as a bitrate hint.",
                "Use wavResampleRate 0 or 48000 for clearer intent.",
                "docs/docs/n64/audio-assets.md#45-opus-forces-48-khz",
            )
        )

    if ext == ".wav":
        try:
            metadata.update(read_wav_info(path))
        except Exception as exc:  # noqa: BLE001
            issues.append(
                issue(
                    "error",
                    "A10",
                    f"WAV source is malformed or unreadable: {exc}.",
                    "Replace or re-export the source as a valid RIFF/WAVE file before building.",
                    "docs/docs/n64/asset-checklist.md#audio-wav--mp3--xm",
                )
            )
    elif ext == ".mp3":
        issues.append(
            issue(
                "info",
                "A1",
                "MP3 is accepted and all --wav-* flags apply, but it is decoded and re-encoded for ROM.",
                "For long recorded music, consider Opus; for game music, consider XM64.",
                "docs/docs/n64/audio-assets.md#3-the-mp3-open-question--definitively-answered",
            )
        )
    elif ext == ".xm":
        channels = read_xm_channels(path)
        metadata["xm_channels"] = channels
        if channels is not None and channels > int(limits["audio"]["xm"]["max_channels"]):
            issues.append(
                issue(
                    "error",
                    "A8",
                    f"XM has {channels} channels, exceeding the 32-channel mixer cap.",
                    "Reduce module channel count to <=32.",
                    "docs/docs/n64/audio-assets.md#77-runtime-channel-count",
                )
            )
        if wav_compression_id == 3:
            issues.append(
                issue(
                    "warning",
                    "A6",
                    "BF64 does not pass wavCompression to MUSIC_XM, so this config value is ignored for .xm assets.",
                    "Do not request opus via manual --xm-compress; XM64 supports raw or VADPCM samples.",
                    "docs/docs/n64/asset-checklist.md#audio-wav--mp3--xm",
                )
            )

    if args.role == "sfx" and ext in {".wav", ".mp3"} and conf.get("wavForceMono") is False:
        issues.append(
            issue(
                "warning",
                "A5",
                "SFX should usually set wavForceMono true; stereo doubles ROM size and channel pressure.",
                "Set wavForceMono: true for positional/non-music SFX.",
                "docs/docs/n64/audio-assets.md#54-mono-vs-stereo",
            )
        )

    return {"ok": not has_errors(issues), "path": str(path), "kind": "audio", "metadata": metadata, "issues": issues}


def validate_font(path: Path, conf_path: str | None) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if path.suffix.lower() not in {".ttf", ".otf"}:
        issues.append(
            issue(
                "error",
                "F1",
                f"Font assets must be .ttf or .otf, got {path.suffix or '(no extension)'}.",
                "Convert or choose a TrueType/OpenType font.",
                "docs/docs/n64/asset-checklist.md#fonts-ttf",
            )
        )
    return {"ok": not has_errors(issues), "path": str(path), "kind": "font", "metadata": {"conf": conf_path}, "issues": issues}


def classify_asset(path: Path) -> str:
    lower = path.name.lower()
    ext = path.suffix.lower()
    if ext == ".p64proj":
        return "project"
    if lower == "scene.json":
        return "scene"
    if ext == ".png":
        return "texture"
    if ext in {".glb", ".gltf"}:
        return "model"
    if ext in {".wav", ".mp3", ".xm", ".aiff", ".ym", ".it", ".s3m", ".mod"}:
        return "audio"
    if ext in {".ttf", ".otf"}:
        return "font"
    if ext == ".bfui":
        return "ui"
    if lower.endswith(".prefab"):
        return "prefab"
    if lower.endswith(".p64graph"):
        return "node_graph"
    return "unknown"


def asset_conf_path(asset_path: Path) -> Path:
    return Path(str(asset_path) + ".conf")


def path_relative_to(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def is_path_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def conf_parse_issue(conf: dict[str, Any], conf_path: str | None) -> dict[str, str] | None:
    if "__parse_error__" not in conf:
        return None
    return issue(
        "error",
        "CONF",
        f"Could not parse asset sidecar {conf_path}: {conf['__parse_error__']}",
        "Fix the sidecar JSON or remove it so BF64 can regenerate metadata.",
        "docs/docs/agent/ARCHITECTURE.md#31-project-format",
    )


def asset_output_paths(project_root: Path, path: Path, kind: str) -> dict[str, str]:
    rel_project = path_relative_to(path, project_root)
    rel_assets = rel_project
    if rel_assets.startswith("assets/"):
        rel_assets = rel_assets[len("assets/") :]

    out_path = Path("filesystem") / rel_assets
    lower = path.name.lower()
    ext = path.suffix.lower()
    new_ext: str | None = None
    if kind == "texture":
        new_ext = ".bci" if lower.endswith(".bci.png") else ".sprite"
    elif kind == "audio" and ext in {".wav", ".mp3"}:
        new_ext = ".wav64"
    elif kind == "audio" and ext == ".xm":
        new_ext = ".xm64"
    elif kind == "model":
        new_ext = ".t3dm"
    elif kind == "font" and ext in {".ttf", ".otf"}:
      new_ext = ".font64"
    elif kind == "ui":
        new_ext = ".ui64"
    elif kind == "prefab":
        new_ext = ".pf"
    elif kind == "node_graph":
        new_ext = ".pg"

    if new_ext is None:
        return {}

    out_path = out_path.with_suffix(new_ext)
    out = str(out_path)
    return {
        "out_path": out,
        "rom_path": "rom:/" + out.removeprefix("filesystem/"),
    }


def asset_entry(
    project_root: Path,
    path: Path,
    exclusion_patterns: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    kind = classify_asset(path)
    conf, conf_path = load_conf(path, None)
    parse_issue = conf_parse_issue(conf, conf_path)
    conf_exists = conf_path is not None
    conf_ok = parse_issue is None
    safe_conf, conf_defaulted_fields = normalize_asset_conf(conf if conf_ok else {})
    try:
        size_bytes = path.stat().st_size
    except OSError:
        size_bytes = 0

    asset_path = path_relative_to(path, project_root / "assets")
    patterns = exclusion_patterns if exclusion_patterns is not None else load_asset_exclusion_patterns(project_root)
    matched_patterns = matching_asset_exclusion_patterns(asset_path, patterns)
    sidecar_excluded = bool(safe_conf.get("exclude", False))
    project_excluded = bool(matched_patterns)
    effective_excluded = sidecar_excluded or project_excluded
    exclude_source: str | None = None
    if sidecar_excluded and project_excluded:
        exclude_source = "sidecar+project"
    elif sidecar_excluded:
        exclude_source = "sidecar"
    elif project_excluded:
        exclude_source = "project"

    entry: dict[str, Any] = {
        "path": str(path),
        "relative_path": path_relative_to(path, project_root),
        "asset_path": asset_path,
        "name": path.name,
        "extension": path.suffix.lower() or "(none)",
        "kind": kind,
        "validatable": kind in VALIDATABLE_ASSET_KINDS,
        "size_bytes": size_bytes,
        "conf_path": conf_path or str(asset_conf_path(path)),
        "conf_exists": conf_exists,
        "conf_ok": conf_ok,
        "conf_defaulted_fields": conf_defaulted_fields,
        "sidecar_excluded": sidecar_excluded,
        "project_excluded": project_excluded,
        "matched_exclusion_patterns": matched_patterns,
        "exclude": effective_excluded,
        "exclude_source": exclude_source,
        "issues": [parse_issue] if parse_issue else [],
    }
    for key in (
        "uuid",
        "format",
        "baseScale",
        "compression",
        "gltfBVH",
        "wavForceMono",
        "wavResampleRate",
        "wavCompression",
        "fontId",
    ):
        if key in safe_conf:
            entry[key] = safe_conf[key]
    if "fontCharset" in safe_conf:
        entry["fontCharsetLength"] = len(str(safe_conf["fontCharset"]))
    entry.update(asset_output_paths(project_root, path, kind))
    return entry


def scan_project_assets(project_root: Path, kind: str | None = None, include_entries: bool = False) -> dict[str, Any]:
    assets_root = project_root / "assets"
    by_kind: dict[str, int] = {}
    by_extension: dict[str, int] = {}
    conf_count = 0
    missing_assets_for_conf: list[str] = []
    total_files = 0
    entries: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    exclusion_patterns = load_asset_exclusion_patterns(project_root)

    if not assets_root.exists():
        inventory: dict[str, Any] = {
            "assets_root": str(assets_root),
            "exists": False,
            "filter_kind": kind,
            "total_files": 0,
            "total_assets": 0,
            "returned_assets": 0,
            "conf_count": 0,
            "by_kind": {},
            "by_extension": {},
            "missing_assets_for_conf": [],
            "validatable_count": 0,
            "unsupported_count": 0,
            "asset_exclusion_patterns": [configured for configured, _normalized in exclusion_patterns],
            "issues": [],
        }
        if include_entries:
            inventory["assets"] = []
        return inventory

    for path in assets_root.rglob("*"):
        if not path.is_file():
            continue
        total_files += 1
        rel = str(path.relative_to(project_root))
        if path.name.endswith(".conf"):
            conf_count += 1
            asset_path = Path(str(path)[:-5])
            if not asset_path.exists():
                missing_assets_for_conf.append(rel)
            continue
        asset_kind = classify_asset(path)
        by_kind[asset_kind] = by_kind.get(asset_kind, 0) + 1
        ext = path.suffix.lower() or "(none)"
        by_extension[ext] = by_extension.get(ext, 0) + 1
        entry = asset_entry(project_root, path, exclusion_patterns)
        if entry["issues"]:
            issues.extend(entry["issues"])
        entries.append(entry)

    selected_entries = [entry for entry in entries if kind is None or entry["kind"] == kind]
    validatable_count = sum(1 for entry in entries if entry["validatable"])
    unsupported_count = len(entries) - validatable_count

    inventory = {
        "assets_root": str(assets_root),
        "exists": True,
        "filter_kind": kind,
        "total_files": total_files,
        "total_assets": len(entries),
        "returned_assets": len(selected_entries),
        "conf_count": conf_count,
        "by_kind": dict(sorted(by_kind.items())),
        "by_extension": dict(sorted(by_extension.items())),
        "missing_assets_for_conf": missing_assets_for_conf[:50],
        "validatable_count": validatable_count,
        "unsupported_count": unsupported_count,
        "asset_exclusion_patterns": [configured for configured, _normalized in exclusion_patterns],
        "issues": issues,
    }
    if include_entries:
        inventory["assets"] = selected_entries
    return inventory


def asset_inventory(project_root: Path) -> dict[str, Any]:
    inventory = scan_project_assets(project_root, include_entries=False)
    inventory.pop("issues", None)
    return inventory


def toolchain_summary(doctor: dict[str, Any]) -> dict[str, Any]:
    checks = doctor.get("checks", [])
    missing = [check["name"] for check in checks if not check.get("ok")]
    build_tools = {"N64_INST", "mksprite", "audioconv64", "n64tool"}
    emu_tools = {"emulator"}
    return {
        "ok": doctor.get("ok", False),
        "missing": missing,
        "build_ready": not any(name in missing for name in build_tools),
        "run_ready": not any(name in missing for name in emu_tools),
    }


def suggested_next_actions(
    validation: dict[str, Any],
    doctor: dict[str, Any],
    inventory: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if has_errors(validation.get("issues", [])):
        actions.append("Fix project/scene validation errors before attempting a ROM build.")
    if not inventory.get("exists"):
        actions.append("Create an assets/ directory or open/save the project in BF64.")

    toolchain = toolchain_summary(doctor)
    if not toolchain["build_ready"]:
        actions.append("Install/configure the libdragon toolchain before using future build/import commands.")
    if not toolchain["run_ready"]:
        actions.append("Install ares or gopher64 before using future run commands.")
    if not actions:
        actions.append("Project status is clean for the currently implemented read-only checks.")
    return actions


def build_project_status(project_arg: str | None, strict_doctor: bool = False) -> dict[str, Any]:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(project_arg)
    if project_root is None or config_path is None or config is None:
        doctor = build_doctor_result(strict_doctor)
        return {
            "ok": False,
            "command": "project status",
            "kind": "project_status",
            "project": project_arg,
            "doctor": doctor,
            "issues": issues,
            "next_actions": ["Pass --project <project-dir> or --project <path/to/project.p64proj>."],
        }

    validation = validate_project_file(config_path, limits)
    doctor = build_doctor_result(strict_doctor)
    inventory = asset_inventory(project_root)
    status_issues = list(issues)
    status_issues.extend(validation.get("issues", []))
    if strict_doctor:
        status_issues.extend(doctor.get("issues", []))

    result = {
        "ok": not has_errors(status_issues),
        "command": "project status",
        "kind": "project_status",
        "project": project_summary(project_root, config_path, config),
        "validation": validation,
        "doctor": doctor,
        "toolchain": toolchain_summary(doctor),
        "assets": inventory,
        "issues": status_issues,
        "next_actions": suggested_next_actions(validation, doctor, inventory),
    }
    return result


def print_project_status(result: dict[str, Any]) -> None:
    output_result(result, False)
    project = result.get("project")
    if isinstance(project, dict):
        print(f"Project: {project.get('name')} ({project.get('path')})")
        print(f"ROM: {project.get('romName')}")
        print(
            "Scenes: boot={boot} reset={reset} last={last}".format(
                boot=project.get("sceneIdOnBoot"),
                reset=project.get("sceneIdOnReset"),
                last=project.get("sceneIdLastOpened"),
            )
        )
    validation = result.get("validation", {})
    if isinstance(validation, dict):
        print(f"Scene count: {validation.get('scene_count', 0)}")
    assets = result.get("assets", {})
    if isinstance(assets, dict):
        print(f"Assets: {assets.get('total_assets', 0)} files by kind {assets.get('by_kind', {})}")
    toolchain = result.get("toolchain", {})
    if isinstance(toolchain, dict):
        print(f"Toolchain: build_ready={toolchain.get('build_ready')} run_ready={toolchain.get('run_ready')}")
    if result.get("next_actions"):
        print("Next actions:")
        for action in result["next_actions"]:
            print(f"- {action}")


def cmd_project_status(args: argparse.Namespace) -> int:
    result = build_project_status(args.project, args.strict_doctor)
    exit_code = 1 if has_errors(result.get("issues", [])) else 0
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_project_status(result)
    project_path = None
    project = result.get("project")
    if isinstance(project, dict) and project.get("config_path"):
        project_path = Path(project["config_path"])
    record_if_requested(args, result, exit_code, project_path)
    return exit_code


def make_name_safe(name: str) -> str:
    safe_name = ""
    for char in name:
        if char.isascii() and (char.isalnum() or char in {"_", "-"}):
            safe_name += char
        elif char == " ":
            safe_name += "_"
    return safe_name


def default_project_name(project_root: Path) -> str:
    raw = project_root.name.replace("_", " ").replace("-", " ").strip()
    if not raw:
        return "New Project"
    return " ".join(part[:1].upper() + part[1:] for part in raw.split())


def default_rom_name(project_root: Path) -> str:
    safe = make_name_safe(project_root.name)
    return safe or "p64_project"


def new_project_config(name: str, rom_name: str, emulator: str, n64_inst: str) -> dict[str, Any]:
    return {
        "name": name,
        "pathEmu": emulator,
        "pathN64Inst": n64_inst,
        "romName": rom_name,
        "sceneIdLastOpened": 1,
        "sceneIdOnBoot": 1,
        "sceneIdOnReset": 1,
        "assetExclusions": [],
    }


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)


def write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def directory_has_entries(path: Path) -> bool:
    try:
        next(path.iterdir())
        return True
    except StopIteration:
        return False


def add_change(
    changes: list[dict[str, str]],
    *,
    action: str,
    kind: str,
    path: Path,
    source: Path | None = None,
) -> None:
    entry = {"action": action, "kind": kind, "path": str(path)}
    if source:
        entry["source"] = str(source)
    changes.append(entry)


def copy_template_project(
    source_root: Path,
    project_root: Path,
    *,
    force: bool,
    merge: bool,
    changes: list[dict[str, str]],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    preserved_files: set[Path] = set()
    for source in sorted(source_root.rglob("*"), key=lambda item: str(item.relative_to(source_root))):
        relative = source.relative_to(source_root)
        if relative == Path(PROJECT_FILENAME):
            continue
        dest = project_root / relative
        if source.is_dir():
            if dest.exists() and not dest.is_dir():
                issues.append(
                    issue(
                        "error",
                        "NEW_CONFLICT",
                        f"Cannot create directory because a file already exists: {dest}.",
                        "Remove the conflicting path or choose another project directory.",
                    )
                )
                continue
            existed = dest.exists()
            dest.mkdir(parents=True, exist_ok=True)
            add_change(changes, action="skipped" if existed else "created", kind="directory", path=dest, source=source)
            continue

        if dest.exists() and dest.is_dir():
            issues.append(
                issue(
                    "error",
                    "NEW_CONFLICT",
                    f"Cannot write template file because a directory already exists: {dest}.",
                    "Remove the conflicting path or choose another project directory.",
                )
            )
            continue
        if merge and source.name.endswith(".conf"):
            asset_dest = Path(str(dest)[: -len(".conf")])
            if asset_dest in preserved_files:
                add_change(changes, action="skipped", kind="file", path=dest, source=source)
                continue
        if dest.exists() and merge:
            preserved_files.add(dest)
            add_change(changes, action="preserved", kind="file", path=dest, source=source)
            continue
        if dest.exists() and not force:
            issues.append(
                issue(
                    "error",
                    "NEW_EXISTS",
                    f"Refusing to overwrite existing file: {dest}.",
                    "Use an empty target directory or pass --force.",
                )
            )
            continue

        existed = dest.exists()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        add_change(changes, action="overwritten" if existed else "created", kind="file", path=dest, source=source)
    return issues


def remove_known_generated_outputs(project_root: Path, rom_name: str, changes: list[dict[str, str]]) -> None:
    cleanup_paths = [
        project_root / "Makefile",
        project_root / "build",
        project_root / "filesystem",
        project_root / "p64_project.z64",
        project_root / f"{rom_name}.z64",
    ]
    seen: set[Path] = set()
    for path in cleanup_paths:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        kind = "directory" if path.is_dir() else "file"
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        add_change(changes, action="removed", kind=kind, path=path)


def ensure_bootstrap_files(project_root: Path, force: bool, merge: bool, changes: list[dict[str, str]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    bootstrap_dirs = [
        project_root / "data",
        project_root / "data" / "scenes",
        project_root / "assets",
        project_root / "assets" / "p64",
        project_root / "src",
        project_root / "src" / "p64",
        project_root / "src" / "user",
    ]
    for directory in bootstrap_dirs:
        existed = directory.exists()
        if existed and not directory.is_dir():
            issues.append(
                issue(
                    "error",
                    "NEW_CONFLICT",
                    f"Cannot create directory because a file already exists: {directory}.",
                    "Remove the conflicting path or choose another project directory.",
                )
            )
            continue
        directory.mkdir(parents=True, exist_ok=True)
        add_change(changes, action="skipped" if existed else "created", kind="directory", path=directory)

    bootstrap_files = [
        (REPO_ROOT / "data" / "build" / "baseGitignore", project_root / ".gitignore"),
        (REPO_ROOT / "data" / "build" / "baseMakefile.custom", project_root / "Makefile.custom"),
        (REPO_ROOT / "data" / "build" / "assets" / "font.ia4.png", project_root / "assets" / "p64" / "font.ia4.png"),
    ]
    for source, dest in bootstrap_files:
        if not source.exists():
            issues.append(
                issue(
                    "error",
                    "NEW_TEMPLATE",
                    f"Missing bootstrap template file: {source}.",
                    "Restore the repository data/build templates before creating projects.",
                )
            )
            continue
        if dest.exists() and dest.is_dir():
            issues.append(
                issue(
                    "error",
                    "NEW_CONFLICT",
                    f"Cannot write bootstrap file because a directory already exists: {dest}.",
                    "Remove the conflicting path or choose another project directory.",
                )
            )
            continue
        if dest.exists() and merge:
            add_change(changes, action="preserved", kind="file", path=dest, source=source)
            continue
        existed = dest.exists()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        add_change(changes, action="overwritten" if existed else "created", kind="file", path=dest, source=source)
    return issues


def merge_project_gitignore(project_root: Path, changes: list[dict[str, str]]) -> None:
    destination = project_root / ".gitignore"
    sources = [EMPTY_PROJECT_TEMPLATE / ".gitignore", REPO_ROOT / "data" / "build" / "baseGitignore"]
    existing = destination.read_text(encoding="utf-8") if destination.is_file() else ""
    existing_patterns = {
        line.strip() for line in existing.splitlines() if line.strip() and not line.lstrip().startswith("#")
    }
    additions: list[str] = []
    for source in sources:
        if not source.is_file():
            continue
        for line in source.read_text(encoding="utf-8").splitlines():
            pattern = line.strip()
            if not pattern or pattern.startswith("#") or pattern in existing_patterns:
                continue
            existing_patterns.add(pattern)
            additions.append(pattern)
    if not additions:
        return
    merged = existing
    if merged and not merged.endswith("\n"):
        merged += "\n"
    if merged:
        merged += "\n"
    merged += "# BF64 generated paths\n" + "\n".join(additions) + "\n"
    write_text_file(destination, merged)
    add_change(changes, action="merged", kind="file", path=destination)


def scaffold_preflight_issues(project_root: Path) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    conflicts: set[Path] = set()
    if EMPTY_PROJECT_TEMPLATE.is_dir():
        for source in EMPTY_PROJECT_TEMPLATE.rglob("*"):
            relative = source.relative_to(EMPTY_PROJECT_TEMPLATE)
            if relative == Path(PROJECT_FILENAME):
                continue
            destination = project_root / relative
            if source.is_dir() and destination.exists() and not destination.is_dir():
                conflicts.add(destination)
            if source.is_file() and destination.exists() and not destination.is_file():
                conflicts.add(destination)
    for relative in (
        Path("data"), Path("data/scenes"), Path("assets"), Path("assets/p64"),
        Path("src"), Path("src/p64"), Path("src/user"),
    ):
        destination = project_root / relative
        if destination.exists() and not destination.is_dir():
            conflicts.add(destination)
    for relative in (Path(".gitignore"), Path("Makefile.custom"), Path("assets/p64/font.ia4.png"), Path(PROJECT_FILENAME)):
        destination = project_root / relative
        if destination.exists() and not destination.is_file():
            conflicts.add(destination)
    for path in sorted(conflicts):
        issues.append(
            issue(
                "error",
                "NEW_CONFLICT",
                f"Scaffold path has an incompatible existing file/directory: {path}.",
                "Move the conflicting path before initializing; no scaffold files were written.",
            )
        )
    return issues


def new_project_next_actions(result: dict[str, Any]) -> list[str]:
    if has_errors(result.get("issues", [])):
        command = result.get("command", "new")
        return [f"Fix the reported scaffold issue, then rerun `bf64 {command}`."]
    project = result.get("project", {})
    project_path = str(project.get("path", result.get("path", ""))) if isinstance(project, dict) else str(result.get("path", ""))
    quoted = shlex.quote(project_path)
    return [
        f"./bf64 project status --project {quoted} --json",
        f"./bf64 build --project {quoted} --json",
        f"./bf64 run --project {quoted} --json",
    ]


def new_project_artifacts(changes: list[dict[str, str]]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for change in changes:
        if change.get("action") in {"removed", "skipped"}:
            continue
        path = Path(change["path"])
        kind = f"project_scaffold_{change.get('kind', 'path')}"
        key = (kind, str(path))
        if key in seen:
            continue
        seen.add(key)
        artifacts.append(artifact_entry(path, kind))
    return artifacts


def build_new_project(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.path).expanduser()
    config_path = project_root / PROJECT_FILENAME
    name = args.name or default_project_name(project_root)
    rom_name = make_name_safe(args.rom_name) if args.rom_name else default_rom_name(project_root)
    emulator = args.emulator or "ares"
    n64_inst = args.n64_inst or ""
    issues: list[dict[str, str]] = []
    changes: list[dict[str, str]] = []
    merge = bool(getattr(args, "merge", False))
    command_name = str(getattr(args, "command", "new"))
    existing_config: dict[str, Any] | None = None

    if merge and bool(getattr(args, "force", False)):
        issues.append(issue("error", "NEW_MODE", "--merge and --force are mutually exclusive."))

    if project_root.suffix == ".p64proj":
        issues.append(
            issue(
                "error",
                "NEW_PATH",
                "`bf64 new` expects a project directory, not a project.p64proj file path.",
                "Pass a directory path such as `./games/my_game`.",
            )
        )
    if " " in str(project_root.resolve(strict=False)):
        issues.append(
            issue(
                "error",
                "NEW_PATH",
                f"Project path contains spaces: {project_root}.",
                "Choose a path without spaces; the editor and build launcher reject project paths with spaces.",
                "docs/docs/agent/ARCHITECTURE.md#launcher",
            )
        )
    if project_root.exists() and not project_root.is_dir():
        issues.append(
            issue(
                "error",
                "NEW_PATH",
                f"Target exists and is not a directory: {project_root}.",
                "Choose a new directory path.",
            )
        )
    template_root = EMPTY_PROJECT_TEMPLATE.resolve(strict=False)
    project_resolved = project_root.resolve(strict=False)
    if project_resolved == template_root or project_resolved.is_relative_to(template_root):
        issues.append(
            issue(
                "error",
                "NEW_PATH",
                f"Refusing to create a project inside the template directory: {EMPTY_PROJECT_TEMPLATE}.",
                "Choose a target outside n64/examples/empty.",
            )
        )
    if project_root.resolve(strict=False) == REPO_ROOT:
        issues.append(
            issue(
                "error",
                "NEW_PATH",
                "Refusing to create a project at the repository root.",
                "Choose an empty subdirectory or a separate projects directory.",
            )
        )
    if not rom_name:
        issues.append(
            issue(
                "error",
                "NEW_ROM_NAME",
                "ROM name does not contain any filesystem-safe characters.",
                "Use letters, numbers, underscores, or hyphens.",
            )
        )
    if not EMPTY_PROJECT_TEMPLATE.exists():
        issues.append(
            issue(
                "error",
                "NEW_TEMPLATE",
                f"Missing project template: {EMPTY_PROJECT_TEMPLATE}.",
                "Restore n64/examples/empty before creating projects.",
            )
        )
    if project_root.exists() and project_root.is_dir() and directory_has_entries(project_root) and not args.force and not merge:
        issues.append(
            issue(
                "error",
                "NEW_EXISTS",
                f"Target directory is not empty: {project_root}.",
                "Choose an empty directory or pass --force to overwrite scaffold files.",
            )
        )
    if merge and config_path.exists():
        try:
            loaded_config = read_json_file(config_path)
            if not isinstance(loaded_config, dict):
                raise ValueError("project config is not a JSON object")
            existing_config = loaded_config
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(
                issue(
                    "error",
                    "NEW_CONFIG",
                    f"Existing project config cannot be preserved because it is invalid: {exc}.",
                    "Repair or move project.p64proj before merge initialization.",
                )
            )

    if project_root.exists() and project_root.is_dir() and EMPTY_PROJECT_TEMPLATE.exists():
        issues.extend(scaffold_preflight_issues(project_root))

    project_name = str((existing_config or {}).get("name") or name)
    project_rom_name = str((existing_config or {}).get("romName") or rom_name)

    result: dict[str, Any] = {
        "ok": False,
        "command": command_name,
        "kind": "project_init" if command_name == "init" else "project_new",
        "path": str(project_root),
        "template": str(EMPTY_PROJECT_TEMPLATE),
        "force": bool(args.force),
        "merge": merge,
        "project": {
            "path": str(project_root),
            "config_path": str(config_path),
            "name": project_name,
            "romName": project_rom_name,
            "sceneIdOnBoot": (existing_config or {}).get("sceneIdOnBoot", 1),
            "sceneIdOnReset": (existing_config or {}).get("sceneIdOnReset", 1),
            "sceneIdLastOpened": (existing_config or {}).get("sceneIdLastOpened", 1),
        },
        "changes": changes,
        "artifacts": [],
        "validation": None,
        "issues": issues,
        "next_actions": [],
    }
    if has_errors(issues):
        result["next_actions"] = new_project_next_actions(result)
        return result

    try:
        existed = project_root.exists()
        project_root.mkdir(parents=True, exist_ok=True)
        add_change(changes, action="skipped" if existed else "created", kind="directory", path=project_root)
        issues.extend(copy_template_project(EMPTY_PROJECT_TEMPLATE, project_root, force=args.force, merge=merge, changes=changes))
        if not merge:
            remove_known_generated_outputs(project_root, rom_name, changes)
        issues.extend(ensure_bootstrap_files(project_root, args.force, merge, changes))
        if merge:
            merge_project_gitignore(project_root, changes)

        if existing_config is not None:
            config = existing_config
            add_change(changes, action="preserved", kind="file", path=config_path)
        else:
            config = new_project_config(name, rom_name, emulator, n64_inst)
            config_existed = config_path.exists()
            write_json_file(config_path, config)
            add_change(changes, action="overwritten" if config_existed else "created", kind="file", path=config_path)
        result["project"].update(
            {
                "name": config.get("name", name),
                "romName": config.get("romName", rom_name),
                "sceneIdOnBoot": config.get("sceneIdOnBoot", 1),
                "sceneIdOnReset": config.get("sceneIdOnReset", 1),
                "sceneIdLastOpened": config.get("sceneIdLastOpened", 1),
            }
        )
    except Exception as exc:  # noqa: BLE001
        issues.append(
            issue(
                "error",
                "NEW_IO",
                f"Could not create project scaffold: {exc}",
                "Check path permissions and available disk space, then rerun `bf64 new`.",
            )
        )

    if not has_errors(issues):
        validation = validate_project_file(config_path, load_limits())
        result["validation"] = {
            "ok": validation.get("ok", False),
            "scene_count": validation.get("scene_count", 0),
            "issue_count": len(validation.get("issues", [])),
        }
        issues.extend(validation.get("issues", []))

    result["ok"] = not has_errors(issues)
    result["issues"] = issues
    result["artifacts"] = new_project_artifacts(changes)
    result["next_actions"] = new_project_next_actions(result)
    return result


def print_new_result(result: dict[str, Any]) -> None:
    output_result(result, False)
    project = result.get("project")
    if isinstance(project, dict):
        print(f"Project: {project.get('name')} ({project.get('path')})")
        print(f"ROM: {project.get('romName')}")
    changes = result.get("changes", [])
    if isinstance(changes, list):
        created = sum(1 for item in changes if item.get("action") == "created")
        overwritten = sum(1 for item in changes if item.get("action") == "overwritten")
        removed = sum(1 for item in changes if item.get("action") == "removed")
        preserved = sum(1 for item in changes if item.get("action") == "preserved")
        merged = sum(1 for item in changes if item.get("action") == "merged")
        print(f"Changes: created={created} preserved={preserved} merged={merged} overwritten={overwritten} removed={removed}")
    if result.get("next_actions"):
        print("Next actions:")
        for action in result["next_actions"]:
            print(f"- {action}")


def cmd_new(args: argparse.Namespace) -> int:
    result = build_new_project(args)
    if any(item.get("rule") == "NEW_TEMPLATE" for item in result.get("issues", [])):
        exit_code = 3
    else:
        exit_code = 1 if has_errors(result.get("issues", [])) else 0
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_new_result(result)
    project_path = None
    project = result.get("project")
    if isinstance(project, dict) and project.get("config_path"):
        project_path = Path(project["config_path"])
    record_if_requested(args, result, exit_code, project_path)
    return exit_code


def cmd_init(args: argparse.Namespace) -> int:
    args.path = args.project
    args.merge = True
    args.force = False
    return cmd_new(args)


def artifact_entry(path: Path, kind: str, expected: bool = True) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "kind": kind,
        "path": str(path),
        "expected": expected,
        "exists": path.exists(),
    }
    if path.exists() and path.is_file():
        try:
            entry["size_bytes"] = path.stat().st_size
        except OSError:
            pass
    return entry


def discover_n64_inst(
    config: dict[str, Any] | None = None,
    explicit: str | None = None,
) -> tuple[Path | None, str]:
    """Resolve the libdragon SDK without requiring callers to mutate PATH."""
    config = config or {}
    project_value = str(config.get("pathN64Inst") or "").strip()
    env_value = os.environ.get("N64_INST", "").strip()
    candidates: list[tuple[str, str]] = []
    if explicit:
        candidates.append(("explicit", explicit))
    elif project_value:
        candidates.append(("project", project_value))
    elif env_value:
        candidates.append(("environment", env_value))
    else:
        candidates.extend(
            (
                ("default", str(Path.home() / "Documents" / "libdragon-sdk")),
                ("default", str(Path.home() / "libdragon-sdk")),
                ("default", "/opt/libdragon"),
            )
        )

    for source, raw in candidates:
        candidate = Path(raw).expanduser().resolve()
        if source != "default" or candidate.exists():
            return candidate, source
    return None, "missing"


def build_toolchain_status(
    config: dict[str, Any],
    strict: bool = False,
    explicit_n64_inst: str | None = None,
) -> dict[str, Any]:
    project_n64_inst = str(config.get("pathN64Inst") or "")
    env_n64_inst = os.environ.get("N64_INST", "")
    n64_inst_path, source = discover_n64_inst(config, explicit_n64_inst)
    effective_n64_inst = str(n64_inst_path) if n64_inst_path is not None else ""
    severity = "error" if strict else "warning"
    checks: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []

    def add_check(name: str, ok: bool, detail: str, fix: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            issues.append(issue(severity, "BUILD_TOOLCHAIN", detail, fix))

    make_path = shutil.which("make")
    add_check("make", make_path is not None, make_path or "make not found on PATH", "Install make or add it to PATH.")

    if n64_inst_path is not None:
        add_check(
            "N64_INST",
            n64_inst_path.exists(),
            str(n64_inst_path) if n64_inst_path.exists() else f"N64_INST path does not exist: {n64_inst_path}",
            "Set project pathN64Inst or N64_INST to a valid libdragon toolchain path.",
        )
    else:
        add_check(
            "N64_INST",
            False,
            "No project pathN64Inst and N64_INST is not set",
            "Set N64_INST or project pathN64Inst before running a real ROM build.",
        )

    for name, rel in BUILD_TOOLCHAIN_FILES:
        if not effective_n64_inst:
            add_check(name, False, f"{name} cannot be checked because N64_INST is not configured.")
            continue
        expected = Path(effective_n64_inst) / rel
        add_check(name, expected.exists(), str(expected), f"Install/build the libdragon SDK so {rel} exists.")

    return {
        "strict": strict,
        "project_pathN64Inst": project_n64_inst,
        "env_N64_INST": env_n64_inst,
        "effective_N64_INST": effective_n64_inst,
        "source": source,
        "build_ready": not any(not check.get("ok", False) for check in checks),
        "checks": checks,
        "issues": issues,
    }


def build_scene_artifacts(project_root: Path, scenes: list[tuple[int, Path]]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for scene_id, _path in scenes:
        stem = f"s{scene_id:04d}"
        artifacts.append(artifact_entry(project_root / "filesystem" / "p64" / stem, "scene_binary"))
        artifacts.append(artifact_entry(project_root / "filesystem" / "p64" / f"{stem}o", "scene_objects"))
    return artifacts


def build_asset_output_plan(project_root: Path, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for entry in assets:
        if entry.get("exclude"):
            continue
        out_path = entry.get("out_path")
        if not out_path:
            continue
        outputs.append(
            {
                "kind": entry.get("kind"),
                "source": entry.get("relative_path"),
                "out_path": out_path,
                "rom_path": entry.get("rom_path"),
                "exists": (project_root / str(out_path)).exists(),
            }
        )
    outputs.sort(key=lambda item: str(item.get("out_path", "")))
    return outputs


def build_node_graph_source_artifacts(project_root: Path, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for entry in assets:
        if entry.get("kind") != "node_graph" or entry.get("exclude"):
            continue
        uuid_value = optional_int(entry.get("uuid"))
        if uuid_value is None or uuid_value == 0:
            continue
        artifacts.append(artifact_entry(project_root / "src" / "p64" / f"{uuid_value:016x}.cpp", "node_graph_source"))
    return artifacts


def build_bootstrap_plan(project_root: Path) -> dict[str, Any]:
    directories = [
        project_root / "data",
        project_root / "data" / "scenes",
        project_root / "assets",
        project_root / "assets" / "p64",
        project_root / "src",
        project_root / "src" / "p64",
        project_root / "src" / "user",
        project_root / "filesystem" / "p64",
        project_root / "build",
        project_root / "engine",
        project_root / "metadata",
    ]
    files = [
        project_root / ".gitignore",
        project_root / "Makefile.custom",
        project_root / "assets" / "p64" / "font.ia4.png",
    ]
    return {
        "directories": [{"path": str(path), "exists": path.exists()} for path in directories],
        "files": [{"path": str(path), "exists": path.exists()} for path in files],
        "note": "The editor Project constructor creates missing bootstrap files; dry-run does not mutate them.",
    }


def build_expected_artifacts(
    project_root: Path,
    config: dict[str, Any],
    scenes: list[tuple[int, Path]],
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rom_name = str(config.get("romName") or "pyrite64")
    artifacts = [
        artifact_entry(project_root / f"{rom_name}.z64", "rom"),
        artifact_entry(project_root / "build" / f"{rom_name}.dfs", "dfs_image"),
        artifact_entry(project_root / "build" / f"{rom_name}.elf", "elf"),
        artifact_entry(project_root / "Makefile", "generated_makefile"),
        artifact_entry(project_root / "filesystem" / "p64" / "a", "asset_table_binary"),
        artifact_entry(project_root / "filesystem" / "p64" / "conf", "project_runtime_conf"),
        artifact_entry(project_root / "filesystem" / "p64" / "fileList.txt", "asset_file_list"),
        artifact_entry(project_root / "filesystem" / "p64" / "font.ia4.sprite", "builtin_font_sprite"),
        artifact_entry(project_root / "src" / "p64" / "assetTable.h", "generated_source"),
        artifact_entry(project_root / "src" / "p64" / "sceneTable.h", "generated_source"),
        artifact_entry(project_root / "src" / "p64" / "sceneTable.cpp", "generated_source"),
        artifact_entry(project_root / "src" / "p64" / "scriptTable.cpp", "generated_source"),
        artifact_entry(project_root / "src" / "p64" / "globalScriptTable.cpp", "generated_source"),
    ]
    if (config.get("metadata") or {}).get("enabled"):
        artifacts.append(artifact_entry(project_root / "metadata" / "metadata.ini", "rom_metadata"))
    artifacts.extend(build_scene_artifacts(project_root, scenes))
    artifacts.extend(build_node_graph_source_artifacts(project_root, assets))
    for output in build_asset_output_plan(project_root, assets):
        artifacts.append(artifact_entry(project_root / str(output["out_path"]), f"asset_{output['kind']}"))
    return artifacts


def build_plan_next_actions(result: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if has_errors(result.get("issues", [])):
        actions.append("Fix build-plan errors before attempting a real ROM build.")
    toolchain = result.get("toolchain", {})
    if isinstance(toolchain, dict) and not toolchain.get("build_ready"):
        actions.append("Configure N64_INST/pathN64Inst and libdragon tools before invoking the real build.")
    if not actions:
        actions.append("Dry-run plan is clean; the next CLI slice can safely add an explicit execute mode.")
    return actions


def build_execute_next_actions(result: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    execute = result.get("execute", {})
    if isinstance(execute, dict) and not execute.get("executed"):
        actions.append("Fix preflight or binary resolution errors before executing the build.")
    elif result.get("ok"):
        rom = (result.get("plan") or {}).get("rom", {}) if isinstance(result.get("plan"), dict) else {}
        rom_path = rom.get("path") if isinstance(rom, dict) else ""
        actions.append(f"Build completed; the next CLI slice can launch the ROM at {rom_path}.")
    else:
        actions.append("Inspect the captured Pyrite64 build output and fix the reported build failure.")
    return actions


def build_build_plan(project_arg: str | None, strict_toolchain: bool = False) -> dict[str, Any]:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(project_arg)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "build",
            "kind": "build_plan",
            "mode": "dry_run",
            "project": project_arg,
            "issues": issues,
            "next_actions": ["Pass --project <project-dir> or --project <path/to/project.p64proj>."],
            "artifacts": [],
        }
        return result

    project = project_summary(project_root, config_path, config)
    validation = validate_project_file(config_path, limits)
    inventory = scan_project_assets(project_root, include_entries=True)
    discovered_assets = inventory.pop("assets", [])
    selection = select_project_assets(discovered_assets)
    assets = selection["assets"]
    validate_args = argparse.Namespace(texture_format=None, scene_pipeline=None, role="unknown")
    asset_results = [validate_project_asset_entry(entry, limits, validate_args) for entry in assets]
    asset_summary = summarize_asset_validation(asset_results)
    asset_summary["included"] = selection["included"]
    asset_summary["excluded"] = selection["excluded"]
    asset_summary["include_excluded"] = selection["include_excluded"]
    asset_issues = flatten_asset_issues(asset_results, project_root)
    scenes, scene_scan_issues = iter_scene_files(project_root)
    toolchain = build_toolchain_status(config, strict_toolchain)

    all_issues = list(issues)
    all_issues.extend(validation.get("issues", []))
    all_issues.extend(asset_issues)
    all_issues.extend(scene_scan_issues)
    all_issues.extend(toolchain.get("issues", []))

    if " " in str(project_root.resolve()):
        all_issues.append(
            issue(
                "error",
                "BUILD_PATH",
                f"Project path contains spaces: {project_root}.",
                "Move the project to a path without spaces before building; the Pyrite64 launcher rejects these paths for Makefile/toolchain compatibility.",
                "docs/docs/agent/ARCHITECTURE.md#launcher",
            )
        )

    rom_name = str(config.get("romName") or "pyrite64")
    asset_outputs = build_asset_output_plan(project_root, assets)
    artifacts = build_expected_artifacts(project_root, config, scenes, assets)
    result = {
        "ok": not has_errors(all_issues),
        "command": "build",
        "kind": "build_plan",
        "mode": "dry_run",
        "dry_run": True,
        "project": project,
        "toolchain": toolchain,
        "validation": {
            "project": {
                "ok": validation.get("ok", False),
                "scene_count": validation.get("scene_count", 0),
                "issue_count": len(validation.get("issues", [])),
            },
            "assets": asset_summary,
        },
        "plan": {
            "rom": {
                "name": rom_name,
                "path": str(project_root / f"{rom_name}.z64"),
                "exists": (project_root / f"{rom_name}.z64").exists(),
            },
            "makefile": {
                "path": str(project_root / "Makefile"),
                "template": str(REPO_ROOT / "data" / "build" / "baseMakefile.mk"),
                "custom": str(project_root / "Makefile.custom"),
                "custom_exists": (project_root / "Makefile.custom").exists(),
            },
            "make_command": f'make -C "{project_root}" -j8',
            "editor_cli_command": f'<pyrite64-binary> --cli --cmd build "{config_path}"',
            "bootstrap": build_bootstrap_plan(project_root),
            "scene_outputs": [artifact for artifact in build_scene_artifacts(project_root, scenes)],
            "asset_outputs": asset_outputs,
            "generated_sources": [
                str(project_root / "src" / "p64" / name)
                for name in ("assetTable.h", "sceneTable.h", "sceneTable.cpp", "scriptTable.cpp", "globalScriptTable.cpp")
            ],
            "dynamic_outputs": [
                "filesystem/**/*.sdata files may be added by the tiny3d importer for animated models.",
                "metadata/img_* and metadata/description*.txt are generated when ROM metadata references image/text fields.",
            ],
        },
        "inventory": inventory,
        "issues": all_issues,
        "artifacts": artifacts,
    }
    result["next_actions"] = build_plan_next_actions(result)
    return result


def tail_text(text: str | bytes | None, max_lines: int = 200, max_chars: int = 20000) -> str:
    if not text:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    elif not isinstance(text, str):
        text = str(text)
    lines = text.splitlines()
    if len(lines) > max_lines:
        text = "\n".join(lines[-max_lines:])
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


def pyrite_binary_candidates(explicit_binary: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_binary:
        raw = Path(explicit_binary).expanduser()
        candidates.append(raw if raw.is_absolute() else Path.cwd() / raw)
    else:
        for name in PYRITE_BINARY_NAMES:
            candidates.append(REPO_ROOT / name)
            candidates.append(REPO_ROOT / "build" / name)
        for name in PYRITE_BINARY_NAMES:
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        try:
            key = str(candidate.resolve())
        except OSError:
            pass
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def resolve_pyrite_binary(explicit_binary: str | None = None) -> tuple[Path | None, list[Path], list[dict[str, str]]]:
    candidates = pyrite_binary_candidates(explicit_binary)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate, candidates, []

    if explicit_binary:
        message = f"Pyrite64 binary is not executable or does not exist: {explicit_binary}."
    else:
        message = "Could not find an executable Pyrite64 binary."
    return (
        None,
        candidates,
        [
            issue(
                "error",
                "BUILD_BINARY",
                message,
                "Build the editor with CMake or pass --pyrite64-binary <path/to/pyrite64>.",
                "docs/docs/dev/build.rst",
            )
        ],
    )


def refresh_artifact_entries(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refreshed: list[dict[str, Any]] = []
    for artifact in artifacts:
        entry = dict(artifact)
        path = Path(str(entry.get("path", "")))
        entry["exists"] = path.exists()
        entry.pop("size_bytes", None)
        if path.exists() and path.is_file():
            try:
                entry["size_bytes"] = path.stat().st_size
            except OSError:
                pass
        refreshed.append(entry)
    return refreshed


def build_command_exit_code(result: dict[str, Any]) -> int:
    env_rules = {"BUILD_TOOLCHAIN", "BUILD_BINARY"}
    if any(item.get("severity") == "error" and item.get("rule") in env_rules for item in result.get("issues", [])):
        return 2
    return 1 if has_errors(result.get("issues", [])) else 0


def command_exit_code(result: dict[str, Any], env_rules: set[str]) -> int:
    if any(item.get("severity") == "error" and item.get("rule") in env_rules for item in result.get("issues", [])):
        return 2
    return 1 if has_errors(result.get("issues", [])) else 0


def execute_build(args: argparse.Namespace) -> dict[str, Any]:
    result = build_build_plan(args.project, True)
    result["mode"] = "execute"
    result["dry_run"] = False
    result["execute"] = {
        "requested": True,
        "executed": False,
        "binary": None,
        "candidates": [],
        "argv": [],
        "returncode": None,
        "duration_ms": None,
    }

    if has_errors(result.get("issues", [])):
        result["execute"]["skipped_reason"] = "preflight_failed"
        result["next_actions"] = build_execute_next_actions(result)
        return result

    binary, candidates, binary_issues = resolve_pyrite_binary(args.pyrite64_binary)
    result["execute"]["candidates"] = [str(candidate) for candidate in candidates]
    if binary_issues:
        result["issues"].extend(binary_issues)
        result["ok"] = False
        result["execute"]["skipped_reason"] = "binary_not_found"
        result["next_actions"] = build_execute_next_actions(result)
        return result

    project = result.get("project", {})
    config_path = Path(str(project.get("config_path"))) if isinstance(project, dict) else None
    if config_path is None:
        result["issues"].append(issue("error", "PROJECT", "Build plan is missing project config_path."))
        result["ok"] = False
        result["execute"]["skipped_reason"] = "missing_project_config"
        result["next_actions"] = build_execute_next_actions(result)
        return result

    argv = [str(binary), "--cli", "--cmd", "build", str(config_path)]
    result["execute"]["binary"] = str(binary)
    result["execute"]["argv"] = argv
    build_env = os.environ.copy()
    if bool(getattr(args, "profile", False)):
        build_env["BF64_PROFILE"] = "1"
        build_env["BF64_PROFILE_WARMUP"] = str(getattr(args, "profile_warmup", 120))
        build_env["BF64_PROFILE_FRAMES"] = str(getattr(args, "profile_frames", 300))
        result["execute"]["profile"] = {
            "enabled": True,
            "warmup_frames": int(build_env["BF64_PROFILE_WARMUP"]),
            "sample_frames": int(build_env["BF64_PROFILE_FRAMES"]),
        }
    started_at = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            env=build_env,
            timeout=args.timeout if args.timeout and args.timeout > 0 else None,
        )
        result["execute"]["executed"] = True
        result["execute"]["returncode"] = proc.returncode
        result["execute"]["duration_ms"] = int((time.perf_counter() - started_at) * 1000)
        result["execute"]["stdout_tail"] = tail_text(proc.stdout)
        result["execute"]["stderr_tail"] = tail_text(proc.stderr)
        result["artifacts"] = refresh_artifact_entries(result.get("artifacts", []))
        rom = (result.get("plan") or {}).get("rom", {}) if isinstance(result.get("plan"), dict) else {}
        if isinstance(rom, dict) and rom.get("path"):
            rom_path = Path(str(rom["path"]))
            rom["exists"] = rom_path.exists()
            if rom_path.exists() and rom_path.is_file():
                try:
                    rom["size_bytes"] = rom_path.stat().st_size
                except OSError:
                    pass
        if proc.returncode != 0:
            result["issues"].append(
                issue(
                    "error",
                    "BUILD_EXECUTE",
                    f"Pyrite64 CLI build failed with exit code {proc.returncode}.",
                    "Inspect execute.stdout_tail and execute.stderr_tail for the underlying compiler/toolchain error.",
                )
            )
        result["ok"] = not has_errors(result.get("issues", []))
    except subprocess.TimeoutExpired as exc:
        result["execute"]["executed"] = True
        result["execute"]["returncode"] = None
        result["execute"]["duration_ms"] = int((time.perf_counter() - started_at) * 1000)
        result["execute"]["stdout_tail"] = tail_text(exc.stdout or "")
        result["execute"]["stderr_tail"] = tail_text(exc.stderr or "")
        result["issues"].append(
            issue(
                "error",
                "BUILD_TIMEOUT",
                f"Pyrite64 CLI build timed out after {args.timeout} seconds.",
                "Increase --timeout or inspect whether the build is waiting on an external tool.",
            )
        )
        result["ok"] = False
    except OSError as exc:
        result["issues"].append(
            issue(
                "error",
                "BUILD_BINARY",
                f"Could not execute Pyrite64 binary: {exc}",
                "Build the editor with CMake or pass --pyrite64-binary <path/to/pyrite64>.",
            )
        )
        result["ok"] = False

    result["next_actions"] = build_execute_next_actions(result)
    return result


def print_build_plan(result: dict[str, Any]) -> None:
    output_result(result, False)
    project = result.get("project")
    if isinstance(project, dict):
        print(f"Project: {project.get('name')} ({project.get('path')})")
    plan = result.get("plan", {})
    if isinstance(plan, dict):
        rom = plan.get("rom", {})
        if isinstance(rom, dict):
            print(f"ROM: {rom.get('path')} exists={rom.get('exists')}")
        print(f"Mode: {result.get('mode')}")
        print(f"Would run: {plan.get('make_command')}")
    validation = result.get("validation", {})
    if isinstance(validation, dict):
        project_validation = validation.get("project", {})
        asset_validation = validation.get("assets", {})
        print(
            "Validation: scenes={scenes} asset_validated={validated} asset_skipped={skipped} asset_failed={failed}".format(
                scenes=project_validation.get("scene_count") if isinstance(project_validation, dict) else "?",
                validated=asset_validation.get("validated") if isinstance(asset_validation, dict) else "?",
                skipped=asset_validation.get("skipped") if isinstance(asset_validation, dict) else "?",
                failed=asset_validation.get("failed") if isinstance(asset_validation, dict) else "?",
            )
        )
    toolchain = result.get("toolchain", {})
    if isinstance(toolchain, dict):
        print(f"Toolchain: build_ready={toolchain.get('build_ready')} N64_INST={toolchain.get('effective_N64_INST') or '(unset)'}")
    execute = result.get("execute", {})
    if isinstance(execute, dict) and execute.get("requested"):
        print(f"Execute: executed={execute.get('executed')} returncode={execute.get('returncode')} binary={execute.get('binary')}")
    if result.get("next_actions"):
        print("Next actions:")
        for action in result["next_actions"]:
            print(f"- {action}")


def cmd_build(args: argparse.Namespace) -> int:
    result = execute_build(args) if args.execute else build_build_plan(args.project, args.strict_toolchain)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_build_plan(result)
    exit_code = build_command_exit_code(result)
    project_path = None
    project = result.get("project")
    if isinstance(project, dict) and project.get("config_path"):
        project_path = Path(project["config_path"])
    record_if_requested(args, result, exit_code, project_path)
    return exit_code


def run_next_actions(result: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if result.get("ok"):
        actions.append("Run command completed; inspect emulator stdout/stderr tails for runtime output.")
        return actions
    if any(item.get("rule") == "RUN_ROM" for item in result.get("issues", [])):
        actions.append("Build the ROM first with ./bf64 build --execute or re-run with ./bf64 run --build.")
    if any(item.get("rule") == "RUN_EMULATOR" for item in result.get("issues", [])):
        actions.append("Install ares/gopher64 or pass --emulator <command>.")
    if any(item.get("rule") == "RUN_EXECUTE" for item in result.get("issues", [])):
        actions.append("Inspect run.stdout_tail and run.stderr_tail for emulator failure details.")
    if any(item.get("rule") in {"PROFILE_CAPTURE", "PROFILE_SCHEMA"} for item in result.get("issues", [])):
        actions.append("Rebuild with --build --profile and confirm the emulator forwards libdragon debug output to stdout.")
    if not actions:
        actions.append("Fix run errors and try again.")
    return actions


def resolve_emulator_command(emulator_spec: str | None) -> tuple[list[str] | None, list[dict[str, str]]]:
    raw = (emulator_spec or "ares").strip()
    if not raw:
        return None, [
            issue(
                "error",
                "RUN_EMULATOR",
                "Emulator command is empty.",
                "Set project pathEmu or pass --emulator ares/gopher64.",
            )
        ]
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        return None, [issue("error", "RUN_EMULATOR", f"Could not parse emulator command: {exc}", "Fix shell quoting.")]
    if not parts:
        return None, [issue("error", "RUN_EMULATOR", "Emulator command is empty.")]

    executable = parts[0]
    executable_path = Path(executable).expanduser()
    has_path_separator = "/" in executable or "\\" in executable
    if has_path_separator or executable_path.is_absolute():
        candidate = executable_path if executable_path.is_absolute() else Path.cwd() / executable_path
        if not candidate.exists() or not candidate.is_file() or not os.access(candidate, os.X_OK):
            return None, [
                issue(
                    "error",
                    "RUN_EMULATOR",
                    f"Emulator is not executable or does not exist: {executable}.",
                    "Pass --emulator <path/to/ares> or install ares/gopher64 on PATH.",
                    "docs/docs/n64/emulation-and-hardware-testing.md",
                )
            ]
        parts[0] = str(candidate)
        return parts, []

    found = shutil.which(executable)
    if not found:
        if executable.lower() in {"ares", "ares.exe"}:
            flatpak = shutil.which("flatpak")
            if flatpak:
                check = subprocess.run(
                    [flatpak, "info", "dev.ares.ares"],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    check=False,
                    timeout=3,
                )
                if check.returncode == 0:
                    return [flatpak, "run", "dev.ares.ares"], []
        return None, [
            issue(
                "error",
                "RUN_EMULATOR",
                f"Emulator command not found on PATH: {executable}.",
                "Install ares/gopher64 or pass --emulator <path/to/emulator>.",
                "docs/docs/n64/emulation-and-hardware-testing.md",
            )
        ]
    parts[0] = found
    return parts, []


def run_command_artifacts(rom_path: Path) -> list[dict[str, Any]]:
    return [artifact_entry(rom_path, "rom")]


def prepare_emulator_argv(
    emulator_argv: list[str],
    project_root: Path,
    rom_path: Path,
    *,
    homebrew_mode: bool = False,
    emulator_version_text: str = "",
) -> list[str]:
    argv = list(emulator_argv)
    resolved_project_root = project_root.expanduser().resolve()
    resolved_rom_path = rom_path.expanduser().resolve()
    is_flatpak_ares = "dev.ares.ares" in argv
    executable_name = Path(argv[0]).name.lower() if argv else ""
    is_ares = is_flatpak_ares or executable_name in {"ares", "ares.exe"}
    if is_flatpak_ares:
        app_index = argv.index("dev.ares.ares")
        if not any(part.startswith("--filesystem=") for part in argv[:app_index]):
            argv.insert(app_index, f"--filesystem={resolved_project_root}")
            app_index += 1
        app_args = argv[app_index + 1 :]
        if "--system" not in app_args:
            argv.extend(["--system", "Nintendo 64"])
        if "--no-file-prompt" not in app_args:
            argv.append("--no-file-prompt")
    if homebrew_mode and is_ares and not any("HomebrewMode=" in part for part in argv):
        match = re.search(r"\bv(\d+)\b", emulator_version_text, re.IGNORECASE)
        version = int(match.group(1)) if match else 148
        # Ares v148 and earlier expose this as General/HomebrewMode. The
        # post-v148 settings reorganization moved it under Developer.
        setting = "General/HomebrewMode=true" if version <= 148 else "Developer/HomebrewMode=true"
        argv.extend(["--setting", setting])
    argv.append(str(resolved_rom_path))
    return argv


def emulator_version(emulator_argv: list[str]) -> str:
    if not emulator_argv:
        return "unknown"
    if "dev.ares.ares" in emulator_argv:
        argv = [emulator_argv[0], "run", "dev.ares.ares", "--version"]
    else:
        argv = [emulator_argv[0], "--version"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, errors="replace", check=False, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else "unknown"


def terminate_profile_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=3)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        try:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=3)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            pass


def execute_profile_emulator(argv: list[str], timeout_seconds: int) -> dict[str, Any]:
    started_at = time.perf_counter()
    proc = subprocess.Popen(
        argv,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
        start_new_session=os.name != "nt",
    )
    output_queue: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        if proc.stdout is not None:
            for line in proc.stdout:
                output_queue.put(line)
        output_queue.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout_seconds
    output: list[str] = []
    runtime_profile: dict[str, Any] | None = None
    parse_error: str | None = None
    timed_out = False
    stream_closed = False
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")

    while runtime_profile is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            line = output_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if proc.poll() is not None and stream_closed:
                break
            continue
        if line is None:
            stream_closed = True
            if proc.poll() is not None:
                break
            continue
        output.append(line)
        clean_line = ansi_pattern.sub("", line)
        marker_index = clean_line.find(PROFILE_MARKER)
        if marker_index < 0:
            continue
        payload = clean_line[marker_index + len(PROFILE_MARKER) :].strip()
        try:
            candidate = json.loads(payload)
            if not isinstance(candidate, dict):
                raise ValueError("profile payload is not an object")
            runtime_profile = candidate
        except (json.JSONDecodeError, ValueError) as exc:
            parse_error = str(exc)
            break

    captured = runtime_profile is not None
    if captured or timed_out or proc.poll() is None:
        terminate_profile_process(proc)
    reader.join(timeout=1)
    while True:
        try:
            line = output_queue.get_nowait()
        except queue.Empty:
            break
        if line is not None:
            output.append(line)

    return {
        "captured": captured,
        "runtime": runtime_profile,
        "parse_error": parse_error,
        "timed_out": timed_out,
        "returncode": proc.poll(),
        "duration_ms": int((time.perf_counter() - started_at) * 1000),
        "stdout": "".join(output),
    }


def profile_file_entry(path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": str(path), "exists": path.is_file(), "size_bytes": None}
    if entry["exists"]:
        try:
            entry["size_bytes"] = path.stat().st_size
        except OSError:
            pass
    return entry


def default_profile_output(project_root: Path, rom_name: str) -> Path:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return project_root / ".bf64" / "profiles" / f"{rom_name}-{timestamp}.json"


def write_profile_artifact(
    output_path: Path,
    project: dict[str, Any],
    runtime_profile: dict[str, Any],
    emulator_spec: str,
    emulator_argv: list[str],
    emulator_version_text: str,
    rom_path: Path,
) -> dict[str, Any]:
    project_root = Path(str(project["path"]))
    rom_name = rom_path.stem
    runtime_target = runtime_profile.get("target", {})
    target = dict(runtime_target) if isinstance(runtime_target, dict) else {"platform": "n64"}
    target.update({"bf64_version": CLI_VERSION, "bf64_revision": current_repo_revision()})
    artifact = {
        "schema": "bf64.profile",
        "version": PROFILE_SCHEMA_VERSION,
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "project": project,
        "target": target,
        "emulator": {
            "command": emulator_spec,
            "argv": emulator_argv,
            "version": emulator_version_text,
        },
        "files": {
            "rom": profile_file_entry(rom_path),
            "elf": profile_file_entry(project_root / "build" / f"{rom_name}.elf"),
            "dfs": profile_file_entry(project_root / "build" / f"{rom_name}.dfs"),
        },
        "runtime": runtime_profile,
    }
    write_json_file(output_path, artifact)
    return artifact


def execute_run(args: argparse.Namespace) -> dict[str, Any]:
    profile_requested = bool(getattr(args, "profile", False))
    profile_warmup = int(getattr(args, "profile_warmup", 120))
    profile_frames = int(getattr(args, "profile_frames", 300))
    build_result: dict[str, Any] | None = None
    if args.build:
        build_args = argparse.Namespace(
            project=args.project,
            pyrite64_binary=args.pyrite64_binary,
            timeout=args.build_timeout,
            profile=profile_requested,
            profile_warmup=profile_warmup,
            profile_frames=profile_frames,
        )
        build_result = execute_build(build_args)
        if not build_result.get("ok"):
            result = {
                "ok": False,
                "command": "run",
                "kind": "run",
                "project": build_result.get("project"),
                "mode": "build_then_run",
                "build": build_result,
                "run": {"requested": True, "executed": False, "skipped_reason": "build_failed"},
                "profile": {"requested": profile_requested, "captured": False},
                "issues": list(build_result.get("issues", [])),
                "artifacts": build_result.get("artifacts", []),
            }
            result["next_actions"] = run_next_actions(result)
            return result

    plan = build_build_plan(args.project, False)
    result: dict[str, Any] = {
        "ok": False,
        "command": "run",
        "kind": "run",
        "mode": "build_then_run" if args.build else "run",
        "project": plan.get("project"),
        "build": build_result,
        "plan": {
            "rom": (plan.get("plan") or {}).get("rom") if isinstance(plan.get("plan"), dict) else None,
        },
        "run": {
            "requested": True,
            "executed": False,
            "emulator": None,
            "argv": [],
            "returncode": None,
            "duration_ms": None,
        },
        "profile": {
            "requested": profile_requested,
            "captured": False,
            "warmup_frames": profile_warmup,
            "sample_frames": profile_frames,
            "output_path": None,
            "runtime": None,
        },
        "issues": [],
        "artifacts": [],
    }

    if profile_requested and (profile_warmup < 0 or profile_warmup > 0xFFFF):
        result["issues"].append(issue("error", "PROFILE_FRAMES", "--profile-warmup must be in 0..65535."))
    if profile_requested and (profile_frames < 1 or profile_frames > 2048):
        result["issues"].append(issue("error", "PROFILE_FRAMES", "--profile-frames must be in 1..2048."))
    if has_errors(result["issues"]):
        result["run"]["skipped_reason"] = "invalid_profile_settings"
        result["next_actions"] = run_next_actions(result)
        return result

    if has_errors(plan.get("issues", [])):
        result["issues"].extend(plan.get("issues", []))
        result["run"]["skipped_reason"] = "plan_failed"
        result["artifacts"] = plan.get("artifacts", [])
        result["next_actions"] = run_next_actions(result)
        return result

    rom_info = (plan.get("plan") or {}).get("rom", {}) if isinstance(plan.get("plan"), dict) else {}
    rom_path = Path(str(rom_info.get("path", ""))) if isinstance(rom_info, dict) else Path()
    result["artifacts"] = run_command_artifacts(rom_path)
    if not rom_path.exists() or not rom_path.is_file():
        result["issues"].append(
            issue(
                "error",
                "RUN_ROM",
                f"ROM does not exist: {rom_path}.",
                "Build the project first with ./bf64 build --execute, or pass --build to run.",
            )
        )
        result["run"]["skipped_reason"] = "rom_missing"
        result["next_actions"] = run_next_actions(result)
        return result

    config = None
    project_path = result.get("project")
    if isinstance(project_path, dict) and project_path.get("config_path"):
        try:
            loaded = read_json_file(Path(project_path["config_path"]))
            if isinstance(loaded, dict):
                config = loaded
        except Exception:
            config = None
    default_emulator = str((config or {}).get("pathEmu") or "ares")
    emulator_spec = args.emulator or default_emulator
    emulator_argv, emulator_issues = resolve_emulator_command(emulator_spec)
    if emulator_issues:
        result["issues"].extend(emulator_issues)
        result["run"]["emulator"] = emulator_spec
        result["run"]["skipped_reason"] = "emulator_not_found"
        result["next_actions"] = run_next_actions(result)
        return result

    project_root = Path(str((result.get("project") or {}).get("path", rom_path.parent)))
    version_text = emulator_version(emulator_argv or []) if profile_requested else None
    argv = prepare_emulator_argv(
        emulator_argv or [],
        project_root,
        rom_path,
        homebrew_mode=profile_requested,
        emulator_version_text=version_text or "",
    )
    result["run"]["emulator"] = emulator_spec
    result["run"]["argv"] = argv
    if profile_requested:
        result["profile"]["emulator_version"] = version_text
    started_at = time.perf_counter()
    try:
        if profile_requested:
            capture_timeout = args.timeout if args.timeout and args.timeout > 0 else 60
            capture = execute_profile_emulator(argv, capture_timeout)
            result["run"]["executed"] = True
            result["run"]["returncode"] = capture["returncode"]
            result["run"]["duration_ms"] = capture["duration_ms"]
            result["run"]["stdout_tail"] = tail_text(capture["stdout"])
            result["run"]["stderr_tail"] = ""
            result["run"]["terminated_after_profile"] = bool(capture["captured"])
            runtime_profile = capture.get("runtime")
            if capture["captured"] and isinstance(runtime_profile, dict):
                if runtime_profile.get("schema") != "bf64.runtime-profile" or runtime_profile.get("version") != 1:
                    result["issues"].append(
                        issue("error", "PROFILE_SCHEMA", "Runtime emitted an unsupported profile schema/version.")
                    )
                else:
                    output_arg = getattr(args, "profile_output", None)
                    output_path = Path(output_arg).expanduser() if output_arg else default_profile_output(project_root, rom_path.stem)
                    if not output_path.is_absolute():
                        output_path = project_root / output_path
                    artifact = write_profile_artifact(
                        output_path,
                        result["project"],
                        runtime_profile,
                        emulator_spec,
                        argv,
                        version_text or "unknown",
                        rom_path,
                    )
                    result["profile"].update(
                        {
                            "captured": True,
                            "output_path": str(output_path),
                            "runtime": runtime_profile,
                            "artifact": artifact,
                        }
                    )
                    result["artifacts"] = run_command_artifacts(rom_path) + [artifact_entry(output_path, "profile")]
            else:
                if capture.get("parse_error"):
                    message = f"Runtime profile marker contained invalid JSON: {capture['parse_error']}."
                elif capture.get("timed_out"):
                    message = f"Runtime profile was not received within {capture_timeout} seconds."
                else:
                    message = "Emulator exited before emitting a runtime profile."
                result["issues"].append(
                    issue(
                        "error",
                        "PROFILE_CAPTURE",
                        message,
                        "Build with `bf64 run --build --profile` and ensure emulator debug output reaches stdout.",
                    )
                )
        else:
            proc = subprocess.run(
                argv,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=args.timeout if args.timeout and args.timeout > 0 else None,
            )
            result["run"]["executed"] = True
            result["run"]["returncode"] = proc.returncode
            result["run"]["duration_ms"] = int((time.perf_counter() - started_at) * 1000)
            result["run"]["stdout_tail"] = tail_text(proc.stdout)
            result["run"]["stderr_tail"] = tail_text(proc.stderr)
            result["artifacts"] = run_command_artifacts(rom_path)
            if proc.returncode != 0:
                result["issues"].append(
                    issue(
                        "error",
                        "RUN_EXECUTE",
                        f"Emulator exited with code {proc.returncode}.",
                        "Inspect run.stdout_tail and run.stderr_tail for emulator details.",
                    )
                )
        result["ok"] = not has_errors(result["issues"])
    except subprocess.TimeoutExpired as exc:
        result["run"]["executed"] = True
        result["run"]["duration_ms"] = int((time.perf_counter() - started_at) * 1000)
        result["run"]["stdout_tail"] = tail_text(exc.stdout or "")
        result["run"]["stderr_tail"] = tail_text(exc.stderr or "")
        result["issues"].append(
            issue(
                "error",
                "RUN_TIMEOUT",
                f"Emulator timed out after {args.timeout} seconds.",
                "Increase --timeout or close the emulator manually.",
            )
        )
    except OSError as exc:
        result["issues"].append(
            issue(
                "error",
                "RUN_EMULATOR",
                f"Could not execute emulator: {exc}",
                "Install ares/gopher64 or pass --emulator <command>.",
            )
        )

    result["next_actions"] = run_next_actions(result)
    return result


def print_run_result(result: dict[str, Any]) -> None:
    output_result(result, False)
    project = result.get("project")
    if isinstance(project, dict):
        print(f"Project: {project.get('name')} ({project.get('path')})")
    run = result.get("run", {})
    if isinstance(run, dict):
        print(f"Run: executed={run.get('executed')} returncode={run.get('returncode')} emulator={run.get('emulator')}")
    profile = result.get("profile", {})
    if isinstance(profile, dict) and profile.get("requested"):
        print(f"Profile: captured={profile.get('captured')} output={profile.get('output_path')}")
        runtime = profile.get("runtime", {})
        if isinstance(runtime, dict):
            frame = runtime.get("frame_time_ms", {})
            fps = runtime.get("fps", {})
            render = runtime.get("render", {})
            memory = runtime.get("memory", {})
            if isinstance(frame, dict) and isinstance(fps, dict):
                print(
                    f"Frame: avg={frame.get('average')}ms p95={frame.get('p95')}ms "
                    f"worst={frame.get('worst')}ms avg_fps={fps.get('average')}"
                )
            triangles = render.get("triangles", {}) if isinstance(render, dict) else {}
            if isinstance(triangles, dict):
                print(f"Render: triangles_avg={triangles.get('average')} triangles_peak={triangles.get('peak')}")
            if isinstance(memory, dict):
                print(f"Memory: peak_rdram_used={memory.get('peak_rdram_used_bytes')} bytes")
    plan = result.get("plan", {})
    rom = plan.get("rom") if isinstance(plan, dict) else None
    if isinstance(rom, dict):
        print(f"ROM: {rom.get('path')} exists={rom.get('exists')}")
    if result.get("next_actions"):
        print("Next actions:")
        for action in result["next_actions"]:
            print(f"- {action}")


def cmd_run(args: argparse.Namespace) -> int:
    result = execute_run(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_run_result(result)
    exit_code = command_exit_code(result, {"BUILD_TOOLCHAIN", "BUILD_BINARY", "RUN_EMULATOR"})
    project_path = None
    project = result.get("project")
    if isinstance(project, dict) and project.get("config_path"):
        project_path = Path(project["config_path"])
    record_if_requested(args, result, exit_code, project_path)
    return exit_code


def resolve_project_asset(project_root: Path, asset_ref: str) -> tuple[Path | None, list[dict[str, str]]]:
    assets_root = project_root / "assets"
    raw = Path(asset_ref)
    issues: list[dict[str, str]] = []

    def usable(path: Path) -> bool:
        return (
            path.exists()
            and path.is_file()
            and not path.name.endswith(".conf")
            and is_path_relative_to(path, assets_root)
        )

    seen: set[str] = set()
    direct_candidates = [raw, project_root / raw, assets_root / raw]
    for candidate in direct_candidates:
        if not usable(candidate):
            continue
        key = str(candidate.resolve())
        if key in seen:
            continue
        return candidate, []

    if not assets_root.exists():
        return None, [
            issue(
                "error",
                "ASSET",
                f"Project assets directory does not exist: {assets_root}.",
                "Create assets/ or pass the correct --project path.",
            )
        ]

    wanted = asset_ref.replace("\\", "/")
    matches: list[Path] = []
    for path in assets_root.rglob("*"):
        if not path.is_file() or path.name.endswith(".conf"):
            continue
        rel_project = path_relative_to(path, project_root).replace("\\", "/")
        rel_asset = path_relative_to(path, assets_root).replace("\\", "/")
        if wanted in {rel_project, rel_asset, path.name}:
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                matches.append(path)

    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        preview = ", ".join(path_relative_to(path, project_root) for path in matches[:10])
        issues.append(
            issue(
                "error",
                "ASSET",
                f"Asset reference '{asset_ref}' is ambiguous; matches: {preview}.",
                "Use the project-relative assets/<path> form.",
            )
        )
    else:
        issues.append(
            issue(
                "error",
                "ASSET",
                f"Could not find asset '{asset_ref}' under {assets_root}.",
                "Use ./bf64 asset ls --project <project> to find the project-relative asset path.",
            )
        )
    return None, issues


def validator_args_from_asset_command(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        texture_format=getattr(args, "texture_format", None),
        scene_pipeline=getattr(args, "scene_pipeline", None),
        role=getattr(args, "role", "unknown"),
    )


def validate_project_asset_entry(
    entry: dict[str, Any],
    limits: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    path = Path(entry["path"])
    kind = str(entry["kind"])
    conf, conf_path = load_conf(path, None)
    parse_issue = conf_parse_issue(conf, conf_path)
    if parse_issue:
        return {
            "ok": False,
            "path": str(path),
            "kind": kind,
            "metadata": {"conf": conf_path, "skipped": False},
            "issues": [parse_issue],
        }
    conf, defaulted_fields = normalize_asset_conf(conf)

    def with_conf_defaults(result: dict[str, Any]) -> dict[str, Any]:
        result.setdefault("metadata", {})["conf_defaulted_fields"] = defaulted_fields
        return result

    if kind not in VALIDATABLE_ASSET_KINDS:
        return with_conf_defaults({
            "ok": True,
            "path": str(path),
            "kind": kind,
            "metadata": {
                "conf": conf_path,
                "skipped": True,
                "skip_reason": "No read-only validator exists for this project asset kind yet.",
            },
            "issues": [],
        })

    validate_args = validator_args_from_asset_command(args)
    if kind == "texture":
        return with_conf_defaults(validate_texture(path, conf, conf_path, validate_args, limits))
    if kind == "model":
        return with_conf_defaults(validate_model(path, conf, conf_path, validate_args, limits))
    if kind == "audio":
        return with_conf_defaults(validate_audio(path, conf, conf_path, validate_args, limits))
    if kind == "font":
        return with_conf_defaults(validate_font(path, conf_path))
    if kind == "ui":
        return with_conf_defaults(validate_ui_document(path))
    if kind == "prefab":
        return with_conf_defaults(validate_prefab_file(path, limits, conf, conf_path))
    if kind == "node_graph":
        project_root = path.parent
        for parent in path.parents:
            if (parent / PROJECT_FILENAME).is_file():
                project_root = parent
                break
        return with_conf_defaults(validate_node_graph_file(path, project_root, conf_path))
    raise AssertionError(f"unhandled asset kind: {kind}")


def select_project_assets(
    assets: list[dict[str, Any]],
    include_excluded: bool = False,
) -> dict[str, Any]:
    included = [entry for entry in assets if not bool(entry.get("exclude"))]
    excluded = [entry for entry in assets if bool(entry.get("exclude"))]
    return {
        "assets": list(assets) if include_excluded else included,
        "included": len(included),
        "excluded": len(excluded),
        "include_excluded": include_excluded,
    }


def summarize_asset_validation(results: list[dict[str, Any]]) -> dict[str, Any]:
    severity_counts: dict[str, int] = {}
    by_kind: dict[str, dict[str, int]] = {}
    for result in results:
        kind = str(result.get("kind", "unknown"))
        stats = by_kind.setdefault(kind, {"total": 0, "validated": 0, "skipped": 0, "failed": 0})
        stats["total"] += 1
        if (result.get("metadata") or {}).get("skipped"):
            stats["skipped"] += 1
        else:
            stats["validated"] += 1
        if not result.get("ok", False):
            stats["failed"] += 1
        for item in result.get("issues", []):
            severity = str(item.get("severity", "info"))
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

    skipped = sum(1 for result in results if (result.get("metadata") or {}).get("skipped"))
    failed = sum(1 for result in results if not result.get("ok", False))
    passed = sum(
        1
        for result in results
        if result.get("ok", False) and not (result.get("metadata") or {}).get("skipped")
    )
    return {
        "selected_assets": len(results),
        "validated": len(results) - skipped,
        "skipped": skipped,
        "passed": passed,
        "failed": failed,
        "issues": severity_counts,
        "by_kind": dict(sorted(by_kind.items())),
    }


def flatten_asset_issues(results: list[dict[str, Any]], project_root: Path) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for result in results:
        rel_path = path_relative_to(Path(result.get("path", "")), project_root)
        for item in result.get("issues", []):
            enriched = dict(item)
            enriched.setdefault("path", rel_path)
            flattened.append(enriched)
    return flattened


def print_asset_ls(result: dict[str, Any]) -> None:
    output_result(result, False)
    project = result.get("project")
    if isinstance(project, dict):
        print(f"Project: {project.get('name')} ({project.get('path')})")
    summary = result.get("summary", {})
    if isinstance(summary, dict):
        print(
            f"Assets: {summary.get('returned_assets', 0)} shown / {summary.get('total_assets', 0)} total "
            f"by kind {summary.get('by_kind', {})}"
        )
    for entry in result.get("assets", []):
        conf_state = "conf=ok" if entry.get("conf_exists") and entry.get("conf_ok") else "conf=missing"
        if entry.get("conf_exists") and not entry.get("conf_ok"):
            conf_state = "conf=invalid"
        print(
            f"{entry.get('kind'):10} {entry.get('relative_path')} "
            f"{entry.get('size_bytes')} bytes {conf_state}"
        )


def print_asset_show(result: dict[str, Any]) -> None:
    output_result(result, False)
    asset = result.get("asset", {})
    if isinstance(asset, dict):
        print(f"Asset: {asset.get('relative_path')} ({asset.get('kind')}, {asset.get('size_bytes')} bytes)")
        print(f"Conf: {asset.get('conf_path')} exists={asset.get('conf_exists')} ok={asset.get('conf_ok')}")
        if asset.get("out_path"):
            print(f"Output: {asset.get('out_path')} -> {asset.get('rom_path')}")
    validation = result.get("validation", {})
    if isinstance(validation, dict):
        metadata = validation.get("metadata", {})
        if isinstance(metadata, dict) and metadata.get("skipped"):
            print(f"Validation: skipped ({metadata.get('skip_reason')})")
        else:
            print(f"Validation: {'OK' if validation.get('ok') else 'FAILED'}")


def print_asset_validate_all(result: dict[str, Any]) -> None:
    output_result(result, False)
    summary = result.get("summary", {})
    if isinstance(summary, dict):
        print(
            f"Assets: included={summary.get('included', 0)} excluded={summary.get('excluded', 0)} "
            f"skipped={summary.get('skipped', 0)} passed={summary.get('passed', 0)} "
            f"failed={summary.get('failed', 0)} issues={summary.get('issues', {})}"
        )
    for item in result.get("results", []):
        metadata = item.get("metadata", {})
        skipped = isinstance(metadata, dict) and metadata.get("skipped")
        status = "SKIP" if skipped else ("OK" if item.get("ok") else "FAILED")
        print(f"{status} {item.get('kind')} {path_relative_to(Path(item.get('path', '')), Path(result['project']['path']))}")
        for issue_item in item.get("issues", []):
            print(f"  {issue_item.get('severity', 'info').upper()} {issue_item.get('rule')}: {issue_item.get('message')}")


def canonical_asset_exclusions(config: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    raw_patterns = config.get("assetExclusions", [])
    if not isinstance(raw_patterns, list):
        return [], [
            issue(
                "error",
                "PROJECT_ASSET_EXCLUSIONS",
                "assetExclusions must be an array of assets-relative glob strings.",
            )
        ]

    patterns: list[str] = []
    issues: list[dict[str, str]] = []
    for index, raw_pattern in enumerate(raw_patterns):
        normalized, error = normalize_asset_exclusion_pattern(raw_pattern)
        if error or normalized is None:
            issues.append(
                issue(
                    "error",
                    "PROJECT_ASSET_EXCLUSIONS",
                    f"assetExclusions[{index}]: {error}",
                )
            )
        elif normalized not in patterns:
            patterns.append(normalized)
    return patterns, issues


def output_asset_exclusion_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    output_result(result, False)
    print("Asset exclusions:")
    for pattern in result.get("patterns", []):
        print(f"  {pattern}")


def cmd_asset_exclusion_list(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    patterns: list[str] = []
    if config is not None:
        patterns, pattern_issues = canonical_asset_exclusions(config)
        issues.extend(pattern_issues)
    result = {
        "ok": not has_errors(issues),
        "command": "asset exclusion list",
        "kind": "asset_exclusions",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None
        else args.project,
        "patterns": patterns,
        "count": len(patterns),
        "issues": issues,
    }
    output_asset_exclusion_result(result, args.json)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def mutate_asset_exclusion(args: argparse.Namespace, operation: str) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    existing: list[str] = []
    if config is not None:
        existing, pattern_issues = canonical_asset_exclusions(config)
        issues.extend(pattern_issues)

    normalized, pattern_error = normalize_asset_exclusion_pattern(args.pattern)
    if pattern_error or normalized is None:
        issues.append(issue("error", "PROJECT_ASSET_EXCLUSIONS", pattern_error or "Invalid asset exclusion pattern."))

    proposed = list(existing)
    changed = False
    if normalized is not None and not has_errors(issues):
        if operation == "add":
            if normalized not in proposed:
                proposed.append(normalized)
                changed = True
        elif normalized not in proposed:
            issues.append(
                issue(
                    "error",
                    "ASSET_EXCLUSION_NOT_FOUND",
                    f"Asset exclusion pattern is not configured: {normalized}.",
                    "Use `bf64 asset exclusion list` to inspect configured patterns.",
                )
            )
        else:
            proposed.remove(normalized)
            changed = True

    changes: list[dict[str, str]] = []
    written = False
    if config_path is not None and config is not None and not has_errors(issues) and changed:
        action = "would_update" if args.dry_run else "updated"
        add_change(changes, action=action, kind="project_asset_exclusions", path=config_path)
        if not args.dry_run:
            proposed_config = dict(config)
            proposed_config["assetExclusions"] = proposed
            try:
                write_json_file(config_path, proposed_config)
                written = True
            except Exception as exc:  # noqa: BLE001
                issues.append(
                    issue(
                        "error",
                        "ASSET_EXCLUSION_IO",
                        f"Could not update project asset exclusions: {exc}.",
                        "Check project.p64proj permissions and retry.",
                    )
                )
                changes.clear()

    effective_patterns = proposed if not has_errors(issues) else existing
    effective_config = dict(config) if config is not None else None
    if effective_config is not None and (args.dry_run or written):
        effective_config["assetExclusions"] = effective_patterns
    result = {
        "ok": not has_errors(issues),
        "command": f"asset exclusion {operation}",
        "kind": "asset_exclusion_mutation",
        "operation": operation,
        "dry_run": bool(args.dry_run),
        "changed": changed and not has_errors(issues),
        "project": project_summary(project_root, config_path, effective_config)
        if project_root is not None and config_path is not None and effective_config is not None
        else args.project,
        "pattern": normalized or args.pattern,
        "patterns": effective_patterns,
        "changes": changes,
        "artifacts": [artifact_entry(config_path, "project_config")] if config_path is not None else [],
        "issues": issues,
    }
    output_asset_exclusion_result(result, args.json)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def cmd_asset_exclusion_add(args: argparse.Namespace) -> int:
    return mutate_asset_exclusion(args, "add")


def cmd_asset_exclusion_remove(args: argparse.Namespace) -> int:
    return mutate_asset_exclusion(args, "remove")


def cmd_asset_ls(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {"ok": False, "command": "asset ls", "kind": "asset_inventory", "project": args.project, "assets": [], "issues": issues}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            output_result(result, False)
        record_if_requested(args, result, 1)
        return 1

    inventory = scan_project_assets(project_root, args.kind, include_entries=True)
    assets = inventory.pop("assets", [])
    issues.extend(inventory.get("issues", []))
    result = {
        "ok": not has_errors(issues),
        "command": "asset ls",
        "kind": "asset_inventory",
        "project": project_summary(project_root, config_path, config),
        "summary": inventory,
        "assets": assets,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_asset_ls(result)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def cmd_asset_show(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {"ok": False, "command": "asset show", "kind": "asset", "project": args.project, "asset": args.asset, "issues": issues}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            output_result(result, False)
        record_if_requested(args, result, 1)
        return 1

    path, find_issues = resolve_project_asset(project_root, args.asset)
    issues.extend(find_issues)
    if path is None:
        result = {
            "ok": False,
            "command": "asset show",
            "kind": "asset",
            "project": project_summary(project_root, config_path, config),
            "asset": args.asset,
            "issues": issues,
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            output_result(result, False)
        record_if_requested(args, result, 1, config_path)
        return 1

    entry = asset_entry(project_root, path)
    conf, _conf_path = load_conf(path, None)
    conf, _defaulted_fields = normalize_asset_conf(conf)
    validation = validate_project_asset_entry(entry, limits, args)
    issues.extend(validation.get("issues", []))
    result = {
        "ok": not has_errors(issues) and validation.get("ok", False),
        "command": "asset show",
        "kind": "asset",
        "project": project_summary(project_root, config_path, config),
        "asset": entry,
        "conf": conf if entry["conf_ok"] else {},
        "validation": validation,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_asset_show(result)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, path)
    return exit_code


def cmd_asset_validate_all(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "asset validate-all",
            "kind": "asset_validation",
            "project": args.project,
            "results": [],
            "issues": issues,
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            output_result(result, False)
        record_if_requested(args, result, 1)
        return 1

    inventory = scan_project_assets(project_root, args.kind, include_entries=True)
    assets = inventory.pop("assets", [])
    selection = select_project_assets(assets, bool(getattr(args, "include_excluded", False)))
    results = [validate_project_asset_entry(entry, limits, args) for entry in selection["assets"]]
    validation_issues = flatten_asset_issues(results, project_root)
    issues.extend(validation_issues)
    summary = summarize_asset_validation(results)
    summary["included"] = selection["included"]
    summary["excluded"] = selection["excluded"]
    summary["include_excluded"] = selection["include_excluded"]
    summary["total_assets"] = inventory.get("total_assets", 0)
    summary["filter_kind"] = args.kind
    result = {
        "ok": not has_errors(issues),
        "command": "asset validate-all",
        "kind": "asset_validation",
        "project": project_summary(project_root, config_path, config),
        "summary": summary,
        "inventory": inventory,
        "results": results,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_asset_validate_all(result)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def validate_asset(args: argparse.Namespace) -> int:
    limits = load_limits()
    path = Path(args.path)
    if not path.exists():
        result = {
            "ok": False,
            "path": str(path),
            "kind": "unknown",
            "metadata": {},
            "issues": [issue("error", "PATH", "Asset path does not exist.", "Check the path and try again.")],
        }
        output_result(result, args.json)
        record_if_requested(args, result, 1, path)
        return 1

    conf, conf_path = load_conf(path, args.conf)
    kind = args.kind or classify_asset(path)
    if kind == "texture":
        result = validate_texture(path, conf, conf_path, args, limits)
    elif kind == "model":
        result = validate_model(path, conf, conf_path, args, limits)
    elif kind == "audio":
        result = validate_audio(path, conf, conf_path, args, limits)
    elif kind == "font":
        result = validate_font(path, conf_path)
    elif kind == "ui":
        result = validate_ui_document(path)
    elif kind == "prefab":
        result = validate_prefab_file(path, limits, conf, conf_path)
    elif kind == "node_graph":
        project_root = next((parent for parent in path.parents if (parent / PROJECT_FILENAME).is_file()), None)
        result = validate_node_graph_file(path, project_root, conf_path)
    elif kind == "project":
        result = validate_project_file(path, limits)
    elif kind == "scene":
        result = validate_scene_file(path, limits)
    else:
        result = {
            "ok": False,
            "path": str(path),
            "kind": kind,
            "metadata": {"conf": conf_path},
            "issues": [
                issue(
                    "error",
                    "TYPE",
                    f"Unsupported or unknown asset type for {path.name}.",
                    "Use --kind texture|model|audio|font|ui|project|scene, or validate a supported asset extension.",
                )
            ],
        }

    output_result(result, args.json)
    exit_code = 1 if has_errors(result.get("issues", [])) else 0
    record_if_requested(args, result, exit_code, path)
    return exit_code


DEFAULT_FONT_CHARSET = (
    " !\"#$%&'()*+,-./\n"
    "0123456789:;<=>?@\n"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`\n"
    "abcdefghijklmnopqrstuvwxyz{|}~"
)


def random_u64() -> int:
    value = uuid.uuid4().int & ((1 << 64) - 1)
    return value or 1


def normalize_asset_dest(source: Path, dest_arg: str | None) -> Path:
    if not dest_arg:
        return Path(source.name)
    raw = dest_arg.replace("\\", "/")
    if raw.startswith("assets/"):
        raw = raw[len("assets/") :]
    dest = Path(raw)
    if raw.endswith("/") or dest.suffix == "":
        dest = dest / source.name
    return dest


def is_safe_asset_relative_path(path: Path) -> bool:
    if path.is_absolute():
        return False
    return all(part not in {"", ".", ".."} for part in path.parts)


def editor_imports_extension(source: Path, kind: str) -> bool:
    ext = source.suffix.lower()
    if kind == "texture":
        return ext == ".png"
    if kind == "model":
        return ext in {".glb", ".gltf"}
    if kind == "audio":
        return ext in {".wav", ".mp3", ".xm"}
    if kind == "font":
        return ext == ".ttf"
    return False


def parse_int_option(value: Any, name: str, issues: list[dict[str, str]]) -> int | None:
    if value is None:
        return None
    parsed = optional_int(value)
    if parsed is None:
        issues.append(issue("error", "IMPORT_CONF", f"{name} must be an integer; got {value}."))
    return parsed


def default_import_conf(
    source: Path,
    kind: str,
    args: argparse.Namespace,
    limits: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    conf: dict[str, Any] = {
        "uuid": random_u64(),
        "format": 0,
        "baseScale": 16,
        "compression": 0,
        "gltfBVH": False,
        "exclude": bool(getattr(args, "exclude", False)),
        "fontCharset": "",
        "fontId": 0,
        "wavCompression": 0,
        "wavForceMono": False,
        "wavResampleRate": 0,
        "data": {},
    }

    compression = parse_int_option(getattr(args, "compression", None), "compression", issues)
    if compression is not None:
        conf["compression"] = compression

    if kind == "texture":
        fmt = parse_texture_format(getattr(args, "texture_format", None), limits)
        if getattr(args, "texture_format", None) is not None:
            if fmt is None:
                issues.append(
                    issue(
                        "error",
                        "IMPORT_CONF",
                        f"Unknown texture format '{args.texture_format}'.",
                        "Use `bf64 constraints texture --json` to list format ids.",
                    )
                )
            else:
                conf["format"] = fmt[1]
        elif source.name.lower().endswith(".bci.png"):
            conf["format"] = int(limits["texture"]["format_ids"]["BCI_256"])
        else:
            inferred = infer_texture_format_from_name(source, limits)
            if inferred:
                conf["format"] = inferred[1]

    if kind == "model":
        base_scale = parse_int_option(getattr(args, "base_scale", None), "baseScale", issues)
        if base_scale is not None:
            conf["baseScale"] = base_scale
        conf["gltfBVH"] = bool(getattr(args, "gltf_bvh", False))

    if kind == "audio":
        wav_compression = parse_int_option(getattr(args, "wav_compression", None), "wavCompression", issues)
        if wav_compression is not None:
            conf["wavCompression"] = wav_compression
        wav_resample_rate = parse_int_option(getattr(args, "wav_resample_rate", None), "wavResampleRate", issues)
        if wav_resample_rate is not None:
            conf["wavResampleRate"] = wav_resample_rate
        conf["wavForceMono"] = bool(getattr(args, "wav_force_mono", False))

    if kind == "font":
        font_id = parse_int_option(getattr(args, "font_id", None), "fontId", issues)
        if font_id is not None:
            conf["fontId"] = font_id
        conf["fontCharset"] = getattr(args, "font_charset", None) or DEFAULT_FONT_CHARSET

    return conf, issues


def validate_import_source(
    source: Path,
    kind: str,
    conf: dict[str, Any],
    target_conf: Path,
    args: argparse.Namespace,
    limits: dict[str, Any],
) -> dict[str, Any]:
    conf_path = str(target_conf)
    if kind == "texture":
        return validate_texture(source, conf, conf_path, args, limits)
    if kind == "model":
        return validate_model(source, conf, conf_path, args, limits)
    if kind == "audio":
        return validate_audio(source, conf, conf_path, args, limits)
    if kind == "font":
        return validate_font(source, conf_path)
    return {
        "ok": False,
        "path": str(source),
        "kind": kind,
        "metadata": {"conf": conf_path},
        "issues": [issue("error", "IMPORT_KIND", f"Unsupported import kind: {kind}.")],
    }


def remove_import_output(project_root: Path, target_path: Path, kind: str, changes: list[dict[str, str]]) -> None:
    outputs = asset_output_paths(project_root, target_path, kind)
    out_path = outputs.get("out_path")
    if not out_path:
        return
    generated = project_root / out_path
    if generated.exists() and generated.is_file():
        generated.unlink()
        add_change(changes, action="removed", kind="generated_output", path=generated)


def import_next_actions(result: dict[str, Any]) -> list[str]:
    if has_errors(result.get("issues", [])):
        return ["Fix the reported import issue, then rerun `bf64 import`."]
    target = result.get("target", {})
    project = result.get("project", {})
    if not isinstance(target, dict) or not isinstance(project, dict):
        return []
    project_path = shlex.quote(str(project.get("path", "")))
    asset_ref = shlex.quote(str(target.get("relative_path", "")))
    return [
        f"./bf64 asset show {asset_ref} --project {project_path} --json",
        f"./bf64 build --project {project_path} --json",
    ]


def print_import_result(result: dict[str, Any]) -> None:
    output_result(result, False)
    source = result.get("source", {})
    target = result.get("target", {})
    if isinstance(source, dict) and isinstance(target, dict):
        print(f"Import: {source.get('path')} -> {target.get('path')}")
        print(f"Kind: {source.get('kind')} mode={result.get('mode')}")
    changes = result.get("changes", [])
    if isinstance(changes, list):
        for change in changes:
            print(f"{change.get('action')} {change.get('kind')}: {change.get('path')}")
    if result.get("next_actions"):
        print("Next actions:")
        for action in result["next_actions"]:
            print(f"- {action}")


def cmd_import(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    source = Path(args.source).expanduser()
    changes: list[dict[str, str]] = []

    project_summary_data: dict[str, Any] | str = args.project
    if project_root is not None and config_path is not None and config is not None:
        project_summary_data = project_summary(project_root, config_path, config)

    kind = classify_asset(source)
    dest_rel = normalize_asset_dest(source, args.dest)
    target_path = (project_root / "assets" / dest_rel) if project_root is not None else Path("assets") / dest_rel
    target_conf = asset_conf_path(target_path)
    source_info: dict[str, Any] = {
        "path": str(source),
        "kind": kind,
        "size_bytes": source.stat().st_size if source.exists() and source.is_file() else 0,
    }
    target_info: dict[str, Any] = {
        "path": str(target_path),
        "relative_path": path_relative_to(target_path, project_root) if project_root is not None else str(Path("assets") / dest_rel),
        "asset_path": str(dest_rel),
        "conf_path": str(target_conf),
    }

    if project_root is None or config_path is None or config is None:
        pass
    elif not source.exists():
        issues.append(issue("error", "IMPORT_SOURCE", f"Source asset does not exist: {source}.", "Check the source path."))
    elif not source.is_file():
        issues.append(issue("error", "IMPORT_SOURCE", f"Source asset is not a file: {source}.", "Import one file at a time."))
    elif source.name.endswith(".conf"):
        issues.append(issue("error", "IMPORT_SOURCE", "Refusing to import a .conf sidecar as an asset.", "Import the asset file instead."))
    elif kind not in IMPORTABLE_ASSET_KINDS:
        issues.append(
            issue(
                "error",
                "IMPORT_KIND",
                f"`bf64 import` currently supports texture, model, audio, and font assets; got {kind}.",
                "Use a .png, .glb/.gltf, .wav/.mp3/.xm, or .ttf file. Prefab/node-graph import will follow dedicated validators.",
            )
        )
    elif not editor_imports_extension(source, kind):
        issues.append(
            issue(
                "error",
                "IMPORT_KIND",
                f"BF64 editor import does not classify {source.suffix or '(no extension)'} files as {kind} assets.",
                "Use .png, .glb/.gltf, .wav/.mp3/.xm, or .ttf for headless import.",
            )
        )

    if project_root is not None:
        if not is_safe_asset_relative_path(dest_rel):
            issues.append(
                issue(
                    "error",
                    "IMPORT_DEST",
                    f"Destination must stay under assets/ and cannot contain '..': {args.dest or source.name}.",
                    "Use a relative asset path such as `props/crate.png`.",
                )
            )
        elif target_path.suffix.lower() != source.suffix.lower():
            issues.append(
                issue(
                    "error",
                    "IMPORT_DEST",
                    f"Destination extension {target_path.suffix or '(none)'} does not match source extension {source.suffix or '(none)'}.",
                    "Use a destination filename with the same extension.",
                )
            )
        elif target_path.name.endswith(".conf"):
            issues.append(issue("error", "IMPORT_DEST", "Destination cannot be a .conf sidecar path."))

        try:
            if source.exists() and source.resolve() == target_path.resolve(strict=False):
                issues.append(
                    issue(
                        "error",
                        "IMPORT_DEST",
                        "Source and destination are the same file.",
                        "Choose a different --dest or skip import; the asset is already in the project.",
                    )
                )
        except OSError:
            pass
        if target_path.exists() and not args.force:
            issues.append(
                issue(
                    "error",
                    "IMPORT_EXISTS",
                    f"Target asset already exists: {target_path}.",
                    "Pass --force to overwrite this asset and its sidecar.",
                )
            )
        if target_conf.exists() and not args.force:
            issues.append(
                issue(
                    "error",
                    "IMPORT_EXISTS",
                    f"Target sidecar already exists: {target_conf}.",
                    "Pass --force to overwrite this sidecar.",
                )
            )

    conf: dict[str, Any] = {}
    validation: dict[str, Any] | None = None
    if not has_errors(issues) and project_root is not None:
        conf, conf_issues = default_import_conf(source, kind, args, limits)
        issues.extend(conf_issues)
    if not has_errors(issues) and project_root is not None:
        validation = validate_import_source(source, kind, conf, target_conf, args, limits)
        issues.extend(validation.get("issues", []))

    if not has_errors(issues) and project_root is not None and not args.dry_run:
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            existed = target_path.exists()
            shutil.copy2(source, target_path)
            add_change(changes, action="overwritten" if existed else "created", kind="asset", path=target_path, source=source)
            conf_existed = target_conf.exists()
            write_json_file(target_conf, conf)
            add_change(changes, action="overwritten" if conf_existed else "created", kind="sidecar", path=target_conf)
            remove_import_output(project_root, target_path, kind, changes)
        except Exception as exc:  # noqa: BLE001
            issues.append(
                issue(
                    "error",
                    "IMPORT_IO",
                    f"Could not import asset: {exc}",
                    "Check path permissions and available disk space, then rerun `bf64 import`.",
                )
            )
    elif not has_errors(issues) and args.dry_run:
        add_change(changes, action="would_create" if not target_path.exists() else "would_overwrite", kind="asset", path=target_path, source=source)
        add_change(changes, action="would_create" if not target_conf.exists() else "would_overwrite", kind="sidecar", path=target_conf)

    imported_entry = asset_entry(project_root, target_path) if project_root is not None and target_path.exists() else target_info
    artifacts = [
        artifact_entry(target_path, "imported_asset"),
        artifact_entry(target_conf, "asset_sidecar"),
    ]
    result = {
        "ok": not has_errors(issues),
        "command": "import",
        "kind": "asset_import",
        "mode": "dry_run" if args.dry_run else "copy",
        "dry_run": bool(args.dry_run),
        "project": project_summary_data,
        "source": source_info,
        "target": imported_entry,
        "conf": conf,
        "validation": validation,
        "changes": changes,
        "artifacts": artifacts,
        "issues": issues,
        "next_actions": [],
    }
    result["next_actions"] = import_next_actions(result)

    exit_code = 1 if has_errors(issues) else 0
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_import_result(result)
    record_if_requested(args, result, exit_code, target_path if not args.dry_run else config_path)
    return exit_code


def doctor_emulator_status() -> tuple[bool, str, str]:
    found = {name: shutil.which(name) for name in ("ares", "gopher64")}
    direct = [f"{name}={path}" for name, path in found.items() if path]
    if direct:
        selected = found.get("ares") or found.get("gopher64")
        version = emulator_version([str(selected)]) if selected else "unknown"
        return True, f"{', '.join(direct)} ({version})", version

    flatpak = shutil.which("flatpak")
    if flatpak:
        try:
            check = subprocess.run(
                [flatpak, "info", "dev.ares.ares"],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            check = None
        if check is not None and check.returncode == 0:
            version = emulator_version([flatpak, "run", "dev.ares.ares"])
            return True, f"Ares Flatpak: {flatpak} run dev.ares.ares ({version})", version
    return False, "ares and gopher64 are not on PATH; Ares Flatpak is not installed", "unknown"


def build_doctor_result(
    strict: bool = False,
    config: dict[str, Any] | None = None,
    explicit_n64_inst: str | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str, severity: str = "error", fix: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            issues.append(issue(severity, "DOCTOR", detail, fix))

    add_check(
        "python",
        sys.version_info >= (3, 10),
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "error",
        "Use Python 3.10 or newer.",
    )
    add_check("repo_root", REPO_ROOT.exists(), str(REPO_ROOT), "error")
    try:
        load_limits()
        add_check("limits_json", True, str(LIMITS_PATH))
    except Exception as exc:  # noqa: BLE001
        add_check("limits_json", False, f"Could not load {LIMITS_PATH}: {exc}", "error", "Fix limits.json.")

    for tool in ("git", "make"):
        path = shutil.which(tool)
        add_check(tool, path is not None, path or f"{tool} not found on PATH", "warning", f"Install {tool} or add it to PATH.")

    toolchain = build_toolchain_status(config or {}, False, explicit_n64_inst)
    for check in toolchain["checks"]:
        if check["name"] == "make":
            continue
        add_check(
            str(check["name"]),
            bool(check["ok"]),
            str(check["detail"]),
            "warning",
            "Run `bf64 toolchain install`, then `bf64 doctor --fix --project <project>`.",
        )

    emulator_ok, emulator_detail, emulator_version_text = doctor_emulator_status()
    add_check(
        "emulator",
        emulator_ok,
        emulator_detail,
        "warning",
        "Install ares or gopher64 for hardware-accurate run checks.",
    )

    if strict:
        for item in issues:
            if item["severity"] == "warning":
                item["severity"] = "error"

    return {
        "ok": not has_errors(issues),
        "command": "doctor",
        "metadata": {"repo_root": str(REPO_ROOT), "strict": strict},
        "toolchain": toolchain,
        "emulator": {
            "available": emulator_ok,
            "detail": emulator_detail,
            "version": emulator_version_text,
        },
        "checks": checks,
        "issues": issues,
    }


def shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def apply_doctor_fix(
    project_arg: str | None,
    explicit_n64_inst: str | None,
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None, Path | None, list[dict[str, str]]]:
    changes: list[dict[str, Any]] = []
    fix_issues: list[dict[str, str]] = []
    result: dict[str, Any] = {
        "requested": True,
        "dry_run": dry_run,
        "planned": False,
        "applied": False,
        "rolled_back": False,
        "changes": changes,
    }
    if not project_arg:
        fix_issues.append(
            issue(
                "error",
                "DOCTOR_FIX",
                "doctor --fix requires --project so the SDK selection can be persisted safely.",
                "Pass --project <project-dir>.",
            )
        )
        return result, None, None, fix_issues

    project_root, config_path, config, project_issues = resolve_project(project_arg)
    fix_issues.extend(project_issues)
    if project_root is None or config_path is None or config is None:
        return result, config, config_path, fix_issues

    sdk_path, source = discover_n64_inst(config, explicit_n64_inst)
    if sdk_path is None or not sdk_path.is_dir():
        fix_issues.append(
            issue(
                "error",
                "DOCTOR_FIX",
                f"No usable libdragon SDK directory was found{f' at {sdk_path}' if sdk_path else ''}.",
                "Run `bf64 toolchain install` or pass --n64-inst <sdk-path>.",
            )
        )
        return result, config, config_path, fix_issues

    missing = [rel for _name, rel in BUILD_TOOLCHAIN_FILES if not (sdk_path / rel).exists()]
    if missing:
        fix_issues.append(
            issue(
                "error",
                "DOCTOR_FIX",
                f"SDK at {sdk_path} is incomplete; missing: {', '.join(missing)}.",
                "Run `bf64 toolchain install --prefix <sdk-path>`.",
            )
        )
        return result, config, config_path, fix_issues

    resolved_sdk = str(sdk_path.resolve())
    env_path = project_root / ".bf64" / "env.sh"
    env_text = (
        "# Generated by bf64 doctor --fix. Source this file in interactive shells.\n"
        f"export N64_INST={shell_single_quote(resolved_sdk)}\n"
        'export PATH="$N64_INST/bin:$PATH"\n'
    )
    proposed_config = dict(config)
    proposed_config["pathN64Inst"] = resolved_sdk
    changes.extend(
        (
            {"action": "update", "path": str(config_path), "field": "pathN64Inst", "value": resolved_sdk},
            {"action": "write", "path": str(env_path)},
        )
    )
    result.update(
        {
            "planned": True,
            "source": source,
            "n64_inst": resolved_sdk,
            "environment_file": str(env_path),
            "activate": f"source {shlex.quote(str(env_path))}",
        }
    )
    if dry_run:
        return result, proposed_config, config_path, fix_issues

    original_config = config_path.read_bytes()
    original_env = env_path.read_bytes() if env_path.exists() else None

    def rollback() -> None:
        write_text_file(config_path, original_config.decode("utf-8"))
        if original_env is None:
            env_path.unlink(missing_ok=True)
        else:
            write_text_file(env_path, original_env.decode("utf-8"))
        result["rolled_back"] = True

    try:
        write_json_file(config_path, proposed_config)
        write_text_file(env_path, env_text)
    except Exception as exc:  # noqa: BLE001 - restore both files as one repair transaction
        try:
            rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            fix_issues.append(issue("error", "DOCTOR_FIX_ROLLBACK", f"Rollback failed: {rollback_exc}."))
        fix_issues.append(issue("error", "DOCTOR_FIX", f"Could not persist toolchain repair: {exc}."))
        return result, config, config_path, fix_issues

    validation_error = ""
    try:
        persisted = read_json_file(config_path)
        if not isinstance(persisted, dict) or persisted.get("pathN64Inst") != resolved_sdk:
            validation_error = "Persisted project config does not contain the selected SDK path."
        elif env_path.read_text(encoding="utf-8") != env_text:
            validation_error = "Persisted shell environment helper does not match the selected SDK path."
        else:
            final_status = build_toolchain_status(persisted, True)
            if not final_status.get("build_ready", False):
                failed = [
                    str(check.get("name"))
                    for check in final_status.get("checks", [])
                    if not check.get("ok")
                ]
                validation_error = f"Final toolchain validation failed{f': {', '.join(failed)}' if failed else ''}."
    except Exception as exc:  # noqa: BLE001 - any failed readback invalidates the transaction
        validation_error = f"Could not validate persisted toolchain repair: {exc}."

    if validation_error:
        try:
            rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            fix_issues.append(issue("error", "DOCTOR_FIX_ROLLBACK", f"Rollback failed: {rollback_exc}."))
        fix_issues.append(
            issue(
                "error",
                "DOCTOR_FIX_VALIDATION",
                validation_error,
                "Verify the SDK is complete and retry doctor --fix.",
            )
        )
        return result, config, config_path, fix_issues

    result["applied"] = True
    return result, proposed_config, config_path, fix_issues


def cmd_doctor(args: argparse.Namespace) -> int:
    config: dict[str, Any] = {}
    config_path: Path | None = None
    context_issues: list[dict[str, str]] = []
    fix_result: dict[str, Any] = {
        "requested": False,
        "dry_run": bool(args.dry_run),
        "planned": False,
        "applied": False,
        "changes": [],
    }
    if args.fix:
        fix_result, fixed_config, config_path, context_issues = apply_doctor_fix(
            args.project,
            args.n64_inst,
            bool(args.dry_run),
        )
        if fixed_config is not None:
            config = fixed_config
    elif args.project:
        _root, config_path, loaded_config, context_issues = resolve_project(args.project)
        if loaded_config is not None:
            config = loaded_config

    result = build_doctor_result(args.strict, config, args.n64_inst)
    result["fix"] = fix_result
    result["issues"] = context_issues + result["issues"]
    result["ok"] = not has_errors(result["issues"])
    if config_path is not None:
        result["metadata"]["project_config"] = str(config_path)
    exit_code = 2 if has_errors(result.get("issues", [])) else 0
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        for check in result.get("checks", []):
            status = "OK" if check["ok"] else "MISSING"
            print(f"{status} {check['name']}: {check['detail']}")
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def resolve_executable(value: str) -> str | None:
    expanded = Path(value).expanduser()
    if expanded.is_absolute() or "/" in value or "\\" in value:
        candidate = expanded.resolve()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        return None
    return shutil.which(value)


def cmd_toolchain_detect(args: argparse.Namespace) -> int:
    config: dict[str, Any] = {}
    project_issues: list[dict[str, str]] = []
    config_path: Path | None = None
    if args.project:
        _root, config_path, loaded, project_issues = resolve_project(args.project)
        if loaded is not None:
            config = loaded
    status = build_toolchain_status(config, True, args.prefix)
    issues = project_issues + status["issues"]
    result = {
        "ok": not has_errors(issues),
        "command": "toolchain detect",
        "toolchain": status,
        "issues": issues,
    }
    exit_code = 0 if result["ok"] else 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        print(f"N64_INST: {status['effective_N64_INST'] or '(not found)'}")
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def toolchain_step(name: str, argv: list[str], reason: str) -> dict[str, Any]:
    return {
        "name": name,
        "argv": argv,
        "reason": reason,
        "executed": False,
        "returncode": None,
    }


def cmd_toolchain_install(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser().resolve()
    prefix = Path(args.prefix).expanduser().resolve()
    make_binary = resolve_executable(args.make_binary)
    issues: list[dict[str, str]] = []
    steps: list[dict[str, Any]] = []

    if not source.is_dir() or not (source / "Makefile").is_file():
        issues.append(
            issue(
                "error",
                "TOOLCHAIN_SOURCE",
                f"libdragon source checkout is missing or has no Makefile: {source}.",
                "Pass --source <libdragon-checkout>.",
            )
        )
    if make_binary is None:
        issues.append(issue("error", "TOOLCHAIN_MAKE", f"Make executable was not found: {args.make_binary}."))

    compiler = prefix / "bin" / "mips64-elf-gcc"
    if not compiler.exists() and not args.skip_toolchain:
        build_script = source / "tools" / "build-toolchain.sh"
        if not build_script.is_file():
            issues.append(
                issue(
                    "error",
                    "TOOLCHAIN_SOURCE",
                    f"Cross-toolchain bootstrap script is missing: {build_script}.",
                )
            )
        else:
            steps.append(
                toolchain_step(
                    "cross_toolchain",
                    ["bash", str(build_script)],
                    "Build and install the mips64-elf GCC/binutils toolchain because the compiler is absent.",
                )
            )
    elif not compiler.exists():
        issues.append(
            issue(
                "error",
                "TOOLCHAIN_COMPILER",
                f"Cross compiler is missing at {compiler} and --skip-toolchain was requested.",
            )
        )

    if make_binary is not None:
        steps.append(
            toolchain_step(
                "libdragon",
                [make_binary, "-C", str(source), "install", "tools-install"],
                "Install libdragon headers, library, make includes, and host asset tools.",
            )
        )
        if not args.skip_tiny3d:
            tiny3d = REPO_ROOT / "vendored" / "tiny3d"
            if not (tiny3d / "Makefile").is_file():
                issues.append(issue("error", "TOOLCHAIN_TINY3D", f"Bundled Tiny3D checkout is missing: {tiny3d}."))
            else:
                steps.append(
                    toolchain_step(
                        "tiny3d",
                        [make_binary, "-C", str(tiny3d), "install"],
                        "Build and install the BF64-pinned Tiny3D library into the SDK.",
                    )
                )

    env = os.environ.copy()
    env["N64_INST"] = str(prefix)
    env["PATH"] = str(prefix / "bin") + os.pathsep + env.get("PATH", "")
    failed = has_errors(issues)
    if not args.dry_run and not failed:
        prefix.mkdir(parents=True, exist_ok=True)
        for index, step in enumerate(steps):
            started = time.perf_counter()
            try:
                proc = subprocess.run(
                    step["argv"],
                    cwd=str(source) if step["name"] == "cross_toolchain" else None,
                    env=env,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    check=False,
                    timeout=args.timeout or None,
                )
                step.update(
                    {
                        "executed": True,
                        "returncode": proc.returncode,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                        "stdout_tail": proc.stdout[-8000:],
                        "stderr_tail": proc.stderr[-8000:],
                    }
                )
            except subprocess.TimeoutExpired as exc:
                step.update(
                    {
                        "executed": True,
                        "timed_out": True,
                        "returncode": None,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                        "stdout_tail": str(exc.stdout or "")[-8000:],
                        "stderr_tail": str(exc.stderr or "")[-8000:],
                    }
                )
            except OSError as exc:
                step.update(
                    {
                        "executed": True,
                        "returncode": None,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                        "stderr_tail": str(exc),
                    }
                )
            if step.get("returncode") != 0:
                issues.append(
                    issue(
                        "error",
                        "TOOLCHAIN_INSTALL",
                        f"Toolchain step {step['name']} failed with exit code {step.get('returncode')}.",
                        "Inspect the step stdout_tail and stderr_tail fields.",
                    )
                )
                for pending in steps[index + 1 :]:
                    pending["skipped"] = True
                break

    post_status = build_toolchain_status({}, not args.dry_run, str(prefix))
    if not args.dry_run:
        issues.extend(post_status["issues"])
    result = {
        "ok": not has_errors(issues),
        "command": "toolchain install",
        "dry_run": bool(args.dry_run),
        "source": str(source),
        "prefix": str(prefix),
        "environment": {"N64_INST": str(prefix), "path_prepend": str(prefix / "bin")},
        "steps": steps,
        "toolchain": post_status,
        "issues": issues,
        "next_actions": [
            f"Run `bf64 doctor --fix --project <project> --n64-inst {shlex.quote(str(prefix))}` after installation."
        ],
    }
    exit_code = 0 if result["ok"] else 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        for step in steps:
            state = "done" if step["executed"] and step.get("returncode") == 0 else "planned"
            print(f"{state:7} {step['name']}: {shlex.join(step['argv'])}")
    record_if_requested(args, result, exit_code, prefix)
    return exit_code


def default_scene_document(name: str) -> dict[str, Any]:
    return {
        "conf": {
            "name": name,
            "fbWidth": 320,
            "fbHeight": 240,
            "fbFormat": 0,
            "clearColor": [0.2, 0.2, 0.2, 1.0],
            "doClearColor": True,
            "doClearDepth": True,
            "renderPipeline": 0,
            "frameLimit": 0,
            "filter": 1,
            "audioFreq": 32000,
            "physicsTickRate": 50,
            "gravity": [0.0, -9.81, 0.0],
            "visualUnitsPerMeter": 100.0,
            "velocitySolverIterations": 7,
            "positionSolverIterations": 6,
            "interpolatePhysicsTransforms": True,
            "layers3D": [],
            "layersPtx": [],
            "layers2D": [],
        },
        "graph": {
            "name": "Scene",
            "uuid": 0,
            "proportionalScale": False,
            "selectable": True,
            "enabled": True,
            "uuidPrefab": 0,
            "pos": [0.0, 0.0, 0.0],
            "rot": [0.0, 0.0, 0.0, 1.0],
            "scale": [1.0, 1.0, 1.0],
            "propOverrides": {},
            "components": [],
            "children": [],
        },
    }


def next_scene_id(project_root: Path) -> int:
    scenes, _issues = iter_scene_files(project_root)
    return max((scene_id for scene_id, _path in scenes), default=0) + 1


def parse_cli_int(value: str) -> int:
    return int(value, 0)


def scene_object_records(doc: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any] | None, list[Any]]]:
    graph = doc.get("graph")
    if not isinstance(graph, dict):
        return []
    root_children = graph.get("children")
    if not isinstance(root_children, list):
        return []
    records: list[tuple[dict[str, Any], dict[str, Any] | None, list[Any]]] = []

    def visit(children: list[Any], parent: dict[str, Any] | None) -> None:
        for child in children:
            if not isinstance(child, dict):
                continue
            records.append((child, parent, children))
            grandchildren = child.get("children")
            if isinstance(grandchildren, list):
                visit(grandchildren, child)

    visit(root_children, None)
    return records


def find_scene_object(
    doc: dict[str, Any],
    object_ref: str,
) -> tuple[tuple[dict[str, Any], dict[str, Any] | None, list[Any]] | None, list[dict[str, str]]]:
    records = scene_object_records(doc)
    try:
        wanted_uuid = parse_cli_int(object_ref)
    except ValueError:
        wanted_uuid = None
    if wanted_uuid is not None:
        for record in records:
            if record[0].get("uuid") == wanted_uuid:
                return record, []
    matches = [record for record in records if str(record[0].get("name", "")).lower() == object_ref.lower()]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, [
            issue(
                "error",
                "SCENE_OBJECT_AMBIGUOUS",
                f"Object name '{object_ref}' matches {len(matches)} objects.",
                "Use the persistent object UUID instead of its name.",
            )
        ]
    return None, [
        issue(
            "error",
            "SCENE_OBJECT",
            f"Could not find object '{object_ref}'.",
            "Use `bf64 scene show <scene> --json` to inspect object UUIDs.",
        )
    ]


def generate_scene_object_uuid(doc: dict[str, Any]) -> int:
    used = {
        int(obj.get("uuid"))
        for obj, _parent, _siblings in scene_object_records(doc)
        if isinstance(obj.get("uuid"), int)
    }
    for _attempt in range(1024):
        value = uuid.uuid4().int & 0xFFFFFFFF
        if value and value not in used:
            return value
    raise RuntimeError("could not allocate a unique 32-bit scene object UUID")


def default_scene_object(name: str, object_uuid: int, position: list[float] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "uuid": object_uuid,
        "proportionalScale": False,
        "selectable": True,
        "enabled": True,
        "uuidPrefab": 0,
        "pos": position or [0.0, 0.0, 0.0],
        "rot": [0.0, 0.0, 0.0, 1.0],
        "scale": [1.0, 1.0, 1.0],
        "propOverrides": {},
        "components": [],
        "children": [],
    }


def normalize_component_type(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def resolve_component_type(value: str) -> tuple[int | None, list[dict[str, str]]]:
    try:
        component_id = parse_cli_int(value)
    except ValueError:
        component_id = COMPONENT_ALIASES.get(normalize_component_type(value))
    if component_id is None or component_id < 0 or component_id >= len(COMPONENT_NAMES):
        return None, [
            issue(
                "error",
                "SCENE_COMPONENT_TYPE",
                f"Unknown component type '{value}'.",
                f"Use a stable component id 0..{len(COMPONENT_NAMES) - 1} or a name such as camera, model, audio3d, code, or ui.",
            )
        ]
    return component_id, []


def default_material_instance() -> dict[str, Any]:
    return {
        "depth": 0,
        "env": [0.0, 0.0, 0.0, 0.0],
        "fresnel": 0,
        "fresnelColor": [0.0, 0.0, 0.0, 0.0],
        "lighting": False,
        "prim": [1.0, 1.0, 1.0, 1.0],
        "setDepth": False,
        "setEnv": False,
        "setFresnel": False,
        "setLighting": False,
        "setPrim": False,
    }


def default_component_data(component_id: int, scene_doc: dict[str, Any]) -> dict[str, Any]:
    conf = scene_doc.get("conf") if isinstance(scene_doc.get("conf"), dict) else {}
    fb_width = optional_int(conf.get("fbWidth")) or 320
    fb_height = optional_int(conf.get("fbHeight")) or 240
    defaults: dict[int, dict[str, Any]] = {
        0: {"script": 0, "args": {}},
        1: {"model": 0, "layerIdx": 0, "culling": False, "meshFilter": "", "material": default_material_instance()},
        2: {"index": 0, "type": 0, "color": [0.0, 0.0, 0.0, 0.0], "size": 0.0},
        3: {
            "vpOffset": [0, 0],
            "vpSize": [fb_width, fb_height],
            "fov": 65.0,
            "near": 100.0,
            "far": 4000.0,
            "aspect": 0.0,
            "mode": 1,
        },
        4: {"modelUUID": 0, "meshFilter": "", "maskRead": 0, "maskWrite": 0},
        5: {
            "halfExtend": [10.0, 10.0, 10.0],
            "offset": [0.0, 0.0, 0.0],
            "type": 0,
            "isTrigger": False,
            "maskRead": 0,
            "maskWrite": 0,
            "friction": 0.8,
            "bounce": 0.0,
        },
        6: {"audioUUID": 0, "volume": 1.0, "loop": False, "autoPlay": False},
        7: {"type": 0, "objectUUID": 0, "usePos": False, "useScale": False, "useRot": False},
        8: {"halfExtend": [0.0, 0.0, 0.0], "offset": [0.0, 0.0, 0.0], "type": 0},
        9: {"asset": 0, "autoRun": True, "objRefs": {}, "varDefaults": {}},
        10: {"model": 0, "layerIdx": 0, "previewAnimName": "", "material": default_material_instance()},
        11: {
            "mass": 1.0,
            "isKinematic": False,
            "constrainPosX": False,
            "constrainPosY": False,
            "constrainPosZ": False,
            "constrainRotX": False,
            "constrainRotY": False,
            "constrainRotZ": False,
            "hasGravity": True,
            "gravityScalar": 1.0,
            "timeScalar": 1.0,
            "angularDamping": 0.03,
        },
        12: {
            "up": [0.0, 1.0, 0.0],
            "centerOffset": [0.0, 0.0, 0.0],
            "gravity": 30.0,
            "maxFallSpeed": 55.0,
            "floorMaxAngle": 0.785398,
            "stepHeight": 0.25,
            "floorSnapDistance": 0.3,
            "radius": 0.5,
            "height": 2.0,
            "collTypes": 1,
            "maxSlides": 4,
            "readMask": 1,
            "followFloor": True,
        },
        13: {"document": 0, "layer": 0, "active": True},
        14: {
            "audioUUID": 0,
            "volume": 1.0,
            "loop": False,
            "autoPlay": False,
            "minDistance": 50.0,
            "maxDistance": 1000.0,
            "rolloff": 1.0,
            "pitch": 1.0,
        },
    }
    return json.loads(json.dumps(defaults[component_id]))


def generate_component_uuid(doc: dict[str, Any]) -> int:
    used = {
        int(component.get("uuid"))
        for obj, _parent, _siblings in scene_object_records(doc)
        for component in obj.get("components", [])
        if isinstance(component, dict) and isinstance(component.get("uuid"), int)
    }
    for _attempt in range(1024):
        value = uuid.uuid4().int & 0xFFFFFFFFFFFFFFFF
        if value and value not in used:
            return value
    raise RuntimeError("could not allocate a unique 64-bit component UUID")


def parse_json_object_argument(value: str | None, label: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if value is None:
        return {}, []
    try:
        raw = Path(value[1:]).read_text(encoding="utf-8") if value.startswith("@") else value
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return {}, [issue("error", "SCENE_JSON", f"Could not parse {label} JSON: {exc}.")]
    if not isinstance(parsed, dict):
        return {}, [issue("error", "SCENE_JSON", f"{label} JSON must be an object.")]
    return parsed, []


def find_scene_component(
    obj: dict[str, Any], component_ref: str
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    components = obj.get("components", [])
    if not isinstance(components, list):
        return None, [issue("error", "SCENE", "Object components must be an array.")]
    try:
        wanted_uuid = parse_cli_int(component_ref)
    except ValueError:
        wanted_uuid = None
    if wanted_uuid is not None:
        for component in components:
            if isinstance(component, dict) and component.get("uuid") == wanted_uuid:
                return component, []
    matches = [
        component
        for component in components
        if isinstance(component, dict) and str(component.get("name", "")).lower() == component_ref.lower()
    ]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, [
            issue(
                "error",
                "SCENE_COMPONENT_AMBIGUOUS",
                f"Component name '{component_ref}' matches {len(matches)} components.",
                "Use the persistent component UUID.",
            )
        ]
    return None, [issue("error", "SCENE_COMPONENT", f"Could not find component '{component_ref}'.")]


def resolve_component_asset(
    project_root: Path,
    component_id: int,
    asset_ref: str,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    mapping = COMPONENT_ASSET_FIELDS.get(component_id)
    if mapping is None:
        return None, [
            issue(
                "error",
                "SCENE_COMPONENT_ASSET",
                f"{COMPONENT_NAMES[component_id]} does not accept an asset assignment.",
            )
        ]
    field, expected_kind = mapping
    path, issues = resolve_project_asset(project_root, asset_ref)
    if path is None:
        return None, issues
    entry = asset_entry(project_root, path)
    if entry.get("kind") != expected_kind:
        issues.append(
            issue(
                "error",
                "SCENE_COMPONENT_ASSET",
                f"{COMPONENT_NAMES[component_id]} requires a {expected_kind} asset; got {entry.get('kind')}.",
            )
        )
    if component_id == COMPONENT_ALIASES["audio3d"] and path.suffix.lower() == ".xm":
        issues.append(
            issue(
                "error",
                "SCENE_COMPONENT_ASSET",
                "Audio (3D) requires a WAV/MP3 waveform asset; XM music is 2D-only.",
                "Attach XM music to Audio (2D), or select a WAV/MP3 asset for positional playback.",
            )
        )
    asset_uuid = optional_int(entry.get("uuid"))
    if asset_uuid is None or asset_uuid <= 0:
        issues.append(
            issue(
                "error",
                "SCENE_COMPONENT_ASSET",
                f"Asset {entry.get('relative_path')} has no positive UUID in its .conf sidecar.",
                "Import or recreate the asset through BF64 so it has stable metadata.",
            )
        )
    if bool(entry.get("exclude")):
        issues.append(
            issue(
                "error",
                "SCENE_COMPONENT_ASSET",
                f"Asset {entry.get('relative_path')} is excluded from builds.",
                "Clear its sidecar exclude flag/project exclusion pattern or assign a build-included asset.",
            )
        )
    return {
        "field": field,
        "uuid": asset_uuid,
        "path": entry.get("relative_path"),
        "kind": entry.get("kind"),
    }, issues


def resolve_object_script(project_root: Path, script_ref: str) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    scripts_root = project_root / "src" / "user"
    entries: list[dict[str, Any]] = []
    if scripts_root.is_dir():
        for path in sorted(scripts_root.rglob("*.cpp")):
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue
            # The editor emits a 16-hex-digit namespace identifier and replaces
            # its first digit with C so it is a valid C++ identifier. The C is
            # therefore part of the stored UUID, not a prefix outside it.
            object_match = re.search(r"::Script::([Cc][0-9A-Fa-f]{15})(?![0-9A-Fa-f])", source)
            global_match = re.search(r"::GlobalScript::([Cc][0-9A-Fa-f]{15})(?![0-9A-Fa-f])", source)
            if object_match:
                entries.append(
                    {
                        "uuid": int(object_match.group(1), 16),
                        "path": path_relative_to(path, project_root).replace("\\", "/"),
                        "name": path.name,
                        "kind": "object_script",
                    }
                )
            elif global_match:
                entries.append(
                    {
                        "uuid": int(global_match.group(1), 16),
                        "path": path_relative_to(path, project_root).replace("\\", "/"),
                        "name": path.name,
                        "kind": "global_script",
                    }
                )

    try:
        wanted_uuid = parse_cli_int(script_ref)
    except ValueError:
        wanted_uuid = None
    wanted = script_ref.replace("\\", "/")
    matches = [
        entry
        for entry in entries
        if (wanted_uuid is not None and entry["uuid"] == wanted_uuid)
        or wanted in {entry["path"], entry["name"], Path(entry["name"]).stem}
    ]
    if len(matches) > 1:
        return None, [
            issue(
                "error",
                "SCENE_SCRIPT_AMBIGUOUS",
                f"Script reference '{script_ref}' matches {len(matches)} files.",
                "Use the project-relative src/user/<path>.cpp reference or script UUID.",
            )
        ]
    if not matches:
        return None, [
            issue(
                "error",
                "SCENE_SCRIPT",
                f"Could not find script '{script_ref}' under src/user.",
                        "Create an object script with a 16-hex-digit P64::Script:: namespace identifier beginning with C.",
            )
        ]
    if matches[0]["kind"] != "object_script":
        return None, [
            issue(
                "error",
                "SCENE_SCRIPT_KIND",
                f"{matches[0]['path']} is a global script and cannot be attached to a Code component.",
                "Select a P64::Script:: object script instead.",
            )
        ]
    return matches[0], []


def cmd_scene_create(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "scene create",
            "kind": "scene_mutation",
            "operation": "create",
            "project": args.project,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scene_id = args.id if args.id is not None else next_scene_id(project_root)
    scene_path = project_root / "data" / "scenes" / str(scene_id) / "scene.json"
    if scene_id <= 0:
        issues.append(issue("error", "SCENE_ID", "Scene ids must be positive integers."))
    if scene_path.exists() or scene_path.parent.exists():
        issues.append(
            issue(
                "error",
                "SCENE_EXISTS",
                f"Scene id {scene_id} already exists at {scene_path.parent}.",
                "Choose another --id or omit it to allocate the next id.",
            )
        )

    doc = default_scene_document(args.name)
    validation = validate_scene_doc(scene_path, scene_id, doc, limits)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_create", kind="scene", path=scene_path)
        else:
            write_json_file(scene_path, doc)
            add_change(changes, action="created", kind="scene", path=scene_path)

    result = {
        "ok": not has_errors(issues),
        "command": "scene create",
        "kind": "scene_mutation",
        "operation": "create",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config),
        "scene": {"id": scene_id, "name": args.name, "path": str(scene_path)},
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, scene_path)
    return exit_code


def cmd_scene_duplicate(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "scene duplicate",
            "kind": "scene_mutation",
            "operation": "duplicate",
            "project": args.project,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    source, source_doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if source is not None:
        issues.extend(source.get("issues", []))
    scene_id = args.id if args.id is not None else next_scene_id(project_root)
    scene_path = project_root / "data" / "scenes" / str(scene_id) / "scene.json"
    if scene_id <= 0:
        issues.append(issue("error", "SCENE_ID", "Scene ids must be positive integers."))
    if scene_path.exists() or scene_path.parent.exists():
        issues.append(
            issue(
                "error",
                "SCENE_EXISTS",
                f"Scene id {scene_id} already exists at {scene_path.parent}.",
                "Choose another --id or omit it to allocate the next id.",
            )
        )

    doc = json.loads(json.dumps(source_doc)) if source_doc is not None else default_scene_document(args.name or "Scene Copy")
    source_name = str((source or {}).get("metadata", {}).get("name", args.scene))
    scene_name = args.name or f"{source_name} Copy"
    doc.setdefault("conf", {})["name"] = scene_name
    validation = validate_scene_doc(scene_path, scene_id, doc, limits)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if source is not None and source_doc is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_create", kind="scene", path=scene_path, source=Path(source["path"]))
        else:
            write_json_file(scene_path, doc)
            add_change(changes, action="created", kind="scene", path=scene_path, source=Path(source["path"]))

    source_info = {
        "id": (source or {}).get("metadata", {}).get("scene_id"),
        "name": source_name,
        "path": (source or {}).get("path"),
    }
    result = {
        "ok": source is not None and source_doc is not None and not has_errors(issues),
        "command": "scene duplicate",
        "kind": "scene_mutation",
        "operation": "duplicate",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config),
        "source": source_info,
        "scene": {"id": scene_id, "name": scene_name, "path": str(scene_path)},
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, scene_path)
    return exit_code


def cmd_scene_rename(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "scene rename",
            "kind": "scene_mutation",
            "operation": "rename",
            "project": args.project,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scene, doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if scene is not None:
        issues.extend(scene.get("issues", []))
    if not args.name.strip():
        issues.append(issue("error", "SCENE_NAME", "Scene name cannot be empty."))

    scene_id = (scene or {}).get("metadata", {}).get("scene_id")
    scene_path = Path((scene or {}).get("path", project_root / "data" / "scenes" / str(args.scene) / "scene.json"))
    if doc is None:
        proposed = default_scene_document(args.name)
    else:
        proposed = json.loads(json.dumps(doc))
        proposed.setdefault("conf", {})["name"] = args.name
    validation = validate_scene_doc(scene_path, optional_int(scene_id), proposed, limits)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if scene is not None and doc is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="scene", path=scene_path)
        else:
            write_json_file(scene_path, proposed)
            add_change(changes, action="updated", kind="scene", path=scene_path)

    result = {
        "ok": scene is not None and doc is not None and not has_errors(issues),
        "command": "scene rename",
        "kind": "scene_mutation",
        "operation": "rename",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config),
        "scene": {"id": scene_id, "name": args.name, "path": str(scene_path)},
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, scene_path)
    return exit_code


def cmd_scene_delete(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "scene delete",
            "kind": "scene_mutation",
            "operation": "delete",
            "project": args.project,
            "rolled_back": False,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scene, _doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if scene is not None:
        issues.extend(scene.get("issues", []))
    scene_id = optional_int((scene or {}).get("metadata", {}).get("scene_id"))
    scene_path = Path((scene or {}).get("path", project_root / "data" / "scenes" / str(args.scene) / "scene.json"))
    scene_dir = scene_path.parent

    proposed_config = json.loads(json.dumps(config))
    reference_keys = [
        key
        for key in ("sceneIdOnBoot", "sceneIdOnReset", "sceneIdLastOpened")
        if scene_id is not None and optional_int(config.get(key, 1)) == scene_id
    ]
    replacement_info: dict[str, Any] | None = None
    if reference_keys:
        if not args.replacement:
            issues.append(
                issue(
                    "error",
                    "SCENE_REFERENCED",
                    f"Scene {scene_id} is referenced by {', '.join(reference_keys)}.",
                    "Pass --replacement <scene> to atomically update project references while deleting.",
                )
            )
        else:
            replacement, _replacement_doc, replacement_issues = find_scene(project_root, args.replacement, limits)
            issues.extend(replacement_issues)
            replacement_id = optional_int((replacement or {}).get("metadata", {}).get("scene_id"))
            if replacement_id is None or replacement_id == scene_id:
                issues.append(issue("error", "SCENE_REPLACEMENT", "Replacement must be a different existing scene."))
            else:
                replacement_info = {
                    "id": replacement_id,
                    "name": (replacement or {}).get("metadata", {}).get("name"),
                }
                for key in reference_keys:
                    proposed_config[key] = replacement_id

    current_validation = validate_project_file(config_path, limits)
    issues.extend(current_validation.get("issues", []))
    validation = current_validation
    changes: list[dict[str, str]] = []
    rolled_back = False
    tombstone = scene_dir.with_name(f".{scene_dir.name}.bf64-delete-{uuid.uuid4().hex}")
    if scene is not None and scene_id is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_delete", kind="scene", path=scene_dir)
            if proposed_config != config:
                add_change(changes, action="would_update", kind="project_config", path=config_path)
        else:
            moved = False
            config_changed = proposed_config != config
            config_written = False
            try:
                os.replace(scene_dir, tombstone)
                moved = True
                if config_changed:
                    write_json_file(config_path, proposed_config)
                    config_written = True
                validation = validate_project_file(config_path, limits)
                if not validation.get("ok", False):
                    raise RuntimeError("project validation failed after deleting the scene")
                shutil.rmtree(tombstone)
                add_change(changes, action="deleted", kind="scene", path=scene_dir)
                if config_changed:
                    add_change(changes, action="updated", kind="project_config", path=config_path)
            except Exception as exc:  # noqa: BLE001 - transaction is restored below
                rollback_errors: list[str] = []
                if config_written:
                    try:
                        write_json_file(config_path, config)
                    except Exception as rollback_exc:  # noqa: BLE001
                        rollback_errors.append(f"project config: {rollback_exc}")
                if moved and tombstone.exists() and not scene_dir.exists():
                    try:
                        os.replace(tombstone, scene_dir)
                    except Exception as rollback_exc:  # noqa: BLE001
                        rollback_errors.append(f"scene directory: {rollback_exc}")
                rolled_back = True
                message = f"Scene deletion failed and was rolled back: {exc}."
                if rollback_errors:
                    message += f" Rollback errors: {'; '.join(rollback_errors)}"
                issues.append(
                    issue(
                        "error",
                        "SCENE_ROLLBACK",
                        message,
                        "Inspect project permissions and validation errors before retrying.",
                    )
                )
                for validation_issue in validation.get("issues", []):
                    enriched = dict(validation_issue)
                    enriched["message"] = f"Proposed state: {enriched.get('message', '')}"
                    issues.append(enriched)

    result_config = proposed_config if not rolled_back and not args.dry_run else config
    result = {
        "ok": scene is not None and scene_id is not None and not has_errors(issues),
        "command": "scene delete",
        "kind": "scene_mutation",
        "operation": "delete",
        "dry_run": bool(args.dry_run),
        "rolled_back": rolled_back,
        "project": project_summary(project_root, config_path, result_config),
        "scene": {
            "id": scene_id,
            "name": (scene or {}).get("metadata", {}).get("name"),
            "path": str(scene_path),
        },
        "replacement": replacement_info,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source"), artifact_entry(config_path, "project_config")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def cmd_scene_object_add(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "scene object add",
            "kind": "scene_mutation",
            "operation": "object_add",
            "project": args.project,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scene, doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if scene is not None:
        issues.extend(scene.get("issues", []))
    scene_id = optional_int((scene or {}).get("metadata", {}).get("scene_id"))
    scene_path = Path((scene or {}).get("path", project_root / "data" / "scenes" / str(args.scene) / "scene.json"))
    proposed = json.loads(json.dumps(doc)) if doc is not None else default_scene_document("Scene")

    used_uuids = {
        int(obj.get("uuid"))
        for obj, _parent, _siblings in scene_object_records(proposed)
        if isinstance(obj.get("uuid"), int)
    }
    object_uuid = args.uuid if args.uuid is not None else generate_scene_object_uuid(proposed)
    if object_uuid <= 0 or object_uuid > 0xFFFFFFFF:
        issues.append(issue("error", "SCENE_OBJECT_UUID", "Object UUID must be in the range 1..0xFFFFFFFF."))
    elif object_uuid in used_uuids:
        issues.append(issue("error", "SCENE_OBJECT_UUID", f"Object UUID {object_uuid} already exists in this scene."))

    parent_info: dict[str, Any] | None = None
    graph = proposed.setdefault("graph", {})
    destination = graph.setdefault("children", [])
    if not isinstance(destination, list):
        issues.append(issue("error", "SCENE", "Scene graph children must be an array."))
        destination = []
    if args.parent.lower() != "root":
        parent_record, parent_issues = find_scene_object(proposed, args.parent)
        issues.extend(parent_issues)
        if parent_record is not None:
            parent_obj = parent_record[0]
            parent_children = parent_obj.setdefault("children", [])
            if isinstance(parent_children, list):
                destination = parent_children
                parent_info = {"uuid": parent_obj.get("uuid"), "name": parent_obj.get("name")}
            else:
                issues.append(issue("error", "SCENE", "Parent object children must be an array."))

    position = [float(value) for value in (args.position or [0.0, 0.0, 0.0])]
    obj = default_scene_object(args.name, object_uuid, position)
    if not has_errors(issues):
        destination.append(obj)
    validation = validate_scene_doc(scene_path, scene_id, proposed, limits)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if scene is not None and doc is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="scene", path=scene_path)
        else:
            write_json_file(scene_path, proposed)
            add_change(changes, action="updated", kind="scene", path=scene_path)

    result = {
        "ok": scene is not None and doc is not None and not has_errors(issues),
        "command": "scene object add",
        "kind": "scene_mutation",
        "operation": "object_add",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config),
        "scene": {"id": scene_id, "path": str(scene_path)},
        "object": {"uuid": object_uuid, "name": args.name, "parent": parent_info},
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, scene_path)
    return exit_code


def cmd_scene_object_update(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "scene object update",
            "kind": "scene_mutation",
            "operation": "object_update",
            "project": args.project,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scene, doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if scene is not None:
        issues.extend(scene.get("issues", []))
    scene_id = optional_int((scene or {}).get("metadata", {}).get("scene_id"))
    scene_path = Path((scene or {}).get("path", project_root / "data" / "scenes" / str(args.scene) / "scene.json"))
    proposed = json.loads(json.dumps(doc)) if doc is not None else default_scene_document("Scene")
    record, object_issues = find_scene_object(proposed, args.object)
    issues.extend(object_issues)

    requested = {
        "name": args.name,
        "pos": args.position,
        "rot": args.rotation,
        "scale": args.scale,
        "enabled": args.enabled,
        "selectable": args.selectable,
        "proportionalScale": args.proportional_scale,
    }
    if all(value is None for value in requested.values()):
        issues.append(
            issue(
                "error",
                "SCENE_OBJECT_UPDATE",
                "No object property update was requested.",
                "Pass --name, a transform option, or a boolean state option.",
            )
        )

    obj: dict[str, Any] | None = record[0] if record is not None else None
    object_uuid = obj.get("uuid") if obj is not None else None
    before = json.loads(json.dumps(obj)) if obj is not None else None
    if obj is not None and not has_errors(issues):
        if args.name is not None:
            obj["name"] = args.name
        if args.position is not None:
            obj["pos"] = [float(value) for value in args.position]
        if args.rotation is not None:
            obj["rot"] = [float(value) for value in args.rotation]
        if args.scale is not None:
            obj["scale"] = [float(value) for value in args.scale]
        if args.enabled is not None:
            obj["enabled"] = bool(args.enabled)
        if args.selectable is not None:
            obj["selectable"] = bool(args.selectable)
        if args.proportional_scale is not None:
            obj["proportionalScale"] = bool(args.proportional_scale)

    validation = validate_scene_doc(scene_path, scene_id, proposed, limits)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if scene is not None and doc is not None and obj is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="scene", path=scene_path)
        else:
            write_json_file(scene_path, proposed)
            add_change(changes, action="updated", kind="scene", path=scene_path)

    result = {
        "ok": scene is not None and doc is not None and obj is not None and not has_errors(issues),
        "command": "scene object update",
        "kind": "scene_mutation",
        "operation": "object_update",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config),
        "scene": {"id": scene_id, "path": str(scene_path)},
        "object": {"uuid": object_uuid, "before": before, "after": obj},
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, scene_path)
    return exit_code


def cmd_scene_object_reparent(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "scene object reparent",
            "kind": "scene_mutation",
            "operation": "object_reparent",
            "project": args.project,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scene, doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if scene is not None:
        issues.extend(scene.get("issues", []))
    scene_id = optional_int((scene or {}).get("metadata", {}).get("scene_id"))
    scene_path = Path((scene or {}).get("path", project_root / "data" / "scenes" / str(args.scene) / "scene.json"))
    proposed = json.loads(json.dumps(doc)) if doc is not None else default_scene_document("Scene")
    record, object_issues = find_scene_object(proposed, args.object)
    issues.extend(object_issues)

    graph = proposed.setdefault("graph", {})
    root_children = graph.setdefault("children", [])
    destination: list[Any] | None = root_children if isinstance(root_children, list) else None
    target_obj: dict[str, Any] | None = None
    if args.parent.lower() != "root":
        target_record, target_issues = find_scene_object(proposed, args.parent)
        issues.extend(target_issues)
        if target_record is not None:
            target_obj = target_record[0]
            target_children = target_obj.setdefault("children", [])
            if isinstance(target_children, list):
                destination = target_children
            else:
                destination = None
                issues.append(issue("error", "SCENE", "Target parent children must be an array."))

    obj = record[0] if record is not None else None
    old_parent = record[1] if record is not None else None
    old_siblings = record[2] if record is not None else None
    if obj is not None and target_obj is not None:
        descendant_ids: set[int] = set()

        def collect_descendants(node: dict[str, Any]) -> None:
            node_uuid = node.get("uuid")
            if isinstance(node_uuid, int):
                descendant_ids.add(node_uuid)
            for child in node.get("children", []):
                if isinstance(child, dict):
                    collect_descendants(child)

        collect_descendants(obj)
        if target_obj.get("uuid") in descendant_ids:
            issues.append(
                issue(
                    "error",
                    "SCENE_REPARENT_CYCLE",
                    "Cannot reparent an object beneath itself or one of its descendants.",
                    "Choose root or an object outside the moving subtree.",
                )
            )

    if obj is not None and old_siblings is not None and destination is not None and not has_errors(issues):
        for index, sibling in enumerate(old_siblings):
            if sibling is obj:
                old_siblings.pop(index)
                break
        destination.append(obj)

    validation = validate_scene_doc(scene_path, scene_id, proposed, limits)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if scene is not None and doc is not None and obj is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="scene", path=scene_path)
        else:
            write_json_file(scene_path, proposed)
            add_change(changes, action="updated", kind="scene", path=scene_path)

    result = {
        "ok": scene is not None and doc is not None and obj is not None and not has_errors(issues),
        "command": "scene object reparent",
        "kind": "scene_mutation",
        "operation": "object_reparent",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config),
        "scene": {"id": scene_id, "path": str(scene_path)},
        "object": {
            "uuid": obj.get("uuid") if obj is not None else None,
            "name": obj.get("name") if obj is not None else None,
            "old_parent": old_parent.get("uuid") if old_parent is not None else "root",
            "parent": target_obj.get("uuid") if target_obj is not None else "root",
        },
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, scene_path)
    return exit_code


def cmd_scene_object_remove(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "scene object remove",
            "kind": "scene_mutation",
            "operation": "object_remove",
            "project": args.project,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scene, doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if scene is not None:
        issues.extend(scene.get("issues", []))
    scene_id = optional_int((scene or {}).get("metadata", {}).get("scene_id"))
    scene_path = Path((scene or {}).get("path", project_root / "data" / "scenes" / str(args.scene) / "scene.json"))
    proposed = json.loads(json.dumps(doc)) if doc is not None else default_scene_document("Scene")
    record, object_issues = find_scene_object(proposed, args.object)
    issues.extend(object_issues)
    obj = record[0] if record is not None else None
    siblings = record[2] if record is not None else None

    def subtree_count(node: dict[str, Any]) -> int:
        return 1 + sum(subtree_count(child) for child in node.get("children", []) if isinstance(child, dict))

    removed_info = {
        "uuid": obj.get("uuid") if obj is not None else None,
        "name": obj.get("name") if obj is not None else None,
        "object_count": subtree_count(obj) if obj is not None else 0,
    }
    if obj is not None and siblings is not None and not has_errors(issues):
        for index, sibling in enumerate(siblings):
            if sibling is obj:
                siblings.pop(index)
                break

    validation = validate_scene_doc(scene_path, scene_id, proposed, limits)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if scene is not None and doc is not None and obj is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="scene", path=scene_path)
        else:
            write_json_file(scene_path, proposed)
            add_change(changes, action="updated", kind="scene", path=scene_path)

    result = {
        "ok": scene is not None and doc is not None and obj is not None and not has_errors(issues),
        "command": "scene object remove",
        "kind": "scene_mutation",
        "operation": "object_remove",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config),
        "scene": {"id": scene_id, "path": str(scene_path)},
        "removed": removed_info,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, scene_path)
    return exit_code


def cmd_scene_component_add(args: argparse.Namespace) -> int:
    command_name = str(getattr(args, "_scene_command_name", "scene component add"))
    operation_name = str(getattr(args, "_scene_operation", "component_add"))
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    issues.extend(getattr(args, "_scene_pre_issues", []))
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": command_name,
            "kind": "scene_mutation",
            "operation": operation_name,
            "project": args.project,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scene, doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if scene is not None:
        issues.extend(scene.get("issues", []))
    scene_id = optional_int((scene or {}).get("metadata", {}).get("scene_id"))
    scene_path = Path((scene or {}).get("path", project_root / "data" / "scenes" / str(args.scene) / "scene.json"))
    proposed = json.loads(json.dumps(doc)) if doc is not None else default_scene_document("Scene")
    object_record, object_issues = find_scene_object(proposed, args.object)
    issues.extend(object_issues)
    obj = object_record[0] if object_record is not None else None
    component_id, type_issues = resolve_component_type(args.type)
    issues.extend(type_issues)
    data_patch, data_issues = parse_json_object_argument(args.data, "component data")
    issues.extend(data_issues)
    attachment: dict[str, Any] | None = None
    asset_ref = getattr(args, "asset", None)
    if asset_ref is not None and component_id is not None:
        attachment, attachment_issues = resolve_component_asset(project_root, component_id, asset_ref)
        issues.extend(attachment_issues)
        if attachment is not None and attachment.get("uuid") is not None:
            data_patch[str(attachment["field"])] = attachment["uuid"]
    script_ref = getattr(args, "script", None)
    script_args, script_args_issues = parse_json_object_argument(getattr(args, "script_args", None), "script arguments")
    issues.extend(script_args_issues)
    if script_ref is not None:
        if component_id != 0:
            issues.append(issue("error", "SCENE_SCRIPT_KIND", "Only a Code component accepts --script."))
        else:
            script_info, script_issues = resolve_object_script(project_root, script_ref)
            issues.extend(script_issues)
            if script_info is not None:
                attachment = script_info
                data_patch["script"] = script_info["uuid"]
                if getattr(args, "script_args", None) is not None:
                    if any(not isinstance(value, str) for value in script_args.values()):
                        issues.append(issue("error", "SCENE_SCRIPT_ARGS", "Code component argument values must be strings."))
                    else:
                        data_patch["args"] = script_args

    component_uuid = args.uuid if args.uuid is not None else generate_component_uuid(proposed)
    used_uuids = {
        int(component.get("uuid"))
        for scene_obj, _parent, _siblings in scene_object_records(proposed)
        for component in scene_obj.get("components", [])
        if isinstance(component, dict) and isinstance(component.get("uuid"), int)
    }
    if component_uuid <= 0 or component_uuid > 0xFFFFFFFFFFFFFFFF:
        issues.append(issue("error", "SCENE_COMPONENT_UUID", "Component UUID must be in the range 1..0xFFFFFFFFFFFFFFFF."))
    elif component_uuid in used_uuids:
        issues.append(issue("error", "SCENE_COMPONENT_UUID", f"Component UUID {component_uuid} already exists in this scene."))

    component: dict[str, Any] | None = None
    if obj is not None and component_id is not None:
        components = obj.setdefault("components", [])
        if not isinstance(components, list):
            issues.append(issue("error", "SCENE", "Object components must be an array."))
        elif component_id == 11 and any(
            isinstance(existing, dict) and existing.get("id") == 11 for existing in components
        ):
            issues.append(issue("error", "SCENE_COMPONENT_DUPLICATE", "An object can only have one Rigid-Body component."))
        elif not has_errors(issues):
            data = default_component_data(component_id, proposed)
            data.update(data_patch)
            component = {
                "id": component_id,
                "uuid": component_uuid,
                "name": args.name or COMPONENT_NAMES[component_id],
                "data": data,
            }
            components.append(component)

    validation = validate_scene_doc(scene_path, scene_id, proposed, limits)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if scene is not None and doc is not None and component is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="scene", path=scene_path)
        else:
            write_json_file(scene_path, proposed)
            add_change(changes, action="updated", kind="scene", path=scene_path)

    result = {
        "ok": scene is not None and doc is not None and component is not None and not has_errors(issues),
        "command": command_name,
        "kind": "scene_mutation",
        "operation": operation_name,
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config),
        "scene": {"id": scene_id, "path": str(scene_path)},
        "object": {"uuid": obj.get("uuid") if obj is not None else None, "name": obj.get("name") if obj is not None else None},
        "component": component or {"id": component_id, "uuid": component_uuid},
        "attachment": attachment,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, scene_path)
    return exit_code


def cmd_scene_component_update(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "scene component update",
            "kind": "scene_mutation",
            "operation": "component_update",
            "project": args.project,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scene, doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if scene is not None:
        issues.extend(scene.get("issues", []))
    scene_id = optional_int((scene or {}).get("metadata", {}).get("scene_id"))
    scene_path = Path((scene or {}).get("path", project_root / "data" / "scenes" / str(args.scene) / "scene.json"))
    proposed = json.loads(json.dumps(doc)) if doc is not None else default_scene_document("Scene")
    object_record, object_issues = find_scene_object(proposed, args.object)
    issues.extend(object_issues)
    obj = object_record[0] if object_record is not None else None
    component: dict[str, Any] | None = None
    if obj is not None:
        component, component_issues = find_scene_component(obj, args.component)
        issues.extend(component_issues)

    data_patch, data_issues = parse_json_object_argument(args.data, "component data")
    issues.extend(data_issues)
    attachment: dict[str, Any] | None = None
    asset_ref = getattr(args, "asset", None)
    script_ref = getattr(args, "script", None)
    script_args, script_args_issues = parse_json_object_argument(getattr(args, "script_args", None), "script arguments")
    issues.extend(script_args_issues)
    component_id = optional_int(component.get("id")) if component is not None else None
    if asset_ref is not None and component_id is not None:
        attachment, attachment_issues = resolve_component_asset(project_root, component_id, asset_ref)
        issues.extend(attachment_issues)
        if attachment is not None and attachment.get("uuid") is not None:
            data_patch[str(attachment["field"])] = attachment["uuid"]
    if script_ref is not None:
        if component_id != 0:
            issues.append(issue("error", "SCENE_SCRIPT_KIND", "Only a Code component accepts --script."))
        else:
            script_info, script_issues = resolve_object_script(project_root, script_ref)
            issues.extend(script_issues)
            if script_info is not None:
                attachment = script_info
                data_patch["script"] = script_info["uuid"]
    if getattr(args, "script_args", None) is not None:
        if component_id != 0:
            issues.append(issue("error", "SCENE_SCRIPT_KIND", "Only a Code component accepts --args."))
        elif any(not isinstance(value, str) for value in script_args.values()):
            issues.append(issue("error", "SCENE_SCRIPT_ARGS", "Code component argument values must be strings."))
        else:
            data_patch["args"] = script_args

    if args.name is None and args.data is None and asset_ref is None and script_ref is None and getattr(args, "script_args", None) is None:
        issues.append(
            issue(
                "error",
                "SCENE_COMPONENT_UPDATE",
                "No component update was requested.",
                "Pass --name and/or --data <json>.",
            )
        )

    before = json.loads(json.dumps(component)) if component is not None else None
    if component is not None and not has_errors(issues):
        if args.name is not None:
            component["name"] = args.name
        if data_patch:
            data = component.setdefault("data", {})
            if isinstance(data, dict):
                data.update(data_patch)
            else:
                issues.append(issue("error", "SCENE", "Component data must be a JSON object."))

    validation = validate_scene_doc(scene_path, scene_id, proposed, limits)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if scene is not None and doc is not None and component is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="scene", path=scene_path)
        else:
            write_json_file(scene_path, proposed)
            add_change(changes, action="updated", kind="scene", path=scene_path)

    result = {
        "ok": scene is not None and doc is not None and component is not None and not has_errors(issues),
        "command": "scene component update",
        "kind": "scene_mutation",
        "operation": "component_update",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config),
        "scene": {"id": scene_id, "path": str(scene_path)},
        "object": {"uuid": obj.get("uuid") if obj is not None else None, "name": obj.get("name") if obj is not None else None},
        "component": {"before": before, "after": component},
        "attachment": attachment,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, scene_path)
    return exit_code


def cmd_scene_component_remove(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {
            "ok": False,
            "command": "scene component remove",
            "kind": "scene_mutation",
            "operation": "component_remove",
            "project": args.project,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scene, doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if scene is not None:
        issues.extend(scene.get("issues", []))
    scene_id = optional_int((scene or {}).get("metadata", {}).get("scene_id"))
    scene_path = Path((scene or {}).get("path", project_root / "data" / "scenes" / str(args.scene) / "scene.json"))
    proposed = json.loads(json.dumps(doc)) if doc is not None else default_scene_document("Scene")
    object_record, object_issues = find_scene_object(proposed, args.object)
    issues.extend(object_issues)
    obj = object_record[0] if object_record is not None else None
    component: dict[str, Any] | None = None
    if obj is not None:
        component, component_issues = find_scene_component(obj, args.component)
        issues.extend(component_issues)

    removed = json.loads(json.dumps(component)) if component is not None else None
    if obj is not None and component is not None and not has_errors(issues):
        components = obj.get("components", [])
        if isinstance(components, list):
            for index, existing in enumerate(components):
                if existing is component:
                    components.pop(index)
                    break
        else:
            issues.append(issue("error", "SCENE", "Object components must be an array."))

    validation = validate_scene_doc(scene_path, scene_id, proposed, limits)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if scene is not None and doc is not None and component is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="scene", path=scene_path)
        else:
            write_json_file(scene_path, proposed)
            add_change(changes, action="updated", kind="scene", path=scene_path)

    result = {
        "ok": scene is not None and doc is not None and component is not None and not has_errors(issues),
        "command": "scene component remove",
        "kind": "scene_mutation",
        "operation": "component_remove",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config),
        "scene": {"id": scene_id, "path": str(scene_path)},
        "object": {"uuid": obj.get("uuid") if obj is not None else None, "name": obj.get("name") if obj is not None else None},
        "removed": removed,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(scene_path, "scene_source")],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, scene_path)
    return exit_code


def cmd_scene_attach(args: argparse.Namespace) -> int:
    kind = normalize_component_type(args.kind)
    specs: dict[str, tuple[str, str | None]] = {
        "ui": ("ui", "asset"),
        "uidocument": ("ui", "asset"),
        "camera": ("camera", None),
        "model": ("model", "asset"),
        "staticmodel": ("model", "asset"),
        "collision": ("collisionmesh" if args.reference else "collider", "asset" if args.reference else None),
        "collisionmesh": ("collisionmesh", "asset"),
        "collider": ("collider", None),
        "light": ("light", None),
        "audio3d": ("audio3d", "asset"),
        "positionalaudio": ("audio3d", "asset"),
        "code": ("code", "script"),
    }
    component_type, reference_kind = specs[kind]
    pre_issues: list[dict[str, str]] = []
    if reference_kind is not None and not args.reference:
        pre_issues.append(
            issue(
                "error",
                "SCENE_ATTACH_REFERENCE",
                f"Attachment type {args.kind} requires an asset or script reference.",
            )
        )
    if reference_kind is None and args.reference:
        pre_issues.append(
            issue(
                "error",
                "SCENE_ATTACH_REFERENCE",
                f"Attachment type {args.kind} does not accept a positional reference; use --data for settings.",
            )
        )

    args.type = component_type
    args.asset = args.reference if reference_kind == "asset" else None
    args.script = args.reference if reference_kind == "script" else None
    args.script_args = getattr(args, "script_args", None)
    args._scene_pre_issues = pre_issues
    args._scene_command_name = "scene attach"
    args._scene_operation = f"attach_{kind}"
    return cmd_scene_component_add(args)


def cmd_scene_ls(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {"ok": False, "command": "scene ls", "project": args.project, "scenes": [], "issues": issues}
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    scenes, scene_issues = list_scene_summaries(project_root, limits)
    issues.extend(scene_issues)
    result = {
        "ok": not has_errors(issues) and not any(not scene.get("ok", False) for scene in scenes),
        "command": "scene ls",
        "project": project_summary(project_root, config_path, config),
        "scenes": [
            {
                "id": scene["metadata"].get("scene_id"),
                "name": scene["metadata"].get("name"),
                "path": scene["path"],
                "ok": scene["ok"],
                "renderPipeline": scene["metadata"].get("renderPipeline"),
                "renderPipelineName": scene["metadata"].get("renderPipelineName"),
                "object_count": scene["metadata"].get("object_count"),
                "component_count": scene["metadata"].get("component_count"),
                "issues": scene.get("issues", []),
            }
            for scene in scenes
        ],
        "issues": issues,
    }
    output_scene_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def cmd_scene_show(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {"ok": False, "command": "scene show", "project": args.project, "issues": issues}
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    summary, doc, find_issues = find_scene(project_root, args.scene, limits)
    issues.extend(find_issues)
    if summary is None or doc is None:
        result = {
            "ok": False,
            "command": "scene show",
            "project": project_summary(project_root, config_path, config),
            "scene": args.scene,
            "issues": issues,
        }
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1, config_path)
        return 1

    issues.extend(summary.get("issues", []))
    result = {
        "ok": not has_errors(issues),
        "command": "scene show",
        "project": project_summary(project_root, config_path, config),
        "scene": summary,
        "doc": doc,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_scene_show(result, args.depth)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, Path(summary["path"]))
    return exit_code


def cmd_scene_validate(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    if project_root is None or config_path is None or config is None:
        result = {"ok": False, "command": "scene validate", "project": args.project, "issues": issues}
        output_scene_result(result, args.json)
        record_if_requested(args, result, 1)
        return 1

    if args.scene:
        summary, _doc, find_issues = find_scene(project_root, args.scene, limits)
        issues.extend(find_issues)
        if summary:
            issues.extend(summary.get("issues", []))
        result = {
            "ok": summary is not None and not has_errors(issues),
            "command": "scene validate",
            "project": project_summary(project_root, config_path, config),
            "scene": summary,
            "issues": issues,
        }
    else:
        result = validate_project_file(config_path, limits)
        result["command"] = "scene validate"
    output_scene_result(result, args.json)
    exit_code = 1 if not result.get("ok") else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def output_scene_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    output_result(result, False)
    project = result.get("project")
    if isinstance(project, dict):
        print(f"Project: {project.get('name')} ({project.get('path')})")
    for scene in result.get("scenes", []):
        status = "OK" if scene.get("ok") else "FAILED"
        print(
            f"{status} scene {scene.get('id')}: {scene.get('name')} "
            f"objects={scene.get('object_count')} components={scene.get('component_count')} "
            f"pipeline={scene.get('renderPipelineName')}"
        )
        for item in scene.get("issues", []):
            print(f"  {item.get('severity', 'info').upper()} {item.get('rule')}: {item.get('message')}")


def print_scene_show(result: dict[str, Any], depth: int) -> None:
    scene = result["scene"]
    meta = scene["metadata"]
    print(f"Scene {meta.get('scene_id')}: {meta.get('name')}")
    print(f"Path: {scene.get('path')}")
    print(
        f"Pipeline: {meta.get('renderPipelineName')} ({meta.get('renderPipeline')}) "
        f"{meta.get('fbWidth')}x{meta.get('fbHeight')} fbFormat={meta.get('fbFormat')}"
    )
    print(f"Objects: {meta.get('object_count')}  Components: {meta.get('component_count')}")
    for item in result.get("issues", []):
        print(f"{item.get('severity', 'info').upper()} {item.get('rule')}: {item.get('message')}")
    if depth == 0:
        return
    print("Object tree:")

    def emit(nodes: list[dict[str, Any]], current_depth: int) -> None:
        if current_depth > depth:
            return
        for node in nodes:
            comps = ", ".join(node.get("components", []))
            comp_text = f" [{comps}]" if comps else ""
            print(f"{'  ' * (current_depth - 1)}- {node.get('name')}{comp_text}")
            emit(node.get("children", []), current_depth + 1)

    emit(scene.get("tree", []), 1)


def random_u32() -> int:
    return (uuid.uuid4().int & 0xFFFFFFFF) or 1


def structured_asset_conf(asset_uuid: int, schema: str) -> dict[str, Any]:
    return {
        "uuid": asset_uuid,
        "format": 0,
        "baseScale": 16,
        "compression": 0,
        "gltfBVH": False,
        "wavForceMono": False,
        "wavResampleRate": 0,
        "wavCompression": 0,
        "fontId": 0,
        "fontCharset": "",
        "exclude": False,
        "data": {"schema": schema},
    }


def normalize_structured_asset_dest(value: str, suffix: str) -> Path:
    raw = value.replace("\\", "/")
    if raw.startswith("assets/"):
        raw = raw[len("assets/") :]
    dest = Path(raw)
    if dest.suffix.lower() != suffix:
        dest = dest.with_suffix(suffix)
    return dest


def resolve_structured_asset(
    project_root: Path,
    reference: str,
    suffix: str,
    label: str,
) -> tuple[Path | None, list[dict[str, str]]]:
    assets_root = project_root / "assets"
    dest = normalize_structured_asset_dest(reference, suffix)
    if is_safe_asset_relative_path(dest):
        candidate = assets_root / dest
        if candidate.is_file():
            return candidate, []

    wanted = Path(reference.replace("\\", "/")).name
    wanted_stem = Path(wanted).stem if Path(wanted).suffix.lower() == suffix else wanted
    matches = [
        path
        for path in assets_root.rglob(f"*{suffix}")
        if path.name == wanted or path.stem == wanted_stem
    ] if assets_root.is_dir() else []
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        preview = ", ".join(path_relative_to(path, project_root) for path in matches[:10])
        return None, [
            issue(
                "error",
                f"{label.upper()}_PATH",
                f"{label} reference '{reference}' is ambiguous; matches: {preview}.",
                f"Use its project-relative assets/<path>{suffix} path.",
            )
        ]
    return None, [
        issue(
            "error",
            f"{label.upper()}_PATH",
            f"Could not find {label} '{reference}' under {assets_root}.",
        )
    ]


def output_structured_asset_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    output_result(result, False)
    for key in ("prefabs", "node_graphs"):
        for entry in result.get(key, []):
            print(f"{'OK' if entry.get('ok') else 'FAILED':6} {entry.get('relative_path')}")


def write_new_structured_asset_pair(
    path: Path,
    document: dict[str, Any],
    conf: dict[str, Any],
    *,
    replace: bool = False,
) -> None:
    conf_path = asset_conf_path(path)
    backups: list[tuple[Path, Path]] = []
    if replace:
        try:
            for original in (path, conf_path):
                if not original.exists():
                    continue
                backup = original.with_name(f".{original.name}.bf64-replace-{uuid.uuid4().hex}")
                os.replace(original, backup)
                backups.append((original, backup))
        except Exception:
            for original, backup in reversed(backups):
                if backup.exists() and not original.exists():
                    os.replace(backup, original)
            raise
    wrote_asset = False
    try:
        write_json_file(path, document)
        wrote_asset = True
        write_json_file(conf_path, conf)
    except Exception:
        if wrote_asset:
            path.unlink(missing_ok=True)
        conf_path.unlink(missing_ok=True)
        for original, backup in reversed(backups):
            if backup.exists() and not original.exists():
                os.replace(backup, original)
        raise
    for _original, backup in backups:
        backup.unlink(missing_ok=True)


def load_prefab(
    project_root: Path,
    reference: str,
    limits: dict[str, Any],
) -> tuple[Path | None, dict[str, Any] | None, dict[str, Any] | None, list[dict[str, str]]]:
    path, issues = resolve_structured_asset(project_root, reference, ".prefab", "prefab")
    if path is None:
        return None, None, None, issues
    try:
        doc = read_json_file(path)
    except Exception as exc:  # noqa: BLE001
        return path, None, None, [issue("error", "PREFAB_JSON", f"Could not parse prefab JSON: {exc}.")]
    conf, conf_path = load_conf(path, None)
    validation = validate_prefab_file(path, limits, conf, conf_path)
    return path, doc if isinstance(doc, dict) else None, validation, issues


def prefab_inventory(project_root: Path, limits: dict[str, Any]) -> list[dict[str, Any]]:
    assets_root = project_root / "assets"
    entries: list[dict[str, Any]] = []
    if not assets_root.is_dir():
        return entries
    for path in sorted(assets_root.rglob("*.prefab")):
        conf, conf_path = load_conf(path, None)
        validation = validate_prefab_file(path, limits, conf, conf_path)
        entries.append(
            {
                "path": str(path),
                "relative_path": path_relative_to(path, project_root),
                "asset_path": path_relative_to(path, assets_root),
                "ok": validation["ok"],
                "uuid": validation["metadata"].get("uuid"),
                "name": validation["metadata"].get("name"),
                "object_count": validation["metadata"].get("object_count", 0),
                "component_count": validation["metadata"].get("component_count", 0),
                "issues": validation.get("issues", []),
            }
        )
    return entries


def cmd_prefab_ls(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    entries = prefab_inventory(project_root, limits) if project_root is not None else []
    for entry in entries:
        issues.extend(entry.get("issues", []))
    result = {
        "ok": not has_errors(issues),
        "command": "prefab ls",
        "kind": "prefab_inventory",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "count": len(entries),
        "prefabs": entries,
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def cmd_prefab_show(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    path: Path | None = None
    doc: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    if project_root is not None:
        path, doc, validation, find_issues = load_prefab(project_root, args.prefab, limits)
        issues.extend(find_issues)
        if validation is not None:
            issues.extend(validation.get("issues", []))
    result = {
        "ok": path is not None and doc is not None and not has_errors(issues),
        "command": "prefab show",
        "kind": "prefab",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "path": str(path) if path else args.prefab,
        "document": doc,
        "validation": validation,
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, path or config_path)
    return exit_code


def cmd_prefab_validate(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    paths: list[Path] = []
    if project_root is not None:
        if args.all:
            paths = sorted((project_root / "assets").rglob("*.prefab"))
        elif args.prefab:
            path, find_issues = resolve_structured_asset(project_root, args.prefab, ".prefab", "prefab")
            issues.extend(find_issues)
            if path is not None:
                paths = [path]
        else:
            issues.append(issue("error", "PREFAB_PATH", "Pass a prefab reference or --all."))
    results: list[dict[str, Any]] = []
    for path in paths:
        conf, conf_path = load_conf(path, None)
        validation = validate_prefab_file(path, limits, conf, conf_path)
        results.append(validation)
        issues.extend(validation.get("issues", []))
    result = {
        "ok": not has_errors(issues),
        "command": "prefab validate",
        "kind": "prefab_validation",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "summary": {
            "prefabs": len(results),
            "passed": sum(1 for item in results if item["ok"]),
            "failed": sum(1 for item in results if not item["ok"]),
        },
        "results": results,
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def cmd_prefab_create(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    dest = normalize_structured_asset_dest(args.path, ".prefab")
    target = project_root / "assets" / dest if project_root is not None else Path("assets") / dest
    conf_path = asset_conf_path(target)
    if not is_safe_asset_relative_path(dest):
        issues.append(issue("error", "PREFAB_PATH", f"Prefab path must stay under assets/: {args.path}."))
    if (target.exists() or conf_path.exists()) and not args.force:
        issues.append(issue("error", "PREFAB_EXISTS", f"Prefab or sidecar already exists at {target}."))

    prefab_uuid = args.uuid if args.uuid is not None else random_u32()
    object_uuid = args.object_uuid if args.object_uuid is not None else random_u32()
    doc = {"uuid": prefab_uuid, "obj": default_scene_object(args.name, object_uuid)}
    conf = structured_asset_conf(prefab_uuid, "bf64.prefab")
    validation = validate_prefab_file(target, limits, conf, str(conf_path), doc)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if project_root is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_create", kind="prefab", path=target)
            add_change(changes, action="would_create", kind="asset_conf", path=conf_path)
        else:
            try:
                write_new_structured_asset_pair(target, doc, conf, replace=bool(args.force))
                add_change(changes, action="created", kind="prefab", path=target)
                add_change(changes, action="created", kind="asset_conf", path=conf_path)
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "PREFAB_IO", f"Could not create prefab: {exc}."))
    result = {
        "ok": not has_errors(issues),
        "command": "prefab create",
        "kind": "prefab_mutation",
        "operation": "create",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "path": str(target),
        "prefab": {"uuid": prefab_uuid, "object_uuid": object_uuid, "name": args.name},
        "document": doc,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(target, "prefab_source"), artifact_entry(conf_path, "asset_sidecar")],
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, target if not args.dry_run else config_path)
    return exit_code


def regenerate_prefab_uuids(doc: dict[str, Any], name: str | None = None) -> None:
    doc["uuid"] = random_u32()
    root = doc.get("obj")
    if not isinstance(root, dict):
        return
    if name is not None:
        root["name"] = name

    def visit(obj: dict[str, Any]) -> None:
        obj["uuid"] = random_u32()
        for component in obj.get("components", []):
            if isinstance(component, dict):
                component["uuid"] = random_u64()
        for child in obj.get("children", []):
            if isinstance(child, dict):
                visit(child)

    visit(root)


def cmd_prefab_duplicate(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    source_path: Path | None = None
    source_doc: dict[str, Any] | None = None
    if project_root is not None:
        source_path, source_doc, source_validation, find_issues = load_prefab(project_root, args.prefab, limits)
        issues.extend(find_issues)
        if source_validation is not None:
            issues.extend(source_validation.get("issues", []))
    dest = normalize_structured_asset_dest(args.path, ".prefab")
    target = project_root / "assets" / dest if project_root is not None else Path("assets") / dest
    conf_path = asset_conf_path(target)
    if not is_safe_asset_relative_path(dest):
        issues.append(issue("error", "PREFAB_PATH", f"Prefab path must stay under assets/: {args.path}."))
    if target.exists() or conf_path.exists():
        issues.append(issue("error", "PREFAB_EXISTS", f"Destination already exists: {target}."))

    proposed = json.loads(json.dumps(source_doc)) if source_doc is not None else {}
    regenerate_prefab_uuids(proposed, args.name)
    conf = structured_asset_conf(int(proposed.get("uuid", 0)), "bf64.prefab")
    validation = validate_prefab_file(target, limits, conf, str(conf_path), proposed)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if source_path is not None and source_doc is not None and project_root is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_create", kind="prefab", path=target, source=source_path)
            add_change(changes, action="would_create", kind="asset_conf", path=conf_path)
        else:
            try:
                write_new_structured_asset_pair(target, proposed, conf)
                add_change(changes, action="created", kind="prefab", path=target, source=source_path)
                add_change(changes, action="created", kind="asset_conf", path=conf_path)
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "PREFAB_IO", f"Could not duplicate prefab: {exc}."))
    result = {
        "ok": source_doc is not None and not has_errors(issues),
        "command": "prefab duplicate",
        "kind": "prefab_mutation",
        "operation": "duplicate",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "source": str(source_path) if source_path else args.prefab,
        "path": str(target),
        "document": proposed,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(target, "prefab_source"), artifact_entry(conf_path, "asset_sidecar")],
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, target if not args.dry_run else config_path)
    return exit_code


def cmd_prefab_rename(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    source: Path | None = None
    if project_root is not None:
        source, _doc, validation, find_issues = load_prefab(project_root, args.prefab, limits)
        issues.extend(find_issues)
        if validation is not None:
            issues.extend(validation.get("issues", []))
    dest = normalize_structured_asset_dest(args.path, ".prefab")
    target = project_root / "assets" / dest if project_root is not None else Path("assets") / dest
    if not is_safe_asset_relative_path(dest):
        issues.append(issue("error", "PREFAB_PATH", f"Prefab path must stay under assets/: {args.path}."))
    if target.exists() or asset_conf_path(target).exists():
        issues.append(issue("error", "PREFAB_EXISTS", f"Destination already exists: {target}."))
    changes: list[dict[str, str]] = []
    old_output: Path | None = None
    if source is not None and project_root is not None:
        old_output_value = asset_output_paths(project_root, source, "prefab").get("out_path")
        if old_output_value:
            old_output = project_root / str(old_output_value)
    if source is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_move", kind="prefab", path=target, source=source)
            if asset_conf_path(source).exists():
                add_change(changes, action="would_move", kind="asset_conf", path=asset_conf_path(target), source=asset_conf_path(source))
        else:
            try:
                move_structured_asset_pair(source, target)
                add_change(changes, action="moved", kind="prefab", path=target, source=source)
                if asset_conf_path(target).exists():
                    add_change(changes, action="moved", kind="asset_conf", path=asset_conf_path(target), source=asset_conf_path(source))
                if old_output is not None and old_output.exists():
                    try:
                        old_output.unlink()
                    except OSError as exc:
                        issues.append(issue("warning", "PREFAB_OUTPUT", f"Could not remove stale generated prefab output {old_output}: {exc}."))
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "PREFAB_ROLLBACK", f"Prefab rename failed and was rolled back: {exc}."))
    result = {
        "ok": source is not None and not has_errors(issues),
        "command": "prefab rename",
        "kind": "prefab_mutation",
        "operation": "rename",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "source": str(source) if source else args.prefab,
        "path": str(target),
        "changes": changes,
        "artifacts": [artifact_entry(target, "prefab_source"), artifact_entry(asset_conf_path(target), "asset_sidecar")],
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, target if not args.dry_run else config_path)
    return exit_code


def decode_json_pointer(pointer: str) -> tuple[list[str], list[dict[str, str]]]:
    if not pointer.startswith("/"):
        return [], [issue("error", "JSON_POINTER", "JSON pointer must start with '/'.")]
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")], []


def set_json_pointer(doc: Any, pointer: str, value: Any) -> list[dict[str, str]]:
    parts, issues = decode_json_pointer(pointer)
    if issues:
        return issues
    target = doc
    for part in parts[:-1]:
        if isinstance(target, dict) and part in target:
            target = target[part]
        elif isinstance(target, list) and part.isdigit() and int(part) < len(target):
            target = target[int(part)]
        else:
            return [issue("error", "JSON_POINTER", f"JSON pointer parent does not exist at {part!r}.")]
    leaf = parts[-1] if parts else ""
    if isinstance(target, dict):
        if leaf not in target:
            return [issue("error", "JSON_POINTER", f"JSON pointer target does not exist: {pointer}.")]
        target[leaf] = value
    elif isinstance(target, list) and leaf.isdigit() and int(leaf) < len(target):
        target[int(leaf)] = value
    else:
        return [issue("error", "JSON_POINTER", f"JSON pointer target does not exist: {pointer}.")]
    return []


def cmd_prefab_set(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    path: Path | None = None
    doc: dict[str, Any] | None = None
    if project_root is not None:
        path, doc, current_validation, find_issues = load_prefab(project_root, args.prefab, limits)
        issues.extend(find_issues)
        if current_validation is not None:
            issues.extend(current_validation.get("issues", []))
    try:
        value = json.loads(args.value)
    except json.JSONDecodeError as exc:
        value = None
        issues.append(issue("error", "PREFAB_VALUE", f"Value must be valid JSON: {exc}."))
    proposed = json.loads(json.dumps(doc)) if doc is not None else {}
    if not has_errors(issues):
        issues.extend(set_json_pointer(proposed, args.pointer, value))
    conf, conf_path = load_conf(path, None) if path is not None else ({}, None)
    validation = validate_prefab_file(
        path or Path(args.prefab),
        limits,
        conf,
        conf_path,
        proposed if doc is not None else None,
    )
    if doc is not None:
        issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if path is not None and doc is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="prefab", path=path)
        else:
            try:
                write_json_file(path, proposed)
                add_change(changes, action="updated", kind="prefab", path=path)
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "PREFAB_IO", f"Could not update prefab: {exc}."))
    result = {
        "ok": doc is not None and not has_errors(issues),
        "command": "prefab set",
        "kind": "prefab_mutation",
        "operation": "set",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "path": str(path) if path else args.prefab,
        "pointer": args.pointer,
        "document": proposed,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(path, "prefab_source")] if path is not None else [],
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, path or config_path)
    return exit_code


def cmd_prefab_delete(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    path: Path | None = None
    if project_root is not None:
        path, _doc, validation, find_issues = load_prefab(project_root, args.prefab, limits)
        issues.extend(find_issues)
        if validation is not None:
            issues.extend(validation.get("issues", []))
    conf_path = asset_conf_path(path) if path is not None else None
    changes: list[dict[str, str]] = []
    if path is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_delete", kind="prefab", path=path)
            if conf_path is not None and conf_path.exists():
                add_change(changes, action="would_delete", kind="asset_conf", path=conf_path)
        else:
            moved: list[tuple[Path, Path]] = []
            try:
                for source in (path, conf_path):
                    if source is None or not source.exists():
                        continue
                    tombstone = source.with_name(f".{source.name}.bf64-delete-{uuid.uuid4().hex}")
                    os.replace(source, tombstone)
                    moved.append((source, tombstone))
                for _source, tombstone in moved:
                    tombstone.unlink()
                add_change(changes, action="deleted", kind="prefab", path=path)
                if conf_path is not None:
                    add_change(changes, action="deleted", kind="asset_conf", path=conf_path)
            except Exception as exc:  # noqa: BLE001
                for source, tombstone in reversed(moved):
                    if tombstone.exists() and not source.exists():
                        os.replace(tombstone, source)
                issues.append(issue("error", "PREFAB_ROLLBACK", f"Prefab deletion failed and was rolled back: {exc}."))
    result = {
        "ok": path is not None and not has_errors(issues),
        "command": "prefab delete",
        "kind": "prefab_mutation",
        "operation": "delete",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "path": str(path) if path else args.prefab,
        "exists": path.exists() if path is not None else False,
        "changes": changes,
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, path or config_path)
    return exit_code


def prefab_scene_view(doc: dict[str, Any]) -> dict[str, Any]:
    root = doc.get("obj")
    return {"conf": {}, "graph": {"children": [root] if isinstance(root, dict) else []}}


def run_prefab_mutation(
    args: argparse.Namespace,
    command: str,
    operation: str,
    mutate: Any,
) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    issues.extend(getattr(args, "_prefab_pre_issues", []))
    path: Path | None = None
    doc: dict[str, Any] | None = None
    if project_root is not None:
        path, doc, _current_validation, find_issues = load_prefab(project_root, args.prefab, limits)
        issues.extend(find_issues)
    proposed = json.loads(json.dumps(doc)) if doc is not None else {}
    payload: dict[str, Any] = {}
    if doc is not None and not has_errors(issues):
        payload = mutate(proposed, issues) or {}
    conf, conf_path = load_conf(path, None) if path is not None else ({}, None)
    validation = validate_prefab_file(
        path or Path(args.prefab),
        limits,
        conf,
        conf_path,
        proposed if doc is not None else None,
    )
    if doc is not None:
        issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if path is not None and doc is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="prefab", path=path)
        else:
            try:
                write_json_file(path, proposed)
                add_change(changes, action="updated", kind="prefab", path=path)
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "PREFAB_IO", f"Could not update prefab: {exc}."))
    result = {
        "ok": doc is not None and not has_errors(issues),
        "command": command,
        "kind": "prefab_mutation",
        "operation": operation,
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "path": str(path) if path else args.prefab,
        "document": proposed,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(path, "prefab_source")] if path is not None else [],
        "issues": issues,
        **payload,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, path or config_path)
    return exit_code


def cmd_prefab_object_add(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        scene_doc = prefab_scene_view(doc)
        used = {
            int(obj.get("uuid"))
            for obj, _parent, _siblings in scene_object_records(scene_doc)
            if isinstance(obj.get("uuid"), int)
        }
        object_uuid = args.uuid if args.uuid is not None else generate_scene_object_uuid(scene_doc)
        if object_uuid <= 0 or object_uuid > 0xFFFFFFFF or object_uuid in used:
            issues.append(issue("error", "PREFAB_OBJECT_UUID", f"Invalid or duplicate object UUID {object_uuid}."))
        root = doc.get("obj")
        destination = root.setdefault("children", []) if isinstance(root, dict) else []
        parent_info = {"uuid": root.get("uuid"), "name": root.get("name")} if isinstance(root, dict) else None
        if args.parent.lower() != "root":
            parent_record, parent_issues = find_scene_object(scene_doc, args.parent)
            issues.extend(parent_issues)
            if parent_record is not None:
                parent = parent_record[0]
                destination = parent.setdefault("children", [])
                parent_info = {"uuid": parent.get("uuid"), "name": parent.get("name")}
        if not isinstance(destination, list):
            issues.append(issue("error", "PREFAB_OBJECT", "Parent children must be an array."))
            destination = []
        obj = default_scene_object(args.name, object_uuid, [float(value) for value in args.position])
        if not has_errors(issues):
            destination.append(obj)
        return {"object": obj, "parent": parent_info}

    return run_prefab_mutation(args, "prefab object add", "object_add", mutate)


def cmd_prefab_object_update(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        record, find_issues = find_scene_object(prefab_scene_view(doc), args.object)
        issues.extend(find_issues)
        obj = record[0] if record is not None else None
        before = json.loads(json.dumps(obj)) if obj is not None else None
        if not any(value is not None for value in (args.name, args.position, args.rotation, args.scale, args.enabled, args.selectable)):
            issues.append(issue("error", "PREFAB_OBJECT_UPDATE", "No object update was requested."))
        if obj is not None and not has_errors(issues):
            if args.name is not None:
                obj["name"] = args.name
            if args.position is not None:
                obj["pos"] = [float(value) for value in args.position]
            if args.rotation is not None:
                obj["rot"] = [float(value) for value in args.rotation]
            if args.scale is not None:
                obj["scale"] = [float(value) for value in args.scale]
            if args.enabled is not None:
                obj["enabled"] = args.enabled
            if args.selectable is not None:
                obj["selectable"] = args.selectable
        return {"object": {"before": before, "after": obj}}

    return run_prefab_mutation(args, "prefab object update", "object_update", mutate)


def cmd_prefab_object_reparent(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        scene_doc = prefab_scene_view(doc)
        record, find_issues = find_scene_object(scene_doc, args.object)
        issues.extend(find_issues)
        if record is None:
            return {}
        obj, parent, siblings = record
        if parent is None:
            issues.append(issue("error", "PREFAB_OBJECT", "The prefab root object cannot be reparented."))
            return {"object": obj}
        root = doc.get("obj")
        destination = root.setdefault("children", []) if isinstance(root, dict) else []
        target_info = {"uuid": root.get("uuid"), "name": root.get("name")} if isinstance(root, dict) else None
        if args.parent.lower() != "root":
            target_record, target_issues = find_scene_object(scene_doc, args.parent)
            issues.extend(target_issues)
            if target_record is not None:
                target = target_record[0]
                descendants = {item.get("uuid") for item, _p, _s in scene_object_records({"graph": {"children": [obj]}})}
                if target.get("uuid") in descendants:
                    issues.append(issue("error", "PREFAB_OBJECT_CYCLE", "Cannot reparent an object under its own subtree."))
                destination = target.setdefault("children", [])
                target_info = {"uuid": target.get("uuid"), "name": target.get("name")}
        if not isinstance(destination, list):
            issues.append(issue("error", "PREFAB_OBJECT", "Target parent children must be an array."))
        if not has_errors(issues):
            siblings.remove(obj)
            destination.append(obj)
        return {"object": obj, "parent": target_info}

    return run_prefab_mutation(args, "prefab object reparent", "object_reparent", mutate)


def cmd_prefab_object_remove(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        record, find_issues = find_scene_object(prefab_scene_view(doc), args.object)
        issues.extend(find_issues)
        if record is None:
            return {}
        obj, parent, siblings = record
        if parent is None:
            issues.append(issue("error", "PREFAB_OBJECT", "The prefab root object cannot be removed."))
        elif not has_errors(issues):
            siblings.remove(obj)
        return {"removed": obj}

    return run_prefab_mutation(args, "prefab object remove", "object_remove", mutate)


def apply_prefab_component_attachment(
    args: argparse.Namespace,
    project_root: Path | None,
    component_id: int | None,
    data_patch: dict[str, Any],
    issues: list[dict[str, str]],
) -> dict[str, Any] | None:
    attachment: dict[str, Any] | None = None
    asset_ref = getattr(args, "asset", None)
    script_ref = getattr(args, "script", None)
    script_args_ref = getattr(args, "script_args", None)
    if asset_ref is not None and script_ref is not None:
        issues.append(issue("error", "PREFAB_ATTACHMENT", "Pass either --asset or --script, not both."))
    if asset_ref is not None and component_id is not None and project_root is not None:
        attachment, attachment_issues = resolve_component_asset(project_root, component_id, asset_ref)
        issues.extend(attachment_issues)
        if attachment is not None and attachment.get("uuid") is not None:
            data_patch[str(attachment["field"])] = attachment["uuid"]
    if script_ref is not None:
        if component_id != 0:
            issues.append(issue("error", "PREFAB_SCRIPT_KIND", "Only a Code component accepts --script."))
        elif project_root is not None:
            script_info, script_issues = resolve_object_script(project_root, script_ref)
            issues.extend(script_issues)
            if script_info is not None:
                attachment = script_info
                data_patch["script"] = script_info["uuid"]
    script_args, script_args_issues = parse_json_object_argument(script_args_ref, "script arguments")
    issues.extend(script_args_issues)
    if script_args_ref is not None:
        if component_id != 0:
            issues.append(issue("error", "PREFAB_SCRIPT_KIND", "Only a Code component accepts --args."))
        elif any(not isinstance(value, str) for value in script_args.values()):
            issues.append(issue("error", "PREFAB_SCRIPT_ARGS", "Code component argument values must be strings."))
        else:
            data_patch["args"] = script_args
    return attachment


def cmd_prefab_component_add(args: argparse.Namespace) -> int:
    command_name = str(getattr(args, "_prefab_command_name", "prefab component add"))
    operation_name = str(getattr(args, "_prefab_operation", "component_add"))
    project_root, _config_path, _config, _project_issues = resolve_project(args.project)

    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        scene_doc = prefab_scene_view(doc)
        record, find_issues = find_scene_object(scene_doc, args.object)
        issues.extend(find_issues)
        obj = record[0] if record is not None else None
        component_id, type_issues = resolve_component_type(args.type)
        issues.extend(type_issues)
        data_patch, data_issues = parse_json_object_argument(args.data, "component data")
        issues.extend(data_issues)
        attachment = apply_prefab_component_attachment(args, project_root, component_id, data_patch, issues)
        component_uuid = args.uuid if args.uuid is not None else generate_component_uuid(scene_doc)
        component: dict[str, Any] | None = None
        if component_uuid <= 0 or component_uuid > 0xFFFFFFFFFFFFFFFF:
            issues.append(issue("error", "PREFAB_COMPONENT_UUID", f"Invalid component UUID {component_uuid}."))
        if obj is not None and component_id is not None:
            components = obj.setdefault("components", [])
            if not isinstance(components, list):
                issues.append(issue("error", "PREFAB_COMPONENT", "Object components must be an array."))
            elif any(isinstance(item, dict) and item.get("uuid") == component_uuid for item in components):
                issues.append(issue("error", "PREFAB_COMPONENT_UUID", f"Duplicate component UUID {component_uuid}."))
            elif component_id == 11 and any(isinstance(item, dict) and item.get("id") == 11 for item in components):
                issues.append(issue("error", "PREFAB_COMPONENT_DUPLICATE", "An object can only have one Rigid-Body component."))
            elif not has_errors(issues):
                data = default_component_data(component_id, scene_doc)
                data.update(data_patch)
                component = {"id": component_id, "uuid": component_uuid, "name": args.name or COMPONENT_NAMES[component_id], "data": data}
                components.append(component)
        return {
            "object": {"uuid": obj.get("uuid"), "name": obj.get("name")} if obj is not None else None,
            "component": component or {"id": component_id, "uuid": component_uuid},
            "attachment": attachment,
        }

    return run_prefab_mutation(args, command_name, operation_name, mutate)


def cmd_prefab_component_update(args: argparse.Namespace) -> int:
    project_root, _config_path, _config, _project_issues = resolve_project(args.project)

    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        record, find_issues = find_scene_object(prefab_scene_view(doc), args.object)
        issues.extend(find_issues)
        obj = record[0] if record is not None else None
        component: dict[str, Any] | None = None
        if obj is not None:
            component, component_issues = find_scene_component(obj, args.component)
            issues.extend(component_issues)
        data_patch, data_issues = parse_json_object_argument(args.data, "component data")
        issues.extend(data_issues)
        component_id = optional_int(component.get("id")) if component is not None else None
        attachment = apply_prefab_component_attachment(args, project_root, component_id, data_patch, issues)
        before = json.loads(json.dumps(component)) if component is not None else None
        if (
            args.name is None
            and args.data is None
            and getattr(args, "asset", None) is None
            and getattr(args, "script", None) is None
            and getattr(args, "script_args", None) is None
        ):
            issues.append(issue("error", "PREFAB_COMPONENT_UPDATE", "No component update was requested."))
        if component is not None and not has_errors(issues):
            if args.name is not None:
                component["name"] = args.name
            if data_patch:
                component.setdefault("data", {}).update(data_patch)
        return {"component": {"before": before, "after": component}, "attachment": attachment}

    return run_prefab_mutation(args, "prefab component update", "component_update", mutate)


def cmd_prefab_component_remove(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        record, find_issues = find_scene_object(prefab_scene_view(doc), args.object)
        issues.extend(find_issues)
        obj = record[0] if record is not None else None
        component: dict[str, Any] | None = None
        if obj is not None:
            component, component_issues = find_scene_component(obj, args.component)
            issues.extend(component_issues)
        if obj is not None and component is not None and not has_errors(issues):
            obj.get("components", []).remove(component)
        return {"removed": component}

    return run_prefab_mutation(args, "prefab component remove", "component_remove", mutate)


def cmd_prefab_attach(args: argparse.Namespace) -> int:
    kind = normalize_component_type(args.kind)
    specs: dict[str, tuple[str, str | None]] = {
        "ui": ("ui", "asset"),
        "uidocument": ("ui", "asset"),
        "camera": ("camera", None),
        "model": ("model", "asset"),
        "staticmodel": ("model", "asset"),
        "collision": ("collisionmesh" if args.reference else "collider", "asset" if args.reference else None),
        "collisionmesh": ("collisionmesh", "asset"),
        "collider": ("collider", None),
        "light": ("light", None),
        "audio3d": ("audio3d", "asset"),
        "positionalaudio": ("audio3d", "asset"),
        "code": ("code", "script"),
    }
    component_type, reference_kind = specs[kind]
    pre_issues: list[dict[str, str]] = []
    if reference_kind is not None and not args.reference:
        pre_issues.append(
            issue("error", "PREFAB_ATTACH_REFERENCE", f"Attachment type {args.kind} requires an asset or script reference.")
        )
    if reference_kind is None and args.reference:
        pre_issues.append(
            issue(
                "error",
                "PREFAB_ATTACH_REFERENCE",
                f"Attachment type {args.kind} does not accept a positional reference; use --data for settings.",
            )
        )
    args.type = component_type
    args.asset = args.reference if reference_kind == "asset" else None
    args.script = args.reference if reference_kind == "script" else None
    args.script_args = getattr(args, "script_args", None)
    args._prefab_pre_issues = pre_issues
    args._prefab_command_name = "prefab attach"
    args._prefab_operation = f"attach_{kind}"
    return cmd_prefab_component_add(args)


def default_node_graph_document() -> dict[str, Any]:
    return {
        "repeatable": False,
        "view": [0.0, 0.0, 1.0],
        "variables": [],
        "nodes": [],
        "links": [],
        "groups": [],
    }


def load_node_graph(
    project_root: Path,
    reference: str,
) -> tuple[Path | None, dict[str, Any] | None, dict[str, Any] | None, list[dict[str, str]]]:
    path, issues = resolve_structured_asset(project_root, reference, ".p64graph", "node_graph")
    if path is None:
        return None, None, None, issues
    try:
        doc = read_json_file(path)
    except Exception as exc:  # noqa: BLE001
        return path, None, None, [issue("error", "NODE_GRAPH_JSON", f"Could not parse node graph JSON: {exc}.")]
    _conf, conf_path = load_conf(path, None)
    validation = validate_node_graph_file(path, project_root, conf_path)
    return path, doc if isinstance(doc, dict) else None, validation, issues


def node_graph_inventory(project_root: Path) -> list[dict[str, Any]]:
    assets_root = project_root / "assets"
    entries: list[dict[str, Any]] = []
    if not assets_root.is_dir():
        return entries
    for path in sorted(assets_root.rglob("*.p64graph")):
        _conf, conf_path = load_conf(path, None)
        validation = validate_node_graph_file(path, project_root, conf_path)
        entries.append(
            {
                "path": str(path),
                "relative_path": path_relative_to(path, project_root),
                "asset_path": path_relative_to(path, assets_root),
                "ok": validation["ok"],
                **{key: validation["metadata"].get(key, 0) for key in ("node_count", "link_count", "variable_count", "group_count")},
                "issues": validation.get("issues", []),
            }
        )
    return entries


def cmd_node_graph_ls(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    entries = node_graph_inventory(project_root) if project_root is not None else []
    for entry in entries:
        issues.extend(entry.get("issues", []))
    result = {
        "ok": not has_errors(issues),
        "command": "node-graph ls",
        "kind": "node_graph_inventory",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "count": len(entries),
        "node_graphs": entries,
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def cmd_node_graph_show(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    path: Path | None = None
    doc: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    if project_root is not None:
        path, doc, validation, find_issues = load_node_graph(project_root, args.graph)
        issues.extend(find_issues)
        if validation is not None:
            issues.extend(validation.get("issues", []))
    result = {
        "ok": path is not None and doc is not None and not has_errors(issues),
        "command": "node-graph show",
        "kind": "node_graph",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "path": str(path) if path else args.graph,
        "document": doc,
        "validation": validation,
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, path or config_path)
    return exit_code


def cmd_node_graph_validate(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    paths: list[Path] = []
    if project_root is not None:
        if args.all:
            paths = sorted((project_root / "assets").rglob("*.p64graph"))
        elif args.graph:
            path, find_issues = resolve_structured_asset(project_root, args.graph, ".p64graph", "node_graph")
            issues.extend(find_issues)
            if path is not None:
                paths = [path]
        else:
            issues.append(issue("error", "NODE_GRAPH_PATH", "Pass a node graph reference or --all."))
    results: list[dict[str, Any]] = []
    for path in paths:
        _conf, conf_path = load_conf(path, None)
        validation = validate_node_graph_file(path, project_root, conf_path)
        results.append(validation)
        issues.extend(validation.get("issues", []))
    result = {
        "ok": not has_errors(issues),
        "command": "node-graph validate",
        "kind": "node_graph_validation",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "summary": {
            "node_graphs": len(results),
            "passed": sum(1 for item in results if item["ok"]),
            "failed": sum(1 for item in results if not item["ok"]),
        },
        "results": results,
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def cmd_node_graph_create(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    dest = normalize_structured_asset_dest(args.path, ".p64graph")
    target = project_root / "assets" / dest if project_root is not None else Path("assets") / dest
    conf_path = asset_conf_path(target)
    if not is_safe_asset_relative_path(dest):
        issues.append(issue("error", "NODE_GRAPH_PATH", f"Node graph path must stay under assets/: {args.path}."))
    if target.exists() or conf_path.exists():
        issues.append(issue("error", "NODE_GRAPH_EXISTS", f"Node graph or sidecar already exists at {target}."))
    doc = default_node_graph_document()
    conf = structured_asset_conf(random_u64(), "bf64.node-graph")
    validation = validate_node_graph_file(target, project_root, str(conf_path), doc)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if project_root is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_create", kind="node_graph", path=target)
            add_change(changes, action="would_create", kind="asset_conf", path=conf_path)
        else:
            try:
                write_new_structured_asset_pair(target, doc, conf)
                add_change(changes, action="created", kind="node_graph", path=target)
                add_change(changes, action="created", kind="asset_conf", path=conf_path)
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "NODE_GRAPH_IO", f"Could not create node graph: {exc}."))
    result = {
        "ok": not has_errors(issues),
        "command": "node-graph create",
        "kind": "node_graph_mutation",
        "operation": "create",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "path": str(target),
        "document": doc,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(target, "node_graph_source"), artifact_entry(conf_path, "asset_sidecar")],
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, target if not args.dry_run else config_path)
    return exit_code


def find_node_graph_node(doc: dict[str, Any], reference: str) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    try:
        wanted = parse_cli_int(reference)
    except ValueError:
        return None, [issue("error", "NODE_GRAPH_NODE", f"Node reference must be an integer UUID: {reference}.")]
    nodes = doc.get("nodes", [])
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict) and node.get("uuid") == wanted:
                return node, []
    return None, [issue("error", "NODE_GRAPH_NODE", f"Could not find node UUID {wanted}.")]


def run_node_graph_mutation(
    args: argparse.Namespace,
    command: str,
    operation: str,
    mutate: Any,
) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    path: Path | None = None
    doc: dict[str, Any] | None = None
    if project_root is not None:
        path, doc, _current_validation, find_issues = load_node_graph(project_root, args.graph)
        issues.extend(find_issues)
    proposed = json.loads(json.dumps(doc)) if doc is not None else default_node_graph_document()
    payload: dict[str, Any] = {}
    if doc is not None and not has_errors(issues):
        payload = mutate(proposed, issues) or {}
    _conf, conf_path = load_conf(path, None) if path is not None else ({}, None)
    validation = validate_node_graph_file(
        path or Path(args.graph),
        project_root,
        conf_path,
        proposed if doc is not None else None,
    )
    if doc is not None:
        issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if path is not None and doc is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_update", kind="node_graph", path=path)
        else:
            try:
                write_json_file(path, proposed)
                add_change(changes, action="updated", kind="node_graph", path=path)
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "NODE_GRAPH_IO", f"Could not update node graph: {exc}."))
    result = {
        "ok": doc is not None and not has_errors(issues),
        "command": command,
        "kind": "node_graph_mutation",
        "operation": operation,
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "path": str(path) if path else args.graph,
        "document": proposed,
        "validation": validation,
        "changes": changes,
        "artifacts": [artifact_entry(path, "node_graph_source")] if path is not None else [],
        "issues": issues,
        **payload,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, path or config_path)
    return exit_code


def cmd_node_graph_node_add(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        data, data_issues = parse_json_object_argument(args.data, "node data")
        issues.extend(data_issues)
        nodes = doc.setdefault("nodes", [])
        if not isinstance(nodes, list):
            issues.append(issue("error", "NODE_GRAPH_NODE", "nodes must be an array."))
            return {}
        node_uuid = args.uuid if args.uuid is not None else random_u64()
        if any(isinstance(node, dict) and node.get("uuid") == node_uuid for node in nodes):
            issues.append(issue("error", "NODE_GRAPH_NODE", f"Node UUID {node_uuid} already exists."))
        node = dict(data)
        node.update({"uuid": node_uuid, "typeId": args.type_id, "pos": [float(args.pos[0]), float(args.pos[1])]})
        if not has_errors(issues):
            nodes.append(node)
        return {"node": node}

    return run_node_graph_mutation(args, "node-graph node add", "node_add", mutate)


def cmd_node_graph_node_remove(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        node, node_issues = find_node_graph_node(doc, args.node)
        issues.extend(node_issues)
        if node is None:
            return {"removed_incident_links": 0}
        node_uuid = node.get("uuid")
        nodes = doc.get("nodes", [])
        links = doc.get("links", [])
        if isinstance(nodes, list):
            nodes.remove(node)
        before = len(links) if isinstance(links, list) else 0
        if isinstance(links, list):
            doc["links"] = [link for link in links if not isinstance(link, dict) or node_uuid not in {link.get("src"), link.get("dst")}]
        return {"removed": node, "removed_incident_links": before - len(doc.get("links", []))}

    return run_node_graph_mutation(args, "node-graph node remove", "node_remove", mutate)


def cmd_node_graph_node_update(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        node, node_issues = find_node_graph_node(doc, args.node)
        issues.extend(node_issues)
        data, data_issues = parse_json_object_argument(args.data, "node data")
        issues.extend(data_issues)
        before = json.loads(json.dumps(node)) if node is not None else None
        if args.type_id is None and args.pos is None and args.data is None:
            issues.append(issue("error", "NODE_GRAPH_NODE", "No node update was requested."))
        if node is not None and not has_errors(issues):
            reserved = {"uuid", "typeId", "type", "pos"}
            if any(key in data for key in reserved):
                issues.append(issue("error", "NODE_GRAPH_NODE", f"--data cannot replace reserved keys {sorted(reserved)}."))
            else:
                node.update(data)
                if args.type_id is not None:
                    node["typeId"] = args.type_id
                    node.pop("type", None)
                if args.pos is not None:
                    node["pos"] = [float(args.pos[0]), float(args.pos[1])]
        return {"node": {"before": before, "after": node}}

    return run_node_graph_mutation(args, "node-graph node update", "node_update", mutate)


def cmd_node_graph_link_add(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        try:
            src = parse_cli_int(args.src)
            dst = parse_cli_int(args.dst)
        except ValueError:
            issues.append(issue("error", "NODE_GRAPH_LINK", "Link endpoints must be integer node UUIDs."))
            return {}
        link = {"src": src, "srcPort": args.src_port, "dst": dst, "dstPort": args.dst_port}
        links = doc.setdefault("links", [])
        if not isinstance(links, list):
            issues.append(issue("error", "NODE_GRAPH_LINK", "links must be an array."))
        elif link in links:
            issues.append(issue("error", "NODE_GRAPH_LINK", "That exact link already exists."))
        elif not has_errors(issues):
            links.append(link)
        return {"link": link}

    return run_node_graph_mutation(args, "node-graph link add", "link_add", mutate)


def cmd_node_graph_link_remove(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        try:
            src = parse_cli_int(args.src)
            dst = parse_cli_int(args.dst)
        except ValueError:
            issues.append(issue("error", "NODE_GRAPH_LINK", "Link endpoints must be integer node UUIDs."))
            return {"removed_links": 0}
        links = doc.get("links", [])
        if not isinstance(links, list):
            issues.append(issue("error", "NODE_GRAPH_LINK", "links must be an array."))
            return {"removed_links": 0}
        kept: list[Any] = []
        removed: list[dict[str, Any]] = []
        for link in links:
            match = isinstance(link, dict) and link.get("src") == src and link.get("dst") == dst
            if args.src_port is not None:
                match = match and link.get("srcPort", 0) == args.src_port
            if args.dst_port is not None:
                match = match and link.get("dstPort", 0) == args.dst_port
            if match:
                removed.append(link)
            else:
                kept.append(link)
        if not removed:
            issues.append(issue("error", "NODE_GRAPH_LINK", f"No matching link exists from {src} to {dst}."))
        else:
            doc["links"] = kept
        return {"removed_links": len(removed), "removed": removed}

    return run_node_graph_mutation(args, "node-graph link remove", "link_remove", mutate)


def cmd_node_graph_variable_add(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        variable = {"name": args.name, "type": args.type}
        variables = doc.setdefault("variables", [])
        if not isinstance(variables, list):
            issues.append(issue("error", "NODE_GRAPH_VARIABLE", "variables must be an array."))
        elif any(isinstance(item, dict) and item.get("name") == args.name for item in variables):
            issues.append(issue("error", "NODE_GRAPH_VARIABLE", f"Variable already exists: {args.name}."))
        elif not has_errors(issues):
            variables.append(variable)
        return {"variable": variable}

    return run_node_graph_mutation(args, "node-graph variable add", "variable_add", mutate)


def cmd_node_graph_variable_update(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        variables = doc.get("variables", [])
        variable = next(
            (item for item in variables if isinstance(item, dict) and item.get("name") == args.variable),
            None,
        ) if isinstance(variables, list) else None
        if variable is None:
            issues.append(issue("error", "NODE_GRAPH_VARIABLE", f"Could not find variable {args.variable}."))
            return {}
        if args.name is None and args.type is None:
            issues.append(issue("error", "NODE_GRAPH_VARIABLE", "No variable update was requested."))
        if args.name is not None and args.name != args.variable and any(
            isinstance(item, dict) and item.get("name") == args.name for item in variables
        ):
            issues.append(issue("error", "NODE_GRAPH_VARIABLE", f"Variable already exists: {args.name}."))
        before = dict(variable)
        if not has_errors(issues):
            if args.name is not None:
                variable["name"] = args.name
                for node in doc.get("nodes", []):
                    if isinstance(node, dict) and node.get("var") == args.variable:
                        node["var"] = args.name
            if args.type is not None:
                variable["type"] = args.type
        return {"variable": {"before": before, "after": dict(variable)}}

    return run_node_graph_mutation(args, "node-graph variable update", "variable_update", mutate)


def cmd_node_graph_variable_remove(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        variables = doc.get("variables", [])
        variable = next(
            (item for item in variables if isinstance(item, dict) and item.get("name") == args.variable),
            None,
        ) if isinstance(variables, list) else None
        if variable is None:
            issues.append(issue("error", "NODE_GRAPH_VARIABLE", f"Could not find variable {args.variable}."))
            return {}
        references = [
            node.get("uuid")
            for node in doc.get("nodes", [])
            if isinstance(node, dict) and node.get("var") == args.variable
        ]
        if references and not args.force:
            issues.append(
                issue(
                    "error",
                    "NODE_GRAPH_VARIABLE",
                    f"Variable {args.variable} is referenced by nodes {references}.",
                    "Remove/update those nodes or pass --force to remove them with the variable.",
                )
            )
        if not has_errors(issues):
            variables.remove(variable)
            if references:
                removed_set = set(references)
                doc["nodes"] = [node for node in doc.get("nodes", []) if not isinstance(node, dict) or node.get("uuid") not in removed_set]
                doc["links"] = [
                    link for link in doc.get("links", [])
                    if not isinstance(link, dict) or (link.get("src") not in removed_set and link.get("dst") not in removed_set)
                ]
        return {"removed": variable, "removed_node_uuids": references if args.force else []}

    return run_node_graph_mutation(args, "node-graph variable remove", "variable_remove", mutate)


def cmd_node_graph_group_add(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        groups = doc.setdefault("groups", [])
        if not isinstance(groups, list):
            issues.append(issue("error", "NODE_GRAPH_GROUP", "groups must be an array."))
            return {}
        group = {
            "title": args.title,
            "pos": [float(args.pos[0]), float(args.pos[1])],
            "size": [float(args.size[0]), float(args.size[1])],
        }
        groups.append(group)
        return {"group": group, "group_index": len(groups) - 1}

    return run_node_graph_mutation(args, "node-graph group add", "group_add", mutate)


def node_graph_group_by_index(doc: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    groups = doc.get("groups", [])
    if not isinstance(groups, list) or index < 0 or index >= len(groups) or not isinstance(groups[index], dict):
        return None, [issue("error", "NODE_GRAPH_GROUP", f"Could not find group index {index}.")]
    return groups[index], []


def cmd_node_graph_group_update(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        group, group_issues = node_graph_group_by_index(doc, args.index)
        issues.extend(group_issues)
        before = dict(group) if group is not None else None
        if args.title is None and args.pos is None and args.size is None:
            issues.append(issue("error", "NODE_GRAPH_GROUP", "No group update was requested."))
        if group is not None and not has_errors(issues):
            if args.title is not None:
                group["title"] = args.title
            if args.pos is not None:
                group["pos"] = [float(args.pos[0]), float(args.pos[1])]
            if args.size is not None:
                group["size"] = [float(args.size[0]), float(args.size[1])]
        return {"group": {"before": before, "after": group}, "group_index": args.index}

    return run_node_graph_mutation(args, "node-graph group update", "group_update", mutate)


def cmd_node_graph_group_remove(args: argparse.Namespace) -> int:
    def mutate(doc: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
        group, group_issues = node_graph_group_by_index(doc, args.index)
        issues.extend(group_issues)
        if group is not None and not has_errors(issues):
            doc["groups"].pop(args.index)
        return {"removed": group, "group_index": args.index}

    return run_node_graph_mutation(args, "node-graph group remove", "group_remove", mutate)


def regenerate_node_graph_uuids(doc: dict[str, Any]) -> None:
    remap: dict[int, int] = {}
    for node in doc.get("nodes", []):
        if isinstance(node, dict) and isinstance(node.get("uuid"), int):
            old = node["uuid"]
            new = random_u64()
            remap[old] = new
            node["uuid"] = new
    for link in doc.get("links", []):
        if isinstance(link, dict):
            if link.get("src") in remap:
                link["src"] = remap[link["src"]]
            if link.get("dst") in remap:
                link["dst"] = remap[link["dst"]]


def cmd_node_graph_duplicate(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    source_path: Path | None = None
    source_doc: dict[str, Any] | None = None
    if project_root is not None:
        source_path, source_doc, source_validation, find_issues = load_node_graph(project_root, args.graph)
        issues.extend(find_issues)
        if source_validation is not None:
            issues.extend(item for item in source_validation.get("issues", []) if item.get("severity") == "error")
    dest = normalize_structured_asset_dest(args.path, ".p64graph")
    target = project_root / "assets" / dest if project_root is not None else Path("assets") / dest
    conf_path = asset_conf_path(target)
    if not is_safe_asset_relative_path(dest):
        issues.append(issue("error", "NODE_GRAPH_PATH", f"Node graph path must stay under assets/: {args.path}."))
    if target.exists() or conf_path.exists():
        issues.append(issue("error", "NODE_GRAPH_EXISTS", f"Destination already exists: {target}."))
    proposed = json.loads(json.dumps(source_doc)) if source_doc is not None else default_node_graph_document()
    regenerate_node_graph_uuids(proposed)
    conf = structured_asset_conf(random_u64(), "bf64.node-graph")
    validation = validate_node_graph_file(target, project_root, str(conf_path), proposed)
    issues.extend(validation.get("issues", []))
    changes: list[dict[str, str]] = []
    if source_doc is not None and source_path is not None and project_root is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_create", kind="node_graph", path=target, source=source_path)
            add_change(changes, action="would_create", kind="asset_conf", path=conf_path)
        else:
            try:
                write_new_structured_asset_pair(target, proposed, conf)
                add_change(changes, action="created", kind="node_graph", path=target, source=source_path)
                add_change(changes, action="created", kind="asset_conf", path=conf_path)
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "NODE_GRAPH_IO", f"Could not duplicate node graph: {exc}."))
    result = {
        "ok": source_doc is not None and not has_errors(issues),
        "command": "node-graph duplicate",
        "kind": "node_graph_mutation",
        "operation": "duplicate",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "source": str(source_path) if source_path else args.graph,
        "path": str(target),
        "document": proposed,
        "validation": validation,
        "changes": changes,
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, target if not args.dry_run else config_path)
    return exit_code


def move_structured_asset_pair(source: Path, target: Path) -> None:
    source_conf = asset_conf_path(source)
    target_conf = asset_conf_path(target)
    moved: list[tuple[Path, Path]] = []
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        moved.append((target, source))
        if source_conf.exists():
            os.replace(source_conf, target_conf)
            moved.append((target_conf, source_conf))
    except Exception:
        for current, original in reversed(moved):
            if current.exists() and not original.exists():
                os.replace(current, original)
        raise


def cmd_node_graph_rename(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    source: Path | None = None
    if project_root is not None:
        source, find_issues = resolve_structured_asset(project_root, args.graph, ".p64graph", "node_graph")
        issues.extend(find_issues)
    dest = normalize_structured_asset_dest(args.path, ".p64graph")
    target = project_root / "assets" / dest if project_root is not None else Path("assets") / dest
    if not is_safe_asset_relative_path(dest):
        issues.append(issue("error", "NODE_GRAPH_PATH", f"Node graph path must stay under assets/: {args.path}."))
    if target.exists() or asset_conf_path(target).exists():
        issues.append(issue("error", "NODE_GRAPH_EXISTS", f"Destination already exists: {target}."))
    changes: list[dict[str, str]] = []
    if source is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_move", kind="node_graph", path=target, source=source)
        else:
            try:
                move_structured_asset_pair(source, target)
                add_change(changes, action="moved", kind="node_graph", path=target, source=source)
                old_output = project_root / asset_output_paths(project_root, source, "node_graph").get("out_path", "")
                if old_output != project_root and old_output.exists():
                    old_output.unlink()
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "NODE_GRAPH_ROLLBACK", f"Node graph rename failed and was rolled back: {exc}."))
    result = {
        "ok": source is not None and not has_errors(issues),
        "command": "node-graph rename",
        "kind": "node_graph_mutation",
        "operation": "rename",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "source": str(source) if source else args.graph,
        "path": str(target),
        "changes": changes,
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, target if not args.dry_run else config_path)
    return exit_code


def cmd_node_graph_delete(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    path: Path | None = None
    if project_root is not None:
        path, find_issues = resolve_structured_asset(project_root, args.graph, ".p64graph", "node_graph")
        issues.extend(find_issues)
    conf_path = asset_conf_path(path) if path is not None else None
    changes: list[dict[str, str]] = []
    if path is not None and not has_errors(issues):
        if args.dry_run:
            add_change(changes, action="would_delete", kind="node_graph", path=path)
        else:
            moved: list[tuple[Path, Path]] = []
            try:
                for source in (path, conf_path):
                    if source is None or not source.exists():
                        continue
                    tombstone = source.with_name(f".{source.name}.bf64-delete-{uuid.uuid4().hex}")
                    os.replace(source, tombstone)
                    moved.append((source, tombstone))
                for _source, tombstone in moved:
                    tombstone.unlink()
                add_change(changes, action="deleted", kind="node_graph", path=path)
            except Exception as exc:  # noqa: BLE001
                for source, tombstone in reversed(moved):
                    if tombstone.exists() and not source.exists():
                        os.replace(tombstone, source)
                issues.append(issue("error", "NODE_GRAPH_ROLLBACK", f"Node graph deletion failed and was rolled back: {exc}."))
    result = {
        "ok": path is not None and not has_errors(issues),
        "command": "node-graph delete",
        "kind": "node_graph_mutation",
        "operation": "delete",
        "dry_run": bool(args.dry_run),
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "path": str(path) if path else args.graph,
        "exists": path.exists() if path is not None else False,
        "changes": changes,
        "issues": issues,
    }
    output_structured_asset_result(result, args.json)
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, path or config_path)
    return exit_code


def cmd_constraints(args: argparse.Namespace) -> int:
    limits = load_limits()
    if args.topic == "list":
        result = {
            "ok": True,
            "command": "constraints list",
            "topics": sorted(k for k in limits.keys() if k not in {"schema_version", "reviewed", "description", "sources"}),
        }
    else:
        topic = args.topic
        if topic not in limits:
            result = {
                "ok": False,
                "topic": topic,
                "issues": [issue("error", "TOPIC", f"Unknown constraints topic '{topic}'.")],
            }
        else:
            result = {"ok": True, "topic": topic, "data": limits[topic]}

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("ok") and "topics" in result:
        print("Available topics:")
        for topic in result["topics"]:
            print(f"  {topic}")
    elif result.get("ok"):
        print(json.dumps(result["data"], indent=2, sort_keys=True))
    else:
        output_result(result, False)
    return 0 if result.get("ok") else 1


def command_name_from_args(args: argparse.Namespace) -> str:
    parts = [getattr(args, "command", "unknown")]
    for attr in (
        "project_command",
        "focus_area_command",
        "asset_command",
        "asset_exclusion_command",
        "ui_command",
        "prefab_command",
        "prefab_object_command",
        "prefab_component_command",
        "node_graph_command",
        "node_graph_node_command",
        "node_graph_link_command",
        "node_graph_variable_command",
        "node_graph_group_command",
        "scene_command",
        "scene_object_command",
        "scene_component_command",
        "history_command",
    ):
        value = getattr(args, attr, None)
        if value:
            parts.append(str(value))
    return " ".join(parts)


def current_repo_revision() -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def issue_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for item in issues:
        severity = str(item.get("severity", "info"))
        rule = str(item.get("rule", ""))
        by_severity[severity] = by_severity.get(severity, 0) + 1
        if rule:
            by_rule[rule] = by_rule.get(rule, 0) + 1
    return {"total": len(issues), "by_severity": by_severity, "by_rule": by_rule}


def result_project_path(result: dict[str, Any]) -> str | None:
    project = result.get("project")
    if isinstance(project, dict) and project.get("path"):
        return str(project["path"])
    metadata = result.get("metadata")
    if isinstance(metadata, dict) and result.get("kind") == "project" and metadata.get("path"):
        return str(metadata["path"])
    return None


def record_if_requested(args: argparse.Namespace, result: dict[str, Any], exit_code: int, path: Path | None = None) -> None:
    if not getattr(args, "record", False):
        return
    started_at = float(getattr(args, "_started_at", time.perf_counter()))
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    history_path = Path(args.history_path) if getattr(args, "history_path", None) else DEFAULT_HISTORY_PATH
    record_operation(
        command_name_from_args(args),
        path,
        result,
        history_path=history_path,
        argv=list(getattr(args, "_argv", [])),
        exit_code=exit_code,
        duration_ms=duration_ms,
    )


def record_operation(
    command: str,
    path: Path | None,
    result: dict[str, Any],
    history_path: Path = DEFAULT_HISTORY_PATH,
    *,
    argv: list[str] | None = None,
    exit_code: int = 0,
    duration_ms: int | None = None,
) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    issues = result.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    record = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "operation_id": str(uuid.uuid4()),
        "ts": time.time(),
        "tool": {
            "name": "bf64",
            "version": CLI_VERSION,
            "repo_revision": current_repo_revision(),
        },
        "command": command,
        "argv": argv or [],
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "path": str(path) if path else None,
        "project_path": result_project_path(result),
        "ok": result.get("ok", False),
        "kind": result.get("kind"),
        "issue_count": len(issues),
        "issue_summary": issue_summary(issues),
        "issues": issues,
        "artifacts": result.get("artifacts", []),
    }
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def read_history(history_path: Path = DEFAULT_HISTORY_PATH) -> list[dict[str, Any]]:
    if not history_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with history_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def cmd_history(args: argparse.Namespace) -> int:
    history_path = Path(args.history_path) if args.history_path else DEFAULT_HISTORY_PATH
    rows = read_history(history_path)
    if args.limit:
        rows = rows[-args.limit :]
    result = {"ok": True, "command": "history list", "history_path": str(history_path), "operations": rows, "count": len(rows)}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if not rows:
            print(f"No operations recorded at {history_path}")
        for row in rows:
            status = "OK" if row.get("ok") else "FAILED"
            print(f"{int(row.get('ts', 0))} {status} {row.get('command')} {row.get('path')}")
    return 0


def cmd_focus_list(args: argparse.Namespace) -> int:
    try:
        catalog = load_focus_catalog(FOCUS_AREAS_PATH)
        issues: list[dict[str, str]] = []
    except Exception as exc:  # noqa: BLE001 - returned through the stable CLI envelope
        catalog = {"schemaVersion": 1, "areas": []}
        issues = [issue("error", "FOCUS_CATALOG", f"Could not load focus-area catalog: {exc}.")]
    result = {
        "ok": not has_errors(issues),
        "command": "focus list",
        "kind": "focus_areas",
        "schema_version": catalog.get("schemaVersion"),
        "areas": catalog.get("areas", []),
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        for area in result["areas"]:
            print(f"{area.get('id'):12} {area.get('status'):10} {area.get('label')}")
    return 1 if has_errors(issues) else 0


def focus_area_definition(area_id: str) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    try:
        catalog = load_focus_catalog(FOCUS_AREAS_PATH)
    except Exception as exc:  # noqa: BLE001
        return None, [issue("error", "FOCUS_CATALOG", f"Could not load focus-area catalog: {exc}.")]
    for area in catalog.get("areas", []):
        if isinstance(area, dict) and area.get("id") == area_id:
            return area, []
    return None, [issue("error", "FOCUS_AREA", f"Unknown focus area: {area_id}.")]


def configured_asset_focus_areas(conf: dict[str, Any]) -> list[str]:
    data = conf.get("data", {})
    if not isinstance(data, dict):
        return []
    values = data.get("focusAreas", [])
    result = [str(value) for value in values if isinstance(value, str)] if isinstance(values, list) else []
    legacy = data.get("focusArea")
    if isinstance(legacy, str) and legacy not in result:
        result.append(legacy)
    return result


def focus_area_accepts_asset(area: dict[str, Any], entry: dict[str, Any]) -> bool:
    area_id = str(area.get("id", ""))
    kind = str(entry.get("kind", "unknown"))
    if kind not in {str(value) for value in area.get("assetKinds", [])}:
        return False
    extension = Path(str(entry.get("path", ""))).suffix.lower()
    if area_id == "sfx" and extension == ".xm":
        return False
    return True


def focus_area_assets(project_root: Path, area: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inventory = scan_project_assets(project_root, include_entries=True)
    compatible: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    area_id = str(area.get("id", ""))
    for entry in inventory.get("assets", []):
        if not focus_area_accepts_asset(area, entry):
            continue
        conf, _conf_path = load_conf(Path(entry["path"]), None)
        tags = configured_asset_focus_areas(conf)
        enriched = dict(entry)
        enriched["focus_areas"] = tags
        enriched["focus_selected"] = area_id in tags
        compatible.append(enriched)
        if enriched["focus_selected"]:
            selected.append(enriched)
    compatible.sort(key=lambda item: str(item.get("asset_path", "")))
    selected.sort(key=lambda item: str(item.get("asset_path", "")))
    return selected, compatible


def cmd_focus_area_ls(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    area, area_issues = focus_area_definition(args.focus_area)
    issues.extend(area_issues)
    selected: list[dict[str, Any]] = []
    compatible: list[dict[str, Any]] = []
    if project_root is not None and area is not None:
        selected, compatible = focus_area_assets(project_root, area)
    result = {
        "ok": not has_errors(issues),
        "command": f"{args.focus_area} ls",
        "kind": "focus_area_inventory",
        "focus_area": area,
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "count": len(selected),
        "candidate_count": len(compatible),
        "untagged_candidate_count": len(compatible) - len(selected),
        "assets": selected,
        "candidates": compatible,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        for entry in selected:
            print(f"{entry.get('kind'):12} {entry.get('asset_path')}")
        if not selected:
            print(f"No tagged {args.focus_area} assets; {len(compatible)} compatible candidate(s).")
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def cmd_focus_area_tag(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    area, area_issues = focus_area_definition(args.focus_area)
    issues.extend(area_issues)
    path: Path | None = None
    entry: dict[str, Any] | None = None
    if project_root is not None:
        path, find_issues = resolve_project_asset(project_root, args.asset)
        issues.extend(find_issues)
        if path is not None:
            entry = asset_entry(project_root, path)
    if area is not None and entry is not None and not focus_area_accepts_asset(area, entry):
        issues.append(
            issue(
                "error",
                "FOCUS_ASSET_KIND",
                f"{area.get('label')} accepts {area.get('assetKinds', [])}; {entry.get('relative_path')} is {entry.get('kind')}.",
            )
        )

    conf_path = asset_conf_path(path) if path is not None else None
    conf: dict[str, Any] = {}
    if path is not None:
        loaded, loaded_path = load_conf(path, None)
        if loaded_path is not None:
            conf_path = Path(loaded_path)
            conf = loaded
        else:
            asset_uuid = random_u64()
            if entry is not None and entry.get("kind") == "prefab":
                try:
                    prefab_doc = read_json_file(path)
                    asset_uuid = int(prefab_doc.get("uuid", asset_uuid)) if isinstance(prefab_doc, dict) else asset_uuid
                except Exception:  # noqa: BLE001
                    pass
            conf = structured_asset_conf(asset_uuid, "bf64.asset")
    if "__parse_error__" in conf:
        issues.append(issue("error", "CONF", f"Could not tag asset with an invalid sidecar: {conf['__parse_error__']}"))
    proposed = json.loads(json.dumps(conf)) if conf else {}
    data = proposed.setdefault("data", {})
    if not isinstance(data, dict):
        issues.append(issue("error", "FOCUS_CONF", "Asset sidecar data must be a JSON object."))
        data = {}
    tags = configured_asset_focus_areas(proposed)
    changed = False
    if args.clear:
        if args.focus_area in tags:
            tags.remove(args.focus_area)
            changed = True
    elif args.focus_area not in tags:
        tags.append(args.focus_area)
        changed = True
    if isinstance(data, dict):
        data["focusAreas"] = tags
        data.pop("focusArea", None)

    changes: list[dict[str, str]] = []
    if conf_path is not None and not has_errors(issues) and changed:
        if args.dry_run:
            add_change(changes, action="would_update", kind="asset_conf", path=conf_path)
        else:
            try:
                write_json_file(conf_path, proposed)
                add_change(changes, action="updated", kind="asset_conf", path=conf_path)
            except Exception as exc:  # noqa: BLE001
                issues.append(issue("error", "FOCUS_IO", f"Could not update asset focus tags: {exc}."))
    result = {
        "ok": path is not None and not has_errors(issues),
        "command": f"{args.focus_area} tag",
        "kind": "focus_area_mutation",
        "operation": "clear_tag" if args.clear else "tag",
        "dry_run": bool(args.dry_run),
        "changed": changed and not has_errors(issues),
        "focus_area": area,
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "asset": entry or args.asset,
        "focus_areas": tags,
        "changes": changes,
        "artifacts": [artifact_entry(conf_path, "asset_sidecar")] if conf_path is not None else [],
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        if path is not None:
            print(f"{path_relative_to(path, project_root)}: {tags}")
    exit_code = 1 if not result["ok"] else 0
    record_if_requested(args, result, exit_code, conf_path or config_path)
    return exit_code


def cmd_focus_area_validate(args: argparse.Namespace) -> int:
    limits = load_limits()
    project_root, config_path, config, issues = resolve_project(args.project)
    area, area_issues = focus_area_definition(args.focus_area)
    issues.extend(area_issues)
    selected: list[dict[str, Any]] = []
    compatible: list[dict[str, Any]] = []
    if project_root is not None and area is not None:
        selected, compatible = focus_area_assets(project_root, area)
    selection = select_project_assets(selected, args.include_excluded)
    validate_args = argparse.Namespace(
        texture_format=None,
        scene_pipeline=None,
        role=args.focus_area if args.focus_area in {"music", "sfx"} else "unknown",
    )
    results = [validate_project_asset_entry(entry, limits, validate_args) for entry in selection["assets"]]
    if project_root is not None:
        issues.extend(flatten_asset_issues(results, project_root))
    summary = summarize_asset_validation(results)
    summary.update(
        {
            "tagged": len(selected),
            "candidates": len(compatible),
            "included": selection["included"],
            "excluded": selection["excluded"],
            "include_excluded": selection["include_excluded"],
        }
    )
    result = {
        "ok": not has_errors(issues),
        "command": f"{args.focus_area} validate",
        "kind": "focus_area_validation",
        "focus_area": area,
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None else args.project,
        "summary": summary,
        "results": results,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_asset_validate_all(result)
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def normalize_ui_dest(value: str) -> Path:
    raw = value.replace("\\", "/")
    if raw.startswith("assets/"):
        raw = raw[len("assets/") :]
    dest = Path(raw)
    if dest.suffix.lower() != ".bfui":
        dest = dest.with_suffix(".bfui")
    return dest


def ui_asset_conf() -> dict[str, Any]:
    return {
        "uuid": random_u64(),
        "format": 0,
        "baseScale": 0,
        "compression": 0,
        "gltfBVH": False,
        "wavForceMono": False,
        "wavResampleRate": 0,
        "wavCompression": 0,
        "fontId": 0,
        "fontCharset": "",
        "exclude": False,
        "data": {"schema": "bf64.ui", "version": 1},
    }


def resolve_project_ui(project_root: Path, reference: str) -> tuple[Path | None, list[dict[str, str]]]:
    assets_root = project_root / "assets"
    normalized = reference.replace("\\", "/")
    if normalized.startswith("assets/"):
        normalized = normalized[len("assets/") :]
    candidates = [assets_root / normalized]
    if not normalized.lower().endswith(".bfui"):
        candidates.append(assets_root / f"{normalized}.bfui")
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() == ".bfui":
            return candidate, []
    matches = [path for path in assets_root.rglob("*.bfui") if path.name == Path(normalized).name]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, [
            issue(
                "error",
                "UI_PATH",
                f"UI document '{reference}' is ambiguous.",
                "Use its project-relative assets/<path>.bfui path.",
            )
        ]
    return None, [
        issue(
            "error",
            "UI_PATH",
            f"Could not find UI document '{reference}' under {assets_root}.",
            "Use `bf64 ui ls --project <project>` to list documents.",
        )
    ]


def cmd_ui_new(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    changes: list[dict[str, str]] = []
    dest = normalize_ui_dest(args.path)
    target = (project_root / "assets" / dest) if project_root else Path("assets") / dest
    conf_path = asset_conf_path(target)
    if not is_safe_asset_relative_path(dest):
        issues.append(
            issue(
                "error",
                "UI_PATH",
                f"UI path must remain under assets/: {args.path}.",
                "Use a relative path such as menus/title.bfui.",
            )
        )
    if not 1 <= args.width <= 640 or not 1 <= args.height <= 576:
        issues.append(issue("error", "UI_CANVAS", "Canvas must be within 1..640 by 1..576 pixels."))
    if target.exists() and not args.force:
        issues.append(
            issue(
                "error",
                "UI_EXISTS",
                f"UI document already exists: {target}.",
                "Choose another path or pass --force.",
            )
        )

    if not has_errors(issues) and project_root is not None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            document = default_ui_document(args.width, args.height)
            target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            conf_path.write_text(json.dumps(ui_asset_conf(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            add_change(changes, action="created" if not args.force else "overwritten", kind="ui_document", path=target)
            add_change(changes, action="created" if not args.force else "overwritten", kind="asset_conf", path=conf_path)
        except Exception as exc:  # noqa: BLE001
            issues.append(issue("error", "UI_IO", f"Could not create UI document: {exc}."))

    validation = validate_ui_document(target, project_root) if target.is_file() else None
    if validation:
        issues.extend(validation.get("issues", []))
    result = {
        "ok": not has_errors(issues),
        "command": "ui new",
        "kind": "ui_document",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None
        else args.project,
        "path": str(target),
        "relative_path": path_relative_to(target, project_root) if project_root else str(target),
        "changes": changes,
        "validation": validation,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        if result["ok"]:
            print(f"Created {result['relative_path']} ({args.width}x{args.height})")
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, target)
    return exit_code


def ui_inventory(project_root: Path) -> list[dict[str, Any]]:
    assets_root = project_root / "assets"
    values: list[dict[str, Any]] = []
    if not assets_root.is_dir():
        return values
    for path in sorted(assets_root.rglob("*.bfui")):
        validation = validate_ui_document(path, project_root)
        values.append(
            {
                "path": str(path),
                "relative_path": path_relative_to(path, project_root),
                "asset_path": path_relative_to(path, assets_root),
                "uuid": load_conf(path, None)[0].get("uuid", 0),
                "ok": validation["ok"],
                "element_count": validation["metadata"].get("element_count", 0),
                "focusable_count": validation["metadata"].get("focusable_count", 0),
                "issue_count": len(validation.get("issues", [])),
            }
        )
    return values


def cmd_ui_ls(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    documents = ui_inventory(project_root) if project_root else []
    result = {
        "ok": not has_errors(issues),
        "command": "ui ls",
        "kind": "ui_inventory",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None
        else args.project,
        "count": len(documents),
        "documents": documents,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        for document in documents:
            status = "OK" if document["ok"] else "FAILED"
            print(f"{status:6} {document['relative_path']} ({document['element_count']} elements)")
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def cmd_ui_show(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    path = None
    if project_root:
        path, path_issues = resolve_project_ui(project_root, args.document)
        issues.extend(path_issues)
    document: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    if path:
        try:
            document = read_json_file(path)
        except Exception as exc:  # noqa: BLE001
            issues.append(issue("error", "UI_JSON", f"Could not read UI document: {exc}."))
        validation = validate_ui_document(path, project_root)
        issues.extend(validation.get("issues", []))
    result = {
        "ok": not has_errors(issues),
        "command": "ui show",
        "kind": "ui_document",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None
        else args.project,
        "path": str(path) if path else args.document,
        "document": document,
        "validation": validation,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        if validation:
            print(
                f"Elements: {validation['metadata'].get('element_count', 0)}, "
                f"focusable: {validation['metadata'].get('focusable_count', 0)}"
            )
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, path or config_path)
    return exit_code


def cmd_ui_validate(args: argparse.Namespace) -> int:
    project_root, config_path, config, issues = resolve_project(args.project)
    paths: list[Path] = []
    if project_root:
        if args.all:
            paths = sorted((project_root / "assets").rglob("*.bfui"))
        elif args.document:
            path, path_issues = resolve_project_ui(project_root, args.document)
            issues.extend(path_issues)
            if path:
                paths = [path]
        else:
            issues.append(issue("error", "UI_PATH", "Pass a UI document or --all."))
    results = [validate_ui_document(path, project_root) for path in paths]
    for validation in results:
        for item in validation.get("issues", []):
            enriched = dict(item)
            enriched.setdefault("path", path_relative_to(Path(validation["path"]), project_root))
            issues.append(enriched)
    result = {
        "ok": not has_errors(issues),
        "command": "ui validate",
        "kind": "ui_validation",
        "project": project_summary(project_root, config_path, config)
        if project_root is not None and config_path is not None and config is not None
        else args.project,
        "summary": {
            "documents": len(results),
            "passed": sum(1 for item in results if item["ok"]),
            "failed": sum(1 for item in results if not item["ok"]),
        },
        "results": results,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        for validation in results:
            status = "OK" if validation["ok"] else "FAILED"
            print(f"{status:6} {path_relative_to(Path(validation['path']), project_root)}")
    exit_code = 1 if has_errors(issues) else 0
    record_if_requested(args, result, exit_code, config_path)
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bf64", description="Agent-first BF64 utility surface")
    parser.add_argument("--version", action="version", version=f"%(prog)s {CLI_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check local BF64 agent/tooling environment")
    doctor.add_argument("--strict", action="store_true", help="Treat missing optional build/run tools as errors")
    doctor.add_argument("--project", help="Project whose pathN64Inst should be checked or repaired")
    doctor.add_argument("--n64-inst", help="Explicit libdragon SDK prefix to check or persist")
    doctor.add_argument("--fix", action="store_true", help="Atomically persist a valid SDK path and project-local shell helper")
    doctor.add_argument("--dry-run", action="store_true", help="Plan --fix changes without writing")
    doctor.add_argument("--json", action="store_true", help="Emit stable JSON")
    doctor.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    doctor.add_argument("--history-path", help="Override operation history JSONL path for --record")
    doctor.set_defaults(func=cmd_doctor)

    toolchain = sub.add_parser("toolchain", help="Detect or install the Linux libdragon/Tiny3D toolchain")
    toolchain_sub = toolchain.add_subparsers(dest="toolchain_command", required=True)

    toolchain_detect = toolchain_sub.add_parser("detect", help="Resolve and verify an installed libdragon SDK")
    toolchain_detect.add_argument("--project", help="Project whose pathN64Inst should participate in discovery")
    toolchain_detect.add_argument("--prefix", help="Explicit SDK prefix; overrides project, environment, and defaults")
    toolchain_detect.add_argument("--json", action="store_true", help="Emit stable JSON")
    toolchain_detect.add_argument("--record", action="store_true", help="Append result to operation history")
    toolchain_detect.add_argument("--history-path", help="Override operation history JSONL path")
    toolchain_detect.set_defaults(func=cmd_toolchain_detect)

    toolchain_install = toolchain_sub.add_parser("install", help="Install libdragon and the pinned Tiny3D into an SDK prefix")
    toolchain_install.add_argument(
        "--source",
        default=str(Path.home() / "Documents" / "libdragon"),
        help="libdragon source checkout; defaults to ~/Documents/libdragon",
    )
    toolchain_install.add_argument(
        "--prefix",
        default=str(Path.home() / "Documents" / "libdragon-sdk"),
        help="SDK install prefix; defaults to ~/Documents/libdragon-sdk",
    )
    toolchain_install.add_argument("--make-binary", default="make", help="Make executable or path")
    toolchain_install.add_argument("--skip-toolchain", action="store_true", help="Do not build a missing mips64-elf compiler")
    toolchain_install.add_argument("--skip-tiny3d", action="store_true", help="Do not install bundled Tiny3D")
    toolchain_install.add_argument("--timeout", type=int, default=0, help="Per-step timeout in seconds; 0 means no timeout")
    toolchain_install.add_argument("--dry-run", action="store_true", help="Print the install plan without executing commands")
    toolchain_install.add_argument("--json", action="store_true", help="Emit stable JSON")
    toolchain_install.add_argument("--record", action="store_true", help="Append result to operation history")
    toolchain_install.add_argument("--history-path", help="Override operation history JSONL path")
    toolchain_install.set_defaults(func=cmd_toolchain_install)

    constraints = sub.add_parser("constraints", help="Query machine-readable N64/BF64 limits")
    constraints.add_argument("topic", nargs="?", default="list", help="list, texture, model, audio, scene, rom, or exit_codes")
    constraints.add_argument("--json", action="store_true", help="Emit stable JSON")
    constraints.set_defaults(func=cmd_constraints)

    validate = sub.add_parser("validate", help="Validate one asset, project, or scene against BF64/N64 constraints")
    validate.add_argument("path", help="Asset path, project.p64proj, or scene.json")
    validate.add_argument("--kind", choices=["texture", "model", "audio", "font", "ui", "project", "scene"], help="Override input kind")
    validate.add_argument("--conf", help="Explicit .conf sidecar path")
    validate.add_argument("--json", action="store_true", help="Emit stable JSON")
    validate.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    validate.add_argument("--history-path", help="Override operation history JSONL path for --record")
    validate.add_argument("--texture-format", help="Texture format name or id for strict texture validation")
    validate.add_argument("--scene-pipeline", help="default, hdr, bigtex, or 0/1/2")
    validate.add_argument("--role", choices=["sfx", "music", "voice", "unknown"], default="unknown", help="Audio role hint")
    validate.set_defaults(func=validate_asset)

    build = sub.add_parser("build", help="Plan or execute a BF64 ROM build")
    build.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    build.add_argument("--execute", action="store_true", help="Run the existing Pyrite64 CLI build after strict preflight")
    build.add_argument("--pyrite64-binary", help="Path to the Pyrite64 editor binary used by --execute")
    build.add_argument("--timeout", type=int, default=0, help="Optional --execute timeout in seconds; 0 means no timeout")
    build.add_argument("--strict-toolchain", action="store_true", help="Treat missing build toolchain pieces as errors")
    build.add_argument("--json", action="store_true", help="Emit stable JSON")
    build.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    build.add_argument("--history-path", help="Override operation history JSONL path for --record")
    build.set_defaults(func=cmd_build)

    run = sub.add_parser("run", help="Run a built BF64 ROM in an emulator")
    run.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    run.add_argument("--build", action="store_true", help="Run build --execute before launching the ROM")
    run.add_argument("--pyrite64-binary", help="Path to the Pyrite64 editor binary used by --build")
    run.add_argument("--emulator", help="Emulator command override; defaults to project pathEmu or ares")
    run.add_argument("--timeout", type=int, default=0, help="Optional emulator timeout in seconds; 0 means no timeout")
    run.add_argument("--build-timeout", type=int, default=0, help="Optional --build timeout in seconds; 0 means no timeout")
    run.add_argument("--profile", action="store_true", help="Capture a bounded structured runtime profile and stop the emulator")
    run.add_argument("--profile-warmup", type=int, default=120, help="Frames to discard before profiling (0..65535)")
    run.add_argument("--profile-frames", type=int, default=300, help="Frames to sample (1..2048)")
    run.add_argument("--profile-output", help="Profile JSON artifact path; defaults under <project>/.bf64/profiles")
    run.add_argument("--json", action="store_true", help="Emit stable JSON")
    run.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    run.add_argument("--history-path", help="Override operation history JSONL path for --record")
    run.set_defaults(func=cmd_run)

    new = sub.add_parser("new", help="Create a new BF64 project from the editor-compatible starter template")
    new.add_argument("path", help="Project directory to create; must not contain spaces")
    new.add_argument("--name", help="Human-readable project name; defaults to the target directory name")
    new.add_argument("--rom-name", help="ROM filename stem; defaults to a safe version of the target directory name")
    new.add_argument("--emulator", default="ares", help="Project pathEmu value; defaults to ares")
    new.add_argument("--n64-inst", default="", help="Project pathN64Inst value; defaults to empty and can use N64_INST at build time")
    new_mode = new.add_mutually_exclusive_group()
    new_mode.add_argument("--force", action="store_true", help="Overwrite scaffold files in an existing directory")
    new_mode.add_argument("--merge", action="store_true", help="Add only missing scaffold files and preserve existing repository content")
    new.add_argument("--json", action="store_true", help="Emit stable JSON")
    new.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    new.add_argument("--history-path", help="Override operation history JSONL path for --record")
    new.set_defaults(func=cmd_new)

    init = sub.add_parser("init", help="Merge-initialize an existing asset-first repository as a BF64 project")
    init.add_argument("--project", default=".", help="Existing repository directory to initialize")
    init.add_argument("--name", help="Human-readable project name used only when creating project.p64proj")
    init.add_argument("--rom-name", help="ROM filename stem used only when creating project.p64proj")
    init.add_argument("--emulator", default="ares", help="Project pathEmu value used only when creating project.p64proj")
    init.add_argument("--n64-inst", default="", help="Project pathN64Inst value used only when creating project.p64proj")
    init.add_argument("--json", action="store_true", help="Emit stable JSON")
    init.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    init.add_argument("--history-path", help="Override operation history JSONL path for --record")
    init.set_defaults(func=cmd_init)

    import_cmd = sub.add_parser("import", help="Import one supported asset into a BF64 project")
    import_cmd.add_argument("source", help="Source asset file to copy into project assets/")
    import_cmd.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    import_cmd.add_argument("--dest", help="Destination under assets/; defaults to the source basename")
    import_cmd.add_argument("--force", action="store_true", help="Overwrite an existing target asset and sidecar")
    import_cmd.add_argument("--dry-run", action="store_true", help="Validate and report planned changes without copying files")
    import_cmd.add_argument("--texture-format", help="Texture format name or id to write into the imported sidecar")
    import_cmd.add_argument("--scene-pipeline", help="default, hdr, bigtex, or 0/1/2 for texture validation")
    import_cmd.add_argument("--compression", help="Asset compression value to write into the imported sidecar")
    import_cmd.add_argument("--base-scale", help="Model baseScale value to write into the imported sidecar")
    import_cmd.add_argument("--gltf-bvh", action="store_true", help="Enable model BVH generation in the imported sidecar")
    import_cmd.add_argument("--wav-force-mono", action="store_true", help="Set wavForceMono in the imported sidecar")
    import_cmd.add_argument("--wav-resample-rate", help="Set wavResampleRate in the imported sidecar")
    import_cmd.add_argument("--wav-compression", help="Set wavCompression in the imported sidecar")
    import_cmd.add_argument("--role", choices=["sfx", "music", "voice", "unknown"], default="unknown", help="Audio role hint")
    import_cmd.add_argument("--font-id", help="Set fontId in the imported sidecar")
    import_cmd.add_argument("--font-charset", help="Set fontCharset in the imported sidecar; defaults to BF64's built-in charset")
    import_cmd.add_argument("--exclude", action="store_true", help="Mark the imported asset sidecar as excluded from builds")
    import_cmd.add_argument("--json", action="store_true", help="Emit stable JSON")
    import_cmd.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    import_cmd.add_argument("--history-path", help="Override operation history JSONL path for --record")
    import_cmd.set_defaults(func=cmd_import)

    focus = sub.add_parser("focus", help="Inspect dedicated BF64 product focus areas")
    focus_sub = focus.add_subparsers(dest="focus_command", required=True)
    focus_list = focus_sub.add_parser("list", help="List focus areas and implementation status")
    focus_list.add_argument("--json", action="store_true", help="Emit stable JSON")
    focus_list.set_defaults(func=cmd_focus_list)

    for area_id, area_label in (
        ("music", "music assets"),
        ("sfx", "sound-effect assets"),
        ("environment", "3D environment assets"),
        ("avatar", "3D avatar assets"),
        ("cutscene", "cutscene assets"),
    ):
        area_parser = sub.add_parser(area_id, help=f"Work with dedicated {area_label}")
        area_sub = area_parser.add_subparsers(dest="focus_area_command", required=True)

        area_ls = area_sub.add_parser("ls", help=f"List tagged {area_label} and compatible candidates")
        area_ls.add_argument("--project", default=".")
        area_ls.add_argument("--json", action="store_true")
        area_ls.add_argument("--record", action="store_true")
        area_ls.add_argument("--history-path")
        area_ls.set_defaults(func=cmd_focus_area_ls, focus_area=area_id)

        area_validate = area_sub.add_parser("validate", help=f"Validate tagged {area_label}")
        area_validate.add_argument("--project", default=".")
        area_validate.add_argument("--include-excluded", action="store_true")
        area_validate.add_argument("--json", action="store_true")
        area_validate.add_argument("--record", action="store_true")
        area_validate.add_argument("--history-path")
        area_validate.set_defaults(func=cmd_focus_area_validate, focus_area=area_id)

        area_tag = area_sub.add_parser("tag", help=f"Assign or clear the {area_id} focus tag on an asset")
        area_tag.add_argument("asset", help="Project asset path or unique basename")
        area_tag.add_argument("--clear", action="store_true", help="Remove this focus tag")
        area_tag.add_argument("--project", default=".")
        area_tag.add_argument("--dry-run", action="store_true")
        area_tag.add_argument("--json", action="store_true")
        area_tag.add_argument("--record", action="store_true")
        area_tag.add_argument("--history-path")
        area_tag.set_defaults(func=cmd_focus_area_tag, focus_area=area_id)

    ui = sub.add_parser("ui", help="Author and validate 2D UI documents")
    ui_sub = ui.add_subparsers(dest="ui_command", required=True)
    ui_new = ui_sub.add_parser("new", help="Create a versioned .bfui document")
    ui_new.add_argument("path", help="Destination under project assets/, with or without .bfui")
    ui_new.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    ui_new.add_argument("--width", type=int, default=320, help="Target canvas width; defaults to 320")
    ui_new.add_argument("--height", type=int, default=240, help="Target canvas height; defaults to 240")
    ui_new.add_argument("--force", action="store_true", help="Overwrite an existing UI document")
    ui_new.add_argument("--json", action="store_true", help="Emit stable JSON")
    ui_new.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    ui_new.add_argument("--history-path", help="Override operation history JSONL path for --record")
    ui_new.set_defaults(func=cmd_ui_new)

    ui_ls = ui_sub.add_parser("ls", help="List UI documents in a project")
    ui_ls.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    ui_ls.add_argument("--json", action="store_true", help="Emit stable JSON")
    ui_ls.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    ui_ls.add_argument("--history-path", help="Override operation history JSONL path for --record")
    ui_ls.set_defaults(func=cmd_ui_ls)

    ui_show = ui_sub.add_parser("show", help="Show one UI document and its validation")
    ui_show.add_argument("document", help="Project-relative path or unique .bfui basename")
    ui_show.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    ui_show.add_argument("--json", action="store_true", help="Emit stable JSON including the source document")
    ui_show.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    ui_show.add_argument("--history-path", help="Override operation history JSONL path for --record")
    ui_show.set_defaults(func=cmd_ui_show)

    ui_validate = ui_sub.add_parser("validate", help="Validate one or all UI documents")
    ui_validate.add_argument("document", nargs="?", help="Project-relative path or unique .bfui basename")
    ui_validate.add_argument("--all", action="store_true", help="Validate every .bfui document in the project")
    ui_validate.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    ui_validate.add_argument("--json", action="store_true", help="Emit stable JSON")
    ui_validate.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    ui_validate.add_argument("--history-path", help="Override operation history JSONL path for --record")
    ui_validate.set_defaults(func=cmd_ui_validate)

    prefab = sub.add_parser("prefab", help="Author and validate structured prefab assets")
    prefab_sub = prefab.add_subparsers(dest="prefab_command", required=True)

    prefab_ls = prefab_sub.add_parser("ls", help="List project prefabs")
    prefab_ls.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    prefab_ls.add_argument("--json", action="store_true", help="Emit stable JSON")
    prefab_ls.add_argument("--record", action="store_true", help="Append result to operation history")
    prefab_ls.add_argument("--history-path", help="Override operation history JSONL path")
    prefab_ls.set_defaults(func=cmd_prefab_ls)

    prefab_show = prefab_sub.add_parser("show", help="Show one prefab document and validation")
    prefab_show.add_argument("prefab", help="Prefab path, stem, or unique basename")
    prefab_show.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    prefab_show.add_argument("--json", action="store_true", help="Emit stable JSON")
    prefab_show.add_argument("--record", action="store_true", help="Append result to operation history")
    prefab_show.add_argument("--history-path", help="Override operation history JSONL path")
    prefab_show.set_defaults(func=cmd_prefab_show)

    prefab_validate = prefab_sub.add_parser("validate", help="Validate one or all prefab documents")
    prefab_validate.add_argument("prefab", nargs="?", help="Prefab path, stem, or unique basename")
    prefab_validate.add_argument("--all", action="store_true", help="Validate every project prefab")
    prefab_validate.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    prefab_validate.add_argument("--json", action="store_true", help="Emit stable JSON")
    prefab_validate.add_argument("--record", action="store_true", help="Append result to operation history")
    prefab_validate.add_argument("--history-path", help="Override operation history JSONL path")
    prefab_validate.set_defaults(func=cmd_prefab_validate)

    prefab_create = prefab_sub.add_parser("create", help="Create an editor-compatible prefab and sidecar")
    prefab_create.add_argument("path", help="Assets-relative prefab path; .prefab is optional")
    prefab_create.add_argument("--name", default="New Prefab", help="Root object display name")
    prefab_create.add_argument("--uuid", type=parse_cli_int, help="Explicit 32-bit prefab UUID")
    prefab_create.add_argument("--object-uuid", type=parse_cli_int, help="Explicit 32-bit root object UUID")
    prefab_create.add_argument("--force", action="store_true", help="Replace an existing prefab pair")
    prefab_create.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    prefab_create.add_argument("--dry-run", action="store_true", help="Validate without writing")
    prefab_create.add_argument("--json", action="store_true", help="Emit stable JSON")
    prefab_create.add_argument("--record", action="store_true", help="Append result to operation history")
    prefab_create.add_argument("--history-path", help="Override operation history JSONL path")
    prefab_create.set_defaults(func=cmd_prefab_create)

    prefab_duplicate = prefab_sub.add_parser("duplicate", help="Duplicate a prefab with regenerated persistent UUIDs")
    prefab_duplicate.add_argument("prefab", help="Source prefab")
    prefab_duplicate.add_argument("path", help="Destination assets-relative path")
    prefab_duplicate.add_argument("--name", help="New root object name")
    prefab_duplicate.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    prefab_duplicate.add_argument("--dry-run", action="store_true", help="Validate without writing")
    prefab_duplicate.add_argument("--json", action="store_true", help="Emit stable JSON")
    prefab_duplicate.add_argument("--record", action="store_true", help="Append result to operation history")
    prefab_duplicate.add_argument("--history-path", help="Override operation history JSONL path")
    prefab_duplicate.set_defaults(func=cmd_prefab_duplicate)

    prefab_rename = prefab_sub.add_parser("rename", help="Atomically move a prefab and its sidecar")
    prefab_rename.add_argument("prefab", help="Source prefab")
    prefab_rename.add_argument("path", help="Destination assets-relative path")
    prefab_rename.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    prefab_rename.add_argument("--dry-run", action="store_true", help="Validate without writing")
    prefab_rename.add_argument("--json", action="store_true", help="Emit stable JSON")
    prefab_rename.add_argument("--record", action="store_true", help="Append result to operation history")
    prefab_rename.add_argument("--history-path", help="Override operation history JSONL path")
    prefab_rename.set_defaults(func=cmd_prefab_rename)

    prefab_object = prefab_sub.add_parser("object", help="Add, update, reparent, or remove prefab objects")
    prefab_object_sub = prefab_object.add_subparsers(dest="prefab_object_command", required=True)
    prefab_object_add = prefab_object_sub.add_parser("add", help="Add a child object")
    prefab_object_add.add_argument("prefab", help="Prefab to mutate")
    prefab_object_add.add_argument("--name", default="New Object")
    prefab_object_add.add_argument("--uuid", type=parse_cli_int)
    prefab_object_add.add_argument("--parent", default="root", help="Parent UUID/name; root means the prefab root object")
    prefab_object_add.add_argument("--position", nargs=3, type=float, default=[0.0, 0.0, 0.0])
    prefab_object_add.add_argument("--project", default=".")
    prefab_object_add.add_argument("--dry-run", action="store_true")
    prefab_object_add.add_argument("--json", action="store_true")
    prefab_object_add.add_argument("--record", action="store_true")
    prefab_object_add.add_argument("--history-path")
    prefab_object_add.set_defaults(func=cmd_prefab_object_add)

    prefab_object_update = prefab_object_sub.add_parser("update", help="Update authored object properties")
    prefab_object_update.add_argument("prefab")
    prefab_object_update.add_argument("object", help="Object UUID or unique name")
    prefab_object_update.add_argument("--name")
    prefab_object_update.add_argument("--position", nargs=3, type=float)
    prefab_object_update.add_argument("--rotation", nargs=4, type=float)
    prefab_object_update.add_argument("--scale", nargs=3, type=float)
    prefab_object_update.add_argument("--enabled", action=argparse.BooleanOptionalAction, default=None)
    prefab_object_update.add_argument("--selectable", action=argparse.BooleanOptionalAction, default=None)
    prefab_object_update.add_argument("--project", default=".")
    prefab_object_update.add_argument("--dry-run", action="store_true")
    prefab_object_update.add_argument("--json", action="store_true")
    prefab_object_update.add_argument("--record", action="store_true")
    prefab_object_update.add_argument("--history-path")
    prefab_object_update.set_defaults(func=cmd_prefab_object_update)

    prefab_object_reparent = prefab_object_sub.add_parser("reparent", help="Move an object subtree")
    prefab_object_reparent.add_argument("prefab")
    prefab_object_reparent.add_argument("object")
    prefab_object_reparent.add_argument("--parent", required=True)
    prefab_object_reparent.add_argument("--project", default=".")
    prefab_object_reparent.add_argument("--dry-run", action="store_true")
    prefab_object_reparent.add_argument("--json", action="store_true")
    prefab_object_reparent.add_argument("--record", action="store_true")
    prefab_object_reparent.add_argument("--history-path")
    prefab_object_reparent.set_defaults(func=cmd_prefab_object_reparent)

    prefab_object_remove = prefab_object_sub.add_parser("remove", help="Remove a child object subtree")
    prefab_object_remove.add_argument("prefab")
    prefab_object_remove.add_argument("object")
    prefab_object_remove.add_argument("--project", default=".")
    prefab_object_remove.add_argument("--dry-run", action="store_true")
    prefab_object_remove.add_argument("--json", action="store_true")
    prefab_object_remove.add_argument("--record", action="store_true")
    prefab_object_remove.add_argument("--history-path")
    prefab_object_remove.set_defaults(func=cmd_prefab_object_remove)

    prefab_component = prefab_sub.add_parser("component", help="Add, update, or remove prefab components")
    prefab_component_sub = prefab_component.add_subparsers(dest="prefab_component_command", required=True)
    prefab_component_add = prefab_component_sub.add_parser("add", help="Add a component")
    prefab_component_add.add_argument("prefab")
    prefab_component_add.add_argument("object")
    prefab_component_add.add_argument("type", help="Component id or name")
    prefab_component_add.add_argument("--uuid", type=parse_cli_int)
    prefab_component_add.add_argument("--name")
    prefab_component_add.add_argument("--data", help="Component data patch JSON")
    prefab_component_add.add_argument("--asset", help="Compatible asset reference assigned by stable sidecar UUID")
    prefab_component_add.add_argument("--script", help="Code adapter source path, UUID, or unique basename")
    prefab_component_add.add_argument("--args", dest="script_args", help="Code argument JSON object or @file")
    prefab_component_add.add_argument("--project", default=".")
    prefab_component_add.add_argument("--dry-run", action="store_true")
    prefab_component_add.add_argument("--json", action="store_true")
    prefab_component_add.add_argument("--record", action="store_true")
    prefab_component_add.add_argument("--history-path")
    prefab_component_add.set_defaults(func=cmd_prefab_component_add)

    prefab_component_update = prefab_component_sub.add_parser("update", help="Update a component")
    prefab_component_update.add_argument("prefab")
    prefab_component_update.add_argument("object")
    prefab_component_update.add_argument("component", help="Component UUID or unique name")
    prefab_component_update.add_argument("--name")
    prefab_component_update.add_argument("--data", help="Component data patch JSON")
    prefab_component_update.add_argument("--asset", help="Compatible replacement asset reference")
    prefab_component_update.add_argument("--script", help="Replacement Code adapter source path, UUID, or basename")
    prefab_component_update.add_argument("--args", dest="script_args", help="Code argument JSON object or @file")
    prefab_component_update.add_argument("--project", default=".")
    prefab_component_update.add_argument("--dry-run", action="store_true")
    prefab_component_update.add_argument("--json", action="store_true")
    prefab_component_update.add_argument("--record", action="store_true")
    prefab_component_update.add_argument("--history-path")
    prefab_component_update.set_defaults(func=cmd_prefab_component_update)

    prefab_component_remove = prefab_component_sub.add_parser("remove", help="Remove a component")
    prefab_component_remove.add_argument("prefab")
    prefab_component_remove.add_argument("object")
    prefab_component_remove.add_argument("component")
    prefab_component_remove.add_argument("--project", default=".")
    prefab_component_remove.add_argument("--dry-run", action="store_true")
    prefab_component_remove.add_argument("--json", action="store_true")
    prefab_component_remove.add_argument("--record", action="store_true")
    prefab_component_remove.add_argument("--history-path")
    prefab_component_remove.set_defaults(func=cmd_prefab_component_remove)

    prefab_attach = prefab_sub.add_parser("attach", help="Attach a camera/model/collision/light/UI/Code adapter")
    prefab_attach.add_argument(
        "kind",
        choices=("ui", "camera", "model", "collision", "collision-mesh", "collider", "light", "audio3d", "code"),
        help="Adapter kind",
    )
    prefab_attach.add_argument("prefab", help="Prefab to mutate")
    prefab_attach.add_argument("object", help="Object UUID or unique name")
    prefab_attach.add_argument("reference", nargs="?", help="Required asset or script reference for applicable adapters")
    prefab_attach.add_argument("--uuid", type=parse_cli_int, help="Explicit 64-bit component UUID")
    prefab_attach.add_argument("--name", help="Component display name override")
    prefab_attach.add_argument("--data", help="JSON object or @file merged over compatible defaults")
    prefab_attach.add_argument("--args", dest="script_args", help="Code argument JSON object or @file")
    prefab_attach.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    prefab_attach.add_argument("--dry-run", action="store_true", help="Validate without writing")
    prefab_attach.add_argument("--json", action="store_true", help="Emit stable JSON")
    prefab_attach.add_argument("--record", action="store_true", help="Append result to operation history")
    prefab_attach.add_argument("--history-path", help="Override operation history JSONL path")
    prefab_attach.set_defaults(func=cmd_prefab_attach)

    prefab_set = prefab_sub.add_parser("set", help="Set an existing value using an RFC 6901 JSON pointer")
    prefab_set.add_argument("prefab", help="Prefab to mutate")
    prefab_set.add_argument("pointer", help="JSON pointer such as /obj/enabled")
    prefab_set.add_argument("value", help="JSON value, such as false, 12, or [0,0,0]")
    prefab_set.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    prefab_set.add_argument("--dry-run", action="store_true", help="Validate without writing")
    prefab_set.add_argument("--json", action="store_true", help="Emit stable JSON")
    prefab_set.add_argument("--record", action="store_true", help="Append result to operation history")
    prefab_set.add_argument("--history-path", help="Override operation history JSONL path")
    prefab_set.set_defaults(func=cmd_prefab_set)

    prefab_delete = prefab_sub.add_parser("delete", help="Atomically delete a prefab and sidecar")
    prefab_delete.add_argument("prefab", help="Prefab to delete")
    prefab_delete.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    prefab_delete.add_argument("--dry-run", action="store_true", help="Validate without writing")
    prefab_delete.add_argument("--json", action="store_true", help="Emit stable JSON")
    prefab_delete.add_argument("--record", action="store_true", help="Append result to operation history")
    prefab_delete.add_argument("--history-path", help="Override operation history JSONL path")
    prefab_delete.set_defaults(func=cmd_prefab_delete)

    node_graph = sub.add_parser("node-graph", help="Author and validate structured visual-script graphs")
    node_graph_sub = node_graph.add_subparsers(dest="node_graph_command", required=True)

    node_graph_ls = node_graph_sub.add_parser("ls", help="List project node graphs")
    node_graph_ls.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    node_graph_ls.add_argument("--json", action="store_true", help="Emit stable JSON")
    node_graph_ls.add_argument("--record", action="store_true", help="Append result to operation history")
    node_graph_ls.add_argument("--history-path", help="Override operation history JSONL path")
    node_graph_ls.set_defaults(func=cmd_node_graph_ls)

    node_graph_show = node_graph_sub.add_parser("show", help="Show one graph and validation")
    node_graph_show.add_argument("graph", help="Graph path, stem, or unique basename")
    node_graph_show.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    node_graph_show.add_argument("--json", action="store_true", help="Emit stable JSON")
    node_graph_show.add_argument("--record", action="store_true", help="Append result to operation history")
    node_graph_show.add_argument("--history-path", help="Override operation history JSONL path")
    node_graph_show.set_defaults(func=cmd_node_graph_show)

    node_graph_validate = node_graph_sub.add_parser("validate", help="Validate one or all node graphs")
    node_graph_validate.add_argument("graph", nargs="?", help="Graph path, stem, or unique basename")
    node_graph_validate.add_argument("--all", action="store_true", help="Validate every project node graph")
    node_graph_validate.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    node_graph_validate.add_argument("--json", action="store_true", help="Emit stable JSON")
    node_graph_validate.add_argument("--record", action="store_true", help="Append result to operation history")
    node_graph_validate.add_argument("--history-path", help="Override operation history JSONL path")
    node_graph_validate.set_defaults(func=cmd_node_graph_validate)

    node_graph_create = node_graph_sub.add_parser("create", help="Create an editor-compatible node graph and sidecar")
    node_graph_create.add_argument("path", help="Assets-relative graph path; .p64graph is optional")
    node_graph_create.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    node_graph_create.add_argument("--dry-run", action="store_true", help="Validate without writing")
    node_graph_create.add_argument("--json", action="store_true", help="Emit stable JSON")
    node_graph_create.add_argument("--record", action="store_true", help="Append result to operation history")
    node_graph_create.add_argument("--history-path", help="Override operation history JSONL path")
    node_graph_create.set_defaults(func=cmd_node_graph_create)

    node_graph_duplicate = node_graph_sub.add_parser("duplicate", help="Duplicate a graph and regenerate node/asset UUIDs")
    node_graph_duplicate.add_argument("graph", help="Source graph")
    node_graph_duplicate.add_argument("path", help="Destination assets-relative path")
    node_graph_duplicate.add_argument("--project", default=".")
    node_graph_duplicate.add_argument("--dry-run", action="store_true")
    node_graph_duplicate.add_argument("--json", action="store_true")
    node_graph_duplicate.add_argument("--record", action="store_true")
    node_graph_duplicate.add_argument("--history-path")
    node_graph_duplicate.set_defaults(func=cmd_node_graph_duplicate)

    node_graph_rename = node_graph_sub.add_parser("rename", help="Atomically move a graph and sidecar")
    node_graph_rename.add_argument("graph")
    node_graph_rename.add_argument("path")
    node_graph_rename.add_argument("--project", default=".")
    node_graph_rename.add_argument("--dry-run", action="store_true")
    node_graph_rename.add_argument("--json", action="store_true")
    node_graph_rename.add_argument("--record", action="store_true")
    node_graph_rename.add_argument("--history-path")
    node_graph_rename.set_defaults(func=cmd_node_graph_rename)

    node_graph_delete = node_graph_sub.add_parser("delete", help="Atomically delete a graph and sidecar")
    node_graph_delete.add_argument("graph")
    node_graph_delete.add_argument("--project", default=".")
    node_graph_delete.add_argument("--dry-run", action="store_true")
    node_graph_delete.add_argument("--json", action="store_true")
    node_graph_delete.add_argument("--record", action="store_true")
    node_graph_delete.add_argument("--history-path")
    node_graph_delete.set_defaults(func=cmd_node_graph_delete)

    node_graph_node = node_graph_sub.add_parser("node", help="Add or remove graph nodes")
    node_graph_node_sub = node_graph_node.add_subparsers(dest="node_graph_node_command", required=True)
    node_graph_node_add = node_graph_node_sub.add_parser("add", help="Add a typed node with a persistent UUID")
    node_graph_node_add.add_argument("graph", help="Graph to mutate")
    node_graph_node_add.add_argument("type_id", help="Stable node type id such as core.start")
    node_graph_node_add.add_argument("--uuid", type=parse_cli_int, help="Explicit 64-bit node UUID")
    node_graph_node_add.add_argument("--pos", nargs=2, type=float, default=[0.0, 0.0], metavar=("X", "Y"))
    node_graph_node_add.add_argument("--data", help="Additional node properties as a JSON object")
    node_graph_node_add.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    node_graph_node_add.add_argument("--dry-run", action="store_true", help="Validate without writing")
    node_graph_node_add.add_argument("--json", action="store_true", help="Emit stable JSON")
    node_graph_node_add.add_argument("--record", action="store_true", help="Append result to operation history")
    node_graph_node_add.add_argument("--history-path", help="Override operation history JSONL path")
    node_graph_node_add.set_defaults(func=cmd_node_graph_node_add)

    node_graph_node_update = node_graph_node_sub.add_parser("update", help="Update node type, position, or properties")
    node_graph_node_update.add_argument("graph")
    node_graph_node_update.add_argument("node", help="Node UUID")
    node_graph_node_update.add_argument("--type-id")
    node_graph_node_update.add_argument("--pos", nargs=2, type=float)
    node_graph_node_update.add_argument("--data", help="Node property patch JSON")
    node_graph_node_update.add_argument("--project", default=".")
    node_graph_node_update.add_argument("--dry-run", action="store_true")
    node_graph_node_update.add_argument("--json", action="store_true")
    node_graph_node_update.add_argument("--record", action="store_true")
    node_graph_node_update.add_argument("--history-path")
    node_graph_node_update.set_defaults(func=cmd_node_graph_node_update)

    node_graph_node_remove = node_graph_node_sub.add_parser("remove", help="Remove a node and its incident links")
    node_graph_node_remove.add_argument("graph", help="Graph to mutate")
    node_graph_node_remove.add_argument("node", help="Node UUID")
    node_graph_node_remove.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    node_graph_node_remove.add_argument("--dry-run", action="store_true", help="Validate without writing")
    node_graph_node_remove.add_argument("--json", action="store_true", help="Emit stable JSON")
    node_graph_node_remove.add_argument("--record", action="store_true", help="Append result to operation history")
    node_graph_node_remove.add_argument("--history-path", help="Override operation history JSONL path")
    node_graph_node_remove.set_defaults(func=cmd_node_graph_node_remove)

    node_graph_link = node_graph_sub.add_parser("link", help="Add graph links")
    node_graph_link_sub = node_graph_link.add_subparsers(dest="node_graph_link_command", required=True)
    node_graph_link_add = node_graph_link_sub.add_parser("add", help="Connect two node ports")
    node_graph_link_add.add_argument("graph", help="Graph to mutate")
    node_graph_link_add.add_argument("src", help="Source node UUID")
    node_graph_link_add.add_argument("dst", help="Destination node UUID")
    node_graph_link_add.add_argument("--src-port", type=int, default=0)
    node_graph_link_add.add_argument("--dst-port", type=int, default=0)
    node_graph_link_add.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    node_graph_link_add.add_argument("--dry-run", action="store_true", help="Validate without writing")
    node_graph_link_add.add_argument("--json", action="store_true", help="Emit stable JSON")
    node_graph_link_add.add_argument("--record", action="store_true", help="Append result to operation history")
    node_graph_link_add.add_argument("--history-path", help="Override operation history JSONL path")
    node_graph_link_add.set_defaults(func=cmd_node_graph_link_add)

    node_graph_link_remove = node_graph_link_sub.add_parser("remove", help="Remove matching links between two nodes")
    node_graph_link_remove.add_argument("graph")
    node_graph_link_remove.add_argument("src")
    node_graph_link_remove.add_argument("dst")
    node_graph_link_remove.add_argument("--src-port", type=int)
    node_graph_link_remove.add_argument("--dst-port", type=int)
    node_graph_link_remove.add_argument("--project", default=".")
    node_graph_link_remove.add_argument("--dry-run", action="store_true")
    node_graph_link_remove.add_argument("--json", action="store_true")
    node_graph_link_remove.add_argument("--record", action="store_true")
    node_graph_link_remove.add_argument("--history-path")
    node_graph_link_remove.set_defaults(func=cmd_node_graph_link_remove)

    node_graph_variable = node_graph_sub.add_parser("variable", help="Manage graph variables")
    node_graph_variable_sub = node_graph_variable.add_subparsers(dest="node_graph_variable_command", required=True)
    node_graph_variable_add = node_graph_variable_sub.add_parser("add", help="Add a typed graph variable")
    node_graph_variable_add.add_argument("graph", help="Graph to mutate")
    node_graph_variable_add.add_argument("name", help="Unique variable name")
    node_graph_variable_add.add_argument("type", choices=sorted(NODE_GRAPH_VARIABLE_TYPES))
    node_graph_variable_add.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    node_graph_variable_add.add_argument("--dry-run", action="store_true", help="Validate without writing")
    node_graph_variable_add.add_argument("--json", action="store_true", help="Emit stable JSON")
    node_graph_variable_add.add_argument("--record", action="store_true", help="Append result to operation history")
    node_graph_variable_add.add_argument("--history-path", help="Override operation history JSONL path")
    node_graph_variable_add.set_defaults(func=cmd_node_graph_variable_add)

    node_graph_variable_update = node_graph_variable_sub.add_parser("update", help="Rename or retype a variable")
    node_graph_variable_update.add_argument("graph")
    node_graph_variable_update.add_argument("variable")
    node_graph_variable_update.add_argument("--name")
    node_graph_variable_update.add_argument("--type", choices=sorted(NODE_GRAPH_VARIABLE_TYPES))
    node_graph_variable_update.add_argument("--project", default=".")
    node_graph_variable_update.add_argument("--dry-run", action="store_true")
    node_graph_variable_update.add_argument("--json", action="store_true")
    node_graph_variable_update.add_argument("--record", action="store_true")
    node_graph_variable_update.add_argument("--history-path")
    node_graph_variable_update.set_defaults(func=cmd_node_graph_variable_update)

    node_graph_variable_remove = node_graph_variable_sub.add_parser("remove", help="Remove a variable")
    node_graph_variable_remove.add_argument("graph")
    node_graph_variable_remove.add_argument("variable")
    node_graph_variable_remove.add_argument("--force", action="store_true", help="Also remove nodes that reference the variable")
    node_graph_variable_remove.add_argument("--project", default=".")
    node_graph_variable_remove.add_argument("--dry-run", action="store_true")
    node_graph_variable_remove.add_argument("--json", action="store_true")
    node_graph_variable_remove.add_argument("--record", action="store_true")
    node_graph_variable_remove.add_argument("--history-path")
    node_graph_variable_remove.set_defaults(func=cmd_node_graph_variable_remove)

    node_graph_group = node_graph_sub.add_parser("group", help="Manage graph canvas groups")
    node_graph_group_sub = node_graph_group.add_subparsers(dest="node_graph_group_command", required=True)
    node_graph_group_add = node_graph_group_sub.add_parser("add", help="Add a canvas group")
    node_graph_group_add.add_argument("graph")
    node_graph_group_add.add_argument("title")
    node_graph_group_add.add_argument("--pos", nargs=2, type=float, default=[0.0, 0.0])
    node_graph_group_add.add_argument("--size", nargs=2, type=float, default=[240.0, 160.0])
    node_graph_group_add.add_argument("--project", default=".")
    node_graph_group_add.add_argument("--dry-run", action="store_true")
    node_graph_group_add.add_argument("--json", action="store_true")
    node_graph_group_add.add_argument("--record", action="store_true")
    node_graph_group_add.add_argument("--history-path")
    node_graph_group_add.set_defaults(func=cmd_node_graph_group_add)

    node_graph_group_update = node_graph_group_sub.add_parser("update", help="Update a canvas group by index")
    node_graph_group_update.add_argument("graph")
    node_graph_group_update.add_argument("index", type=int)
    node_graph_group_update.add_argument("--title")
    node_graph_group_update.add_argument("--pos", nargs=2, type=float)
    node_graph_group_update.add_argument("--size", nargs=2, type=float)
    node_graph_group_update.add_argument("--project", default=".")
    node_graph_group_update.add_argument("--dry-run", action="store_true")
    node_graph_group_update.add_argument("--json", action="store_true")
    node_graph_group_update.add_argument("--record", action="store_true")
    node_graph_group_update.add_argument("--history-path")
    node_graph_group_update.set_defaults(func=cmd_node_graph_group_update)

    node_graph_group_remove = node_graph_group_sub.add_parser("remove", help="Remove a canvas group by index")
    node_graph_group_remove.add_argument("graph")
    node_graph_group_remove.add_argument("index", type=int)
    node_graph_group_remove.add_argument("--project", default=".")
    node_graph_group_remove.add_argument("--dry-run", action="store_true")
    node_graph_group_remove.add_argument("--json", action="store_true")
    node_graph_group_remove.add_argument("--record", action="store_true")
    node_graph_group_remove.add_argument("--history-path")
    node_graph_group_remove.set_defaults(func=cmd_node_graph_group_remove)

    project = sub.add_parser("project", help="Read project-level BF64 status")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_status = project_sub.add_parser("status", help="Summarize project config, validation, assets, and toolchain")
    project_status.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    project_status.add_argument("--strict-doctor", action="store_true", help="Treat missing build/run tools as status errors")
    project_status.add_argument("--json", action="store_true", help="Emit stable JSON")
    project_status.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    project_status.add_argument("--history-path", help="Override operation history JSONL path for --record")
    project_status.set_defaults(func=cmd_project_status)

    asset = sub.add_parser("asset", help="Read and validate project assets")
    asset_sub = asset.add_subparsers(dest="asset_command", required=True)
    asset_ls = asset_sub.add_parser("ls", help="List assets in a BF64 project")
    asset_ls.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    asset_ls.add_argument("--kind", choices=PROJECT_ASSET_KINDS, help="Only return assets of this classified kind")
    asset_ls.add_argument("--json", action="store_true", help="Emit stable JSON")
    asset_ls.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    asset_ls.add_argument("--history-path", help="Override operation history JSONL path for --record")
    asset_ls.set_defaults(func=cmd_asset_ls)

    asset_show = asset_sub.add_parser("show", help="Show one project asset by path or unique basename")
    asset_show.add_argument("asset", help="Project-relative path, assets/<path>, or unique basename")
    asset_show.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    asset_show.add_argument("--json", action="store_true", help="Emit stable JSON")
    asset_show.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    asset_show.add_argument("--history-path", help="Override operation history JSONL path for --record")
    asset_show.add_argument("--texture-format", help="Texture format name or id for strict texture validation")
    asset_show.add_argument("--scene-pipeline", help="default, hdr, bigtex, or 0/1/2")
    asset_show.add_argument("--role", choices=["sfx", "music", "voice", "unknown"], default="unknown", help="Audio role hint")
    asset_show.set_defaults(func=cmd_asset_show)

    asset_validate_all = asset_sub.add_parser("validate-all", help="Validate all supported assets in a BF64 project")
    asset_validate_all.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    asset_validate_all.add_argument("--kind", choices=PROJECT_ASSET_KINDS, help="Only validate assets of this classified kind")
    asset_validate_all.add_argument(
        "--include-excluded",
        action="store_true",
        help="Validate assets marked exclude: true as part of a complete source audit",
    )
    asset_validate_all.add_argument("--json", action="store_true", help="Emit stable JSON")
    asset_validate_all.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    asset_validate_all.add_argument("--history-path", help="Override operation history JSONL path for --record")
    asset_validate_all.add_argument("--scene-pipeline", help="default, hdr, bigtex, or 0/1/2")
    asset_validate_all.add_argument("--role", choices=["sfx", "music", "voice", "unknown"], default="unknown", help="Audio role hint")
    asset_validate_all.set_defaults(func=cmd_asset_validate_all)

    asset_exclusion = asset_sub.add_parser("exclusion", help="Manage project-level asset exclusion globs")
    asset_exclusion_sub = asset_exclusion.add_subparsers(dest="asset_exclusion_command", required=True)

    asset_exclusion_list = asset_exclusion_sub.add_parser("list", help="List configured assets-relative exclusion globs")
    asset_exclusion_list.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    asset_exclusion_list.add_argument("--json", action="store_true", help="Emit stable JSON")
    asset_exclusion_list.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    asset_exclusion_list.add_argument("--history-path", help="Override operation history JSONL path for --record")
    asset_exclusion_list.set_defaults(func=cmd_asset_exclusion_list)

    for action, handler in (("add", cmd_asset_exclusion_add), ("remove", cmd_asset_exclusion_remove)):
        action_parser = asset_exclusion_sub.add_parser(
            action,
            help=f"{action.capitalize()} an assets-relative exclusion glob",
        )
        action_parser.add_argument("pattern", help="Glob such as reference/** or models/draft/**")
        action_parser.add_argument("--project", default=".", help="Project directory or project.p64proj path")
        action_parser.add_argument("--dry-run", action="store_true", help="Preview the atomic project config update")
        action_parser.add_argument("--json", action="store_true", help="Emit stable JSON")
        action_parser.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
        action_parser.add_argument("--history-path", help="Override operation history JSONL path for --record")
        action_parser.set_defaults(func=handler)

    scene = sub.add_parser("scene", help="Read and validate project scenes")
    scene_sub = scene.add_subparsers(dest="scene_command", required=True)
    scene_ls = scene_sub.add_parser("ls", help="List scenes in a BF64 project")
    scene_ls.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_ls.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_ls.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_ls.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_ls.set_defaults(func=cmd_scene_ls)

    scene_show = scene_sub.add_parser("show", help="Show one scene by id or exact name")
    scene_show.add_argument("scene", help="Scene id or exact scene name")
    scene_show.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_show.add_argument("--depth", type=int, default=3, help="Human-readable object tree depth; 0 hides tree")
    scene_show.add_argument("--json", action="store_true", help="Emit stable JSON including the raw scene document")
    scene_show.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_show.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_show.set_defaults(func=cmd_scene_show)

    scene_validate = scene_sub.add_parser("validate", help="Validate one scene or all scenes in a BF64 project")
    scene_validate.add_argument("scene", nargs="?", help="Optional scene id or exact scene name")
    scene_validate.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_validate.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_validate.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_validate.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_validate.set_defaults(func=cmd_scene_validate)

    scene_create = scene_sub.add_parser("create", help="Create a validated scene with the next available id")
    scene_create.add_argument("name", help="Scene display name")
    scene_create.add_argument("--id", type=int, help="Explicit positive scene id; defaults to max existing id + 1")
    scene_create.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_create.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_create.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_create.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_create.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_create.set_defaults(func=cmd_scene_create)

    scene_duplicate = scene_sub.add_parser("duplicate", help="Duplicate a validated scene under a new id")
    scene_duplicate.add_argument("scene", help="Source scene id or exact name")
    scene_duplicate.add_argument("--name", help="New scene display name; defaults to '<source> Copy'")
    scene_duplicate.add_argument("--id", type=int, help="Explicit positive destination scene id")
    scene_duplicate.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_duplicate.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_duplicate.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_duplicate.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_duplicate.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_duplicate.set_defaults(func=cmd_scene_duplicate)

    scene_rename = scene_sub.add_parser("rename", help="Rename a scene without changing its graph")
    scene_rename.add_argument("scene", help="Scene id or exact current name")
    scene_rename.add_argument("name", help="New scene display name")
    scene_rename.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_rename.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_rename.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_rename.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_rename.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_rename.set_defaults(func=cmd_scene_rename)

    scene_delete = scene_sub.add_parser("delete", help="Delete a scene transactionally after project validation")
    scene_delete.add_argument("scene", help="Scene id or exact name")
    scene_delete.add_argument(
        "--replacement",
        help="Existing scene id or exact name to receive boot/reset/last-opened references",
    )
    scene_delete.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_delete.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_delete.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_delete.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_delete.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_delete.set_defaults(func=cmd_scene_delete)

    scene_object = scene_sub.add_parser("object", help="Add, update, remove, or reparent scene objects")
    scene_object_sub = scene_object.add_subparsers(dest="scene_object_command", required=True)
    scene_object_add = scene_object_sub.add_parser("add", help="Add an object with a persistent unique UUID")
    scene_object_add.add_argument("scene", help="Scene id or exact name")
    scene_object_add.add_argument("--name", default="New Object", help="Object display name")
    scene_object_add.add_argument("--uuid", type=parse_cli_int, help="Explicit 32-bit UUID; generated when omitted")
    scene_object_add.add_argument("--parent", default="root", help="Parent object UUID/unique name, or root")
    scene_object_add.add_argument("--position", nargs=3, type=float, metavar=("X", "Y", "Z"))
    scene_object_add.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_object_add.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_object_add.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_object_add.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_object_add.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_object_add.set_defaults(func=cmd_scene_object_add)

    scene_object_update = scene_object_sub.add_parser("update", help="Update authored object properties")
    scene_object_update.add_argument("scene", help="Scene id or exact name")
    scene_object_update.add_argument("object", help="Object UUID or unique exact name")
    scene_object_update.add_argument("--name", help="New object display name")
    scene_object_update.add_argument("--position", nargs=3, type=float, metavar=("X", "Y", "Z"))
    scene_object_update.add_argument("--rotation", nargs=4, type=float, metavar=("X", "Y", "Z", "W"))
    scene_object_update.add_argument("--scale", nargs=3, type=float, metavar=("X", "Y", "Z"))
    scene_object_update.add_argument("--enabled", action=argparse.BooleanOptionalAction, default=None)
    scene_object_update.add_argument("--selectable", action=argparse.BooleanOptionalAction, default=None)
    scene_object_update.add_argument(
        "--proportional-scale",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    scene_object_update.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_object_update.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_object_update.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_object_update.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_object_update.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_object_update.set_defaults(func=cmd_scene_object_update)

    scene_object_reparent = scene_object_sub.add_parser("reparent", help="Move an object subtree to a new parent")
    scene_object_reparent.add_argument("scene", help="Scene id or exact name")
    scene_object_reparent.add_argument("object", help="Object UUID or unique exact name")
    scene_object_reparent.add_argument("--parent", required=True, help="New parent UUID/unique name, or root")
    scene_object_reparent.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_object_reparent.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_object_reparent.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_object_reparent.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_object_reparent.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_object_reparent.set_defaults(func=cmd_scene_object_reparent)

    scene_object_remove = scene_object_sub.add_parser("remove", help="Remove an object and its descendant subtree")
    scene_object_remove.add_argument("scene", help="Scene id or exact name")
    scene_object_remove.add_argument("object", help="Object UUID or unique exact name")
    scene_object_remove.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_object_remove.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_object_remove.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_object_remove.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_object_remove.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_object_remove.set_defaults(func=cmd_scene_object_remove)

    scene_component = scene_sub.add_parser("component", help="Add, update, or remove object components")
    scene_component_sub = scene_component.add_subparsers(dest="scene_component_command", required=True)
    scene_component_add = scene_component_sub.add_parser("add", help="Add a component from the stable registry")
    scene_component_add.add_argument("scene", help="Scene id or exact name")
    scene_component_add.add_argument("object", help="Object UUID or unique exact name")
    scene_component_add.add_argument("type", help="Stable component id or type name")
    scene_component_add.add_argument("--uuid", type=parse_cli_int, help="Explicit 64-bit UUID; generated when omitted")
    scene_component_add.add_argument("--name", help="Component display name override")
    scene_component_add.add_argument("--data", help="JSON object or @file merged over editor-compatible defaults")
    scene_component_add.add_argument("--asset", help="Resolve and assign a compatible asset by project reference")
    scene_component_add.add_argument("--script", help="Resolve and assign an object script to a Code component")
    scene_component_add.add_argument("--args", dest="script_args", help="Code argument JSON object or @file")
    scene_component_add.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_component_add.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_component_add.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_component_add.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_component_add.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_component_add.set_defaults(func=cmd_scene_component_add)

    scene_component_update = scene_component_sub.add_parser("update", help="Patch component name and serialized data")
    scene_component_update.add_argument("scene", help="Scene id or exact name")
    scene_component_update.add_argument("object", help="Object UUID or unique exact name")
    scene_component_update.add_argument("component", help="Component UUID or unique exact name")
    scene_component_update.add_argument("--name", help="New component display name")
    scene_component_update.add_argument("--data", help="JSON object or @file merged into component data")
    scene_component_update.add_argument("--asset", help="Resolve and assign a compatible asset by project reference")
    scene_component_update.add_argument("--script", help="Resolve and assign an object script to a Code component")
    scene_component_update.add_argument("--args", dest="script_args", help="Code argument JSON object or @file")
    scene_component_update.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_component_update.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_component_update.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_component_update.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_component_update.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_component_update.set_defaults(func=cmd_scene_component_update)

    scene_component_remove = scene_component_sub.add_parser("remove", help="Remove one component by UUID or unique name")
    scene_component_remove.add_argument("scene", help="Scene id or exact name")
    scene_component_remove.add_argument("object", help="Object UUID or unique exact name")
    scene_component_remove.add_argument("component", help="Component UUID or unique exact name")
    scene_component_remove.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_component_remove.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_component_remove.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_component_remove.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_component_remove.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_component_remove.set_defaults(func=cmd_scene_component_remove)

    scene_attach = scene_sub.add_parser("attach", help="Attach an ergonomic camera/model/collision/light/UI adapter")
    scene_attach.add_argument(
        "kind",
        choices=("ui", "camera", "model", "collision", "collision-mesh", "collider", "light", "audio3d", "code"),
        help="Adapter kind",
    )
    scene_attach.add_argument("scene", help="Scene id or exact name")
    scene_attach.add_argument("object", help="Object UUID or unique exact name")
    scene_attach.add_argument("reference", nargs="?", help="Required asset reference for UI/model/collision-mesh")
    scene_attach.add_argument("--uuid", type=parse_cli_int, help="Explicit 64-bit component UUID")
    scene_attach.add_argument("--name", help="Component display name override")
    scene_attach.add_argument("--data", help="JSON object or @file merged over editor-compatible defaults")
    scene_attach.add_argument("--args", dest="script_args", help="Code argument JSON object or @file")
    scene_attach.add_argument("--project", default=".", help="Project directory or project.p64proj path")
    scene_attach.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    scene_attach.add_argument("--json", action="store_true", help="Emit stable JSON")
    scene_attach.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    scene_attach.add_argument("--history-path", help="Override operation history JSONL path for --record")
    scene_attach.set_defaults(func=cmd_scene_attach)

    history = sub.add_parser("history", help="Read local BF64 operation history")
    history_sub = history.add_subparsers(dest="history_command", required=True)
    history_list = history_sub.add_parser("list", help="List recorded operations")
    history_list.add_argument("--limit", type=int, default=20)
    history_list.add_argument("--history-path")
    history_list.add_argument("--json", action="store_true")
    history_list.set_defaults(func=cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args._argv = list(argv if argv is not None else sys.argv[1:])
    args._started_at = time.perf_counter()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI should return deterministic internal error
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "issues": [
                            issue(
                                "error",
                                "INTERNAL",
                                f"{type(exc).__name__}: {exc}",
                                "Report this as a BF64 tooling bug.",
                            )
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(f"INTERNAL ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
