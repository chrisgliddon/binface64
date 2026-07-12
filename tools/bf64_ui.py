"""Shared focus-area and BF64 UI document support for the repository CLI.

The editor consumes the same JSON contracts.  Keep this module dependency-free so
agents and CI can inspect and validate UI documents without the editor binary.
"""

from __future__ import annotations

import json
import re
import zlib
from pathlib import Path
from typing import Any


UI_SCHEMA = "bf64.ui"
UI_VERSION = 1
UI_ELEMENT_TYPES = {"Container", "Image", "Text", "Button", "TextInput", "ProgressBar"}
UI_FOCUS_TYPES = {"Button", "TextInput"}
UI_MAX_ELEMENTS = 256
UI_MAX_TEXT_LENGTH = 256
UI_ID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
UI_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{8}$")


def ui_issue(
    severity: str,
    rule: str,
    message: str,
    fix: str = "",
    source: str = "",
) -> dict[str, str]:
    value = {"severity": severity, "rule": rule, "message": message}
    if fix:
        value["fix"] = fix
    if source:
        value["source"] = source
    return value


def load_focus_catalog(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        catalog = json.load(fh)
    if not isinstance(catalog, dict) or catalog.get("schemaVersion") != 1:
        raise ValueError("unsupported focus-area catalog")
    areas = catalog.get("areas")
    if not isinstance(areas, list):
        raise ValueError("focus-area catalog must contain an areas array")
    return catalog


def default_ui_document(width: int = 320, height: int = 240) -> dict[str, Any]:
    return {
        "schema": UI_SCHEMA,
        "version": UI_VERSION,
        "canvas": {
            "width": width,
            "height": height,
            "safeArea": [8, 8, 8, 8],
            "snap": 1,
        },
        "root": {
            "id": "root",
            "type": "Container",
            "layout": {
                "anchors": [0.0, 0.0, 1.0, 1.0],
                "offsets": [0, 0, 0, 0],
            },
            "visible": True,
            "enabled": True,
            "style": {"color": "#00000000"},
            "children": [],
        },
    }


def element_hash(element_id: str) -> int:
    return zlib.crc32(element_id.encode("utf-8")) & 0xFFFFFFFF


def find_project_root(path: Path) -> Path | None:
    current = path.resolve(strict=False)
    if current.is_file() or current.suffix:
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "project.p64proj").is_file():
            return candidate
    return None


def _classify_reference(path: Path) -> str:
    lower = path.name.lower()
    if lower.endswith(".png"):
        return "texture"
    if lower.endswith(".ttf") or lower.endswith(".otf"):
        return "font"
    return "unknown"


def _asset_index(project_root: Path | None) -> tuple[dict[int, Path], dict[str, set[Path]]]:
    by_uuid: dict[int, Path] = {}
    by_path: dict[str, set[Path]] = {}
    if project_root is None:
        return by_uuid, by_path
    assets_root = project_root / "assets"
    if not assets_root.is_dir():
        return by_uuid, by_path
    for path in assets_root.rglob("*"):
        if not path.is_file() or path.name.endswith(".conf"):
            continue
        rel_asset = path.relative_to(assets_root).as_posix()
        rel_project = path.relative_to(project_root).as_posix()
        for key in {rel_asset, rel_project, path.name}:
            by_path.setdefault(key, set()).add(path)
        conf_path = Path(str(path) + ".conf")
        if not conf_path.is_file():
            continue
        try:
            conf = json.loads(conf_path.read_text(encoding="utf-8"))
            uuid = int(conf.get("uuid", 0))
            if uuid:
                by_uuid[uuid] = path
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return by_uuid, by_path


