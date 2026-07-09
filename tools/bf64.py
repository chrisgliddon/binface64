#!/usr/bin/env python3
"""Agent-first BF64 utility surface.

This is a lightweight, no-dependency bridge for agents before the formal BF64
CLI/MCP phases land. It exposes machine-readable N64 constraints and a focused
asset validator backed by docs/docs/n64/limits.json.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
LIMITS_PATH = REPO_ROOT / "docs" / "docs" / "n64" / "limits.json"
DEFAULT_HISTORY_PATH = REPO_ROOT / ".bf64" / "operations.jsonl"


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
        if args.record:
            record_operation("validate", path, result)
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
                    "Use --kind texture|model|audio|font, or validate a supported asset extension.",
                )
            ],
        }

    output_result(result, args.json)
    if args.record:
        record_operation("validate", path, result)
    return 1 if has_errors(result.get("issues", [])) else 0


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


def record_operation(command: str, path: Path | None, result: dict[str, Any], history_path: Path = DEFAULT_HISTORY_PATH) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.time(),
        "command": command,
        "path": str(path) if path else None,
        "ok": result.get("ok", False),
        "kind": result.get("kind"),
        "issue_count": len(result.get("issues", [])),
        "issues": result.get("issues", []),
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
    sub = parser.add_subparsers(dest="command", required=True)

    constraints = sub.add_parser("constraints", help="Query machine-readable N64/BF64 limits")
    constraints.add_argument("topic", nargs="?", default="list", help="list, texture, model, audio, scene, rom, or exit_codes")
    constraints.add_argument("--json", action="store_true", help="Emit stable JSON")
    constraints.set_defaults(func=cmd_constraints)

    validate = sub.add_parser("validate", help="Validate one asset against BF64/N64 constraints")
    validate.add_argument("path", help="Asset path")
    validate.add_argument("--kind", choices=["texture", "model", "audio", "font"], help="Override asset kind")
    validate.add_argument("--conf", help="Explicit .conf sidecar path")
    validate.add_argument("--json", action="store_true", help="Emit stable JSON")
    validate.add_argument("--record", action="store_true", help="Append result to .bf64/operations.jsonl")
    validate.add_argument("--texture-format", help="Texture format name or id for strict texture validation")
    validate.add_argument("--scene-pipeline", help="default, hdr, bigtex, or 0/1/2")
    validate.add_argument("--role", choices=["sfx", "music", "voice", "unknown"], default="unknown", help="Audio role hint")
    validate.set_defaults(func=validate_asset)

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
