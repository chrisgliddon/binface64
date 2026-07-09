#!/usr/bin/env python3
"""Agent-first BF64 utility surface.

This is a lightweight, no-dependency bridge for agents before the formal BF64
CLI/MCP phases land. It exposes machine-readable N64 constraints and a focused
asset validator backed by docs/docs/n64/limits.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
LIMITS_PATH = REPO_ROOT / "docs" / "docs" / "n64" / "limits.json"
DEFAULT_HISTORY_PATH = REPO_ROOT / ".bf64" / "operations.jsonl"
PROJECT_FILENAME = "project.p64proj"
EMPTY_PROJECT_TEMPLATE = REPO_ROOT / "n64" / "examples" / "empty"
MAX_COMPONENT_ID = 12
CLI_VERSION = "0.9.0"
HISTORY_SCHEMA_VERSION = 2
VALIDATABLE_ASSET_KINDS = {"texture", "model", "audio", "font"}
IMPORTABLE_ASSET_KINDS = {"texture", "model", "audio", "font"}
PROJECT_ASSET_KINDS = ("texture", "model", "audio", "font", "prefab", "node_graph", "unknown")
PYRITE_BINARY_NAMES = ("pyrite64", "pyrite64.exe")
BUILD_TOOLCHAIN_FILES = (
    ("n64.mk", "include/n64.mk"),
    ("t3d.mk", "include/t3d.mk"),
    ("mkasset", "bin/mkasset"),
    ("mksprite", "bin/mksprite"),
    ("audioconv64", "bin/audioconv64"),
    ("mkfont", "bin/mkfont"),
    ("mkdfs", "bin/mkdfs"),
    ("n64tool", "bin/n64tool"),
)


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
    }


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


def collect_object_stats(graph: Any) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
    issues: list[dict[str, str]] = []
    tree: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        "object_count": 0,
        "component_count": 0,
        "max_depth": 0,
        "component_ids": {},
        "duplicate_object_uuids": [],
    }
    seen_uuids: set[int] = set()

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
        for comp in components:
            stats["component_count"] += 1
            if not isinstance(comp, dict):
                issues.append(issue("error", "SCENE", f"{path} object '{name}' has a non-object component."))
                continue
            comp_id = comp.get("id")
            if not isinstance(comp_id, int) or comp_id < 0 or comp_id > MAX_COMPONENT_ID:
                issues.append(
                    issue(
                        "error",
                        "SCENE",
                        f"{path} object '{name}' has invalid component id {comp_id}.",
                        f"Use a component id in the editor/runtime registry range 0..{MAX_COMPONENT_ID}.",
                        "docs/docs/agent/CODEMAP.md#component-system",
                    )
                )
            else:
                key = str(comp_id)
                stats["component_ids"][key] = int(stats["component_ids"].get(key, 0)) + 1

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

    stats, graph_issues, tree = collect_object_stats(graph)
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
            issues.append(issue("warning", "A10", f"Could not inspect WAV metadata: {exc}"))
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
    elif kind == "font" and ext == ".ttf":
        new_ext = ".font64"
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


def asset_entry(project_root: Path, path: Path) -> dict[str, Any]:
    kind = classify_asset(path)
    conf, conf_path = load_conf(path, None)
    parse_issue = conf_parse_issue(conf, conf_path)
    conf_exists = conf_path is not None
    conf_ok = parse_issue is None
    safe_conf = conf if conf_ok else {}
    try:
        size_bytes = path.stat().st_size
    except OSError:
        size_bytes = 0

    entry: dict[str, Any] = {
        "path": str(path),
        "relative_path": path_relative_to(path, project_root),
        "asset_path": path_relative_to(path, project_root / "assets"),
        "name": path.name,
        "extension": path.suffix.lower() or "(none)",
        "kind": kind,
        "validatable": kind in VALIDATABLE_ASSET_KINDS,
        "size_bytes": size_bytes,
        "conf_path": conf_path or str(asset_conf_path(path)),
        "conf_exists": conf_exists,
        "conf_ok": conf_ok,
        "issues": [parse_issue] if parse_issue else [],
    }
    for key in (
        "uuid",
        "format",
        "baseScale",
        "compression",
        "gltfBVH",
        "exclude",
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
        entry = asset_entry(project_root, path)
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
    }


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    changes: list[dict[str, str]],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for source in sorted(source_root.rglob("*"), key=lambda item: str(item.relative_to(source_root))):
        relative = source.relative_to(source_root)
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


def ensure_bootstrap_files(project_root: Path, force: bool, changes: list[dict[str, str]]) -> list[dict[str, str]]:
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
        existed = dest.exists()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        add_change(changes, action="overwritten" if existed else "created", kind="file", path=dest, source=source)
    return issues


def new_project_next_actions(result: dict[str, Any]) -> list[str]:
    if has_errors(result.get("issues", [])):
        return ["Fix the reported scaffold issue, then rerun `bf64 new`."]
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
        if change.get("action") == "removed":
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
    if project_root.exists() and project_root.is_dir() and directory_has_entries(project_root) and not args.force:
        issues.append(
            issue(
                "error",
                "NEW_EXISTS",
                f"Target directory is not empty: {project_root}.",
                "Choose an empty directory or pass --force to overwrite scaffold files.",
            )
        )

    result: dict[str, Any] = {
        "ok": False,
        "command": "new",
        "kind": "project_new",
        "path": str(project_root),
        "template": str(EMPTY_PROJECT_TEMPLATE),
        "force": bool(args.force),
        "project": {
            "path": str(project_root),
            "config_path": str(config_path),
            "name": name,
            "romName": rom_name,
            "sceneIdOnBoot": 1,
            "sceneIdOnReset": 1,
            "sceneIdLastOpened": 1,
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
        issues.extend(copy_template_project(EMPTY_PROJECT_TEMPLATE, project_root, force=args.force, changes=changes))
        remove_known_generated_outputs(project_root, rom_name, changes)
        issues.extend(ensure_bootstrap_files(project_root, args.force, changes))

        config = new_project_config(name, rom_name, emulator, n64_inst)
        config_existed = config_path.exists()
        write_json_file(config_path, config)
        add_change(changes, action="overwritten" if config_existed else "created", kind="file", path=config_path)
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
        print(f"Changes: created={created} overwritten={overwritten} removed={removed}")
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


def build_toolchain_status(config: dict[str, Any], strict: bool = False) -> dict[str, Any]:
    project_n64_inst = str(config.get("pathN64Inst") or "")
    env_n64_inst = os.environ.get("N64_INST", "")
    effective_n64_inst = project_n64_inst or env_n64_inst
    severity = "error" if strict else "warning"
    checks: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []

    def add_check(name: str, ok: bool, detail: str, fix: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            issues.append(issue(severity, "BUILD_TOOLCHAIN", detail, fix))

    make_path = shutil.which("make")
    add_check("make", make_path is not None, make_path or "make not found on PATH", "Install make or add it to PATH.")

    if effective_n64_inst:
        n64_inst_path = Path(effective_n64_inst)
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
    assets = inventory.pop("assets", [])
    validate_args = argparse.Namespace(texture_format=None, scene_pipeline=None, role="unknown")
    asset_results = [validate_project_asset_entry(entry, limits, validate_args) for entry in assets]
    asset_summary = summarize_asset_validation(asset_results)
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


def tail_text(text: str, max_lines: int = 200, max_chars: int = 20000) -> str:
    if not text:
        return ""
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
    started_at = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
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


def execute_run(args: argparse.Namespace) -> dict[str, Any]:
    build_result: dict[str, Any] | None = None
    if args.build:
        build_args = argparse.Namespace(
            project=args.project,
            pyrite64_binary=args.pyrite64_binary,
            timeout=args.build_timeout,
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
        "issues": [],
        "artifacts": [],
    }

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

    argv = [*(emulator_argv or []), str(rom_path)]
    result["run"]["emulator"] = emulator_spec
    result["run"]["argv"] = argv
    started_at = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
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
    if kind not in VALIDATABLE_ASSET_KINDS:
        return {
            "ok": True,
            "path": str(path),
            "kind": kind,
            "metadata": {
                "conf": conf_path,
                "skipped": True,
                "skip_reason": "No read-only validator exists for this project asset kind yet.",
            },
            "issues": [],
        }

    validate_args = validator_args_from_asset_command(args)
    if kind == "texture":
        return validate_texture(path, conf, conf_path, validate_args, limits)
    if kind == "model":
        return validate_model(path, conf, conf_path, validate_args, limits)
    if kind == "audio":
        return validate_audio(path, conf, conf_path, validate_args, limits)
    if kind == "font":
        return validate_font(path, conf_path)
    raise AssertionError(f"unhandled asset kind: {kind}")


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
    return {
        "selected_assets": len(results),
        "validated": len(results) - skipped,
        "skipped": skipped,
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
            f"Assets: validated={summary.get('validated', 0)} skipped={summary.get('skipped', 0)} "
            f"failed={summary.get('failed', 0)} issues={summary.get('issues', {})}"
        )
    for item in result.get("results", []):
        metadata = item.get("metadata", {})
        skipped = isinstance(metadata, dict) and metadata.get("skipped")
        status = "SKIP" if skipped else ("OK" if item.get("ok") else "FAILED")
        print(f"{status} {item.get('kind')} {path_relative_to(Path(item.get('path', '')), Path(result['project']['path']))}")
        for issue_item in item.get("issues", []):
            print(f"  {issue_item.get('severity', 'info').upper()} {issue_item.get('rule')}: {issue_item.get('message')}")


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
    results = [validate_project_asset_entry(entry, limits, args) for entry in assets]
    validation_issues = flatten_asset_issues(results, project_root)
    issues.extend(validation_issues)
    summary = summarize_asset_validation(results)
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
                    "Use --kind texture|model|audio|font|project|scene, or validate a supported asset extension.",
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


def build_doctor_result(strict: bool = False) -> dict[str, Any]:
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

    n64_inst = os.environ.get("N64_INST", "")
    add_check(
        "N64_INST",
        bool(n64_inst),
        n64_inst or "N64_INST is not set",
        "warning",
        "Set N64_INST to the libdragon toolchain install path before building ROMs.",
    )
    for tool in ("mksprite", "audioconv64", "n64tool"):
        path = shutil.which(tool)
        add_check(
            tool,
            path is not None,
            path or f"{tool} not found on PATH",
            "warning",
            f"Install/build the libdragon toolchain so {tool} is on PATH.",
        )

    emulators = {name: shutil.which(name) for name in ("ares", "gopher64")}
    add_check(
        "emulator",
        any(emulators.values()),
        ", ".join(f"{name}={path or 'missing'}" for name, path in emulators.items()),
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
        "checks": checks,
        "issues": issues,
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    result = build_doctor_result(args.strict)
    exit_code = 2 if has_errors(result.get("issues", [])) else 0
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        output_result(result, False)
        for check in result.get("checks", []):
            status = "OK" if check["ok"] else "MISSING"
            print(f"{status} {check['name']}: {check['detail']}")
    record_if_requested(args, result, exit_code)
    return exit_code

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
    for attr in ("project_command", "asset_command", "scene_command", "history_command"):
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bf64", description="Agent-first BF64 utility surface")
    parser.add_argument("--version", action="version", version=f"%(prog)s {CLI_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check local BF64 agent/tooling environment")
    doctor.add_argument("--strict", action="store_true", help="Treat missing optional build/run tools as errors")
    doctor.add_argument("--json", action="store_true", help="Emit stable JSON")
    doctor.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    doctor.add_argument("--history-path", help="Override operation history JSONL path for --record")
    doctor.set_defaults(func=cmd_doctor)

    constraints = sub.add_parser("constraints", help="Query machine-readable N64/BF64 limits")
    constraints.add_argument("topic", nargs="?", default="list", help="list, texture, model, audio, scene, rom, or exit_codes")
    constraints.add_argument("--json", action="store_true", help="Emit stable JSON")
    constraints.set_defaults(func=cmd_constraints)

    validate = sub.add_parser("validate", help="Validate one asset, project, or scene against BF64/N64 constraints")
    validate.add_argument("path", help="Asset path, project.p64proj, or scene.json")
    validate.add_argument("--kind", choices=["texture", "model", "audio", "font", "project", "scene"], help="Override input kind")
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
    new.add_argument("--force", action="store_true", help="Overwrite scaffold files in an existing directory")
    new.add_argument("--json", action="store_true", help="Emit stable JSON")
    new.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    new.add_argument("--history-path", help="Override operation history JSONL path for --record")
    new.set_defaults(func=cmd_new)

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
    asset_validate_all.add_argument("--json", action="store_true", help="Emit stable JSON")
    asset_validate_all.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    asset_validate_all.add_argument("--history-path", help="Override operation history JSONL path for --record")
    asset_validate_all.add_argument("--scene-pipeline", help="default, hdr, bigtex, or 0/1/2")
    asset_validate_all.add_argument("--role", choices=["sfx", "music", "voice", "unknown"], default="unknown", help="Audio role hint")
    asset_validate_all.set_defaults(func=cmd_asset_validate_all)

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