def _resolve_asset_reference(
    reference: Any,
    expected_kind: str,
    by_uuid: dict[int, Path],
    by_path: dict[str, set[Path]],
) -> tuple[Path | None, dict[str, str] | None]:
    path: Path | None = None
    if isinstance(reference, int) and not isinstance(reference, bool):
        path = by_uuid.get(reference)
    elif isinstance(reference, str) and reference:
        normalized = reference.replace("\\", "/")
        matches = by_path.get(normalized, set())
        if len(matches) == 1:
            path = next(iter(matches))
        elif len(matches) > 1:
            return None, ui_issue(
                "error",
                "UI_ASSET",
                f"Asset reference '{reference}' is ambiguous.",
                "Use an assets/<path> reference or the asset UUID.",
            )
    if path is None:
        return None, ui_issue(
            "error",
            "UI_ASSET",
            f"Could not resolve {expected_kind} asset reference {reference!r}.",
            "Import the asset and use its UUID or project-relative assets/<path>.",
        )
    actual_kind = _classify_reference(path)
    if actual_kind != expected_kind:
        return None, ui_issue(
            "error",
            "UI_ASSET_TYPE",
            f"Expected a {expected_kind} asset, but {path.name} is {actual_kind}.",
        )
    return path, None


def _number_list(value: Any, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    )


def validate_ui_document(
    path: Path,
    project_root: Path | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    metadata: dict[str, Any] = {
        "schema": None,
        "version": None,
        "element_count": 0,
        "focusable_count": 0,
        "progress_bar_count": 0,
        "project": str(project_root) if project_root else None,
        "element_hashes": {},
    }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - returned as structured validation
        return {
            "ok": False,
            "path": str(path),
            "kind": "ui",
            "metadata": metadata,
            "issues": [ui_issue("error", "UI_JSON", f"Could not parse UI document: {exc}")],
        }

    if not isinstance(doc, dict):
        issues.append(ui_issue("error", "UI_SCHEMA", "UI document must be a JSON object."))
        doc = {}
    metadata["schema"] = doc.get("schema")
    metadata["version"] = doc.get("version")
    if doc.get("schema") != UI_SCHEMA:
        issues.append(ui_issue("error", "UI_SCHEMA", f"schema must be '{UI_SCHEMA}'."))
    if doc.get("version") != UI_VERSION:
        issues.append(
            ui_issue(
                "error",
                "UI_VERSION",
                f"Only UI document version {UI_VERSION} is supported; got {doc.get('version')!r}.",
            )
        )

    canvas = doc.get("canvas")
    if not isinstance(canvas, dict):
        issues.append(ui_issue("error", "UI_CANVAS", "canvas must be an object."))
        canvas = {}
    width = canvas.get("width")
    height = canvas.get("height")
    if not isinstance(width, int) or isinstance(width, bool) or width < 1 or width > 640:
        issues.append(ui_issue("error", "UI_CANVAS", "canvas.width must be an integer from 1 to 640."))
        width = 320
    if not isinstance(height, int) or isinstance(height, bool) or height < 1 or height > 576:
        issues.append(ui_issue("error", "UI_CANVAS", "canvas.height must be an integer from 1 to 576."))
        height = 240
    safe_area = canvas.get("safeArea", [0, 0, 0, 0])
    if (
        not _number_list(safe_area, 4)
        or any(not isinstance(value, int) or value < 0 for value in safe_area)
    ):
        issues.append(ui_issue("error", "UI_SAFE_AREA", "canvas.safeArea must contain four non-negative integers."))
    snap = canvas.get("snap", 1)
    if not isinstance(snap, int) or isinstance(snap, bool) or snap < 1 or snap > 64:
        issues.append(ui_issue("error", "UI_SNAP", "canvas.snap must be an integer from 1 to 64."))

    project_root = project_root or find_project_root(path)
    metadata["project"] = str(project_root) if project_root else None
    by_uuid, by_path = _asset_index(project_root)
    ids: dict[str, str] = {}
    id_types: dict[str, str] = {}
    hashes: dict[int, str] = {}
    focus_refs: list[tuple[str, str, str]] = []
    literal_font_checks: list[tuple[str, str, Path]] = []
    referenced_fonts: set[Path] = set()
    element_count = 0

    def visit(element: Any, location: str, parent_rect: tuple[float, float, float, float]) -> None:
        nonlocal element_count
        element_count += 1
        if not isinstance(element, dict):
            issues.append(ui_issue("error", "UI_ELEMENT", f"{location} must be an object."))
            return
        element_id = element.get("id")
        element_type = element.get("type")
        if not isinstance(element_id, str) or not UI_ID_PATTERN.fullmatch(element_id):
            issues.append(
                ui_issue(
                    "error",
                    "UI_ID",
                    f"{location}.id must match {UI_ID_PATTERN.pattern}.",
                )
            )
            element_id = f"invalid:{location}"
        elif element_id in ids:
            issues.append(ui_issue("error", "UI_ID_DUPLICATE", f"Duplicate element id '{element_id}'."))
        else:
            ids[element_id] = location
            id_types[element_id] = element_type
            hashed = element_hash(element_id)
            if hashed in hashes and hashes[hashed] != element_id:
                issues.append(
                    ui_issue(
                        "error",
                        "UI_ID_COLLISION",
                        f"Element ids '{hashes[hashed]}' and '{element_id}' share runtime hash 0x{hashed:08X}.",
                        "Rename one element.",
                    )
                )
            hashes[hashed] = element_id

        if element_type not in UI_ELEMENT_TYPES:
            issues.append(
                ui_issue(
                    "error",
                    "UI_ELEMENT_TYPE",
                    f"{location}.type must be one of {sorted(UI_ELEMENT_TYPES)}.",
                )
            )

        layout = element.get("layout")
        if not isinstance(layout, dict):
            issues.append(ui_issue("error", "UI_LAYOUT", f"{location}.layout must be an object."))
            layout = {}
        anchors = layout.get("anchors")
        offsets = layout.get("offsets")
        if not _number_list(anchors, 4):
            issues.append(ui_issue("error", "UI_ANCHORS", f"{location}.layout.anchors must contain four numbers."))
            anchors = [0, 0, 0, 0]
        elif any(value < 0 or value > 1 for value in anchors) or anchors[0] > anchors[2] or anchors[1] > anchors[3]:
            issues.append(ui_issue("error", "UI_ANCHORS", f"{location} anchors must be ordered values in 0..1."))
        if not _number_list(offsets, 4):
            issues.append(ui_issue("error", "UI_OFFSETS", f"{location}.layout.offsets must contain four numbers."))
            offsets = [0, 0, 0, 0]
        elif any(
            (not isinstance(value, int) and not value.is_integer()) or value < -32768 or value > 32767
            for value in offsets
        ):
            issues.append(
                ui_issue(
                    "error",
                    "UI_OFFSETS",
                    f"{location}.layout.offsets must be integers in the signed 16-bit range.",
                )
            )

        px0, py0, px1, py1 = parent_rect
        parent_w, parent_h = px1 - px0, py1 - py0
        rect = (
            px0 + parent_w * float(anchors[0]) + float(offsets[0]),
            py0 + parent_h * float(anchors[1]) + float(offsets[1]),
            px0 + parent_w * float(anchors[2]) + float(offsets[2]),
            py0 + parent_h * float(anchors[3]) + float(offsets[3]),
        )
        if rect[2] < rect[0] or rect[3] < rect[1]:
            issues.append(ui_issue("error", "UI_RECT", f"{location} resolves to a negative-size rectangle."))
        elif location != "root" and (rect[2] <= 0 or rect[3] <= 0 or rect[0] >= width or rect[1] >= height):
            issues.append(ui_issue("warning", "UI_CLIPPED", f"Element '{element_id}' is fully outside the canvas."))

        visible = element.get("visible", True)
        enabled = element.get("enabled", True)
        if not isinstance(visible, bool) or not isinstance(enabled, bool):
            issues.append(ui_issue("error", "UI_STATE", f"{location} visible/enabled values must be booleans."))

        style = element.get("style", {})
        if not isinstance(style, dict):
            issues.append(ui_issue("error", "UI_STYLE", f"{location}.style must be an object."))
            style = {}
        for color_key in ("color", "textColor", "focusColor", "fillColor"):
            color = style.get(color_key)
            if color is not None and (not isinstance(color, str) or not UI_COLOR_PATTERN.fullmatch(color)):
                issues.append(ui_issue("error", "UI_COLOR", f"{location}.style.{color_key} must be #RRGGBBAA."))

        if element_type == "Image":
            _, asset_issue = _resolve_asset_reference(element.get("asset"), "texture", by_uuid, by_path)
            if asset_issue:
                issues.append(asset_issue)
            if element.get("fit", "stretch") not in {"stretch", "native"}:
                issues.append(ui_issue("error", "UI_IMAGE_FIT", f"{location}.fit must be stretch or native."))

        if element_type in {"Text", "Button", "TextInput"}:
            font_path, asset_issue = _resolve_asset_reference(element.get("font"), "font", by_uuid, by_path)
            if asset_issue:
                issues.append(asset_issue)
            literal = element.get("text", "")
            if element_type == "TextInput":
                literal = str(element.get("placeholder", "")) + str(element.get("value", ""))
            if not isinstance(literal, str):
                issues.append(ui_issue("error", "UI_TEXT", f"{location} text values must be strings."))
            elif font_path:
                literal_font_checks.append((element_id, literal, font_path))
                referenced_fonts.add(font_path)
            if element.get("align", "left") not in {"left", "center", "right"}:
                issues.append(ui_issue("error", "UI_TEXT_ALIGN", f"{location}.align must be left, center, or right."))

        if element_type == "TextInput":
            max_length = element.get("maxLength", 32)
            charset = element.get("charset", "")
            if not isinstance(max_length, int) or isinstance(max_length, bool) or not 1 <= max_length <= UI_MAX_TEXT_LENGTH:
                issues.append(
                    ui_issue(
                        "error",
                        "UI_INPUT_LENGTH",
                        f"{location}.maxLength must be from 1 to {UI_MAX_TEXT_LENGTH}.",
                    )
                )
            value = element.get("value", "")
            placeholder = element.get("placeholder", "")
            if not isinstance(value, str) or not isinstance(placeholder, str):
                issues.append(ui_issue("error", "UI_TEXT", f"{location} value and placeholder must be strings."))
            elif isinstance(max_length, int) and len(value) > max_length:
                issues.append(ui_issue("error", "UI_INPUT_LENGTH", f"{location}.value exceeds maxLength {max_length}."))
            if not isinstance(charset, str) or not charset:
                issues.append(ui_issue("error", "UI_INPUT_CHARSET", f"{location}.charset must be a non-empty string."))
            elif len(set(charset)) != len(charset):
                issues.append(ui_issue("warning", "UI_INPUT_CHARSET", f"{location}.charset contains duplicate characters."))
            elif font_path:
                literal_font_checks.append((element_id, charset, font_path))
            if not isinstance(element.get("submitOnStart", True), bool):
                issues.append(ui_issue("error", "UI_INPUT_SUBMIT", f"{location}.submitOnStart must be a boolean."))

        if element_type == "ProgressBar":
            metadata["progress_bar_count"] += 1
            maximum = element.get("max", 100)
            value = element.get("value", maximum)
            if (
                not isinstance(maximum, int)
                or isinstance(maximum, bool)
                or maximum < 1
                or maximum > 0xFFFF
            ):
                issues.append(
                    ui_issue(
                        "error",
                        "UI_PROGRESS_VALUE",
                        f"{location}.max must be an integer from 1 to 65535.",
                    )
                )
                maximum = 100
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                or value > maximum
            ):
                issues.append(
                    ui_issue(
                        "error",
                        "UI_PROGRESS_VALUE",
                        f"{location}.value must be an integer from 0 through max ({maximum}).",
                    )
                )

            thresholds = element.get("thresholds", [])
            if not isinstance(thresholds, list) or len(thresholds) > 3:
                issues.append(
                    ui_issue(
                        "error",
                        "UI_PROGRESS_THRESHOLDS",
                        f"{location}.thresholds must be an array with at most three entries.",
                    )
                )
            else:
                previous_max = -1
                for threshold_index, threshold in enumerate(thresholds):
                    threshold_location = f"{location}.thresholds[{threshold_index}]"
                    if not isinstance(threshold, dict):
                        issues.append(ui_issue("error", "UI_PROGRESS_THRESHOLDS", f"{threshold_location} must be an object."))
                        continue
                    threshold_max = threshold.get("max")
                    threshold_color = threshold.get("color")
                    if (
                        not isinstance(threshold_max, int)
                        or isinstance(threshold_max, bool)
                        or threshold_max < 0
                        or threshold_max > maximum
                        or threshold_max <= previous_max
                    ):
                        issues.append(
                            ui_issue(
                                "error",
                                "UI_PROGRESS_THRESHOLDS",
                                f"{threshold_location}.max must be strictly ascending in 0..{maximum}.",
                            )
                        )
                    else:
                        previous_max = threshold_max
                    if not isinstance(threshold_color, str) or not UI_COLOR_PATTERN.fullmatch(threshold_color):
                        issues.append(
                            ui_issue(
                                "error",
                                "UI_PROGRESS_THRESHOLDS",
                                f"{threshold_location}.color must be #RRGGBBAA.",
                            )
                        )

        if element_type in UI_FOCUS_TYPES:
            metadata["focusable_count"] += 1
            focus = element.get("focus", {})
            if not isinstance(focus, dict):
                issues.append(ui_issue("error", "UI_FOCUS", f"{location}.focus must be an object."))
            else:
                for direction in ("up", "down", "left", "right"):
                    target = focus.get(direction)
                    if target is not None:
                        if not isinstance(target, str):
                            issues.append(ui_issue("error", "UI_FOCUS", f"{location}.focus.{direction} must be an element id."))
                        else:
                            focus_refs.append((element_id, direction, target))

        children = element.get("children", [])
        if not isinstance(children, list):
            issues.append(ui_issue("error", "UI_CHILDREN", f"{location}.children must be an array."))
            return
        for index, child in enumerate(children):
            visit(child, f"{location}.children[{index}]", rect)

    root = doc.get("root")
    visit(root, "root", (0.0, 0.0, float(width), float(height)))
    metadata["element_count"] = element_count
    metadata["element_hashes"] = {key: f"0x{element_hash(key):08X}" for key in sorted(ids)}
    if element_count > UI_MAX_ELEMENTS:
        issues.append(
            ui_issue(
                "error",
                "UI_ELEMENT_LIMIT",
                f"Document has {element_count} elements; runtime maximum is {UI_MAX_ELEMENTS}.",
            )
        )

    for source_id, direction, target in focus_refs:
        if target not in ids:
            issues.append(
                ui_issue(
                    "error",
                    "UI_FOCUS_TARGET",
                    f"Element '{source_id}' focus.{direction} references missing element '{target}'.",
                )
            )
        elif id_types.get(target) not in UI_FOCUS_TYPES:
            issues.append(
                ui_issue(
                    "error",
                    "UI_FOCUS_TARGET",
                    f"Element '{source_id}' focus.{direction} targets non-focusable element '{target}'.",
                    "Target a Button or TextInput element.",
                )
            )

    font_cache: dict[Path, str | None] = {}
    for font_path in sorted(referenced_fonts):
        try:
            font_conf = json.loads(Path(str(font_path) + ".conf").read_text(encoding="utf-8"))
            font_id = font_conf.get("fontId", 0)
            if isinstance(font_id, dict):
                font_id = font_id.get("value", 0)
            font_id = int(font_id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            font_id = 0
        if not 1 <= font_id <= 15:
            issues.append(
                ui_issue(
                    "error",
                    "UI_FONT_ID",
                    f"UI font {font_path.name} must use an auto-load fontId from 1 to 15; got {font_id}.",
                    "Set the font asset ID in the editor Asset inspector or its .conf sidecar.",
                )
            )
    for element_id, literal, font_path in literal_font_checks:
        if font_path not in font_cache:
            charset: str | None = None
            try:
                conf = json.loads(Path(str(font_path) + ".conf").read_text(encoding="utf-8"))
                value = conf.get("fontCharset")
                if isinstance(value, dict):
                    value = value.get("value")
                if isinstance(value, str):
                    charset = value
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
            font_cache[font_path] = charset
        charset = font_cache[font_path]
        if charset:
            missing = sorted({char for char in literal if char not in charset and char not in "\r\n\t"})
            if missing:
                issues.append(
                    ui_issue(
                        "error",
                        "UI_FONT_CHARSET",
                        f"Element '{element_id}' uses characters absent from {font_path.name}: {''.join(missing)!r}.",
                        "Add the characters to the font asset charset or change the UI text/input charset.",
                    )
                )

    return {
        "ok": not any(item["severity"] == "error" for item in issues),
        "path": str(path),
        "kind": "ui",
        "metadata": metadata,
        "issues": issues,
    }
