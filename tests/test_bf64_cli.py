import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bf64"


class Bf64CliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_json(self, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        proc = self.run_cli(*args)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"stdout was not JSON: {exc}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        return proc, data

    def write_png_header(self, path: Path, width: int, height: int) -> None:
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I4s", 13, b"IHDR") + ihdr)

    def write_minimal_project(self, project: Path, extra_config: dict | None = None) -> None:
        (project / "data" / "scenes" / "1").mkdir(parents=True)
        config = {
            "name": "Fixture",
            "romName": "fixture",
            "sceneIdOnBoot": 1,
            "sceneIdOnReset": 1,
            "sceneIdLastOpened": 1,
        }
        if extra_config:
            config.update(extra_config)
        (project / "project.p64proj").write_text(json.dumps(config), encoding="utf-8")
        scene = {"conf": {"name": "Scene", "renderPipeline": 0}, "graph": {"children": []}}
        (project / "data" / "scenes" / "1" / "scene.json").write_text(json.dumps(scene), encoding="utf-8")

    def write_included_and_excluded_textures(self, project: Path) -> tuple[Path, Path]:
        assets = project / "assets"
        assets.mkdir()
        included = assets / "included.png"
        self.write_png_header(included, 32, 32)
        Path(str(included) + ".conf").write_text(
            json.dumps({"uuid": 1, "format": 2}), encoding="utf-8"
        )
        excluded = assets / "invalid.bci.png"
        self.write_png_header(excluded, 128, 128)
        Path(str(excluded) + ".conf").write_text(
            json.dumps({"uuid": 2, "format": 2, "exclude": True}), encoding="utf-8"
        )
        return included, excluded

    def write_fake_sdk(self, sdk: Path) -> None:
        for rel in (
            "include/n64.mk",
            "include/t3d.mk",
            "bin/mips64-elf-gcc",
            "bin/mkasset",
            "bin/mksprite",
            "bin/audioconv64",
            "bin/mkfont",
            "bin/mkdfs",
            "bin/n64tool",
        ):
            path = sdk / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def write_fake_pyrite64(self, binary: Path, log_path: Path, returncode: int = 0) -> None:
        binary.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"Path({json.dumps(str(log_path))}).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            "print('fake build ok')\n"
            f"raise SystemExit({returncode})\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)

    def write_fake_emulator(self, binary: Path, log_path: Path, returncode: int = 0) -> None:
        binary.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"Path({json.dumps(str(log_path))}).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            "print('fake emulator ok')\n"
            f"raise SystemExit({returncode})\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)

    def write_fake_profile_emulator(self, binary: Path, log_path: Path) -> dict:
        runtime_profile = {
            "schema": "bf64.runtime-profile",
            "version": 1,
            "target": {"platform": "n64", "rdram_total_bytes": 8388608},
            "sampling": {"warmup_frames": 30, "sample_frames": 120},
            "frame_time_ms": {"average": 16.67, "worst": 20.0, "p50": 16.6, "p95": 18.0, "p99": 19.5},
            "fps": {"average": 59.9, "worst": 50.0, "p1": 51.2, "p5": 55.5, "p50": 60.2},
            "render": {
                "triangles": {"total": 12000, "average": 100.0, "peak": 120},
                "draw_calls": {"total": 240, "average": 2.0, "peak": 3},
                "material_changes": {"total": 120, "average": 1.0, "peak": 2},
            },
            "memory": {"peak_rdram_used_bytes": 2097152, "peak_heap_used_bytes": 524288},
            "audio": {"average_voice_count": 1.5, "peak_voice_count": 3},
        }
        binary.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import sys\n"
            "import time\n"
            "from pathlib import Path\n"
            "if '--version' in sys.argv:\n"
            "    print('fake-emu 1.2.3')\n"
            "    raise SystemExit(0)\n"
            f"Path({json.dumps(str(log_path))}).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            f"print('BF64_PROFILE_JSON:' + json.dumps({runtime_profile!r}, separators=(',', ':')), flush=True)\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return runtime_profile

    def write_fake_profile_pyrite64(self, binary: Path, log_path: Path) -> None:
        binary.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"Path({json.dumps(str(log_path))}).write_text(json.dumps({{\n"
            "    'argv': sys.argv[1:],\n"
            "    'profile': os.environ.get('BF64_PROFILE'),\n"
            "    'warmup': os.environ.get('BF64_PROFILE_WARMUP'),\n"
            "    'frames': os.environ.get('BF64_PROFILE_FRAMES'),\n"
            "}), encoding='utf-8')\n"
            "print('fake profile build ok')\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)

    def test_constraints_list_json(self) -> None:
        proc, data = self.run_json("constraints", "list", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertIn("texture", data["topics"])
        self.assertIn("scene", data["topics"])

    def test_focus_catalog_lists_all_dedicated_areas_as_available(self) -> None:
        proc, data = self.run_json("focus", "list", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        areas = {area["id"]: area for area in data["areas"]}
        self.assertEqual(areas["ui"]["status"], "available")
        self.assertEqual(areas["music"]["status"], "available")
        self.assertEqual(areas["sfx"]["cliNamespace"], "sfx")
        self.assertEqual(areas["environment"]["status"], "available")
        self.assertEqual(areas["avatar"]["status"], "available")
        self.assertEqual(areas["cutscene"]["status"], "available")

    def test_dedicated_focus_cli_namespaces_tag_list_and_validate_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            assets = project / "assets"
            (assets / "audio").mkdir(parents=True)
            music = assets / "audio" / "theme.xm"
            sfx = assets / "audio" / "hit.wav"
            texture = assets / "world" / "ground.png"
            texture.parent.mkdir(parents=True)
            music.write_bytes(b"Extended Module: placeholder")
            sfx.write_bytes(b"RIFFplaceholder")
            self.write_png_header(texture, 32, 32)
            for index, path in enumerate((music, sfx, texture), 1):
                Path(str(path) + ".conf").write_text(
                    json.dumps({"uuid": index, "format": 2, "data": {}}), encoding="utf-8"
                )
            self.run_json(
                "node-graph", "create", "cutscenes/intro", "--project", str(project), "--json"
            )

            music_tag_proc, _music_tag = self.run_json(
                "music", "tag", "assets/audio/theme.xm", "--project", str(project), "--json"
            )
            sfx_tag_proc, _sfx_tag = self.run_json(
                "sfx", "tag", "assets/audio/hit.wav", "--project", str(project), "--json"
            )
            environment_tag_proc, _environment_tag = self.run_json(
                "environment", "tag", "assets/world/ground.png", "--project", str(project), "--json"
            )
            cutscene_tag_proc, _cutscene_tag = self.run_json(
                "cutscene", "tag", "assets/cutscenes/intro.p64graph", "--project", str(project), "--json"
            )
            music_ls_proc, music_ls = self.run_json(
                "music", "ls", "--project", str(project), "--json"
            )
            sfx_ls_proc, sfx_ls = self.run_json(
                "sfx", "ls", "--project", str(project), "--json"
            )
            environment_ls_proc, environment_ls = self.run_json(
                "environment", "ls", "--project", str(project), "--json"
            )
            cutscene_validate_proc, cutscene_validate = self.run_json(
                "cutscene", "validate", "--project", str(project), "--json"
            )
            incompatible_proc, incompatible = self.run_json(
                "avatar", "tag", "assets/audio/hit.wav", "--project", str(project), "--json"
            )

        for proc in (music_tag_proc, sfx_tag_proc, environment_tag_proc, cutscene_tag_proc):
            self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(music_ls_proc.returncode, 0, music_ls_proc.stderr)
        self.assertEqual([item["asset_path"] for item in music_ls["assets"]], ["audio/theme.xm"])
        self.assertGreaterEqual(music_ls["candidate_count"], 1)
        self.assertEqual(sfx_ls_proc.returncode, 0, sfx_ls_proc.stderr)
        self.assertEqual([item["asset_path"] for item in sfx_ls["assets"]], ["audio/hit.wav"])
        self.assertEqual(environment_ls_proc.returncode, 0, environment_ls_proc.stderr)
        self.assertEqual(environment_ls["assets"][0]["asset_path"], "world/ground.png")
        self.assertEqual(cutscene_validate_proc.returncode, 0, cutscene_validate_proc.stderr)
        self.assertEqual(cutscene_validate["summary"]["passed"], 1)
        self.assertEqual(incompatible_proc.returncode, 1)
        self.assertIn("FOCUS_ASSET_KIND", {item["rule"] for item in incompatible["issues"]})

    def test_ui_new_list_show_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            new_proc, new_data = self.run_json(
                "ui", "new", "menus/title", "--project", str(project), "--json"
            )
            list_proc, list_data = self.run_json("ui", "ls", "--project", str(project), "--json")
            show_proc, show_data = self.run_json(
                "ui", "show", "assets/menus/title.bfui", "--project", str(project), "--json"
            )
            validate_proc, validate_data = self.run_json(
                "ui", "validate", "--all", "--project", str(project), "--json"
            )

        self.assertEqual(new_proc.returncode, 0, new_proc.stderr)
        self.assertTrue(new_data["ok"])
        self.assertEqual(new_data["validation"]["metadata"]["element_count"], 1)
        self.assertTrue(new_data["path"].endswith("assets/menus/title.bfui"))
        self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
        self.assertEqual(list_data["count"], 1)
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(show_data["document"]["schema"], "bf64.ui")
        self.assertEqual(validate_proc.returncode, 0, validate_proc.stderr)
        self.assertEqual(validate_data["summary"]["passed"], 1)

    def test_ui_validation_reports_duplicate_ids_and_missing_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            ui_path = project / "assets" / "broken.bfui"
            ui_path.parent.mkdir()
            ui_path.write_text(
                json.dumps(
                    {
                        "schema": "bf64.ui",
                        "version": 1,
                        "canvas": {"width": 320, "height": 240, "safeArea": [8, 8, 8, 8], "snap": 1},
                        "root": {
                            "id": "root",
                            "type": "Container",
                            "layout": {"anchors": [0, 0, 1, 1], "offsets": [0, 0, 0, 0]},
                            "children": [
                                {
                                    "id": "root",
                                    "type": "Image",
                                    "asset": "assets/missing.png",
                                    "layout": {"anchors": [0, 0, 0, 0], "offsets": [0, 0, 32, 32]},
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            proc, data = self.run_json(
                "ui", "validate", "assets/broken.bfui", "--project", str(project), "--json"
            )

        self.assertEqual(proc.returncode, 1)
        rules = {item["rule"] for item in data["issues"]}
        self.assertIn("UI_ID_DUPLICATE", rules)
        self.assertIn("UI_ASSET", rules)

    def test_ui_validation_accepts_images_text_buttons_and_controller_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            assets = project / "assets"
            assets.mkdir()
            image = assets / "logo.png"
            font = assets / "ui.ttf"
            self.write_png_header(image, 32, 16)
            font.write_bytes(b"test-font-fixture")
            Path(str(image) + ".conf").write_text(json.dumps({"uuid": 22}), encoding="utf-8")
            Path(str(font) + ".conf").write_text(
                json.dumps({"uuid": 11, "fontId": 2, "fontCharset": " NameOKabcdefghijklmnopqrstuvwxyz"}),
                encoding="utf-8",
            )
            layout = {"anchors": [0, 0, 0, 0], "offsets": [8, 8, 128, 32]}
            ui_path = assets / "complete.bfui"
            ui_path.write_text(
                json.dumps(
                    {
                        "schema": "bf64.ui",
                        "version": 1,
                        "canvas": {"width": 320, "height": 240, "safeArea": [8, 8, 8, 8], "snap": 1},
                        "root": {
                            "id": "root",
                            "type": "Container",
                            "layout": {"anchors": [0, 0, 1, 1], "offsets": [0, 0, 0, 0]},
                            "children": [
                                {"id": "logo", "type": "Image", "asset": "assets/logo.png", "layout": layout},
                                {"id": "label", "type": "Text", "font": 11, "text": "Name", "layout": layout},
                                {
                                    "id": "ok",
                                    "type": "Button",
                                    "font": 11,
                                    "text": "OK",
                                    "focus": {"down": "name"},
                                    "layout": layout,
                                },
                                {
                                    "id": "name",
                                    "type": "TextInput",
                                    "font": "assets/ui.ttf",
                                    "placeholder": "Name",
                                    "value": "",
                                    "charset": " abcdefghijklmnopqrstuvwxyz",
                                    "maxLength": 12,
                                    "focus": {"up": "ok"},
                                    "layout": layout,
                                },
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            proc, data = self.run_json("ui", "validate", "complete", "--project", str(project), "--json")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["results"][0]["metadata"]["element_count"], 5)
        self.assertEqual(data["results"][0]["metadata"]["focusable_count"], 2)

    def test_ui_validation_rejects_ambiguous_assets_invalid_offsets_and_non_focusable_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            assets = project / "assets"
            (assets / "first").mkdir(parents=True)
            (assets / "second").mkdir()
            self.write_png_header(assets / "first" / "logo.png", 16, 16)
            self.write_png_header(assets / "second" / "logo.png", 16, 16)
            font = assets / "ui.otf"
            font.write_bytes(b"test-font-fixture")
            Path(str(font) + ".conf").write_text(
                json.dumps({"uuid": 11, "fontId": 2, "fontCharset": "OK"}), encoding="utf-8"
            )
            layout = {"anchors": [0, 0, 0, 0], "offsets": [0.5, 0, 32, 16]}
            ui_path = assets / "invalid-contract.bfui"
            ui_path.write_text(
                json.dumps(
                    {
                        "schema": "bf64.ui",
                        "version": 1,
                        "canvas": {"width": 320, "height": 240},
                        "root": {
                            "id": "root",
                            "type": "Container",
                            "layout": {"anchors": [0, 0, 1, 1], "offsets": [0, 0, 0, 0]},
                            "children": [
                                {"id": "logo", "type": "Image", "asset": "logo.png", "layout": layout},
                                {"id": "label", "type": "Text", "font": 11, "text": "OK", "layout": layout},
                                {
                                    "id": "ok",
                                    "type": "Button",
                                    "font": 11,
                                    "text": "OK",
                                    "focus": {"down": "label"},
                                    "layout": layout,
                                },
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            proc, data = self.run_json(
                "ui", "validate", "invalid-contract", "--project", str(project), "--json"
            )
            font_proc, font_data = self.run_json(
                "asset", "show", "assets/ui.otf", "--project", str(project), "--json"
            )

        self.assertEqual(proc.returncode, 1)
        rules = [item["rule"] for item in data["issues"]]
        self.assertIn("UI_ASSET", rules)
        self.assertIn("UI_OFFSETS", rules)
        self.assertIn("UI_FOCUS_TARGET", rules)
        self.assertEqual(font_proc.returncode, 0, font_proc.stderr)
        self.assertEqual(font_data["asset"]["kind"], "font")
        self.assertEqual(font_data["asset"]["out_path"], "filesystem/ui.font64")

    def test_scene_validator_accepts_ui_component_id_from_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            scene_path = project / "data" / "scenes" / "1" / "scene.json"
            scene = json.loads(scene_path.read_text(encoding="utf-8"))
            scene["graph"]["children"] = [
                {
                    "name": "UI",
                    "uuid": 1,
                    "components": [
                        {
                            "id": 13,
                            "uuid": 2,
                            "name": "UI Document",
                            "data": {"document": 0, "layer": 0, "active": True},
                        }
                    ],
                    "children": [],
                }
            ]
            scene_path.write_text(json.dumps(scene), encoding="utf-8")
            proc, data = self.run_json("scene", "validate", "1", "--project", str(project), "--json")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])

    def test_root_entrypoint_version(self) -> None:
        proc = self.run_cli("--version")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertRegex(proc.stdout.strip(), r"^bf64 \d+\.\d+\.\d+$")

    def test_new_creates_editor_compatible_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "agent_game"
            proc, data = self.run_json("new", str(target), "--name", "Agent Game", "--json")

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(data["ok"])
            self.assertEqual(data["command"], "new")
            self.assertEqual(data["project"]["name"], "Agent Game")
            self.assertEqual(data["project"]["romName"], "agent_game")
            self.assertEqual(data["validation"]["scene_count"], 1)
            self.assertTrue((target / "project.p64proj").exists())
            self.assertTrue((target / "data" / "scenes" / "1" / "scene.json").exists())
            self.assertTrue((target / "assets" / "box.glb").exists())
            self.assertTrue((target / "assets" / "p64" / "font.ia4.png").exists())
            config = json.loads((target / "project.p64proj").read_text(encoding="utf-8"))
            self.assertEqual(config["name"], "Agent Game")
            self.assertEqual(config["romName"], "agent_game")
            self.assertEqual(config["pathEmu"], "ares")

            validate_proc, validate_data = self.run_json("validate", str(target / "project.p64proj"), "--json")
            self.assertEqual(validate_proc.returncode, 0, validate_proc.stderr)
            self.assertTrue(validate_data["ok"])

    def test_new_refuses_non_empty_directory_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing_game"
            target.mkdir()
            (target / "README.md").write_text("keep me\n", encoding="utf-8")

            proc, data = self.run_json("new", str(target), "--json")

            self.assertEqual(proc.returncode, 1)
            self.assertFalse(data["ok"])
            self.assertTrue(any(item["rule"] == "NEW_EXISTS" for item in data["issues"]))
            self.assertFalse((target / "project.p64proj").exists())
            self.assertEqual((target / "README.md").read_text(encoding="utf-8"), "keep me\n")

    def test_new_force_overwrites_scaffold_files_and_keeps_extra_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing_game"
            target.mkdir()
            (target / "README.md").write_text("keep me\n", encoding="utf-8")
            (target / "project.p64proj").write_text("{}", encoding="utf-8")

            proc, data = self.run_json(
                "new",
                str(target),
                "--force",
                "--name",
                "Forced Game",
                "--rom-name",
                "Forced Game",
                "--json",
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(data["ok"])
            self.assertEqual((target / "README.md").read_text(encoding="utf-8"), "keep me\n")
            config = json.loads((target / "project.p64proj").read_text(encoding="utf-8"))
            self.assertEqual(config["name"], "Forced Game")
            self.assertEqual(config["romName"], "Forced_Game")
            self.assertTrue(any(item["action"] == "overwritten" for item in data["changes"]))

    def test_new_merge_initializes_non_empty_asset_repo_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "asset_first"
            (target / "assets" / "reference").mkdir(parents=True)
            (target / "assets" / "reference" / "concept.png").write_bytes(b"concept")
            (target / "assets" / "box.glb").write_bytes(b"user-owned-model")
            (target / "README.md").write_text("keep me\n", encoding="utf-8")
            (target / ".gitignore").write_text("user-cache/\n", encoding="utf-8")

            proc, data = self.run_json(
                "new", str(target), "--merge", "--name", "Asset First", "--json"
            )
            readme = (target / "README.md").read_text(encoding="utf-8")
            box = (target / "assets" / "box.glb").read_bytes()
            concept = (target / "assets" / "reference" / "concept.png").read_bytes()
            config_exists = (target / "project.p64proj").is_file()
            scene_exists = (target / "data" / "scenes" / "1" / "scene.json").is_file()
            font_exists = (target / "assets" / "p64" / "font.ia4.png").is_file()
            gitignore = (target / ".gitignore").read_text(encoding="utf-8")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(data["merge"])
        self.assertEqual(readme, "keep me\n")
        self.assertEqual(box, b"user-owned-model")
        self.assertEqual(concept, b"concept")
        self.assertTrue(config_exists)
        self.assertTrue(scene_exists)
        self.assertTrue(font_exists)
        self.assertIn("user-cache/", gitignore)
        self.assertIn("filesystem", gitignore)
        self.assertFalse(any(item["action"] in {"overwritten", "removed"} for item in data["changes"]))

    def test_init_alias_merge_initializes_current_asset_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing_repo"
            (target / "assets").mkdir(parents=True)
            (target / "assets" / "hero.glb").write_bytes(b"hero")

            proc, data = self.run_json(
                "init", "--project", str(target), "--name", "Existing Repo", "--json"
            )
            hero = (target / "assets" / "hero.glb").read_bytes()
            config = json.loads((target / "project.p64proj").read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["command"], "init")
        self.assertTrue(data["merge"])
        self.assertEqual(hero, b"hero")
        self.assertEqual(config["name"], "Existing Repo")

    def test_new_merge_preserves_existing_project_config_and_scene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing_project"
            self.write_minimal_project(target, {"name": "Original", "romName": "original_rom"})
            config_before = (target / "project.p64proj").read_bytes()
            scene_before = (target / "data" / "scenes" / "1" / "scene.json").read_bytes()

            proc, data = self.run_json(
                "new", str(target), "--merge", "--name", "Ignored", "--rom-name", "ignored", "--json"
            )
            config_after = (target / "project.p64proj").read_bytes()
            scene_after = (target / "data" / "scenes" / "1" / "scene.json").read_bytes()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(config_after, config_before)
        self.assertEqual(scene_after, scene_before)
        self.assertEqual(data["project"]["name"], "Original")
        self.assertEqual(data["project"]["romName"], "original_rom")

    def test_new_merge_preflights_path_conflicts_without_partial_scaffolding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "conflicted_repo"
            target.mkdir()
            (target / "README.md").write_text("keep\n", encoding="utf-8")
            (target / "data").write_text("not a directory\n", encoding="utf-8")

            proc, data = self.run_json("new", str(target), "--merge", "--json")
            files_after = sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file())

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertTrue(any(item["rule"] == "NEW_CONFLICT" for item in data["issues"]))
        self.assertEqual(files_after, ["README.md", "data"])

    def test_new_rejects_project_paths_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bad path"
            proc, data = self.run_json("new", str(target), "--json")

            self.assertEqual(proc.returncode, 1)
            self.assertFalse(data["ok"])
            self.assertTrue(any(item["rule"] == "NEW_PATH" for item in data["issues"]))
            self.assertFalse(target.exists())

    def test_new_rejects_template_subdirectories(self) -> None:
        target = ROOT / "n64" / "examples" / "empty" / "generated_game"
        proc, data = self.run_json("new", str(target), "--json")

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertTrue(any(item["rule"] == "NEW_PATH" for item in data["issues"]))
        self.assertFalse(target.exists())

    def test_new_records_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "record_game"
            history = Path(tmp) / "history.jsonl"
            proc, data = self.run_json(
                "new",
                str(target),
                "--record",
                "--history-path",
                str(history),
                "--json",
            )
            rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(len(rows), 1)
        record = rows[0]
        self.assertEqual(record["command"], "new")
        self.assertEqual(record["path"], str(target / "project.p64proj"))
        self.assertEqual(record["project_path"], str(target))
        self.assertTrue(any(item["kind"] == "project_scaffold_file" for item in record["artifacts"]))

    def test_project_status_empty_project(self) -> None:
        proc, data = self.run_json("project", "status", "--project", "n64/examples/empty", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["project"]["name"], "Pyrite64 Project")
        self.assertEqual(data["validation"]["scene_count"], 1)
        self.assertEqual(data["assets"]["by_kind"]["model"], 1)
        self.assertIn("build_ready", data["toolchain"])

    def test_asset_ls_empty_project(self) -> None:
        proc, data = self.run_json("asset", "ls", "--project", "n64/examples/empty", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["total_assets"], 3)
        self.assertEqual(data["summary"]["validatable_count"], 2)
        self.assertEqual(data["summary"]["by_kind"]["unknown"], 1)
        paths = {asset["relative_path"]: asset for asset in data["assets"]}
        self.assertEqual(paths["assets/crate32.png"]["kind"], "texture")
        self.assertTrue(paths["assets/crate32.png"]["conf_exists"])
        self.assertEqual(paths["assets/box.glb"]["out_path"], "filesystem/box.t3dm")

    def test_asset_show_texture_includes_validation(self) -> None:
        proc, data = self.run_json("asset", "show", "assets/crate32.png", "--project", "n64/examples/empty", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["asset"]["kind"], "texture")
        self.assertEqual(data["asset"]["relative_path"], "assets/crate32.png")
        self.assertEqual(data["conf"]["format"], 2)
        self.assertTrue(data["validation"]["ok"])
        self.assertEqual(data["validation"]["metadata"]["format"], "RGBA16")

    def test_asset_show_normalizes_incomplete_sidecar_without_rewriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            texture = project / "assets" / "optional.png"
            texture.parent.mkdir()
            self.write_png_header(texture, 32, 32)
            sidecar = Path(str(texture) + ".conf")
            original = '{"exclude":true}'
            sidecar.write_text(original, encoding="utf-8")

            proc, data = self.run_json(
                "asset", "show", "assets/optional.png", "--project", str(project), "--json"
            )

            self.assertEqual(sidecar.read_text(encoding="utf-8"), original)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(
            data["conf"],
            {
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
                "exclude": True,
                "data": {},
            },
        )
        self.assertEqual(
            data["asset"]["conf_defaulted_fields"],
            [
                "uuid",
                "format",
                "baseScale",
                "compression",
                "gltfBVH",
                "wavForceMono",
                "wavResampleRate",
                "wavCompression",
                "fontId",
                "fontCharset",
                "data",
            ],
        )

    def test_asset_show_uses_editor_defaults_for_wrongly_typed_sidecar_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            texture = project / "assets" / "optional.png"
            texture.parent.mkdir()
            self.write_png_header(texture, 32, 32)
            Path(str(texture) + ".conf").write_text(
                json.dumps(
                    {
                        "uuid": "not-an-id",
                        "format": None,
                        "baseScale": "sixteen",
                        "compression": [],
                        "gltfBVH": "true",
                        "wavForceMono": 1,
                        "wavResampleRate": "22050",
                        "wavCompression": {},
                        "fontId": -1,
                        "fontCharset": 42,
                        "exclude": "true",
                        "data": "not-an-object",
                    }
                ),
                encoding="utf-8",
            )

            proc, data = self.run_json(
                "asset", "show", "assets/optional.png", "--project", str(project), "--json"
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["conf"]["uuid"], 0)
        self.assertEqual(data["conf"]["format"], 0)
        self.assertEqual(data["conf"]["baseScale"], 16)
        self.assertEqual(data["conf"]["compression"], 0)
        self.assertIs(data["conf"]["gltfBVH"], False)
        self.assertIs(data["conf"]["wavForceMono"], False)
        self.assertEqual(data["conf"]["wavResampleRate"], 0)
        self.assertEqual(data["conf"]["wavCompression"], 0)
        self.assertEqual(data["conf"]["fontId"], 0)
        self.assertEqual(data["conf"]["fontCharset"], "")
        self.assertIs(data["conf"]["exclude"], False)
        self.assertEqual(data["conf"]["data"], {})
        self.assertEqual(
            data["asset"]["conf_defaulted_fields"],
            [
                "uuid",
                "format",
                "baseScale",
                "compression",
                "gltfBVH",
                "wavForceMono",
                "wavResampleRate",
                "wavCompression",
                "fontId",
                "fontCharset",
                "exclude",
                "data",
            ],
        )

    def test_asset_validate_all_empty_project_skips_unknown_sources(self) -> None:
        proc, data = self.run_json("asset", "validate-all", "--project", "n64/examples/empty", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["validated"], 2)
        self.assertEqual(data["summary"]["skipped"], 1)
        skipped = [item for item in data["results"] if item["metadata"].get("skipped")]
        self.assertEqual(skipped[0]["kind"], "unknown")

    def test_asset_validate_all_human_summary_reports_selection_and_outcomes(self) -> None:
        proc = self.run_cli("asset", "validate-all", "--project", "n64/examples/empty")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("included=3", proc.stdout)
        self.assertIn("excluded=0", proc.stdout)
        self.assertIn("skipped=1", proc.stdout)
        self.assertIn("passed=2", proc.stdout)
        self.assertIn("failed=0", proc.stdout)

    def test_asset_validate_all_skips_excluded_assets_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            included, _excluded = self.write_included_and_excluded_textures(project)

            proc, data = self.run_json(
                "asset", "validate-all", "--project", str(project), "--json"
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["included"], 1)
        self.assertEqual(data["summary"]["excluded"], 1)
        self.assertEqual(data["summary"]["skipped"], 0)
        self.assertEqual(data["summary"]["passed"], 1)
        self.assertEqual(data["summary"]["failed"], 0)
        self.assertEqual([item["path"] for item in data["results"]], [str(included)])

    def test_ui_validation_accepts_progress_bar_values_and_color_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            ui_path = project / "assets" / "hud.bfui"
            ui_path.parent.mkdir()
            ui_path.write_text(
                json.dumps(
                    {
                        "schema": "bf64.ui",
                        "version": 1,
                        "canvas": {"width": 320, "height": 240, "safeArea": [8, 8, 8, 8], "snap": 1},
                        "root": {
                            "id": "root",
                            "type": "Container",
                            "layout": {"anchors": [0, 0, 1, 1], "offsets": [0, 0, 0, 0]},
                            "children": [
                                {
                                    "id": "health",
                                    "type": "ProgressBar",
                                    "layout": {"anchors": [0, 0, 0, 0], "offsets": [8, 8, 108, 20]},
                                    "value": 75,
                                    "max": 100,
                                    "style": {"color": "#202020FF", "fillColor": "#40C060FF"},
                                    "thresholds": [
                                        {"max": 25, "color": "#D04040FF"},
                                        {"max": 50, "color": "#E0B030FF"},
                                    ],
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            proc, data = self.run_json(
                "ui", "validate", "assets/hud.bfui", "--project", str(project), "--json"
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["passed"], 1)
        self.assertEqual(data["results"][0]["metadata"]["progress_bar_count"], 1)

    def test_ui_validation_accepts_vertical_flow_containers_for_collapsible_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            ui_path = project / "assets" / "hud.bfui"
            ui_path.parent.mkdir()
            ui_path.write_text(
                json.dumps(
                    {
                        "schema": "bf64.ui",
                        "version": 1,
                        "canvas": {"width": 320, "height": 240},
                        "root": {
                            "id": "resources",
                            "type": "Container",
                            "layout": {
                                "anchors": [0, 0, 0, 0],
                                "offsets": [8, 8, 108, 88],
                                "flow": "vertical",
                                "gap": 4,
                            },
                            "children": [
                                {
                                    "id": "stamina-row",
                                    "type": "Container",
                                    "layout": {"anchors": [0, 0, 0, 0], "offsets": [0, 0, 100, 12]},
                                },
                                {
                                    "id": "bladder-row",
                                    "type": "Container",
                                    "layout": {"anchors": [0, 0, 0, 0], "offsets": [0, 0, 100, 12]},
                                },
                                {
                                    "id": "money-row",
                                    "type": "Container",
                                    "layout": {"anchors": [0, 0, 0, 0], "offsets": [0, 0, 100, 12]},
                                },
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            proc, data = self.run_json(
                "ui", "validate", "assets/hud.bfui", "--project", str(project), "--json"
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["results"][0]["metadata"]["flow_container_count"], 1)

    def test_ui_validation_rejects_invalid_progress_value_and_threshold_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            ui_path = project / "assets" / "hud.bfui"
            ui_path.parent.mkdir()
            ui_path.write_text(
                json.dumps(
                    {
                        "schema": "bf64.ui",
                        "version": 1,
                        "canvas": {"width": 320, "height": 240},
                        "root": {
                            "id": "root",
                            "type": "Container",
                            "layout": {"anchors": [0, 0, 1, 1], "offsets": [0, 0, 0, 0]},
                            "children": [
                                {
                                    "id": "health",
                                    "type": "ProgressBar",
                                    "layout": {"anchors": [0, 0, 0, 0], "offsets": [8, 8, 108, 20]},
                                    "value": 101,
                                    "max": 100,
                                    "thresholds": [
                                        {"max": 50, "color": "#E0B030FF"},
                                        {"max": 25, "color": "#D04040FF"},
                                    ],
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            proc, data = self.run_json(
                "ui", "validate", "assets/hud.bfui", "--project", str(project), "--json"
            )

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        rules = {item["rule"] for item in data["results"][0]["issues"]}
        self.assertIn("UI_PROGRESS_VALUE", rules)
        self.assertIn("UI_PROGRESS_THRESHOLDS", rules)

    def test_asset_validate_all_can_include_excluded_assets_for_source_audits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            included, excluded = self.write_included_and_excluded_textures(project)

            proc, data = self.run_json(
                "asset",
                "validate-all",
                "--project",
                str(project),
                "--include-excluded",
                "--json",
            )

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertTrue(data["summary"]["include_excluded"])
        self.assertEqual(data["summary"]["included"], 1)
        self.assertEqual(data["summary"]["excluded"], 1)
        self.assertEqual(data["summary"]["selected_assets"], 2)
        self.assertEqual(data["summary"]["skipped"], 0)
        self.assertEqual(data["summary"]["passed"], 1)
        self.assertEqual(data["summary"]["failed"], 1)
        self.assertEqual({item["path"] for item in data["results"]}, {str(included), str(excluded)})

    def test_asset_validate_all_reports_defaults_applied_to_a_minimal_excluded_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            texture = project / "assets" / "optional.png"
            texture.parent.mkdir()
            self.write_png_header(texture, 32, 32)
            Path(str(texture) + ".conf").write_text(
                json.dumps({"exclude": True}), encoding="utf-8"
            )

            proc, data = self.run_json(
                "asset",
                "validate-all",
                "--project",
                str(project),
                "--include-excluded",
                "--json",
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["passed"], 1)
        self.assertEqual(data["summary"]["failed"], 0)
        self.assertEqual(
            data["results"][0]["metadata"]["conf_defaulted_fields"],
            [
                "uuid",
                "format",
                "baseScale",
                "compression",
                "gltfBVH",
                "wavForceMono",
                "wavResampleRate",
                "wavCompression",
                "fontId",
                "fontCharset",
                "data",
            ],
        )

    def test_include_excluded_source_audit_fails_a_malformed_excluded_wav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_minimal_project(project)
            audio = project / "assets" / "broken.wav"
            audio.parent.mkdir()
            audio.write_bytes(b"not a wave file")
            Path(str(audio) + ".conf").write_text(
                json.dumps({"uuid": 77, "exclude": True, "wavCompression": 0}),
                encoding="utf-8",
            )

            default_proc, default_data = self.run_json(
                "asset", "validate-all", "--project", str(project), "--json"
            )
            audit_proc, audit_data = self.run_json(
                "asset", "validate-all", "--project", str(project),
                "--include-excluded", "--json"
            )

        self.assertEqual(default_proc.returncode, 0, default_proc.stderr)
        self.assertEqual(default_data["summary"]["excluded"], 1)
        self.assertEqual(default_data["summary"]["validated"], 0)
        self.assertEqual(audit_proc.returncode, 1, audit_proc.stderr)
        self.assertEqual(audit_data["summary"]["failed"], 1)
        wav_issue = next(
            item
            for result in audit_data["results"]
            for item in result["issues"]
            if item["rule"] == "A10"
        )
        self.assertEqual(wav_issue["severity"], "error")

    def test_project_asset_exclusion_globs_drive_listing_validation_and_build_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(
                project,
                {"assetExclusions": ["assets/reference/**", "models/draft/**"]},
            )

            included = project / "assets" / "included.png"
            reference = project / "assets" / "reference" / "nested" / "invalid.bci.png"
            draft = project / "assets" / "models" / "draft" / "invalid.bci.png"
            for path, size, uuid_value in (
                (included, 32, 1),
                (reference, 128, 2),
                (draft, 128, 3),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                self.write_png_header(path, size, size)
                Path(str(path) + ".conf").write_text(
                    json.dumps({"uuid": uuid_value, "format": 2}), encoding="utf-8"
                )

            list_proc, list_data = self.run_json(
                "asset", "ls", "--project", str(project), "--json"
            )
            validate_proc, validate_data = self.run_json(
                "asset", "validate-all", "--project", str(project), "--json"
            )
            build_proc, build_data = self.run_json("build", "--project", str(project), "--json")
            audit_proc, audit_data = self.run_json(
                "asset",
                "validate-all",
                "--project",
                str(project),
                "--include-excluded",
                "--json",
            )

        self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
        assets = {entry["asset_path"]: entry for entry in list_data["assets"]}
        self.assertFalse(assets["included.png"]["exclude"])
        self.assertTrue(assets["reference/nested/invalid.bci.png"]["project_excluded"])
        self.assertEqual(
            assets["reference/nested/invalid.bci.png"]["matched_exclusion_patterns"],
            ["assets/reference/**"],
        )
        self.assertEqual(
            assets["models/draft/invalid.bci.png"]["exclude_source"], "project"
        )

        self.assertEqual(validate_proc.returncode, 0, validate_proc.stderr)
        self.assertEqual(validate_data["summary"]["included"], 1)
        self.assertEqual(validate_data["summary"]["excluded"], 2)
        self.assertEqual(validate_data["summary"]["passed"], 1)
        self.assertEqual(validate_data["summary"]["failed"], 0)

        self.assertEqual(build_proc.returncode, 0, build_proc.stderr)
        self.assertEqual(build_data["validation"]["assets"]["excluded"], 2)
        self.assertEqual(
            [item["source"] for item in build_data["plan"]["asset_outputs"]],
            ["assets/included.png"],
        )

        self.assertEqual(audit_proc.returncode, 1)
        self.assertEqual(audit_data["summary"]["failed"], 2)

    def test_project_validation_rejects_unsafe_asset_exclusion_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(
                project,
                {"assetExclusions": ["../outside/**", "/absolute/**", 42]},
            )

            proc, data = self.run_json(
                "validate", str(project / "project.p64proj"), "--json"
            )

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertTrue(
            all(item["rule"] == "PROJECT_ASSET_EXCLUSIONS" for item in data["issues"])
        )

    def test_asset_exclusion_cli_add_list_remove_dry_run_and_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            history = Path(tmp) / "operations.jsonl"
            self.write_minimal_project(project)

            list_proc, list_data = self.run_json(
                "asset", "exclusion", "list", "--project", str(project), "--json"
            )
            dry_proc, dry_data = self.run_json(
                "asset",
                "exclusion",
                "add",
                "assets/reference/**",
                "--project",
                str(project),
                "--dry-run",
                "--json",
            )
            config_after_dry_run = json.loads(
                (project / "project.p64proj").read_text(encoding="utf-8")
            )
            add_proc, add_data = self.run_json(
                "asset",
                "exclusion",
                "add",
                "assets/reference/**",
                "--project",
                str(project),
                "--record",
                "--history-path",
                str(history),
                "--json",
            )
            remove_dry_proc, remove_dry_data = self.run_json(
                "asset",
                "exclusion",
                "remove",
                "reference/**",
                "--project",
                str(project),
                "--dry-run",
                "--json",
            )
            config_after_remove_dry_run = json.loads(
                (project / "project.p64proj").read_text(encoding="utf-8")
            )
            remove_proc, remove_data = self.run_json(
                "asset",
                "exclusion",
                "remove",
                "reference/**",
                "--project",
                str(project),
                "--json",
            )
            record = json.loads(history.read_text(encoding="utf-8").strip())

        self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
        self.assertEqual(list_data["patterns"], [])
        self.assertEqual(dry_proc.returncode, 0, dry_proc.stderr)
        self.assertTrue(dry_data["dry_run"])
        self.assertEqual(dry_data["patterns"], ["reference/**"])
        self.assertNotIn("assetExclusions", config_after_dry_run)

        self.assertEqual(add_proc.returncode, 0, add_proc.stderr)
        self.assertEqual(add_data["patterns"], ["reference/**"])
        self.assertEqual(record["command"], "asset exclusion add")
        self.assertEqual(record["project_path"], str(project))

        self.assertEqual(remove_dry_proc.returncode, 0, remove_dry_proc.stderr)
        self.assertTrue(remove_dry_data["dry_run"])
        self.assertEqual(config_after_remove_dry_run["assetExclusions"], ["reference/**"])
        self.assertEqual(remove_proc.returncode, 0, remove_proc.stderr)
        self.assertEqual(remove_data["patterns"], [])

    def test_prefab_cli_create_set_duplicate_validate_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)

            create_proc, create_data = self.run_json(
                "prefab",
                "create",
                "actors/player",
                "--name",
                "Player",
                "--project",
                str(project),
                "--json",
            )
            prefab_path = Path(create_data.get("path", ""))
            original_doc = json.loads(prefab_path.read_text(encoding="utf-8"))
            set_proc, set_data = self.run_json(
                "prefab",
                "set",
                "actors/player",
                "/obj/enabled",
                "false",
                "--project",
                str(project),
                "--json",
            )
            duplicate_proc, duplicate_data = self.run_json(
                "prefab",
                "duplicate",
                "actors/player",
                "actors/player_copy",
                "--name",
                "Player Copy",
                "--project",
                str(project),
                "--json",
            )
            copy_path = Path(duplicate_data.get("path", ""))
            copied_doc = json.loads(copy_path.read_text(encoding="utf-8"))
            copy_conf = json.loads(Path(str(copy_path) + ".conf").read_text(encoding="utf-8"))
            validate_proc, validate_data = self.run_json(
                "prefab", "validate", "--all", "--project", str(project), "--json"
            )
            delete_dry_proc, delete_dry_data = self.run_json(
                "prefab",
                "delete",
                "actors/player_copy",
                "--project",
                str(project),
                "--dry-run",
                "--json",
            )
            copy_exists_after_dry_run = copy_path.exists()
            delete_proc, delete_data = self.run_json(
                "prefab",
                "delete",
                "actors/player_copy",
                "--project",
                str(project),
                "--json",
            )

        self.assertEqual(create_proc.returncode, 0, create_proc.stderr)
        self.assertTrue(create_data["validation"]["ok"])
        self.assertEqual(original_doc["obj"]["name"], "Player")
        self.assertEqual(original_doc["uuid"], create_data["prefab"]["uuid"])

        self.assertEqual(set_proc.returncode, 0, set_proc.stderr)
        self.assertFalse(set_data["document"]["obj"]["enabled"])
        self.assertEqual(duplicate_proc.returncode, 0, duplicate_proc.stderr)
        self.assertNotEqual(copied_doc["uuid"], original_doc["uuid"])
        self.assertNotEqual(copied_doc["obj"]["uuid"], original_doc["obj"]["uuid"])
        self.assertEqual(copied_doc["obj"]["name"], "Player Copy")
        self.assertEqual(copy_conf["uuid"], copied_doc["uuid"])

        self.assertEqual(validate_proc.returncode, 0, validate_proc.stderr)
        self.assertEqual(validate_data["summary"], {"failed": 0, "passed": 2, "prefabs": 2})
        self.assertEqual(delete_dry_proc.returncode, 0, delete_dry_proc.stderr)
        self.assertTrue(delete_dry_data["dry_run"])
        self.assertTrue(copy_exists_after_dry_run)
        self.assertEqual(delete_proc.returncode, 0, delete_proc.stderr)
        self.assertFalse(delete_data["exists"])

    def test_prefab_validation_rejects_duplicate_component_uuids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            prefab = project / "assets" / "broken.prefab"
            prefab.parent.mkdir()
            root = {
                "name": "Broken",
                "uuid": 10,
                "enabled": True,
                "selectable": True,
                "pos": [0, 0, 0],
                "rot": [0, 0, 0, 1],
                "scale": [1, 1, 1],
                "propOverrides": {},
                "uuidPrefab": 0,
                "components": [
                    {"id": 2, "uuid": 99, "name": "Light", "data": {}},
                    {"id": 3, "uuid": 99, "name": "Camera", "data": {}},
                ],
                "children": [],
            }
            prefab.write_text(json.dumps({"uuid": 5, "obj": root}), encoding="utf-8")
            Path(str(prefab) + ".conf").write_text(json.dumps({"uuid": 5}), encoding="utf-8")

            proc, data = self.run_json(
                "prefab", "validate", "broken", "--project", str(project), "--json"
            )

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertIn("PREFAB_COMPONENT_UUID", {item["rule"] for item in data["results"][0]["issues"]})

    def test_node_graph_cli_structured_mutation_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)

            create_proc, create_data = self.run_json(
                "node-graph", "create", "logic/boot", "--project", str(project), "--json"
            )
            start_proc, start_data = self.run_json(
                "node-graph",
                "node",
                "add",
                "logic/boot",
                "core.start",
                "--pos",
                "0",
                "0",
                "--project",
                str(project),
                "--json",
            )
            wait_proc, wait_data = self.run_json(
                "node-graph",
                "node",
                "add",
                "logic/boot",
                "core.wait",
                "--pos",
                "120",
                "0",
                "--data",
                '{"time": 0.5}',
                "--project",
                str(project),
                "--json",
            )
            start_uuid = str(start_data.get("node", {}).get("uuid", 0))
            wait_uuid = str(wait_data.get("node", {}).get("uuid", 0))
            link_proc, link_data = self.run_json(
                "node-graph",
                "link",
                "add",
                "logic/boot",
                start_uuid,
                wait_uuid,
                "--project",
                str(project),
                "--json",
            )
            variable_proc, variable_data = self.run_json(
                "node-graph",
                "variable",
                "add",
                "logic/boot",
                "score",
                "u32",
                "--project",
                str(project),
                "--json",
            )
            validate_proc, validate_data = self.run_json(
                "node-graph", "validate", "logic/boot", "--project", str(project), "--json"
            )
            remove_proc, remove_data = self.run_json(
                "node-graph",
                "node",
                "remove",
                "logic/boot",
                wait_uuid,
                "--project",
                str(project),
                "--json",
            )

        self.assertEqual(create_proc.returncode, 0, create_proc.stderr)
        self.assertTrue(create_data["validation"]["ok"])
        self.assertEqual(start_proc.returncode, 0, start_proc.stderr)
        self.assertEqual(wait_proc.returncode, 0, wait_proc.stderr)
        self.assertEqual(wait_data["node"]["time"], 0.5)
        self.assertEqual(link_proc.returncode, 0, link_proc.stderr)
        self.assertEqual(link_data["link"]["src"], int(start_uuid))
        self.assertEqual(variable_proc.returncode, 0, variable_proc.stderr)
        self.assertEqual(variable_data["variable"], {"name": "score", "type": "u32"})
        self.assertEqual(validate_proc.returncode, 0, validate_proc.stderr)
        self.assertEqual(validate_data["summary"]["passed"], 1)
        self.assertEqual(validate_data["results"][0]["metadata"]["node_count"], 2)
        self.assertEqual(remove_proc.returncode, 0, remove_proc.stderr)
        self.assertEqual(remove_data["removed_incident_links"], 1)
        self.assertEqual(remove_data["document"]["links"], [])

    def test_node_graph_validation_rejects_dangling_links_and_duplicate_variables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            graph = project / "assets" / "broken.p64graph"
            graph.parent.mkdir()
            graph.write_text(
                json.dumps(
                    {
                        "repeatable": False,
                        "view": [0, 0, 1],
                        "variables": [
                            {"name": "score", "type": "u32"},
                            {"name": "score", "type": "u32"},
                        ],
                        "nodes": [{"uuid": 1, "typeId": "core.start", "pos": [0, 0]}],
                        "links": [{"src": 1, "srcPort": 0, "dst": 999, "dstPort": 0}],
                        "groups": [],
                    }
                ),
                encoding="utf-8",
            )
            Path(str(graph) + ".conf").write_text(json.dumps({"uuid": 22}), encoding="utf-8")

            proc, data = self.run_json(
                "node-graph", "validate", "broken", "--project", str(project), "--json"
            )

        self.assertEqual(proc.returncode, 1)
        rules = {item["rule"] for item in data["results"][0]["issues"]}
        self.assertIn("NODE_GRAPH_VARIABLE", rules)
        self.assertIn("NODE_GRAPH_LINK", rules)

    def test_prefab_object_and_component_mutations_use_generated_uuids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            self.run_json(
                "prefab", "create", "actors/root", "--name", "Root", "--project", str(project), "--json"
            )

            object_proc, object_data = self.run_json(
                "prefab",
                "object",
                "add",
                "actors/root",
                "--name",
                "Lamp",
                "--parent",
                "root",
                "--position",
                "1",
                "2",
                "3",
                "--project",
                str(project),
                "--json",
            )
            object_uuid = str(object_data.get("object", {}).get("uuid", 0))
            component_proc, component_data = self.run_json(
                "prefab",
                "component",
                "add",
                "actors/root",
                object_uuid,
                "light",
                "--data",
                '{"size": 25.0}',
                "--project",
                str(project),
                "--json",
            )
            component_uuid = str(component_data.get("component", {}).get("uuid", 0))
            update_proc, update_data = self.run_json(
                "prefab",
                "component",
                "update",
                "actors/root",
                object_uuid,
                component_uuid,
                "--data",
                '{"size": 40.0}',
                "--project",
                str(project),
                "--json",
            )
            remove_proc, remove_data = self.run_json(
                "prefab",
                "object",
                "remove",
                "actors/root",
                object_uuid,
                "--project",
                str(project),
                "--json",
            )

        self.assertEqual(object_proc.returncode, 0, object_proc.stderr)
        self.assertGreater(int(object_uuid), 0)
        self.assertEqual(object_data["object"]["pos"], [1.0, 2.0, 3.0])
        self.assertEqual(component_proc.returncode, 0, component_proc.stderr)
        self.assertGreater(int(component_uuid), 0)
        self.assertEqual(component_data["component"]["id"], 2)
        self.assertEqual(component_data["component"]["data"]["size"], 25.0)
        self.assertEqual(update_proc.returncode, 0, update_proc.stderr)
        self.assertEqual(update_data["component"]["after"]["data"]["size"], 40.0)
        self.assertEqual(remove_proc.returncode, 0, remove_proc.stderr)
        self.assertEqual(remove_data["removed"]["uuid"], int(object_uuid))
        self.assertTrue(remove_data["validation"]["ok"])

    def test_prefab_rename_force_replace_and_attachment_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            model = project / "assets" / "models" / "hero.glb"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"glTF")
            Path(str(model) + ".conf").write_text(json.dumps({"uuid": 9001}), encoding="utf-8")

            create_proc, create_data = self.run_json(
                "prefab", "create", "actors/source", "--name", "Source",
                "--project", str(project), "--json"
            )
            root_uuid = str(create_data["prefab"]["object_uuid"])
            dry_proc, dry_data = self.run_json(
                "prefab", "rename", "actors/source", "actors/hero",
                "--project", str(project), "--dry-run", "--json"
            )
            source_path = project / "assets" / "actors" / "source.prefab"
            source_exists_after_dry_run = source_path.exists()
            rename_proc, rename_data = self.run_json(
                "prefab", "rename", "actors/source", "actors/hero",
                "--project", str(project), "--json"
            )
            hero_path = project / "assets" / "actors" / "hero.prefab"
            camera_proc, camera_data = self.run_json(
                "prefab", "attach", "camera", "actors/hero", root_uuid,
                "--project", str(project), "--json"
            )
            model_proc, model_data = self.run_json(
                "prefab", "attach", "model", "actors/hero", root_uuid, "models/hero.glb",
                "--project", str(project), "--json"
            )
            old_uuid = json.loads(hero_path.read_text(encoding="utf-8"))["uuid"]
            force_proc, force_data = self.run_json(
                "prefab", "create", "actors/hero", "--name", "Replacement", "--force",
                "--project", str(project), "--json"
            )
            hero_exists_after_rename = hero_path.exists()
            replaced = json.loads(hero_path.read_text(encoding="utf-8"))
            replaced_conf = json.loads(Path(str(hero_path) + ".conf").read_text(encoding="utf-8"))

        self.assertEqual(create_proc.returncode, 0, create_proc.stderr)
        self.assertEqual(dry_proc.returncode, 0, dry_proc.stderr)
        self.assertTrue(dry_data["dry_run"])
        self.assertTrue(source_exists_after_dry_run)
        self.assertEqual(rename_proc.returncode, 0, rename_proc.stderr)
        self.assertTrue(hero_exists_after_rename)
        self.assertEqual(camera_proc.returncode, 0, camera_proc.stderr)
        self.assertEqual(camera_data["component"]["id"], 3)
        self.assertEqual(model_proc.returncode, 0, model_proc.stderr)
        self.assertEqual(model_data["component"]["data"]["model"], 9001)
        self.assertEqual(model_data["attachment"]["path"], "assets/models/hero.glb")
        self.assertEqual(force_proc.returncode, 0, force_proc.stderr)
        self.assertNotEqual(replaced["uuid"], old_uuid)
        self.assertEqual(replaced["obj"]["name"], "Replacement")
        self.assertEqual(replaced_conf["uuid"], replaced["uuid"])

    def test_node_graph_full_lifecycle_and_remaining_structured_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            self.run_json(
                "node-graph", "create", "logic/source", "--project", str(project), "--json"
            )
            _proc, start = self.run_json(
                "node-graph", "node", "add", "logic/source", "core.start",
                "--project", str(project), "--json"
            )
            _proc, wait = self.run_json(
                "node-graph", "node", "add", "logic/source", "core.wait",
                "--data", '{"time": 1.0}', "--project", str(project), "--json"
            )
            start_uuid = str(start["node"]["uuid"])
            wait_uuid = str(wait["node"]["uuid"])
            self.run_json(
                "node-graph", "link", "add", "logic/source", start_uuid, wait_uuid,
                "--project", str(project), "--json"
            )
            self.run_json(
                "node-graph", "variable", "add", "logic/source", "score", "u32",
                "--project", str(project), "--json"
            )

            update_proc, update_data = self.run_json(
                "node-graph", "node", "update", "logic/source", wait_uuid,
                "--data", '{"time": 2.5}', "--pos", "200", "30",
                "--project", str(project), "--json"
            )
            unlink_proc, unlink_data = self.run_json(
                "node-graph", "link", "remove", "logic/source", start_uuid, wait_uuid,
                "--project", str(project), "--json"
            )
            variable_proc, variable_data = self.run_json(
                "node-graph", "variable", "update", "logic/source", "score",
                "--name", "points", "--type", "i32",
                "--project", str(project), "--json"
            )
            group_proc, group_data = self.run_json(
                "node-graph", "group", "add", "logic/source", "Timing",
                "--pos", "10", "20", "--size", "300", "120",
                "--project", str(project), "--json"
            )
            duplicate_proc, duplicate_data = self.run_json(
                "node-graph", "duplicate", "logic/source", "logic/copy",
                "--project", str(project), "--json"
            )
            rename_proc, rename_data = self.run_json(
                "node-graph", "rename", "logic/copy", "logic/renamed",
                "--project", str(project), "--json"
            )
            delete_proc, delete_data = self.run_json(
                "node-graph", "delete", "logic/renamed", "--project", str(project), "--json"
            )

        self.assertEqual(update_proc.returncode, 0, update_proc.stderr)
        self.assertEqual(update_data["node"]["after"]["time"], 2.5)
        self.assertEqual(update_data["node"]["after"]["pos"], [200.0, 30.0])
        self.assertEqual(unlink_proc.returncode, 0, unlink_proc.stderr)
        self.assertEqual(unlink_data["removed_links"], 1)
        self.assertEqual(variable_proc.returncode, 0, variable_proc.stderr)
        self.assertEqual(variable_data["variable"]["after"], {"name": "points", "type": "i32"})
        self.assertEqual(group_proc.returncode, 0, group_proc.stderr)
        self.assertEqual(group_data["group_index"], 0)
        self.assertEqual(duplicate_proc.returncode, 0, duplicate_proc.stderr)
        self.assertNotEqual(
            duplicate_data["document"]["nodes"][0]["uuid"], start["node"]["uuid"]
        )
        self.assertEqual(rename_proc.returncode, 0, rename_proc.stderr)
        self.assertTrue(rename_data["path"].endswith("assets/logic/renamed.p64graph"))
        self.assertEqual(delete_proc.returncode, 0, delete_proc.stderr)
        self.assertFalse(delete_data["exists"])

    def test_import_texture_creates_asset_and_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            source = root / "crate.png"
            self.write_minimal_project(project)
            self.write_png_header(source, 32, 32)

            proc, data = self.run_json(
                "import",
                str(source),
                "--project",
                str(project),
                "--dest",
                "textures/crate.png",
                "--texture-format",
                "RGBA16",
                "--json",
            )

            target = project / "assets" / "textures" / "crate.png"
            target_exists = target.exists()
            conf = json.loads(Path(str(target) + ".conf").read_text(encoding="utf-8"))
            show_proc, show_data = self.run_json("asset", "show", "assets/textures/crate.png", "--project", str(project), "--json")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["command"], "import")
        self.assertEqual(data["source"]["kind"], "texture")
        self.assertEqual(data["target"]["relative_path"], "assets/textures/crate.png")
        self.assertTrue(target_exists)
        self.assertEqual(conf["format"], 2)
        self.assertEqual(conf["baseScale"], 16)
        self.assertIsInstance(conf["uuid"], int)
        self.assertTrue(data["validation"]["ok"])
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertTrue(show_data["ok"])
        self.assertEqual(show_data["asset"]["out_path"], "filesystem/textures/crate.sprite")

    def test_import_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            source = root / "crate.png"
            self.write_minimal_project(project)
            self.write_png_header(source, 32, 32)

            proc, data = self.run_json(
                "import",
                str(source),
                "--project",
                str(project),
                "--texture-format",
                "RGBA16",
                "--dry-run",
                "--json",
            )
            target = project / "assets" / "crate.png"
            target_exists = target.exists()
            target_conf_exists = Path(str(target) + ".conf").exists()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(data["dry_run"])
        self.assertFalse(target_exists)
        self.assertFalse(target_conf_exists)
        self.assertEqual(data["changes"][0]["action"], "would_create")
        self.assertFalse(data["artifacts"][0]["exists"])

    def test_import_refuses_existing_asset_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            source = root / "crate.png"
            self.write_minimal_project(project)
            self.write_png_header(source, 32, 32)
            target = project / "assets" / "crate.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("keep me\n", encoding="utf-8")

            proc, data = self.run_json(
                "import",
                str(source),
                "--project",
                str(project),
                "--texture-format",
                "RGBA16",
                "--json",
            )
            target_content = target.read_text(encoding="utf-8")

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertTrue(any(item["rule"] == "IMPORT_EXISTS" for item in data["issues"]))
        self.assertEqual(target_content, "keep me\n")

    def test_import_invalid_asset_fails_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            source = root / "bad.bci.png"
            self.write_minimal_project(project)
            self.write_png_header(source, 128, 128)

            proc, data = self.run_json("import", str(source), "--project", str(project), "--json")
            target = project / "assets" / "bad.bci.png"
            target_exists = target.exists()
            target_conf_exists = Path(str(target) + ".conf").exists()

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertTrue(any(item["rule"] == "T5" for item in data["issues"]))
        self.assertFalse(target_exists)
        self.assertFalse(target_conf_exists)

    def test_import_force_overwrites_and_removes_generated_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            source = root / "crate.png"
            self.write_minimal_project(project)
            self.write_png_header(source, 32, 32)
            target = project / "assets" / "crate.png"
            output = project / "filesystem" / "crate.sprite"
            target.parent.mkdir(parents=True, exist_ok=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"old")
            output.write_bytes(b"stale")

            proc, data = self.run_json(
                "import",
                str(source),
                "--project",
                str(project),
                "--texture-format",
                "RGBA16",
                "--force",
                "--json",
            )
            target_exists = target.exists()
            output_exists = output.exists()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(target_exists)
        self.assertFalse(output_exists)
        self.assertTrue(any(item["action"] == "overwritten" for item in data["changes"]))
        self.assertTrue(any(item["kind"] == "generated_output" for item in data["changes"]))

    def test_import_records_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            source = root / "crate.png"
            history = root / "history.jsonl"
            self.write_minimal_project(project)
            self.write_png_header(source, 32, 32)

            proc, data = self.run_json(
                "import",
                str(source),
                "--project",
                str(project),
                "--texture-format",
                "RGBA16",
                "--record",
                "--history-path",
                str(history),
                "--json",
            )
            rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(len(rows), 1)
        record = rows[0]
        self.assertEqual(record["command"], "import")
        self.assertEqual(record["path"], str(project / "assets" / "crate.png"))
        self.assertEqual(record["project_path"], str(project))
        self.assertTrue(any(item["kind"] == "imported_asset" for item in record["artifacts"]))

    def test_build_plan_empty_project_is_dry_run(self) -> None:
        proc, data = self.run_json("build", "--project", "n64/examples/empty", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["mode"], "dry_run")
        self.assertEqual(data["plan"]["rom"]["path"], "n64/examples/empty/p64_project.z64")
        self.assertEqual(data["validation"]["assets"]["validated"], 2)
        self.assertEqual(data["validation"]["assets"]["skipped"], 1)
        artifact_kinds = {artifact["kind"] for artifact in data["artifacts"]}
        self.assertIn("rom", artifact_kinds)
        self.assertIn("asset_texture", artifact_kinds)
        self.assertIn("scene_binary", artifact_kinds)
        self.assertIn("make", {check["name"] for check in data["toolchain"]["checks"]})

    def test_build_and_validate_all_select_the_same_non_excluded_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            self.write_included_and_excluded_textures(project)

            build_proc, build_data = self.run_json("build", "--project", str(project), "--json")
            audit_proc, audit_data = self.run_json(
                "asset", "validate-all", "--project", str(project), "--json"
            )

        self.assertEqual(build_proc.returncode, 0, build_proc.stderr)
        self.assertEqual(audit_proc.returncode, 0, audit_proc.stderr)
        selection_keys = {"selected_assets", "included", "excluded", "passed", "failed", "skipped"}
        self.assertEqual(
            {key: build_data["validation"]["assets"][key] for key in selection_keys},
            {key: audit_data["summary"][key] for key in selection_keys},
        )
        self.assertEqual(
            [item["source"] for item in build_data["plan"]["asset_outputs"]],
            ["assets/included.png"],
        )

    def test_build_plan_strict_toolchain_uses_exit_code_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_minimal_project(project, {"pathN64Inst": str(project / "missing-sdk")})
            proc, data = self.run_json("build", "--project", str(project), "--strict-toolchain", "--json")

        self.assertEqual(proc.returncode, 2)
        self.assertFalse(data["ok"])
        self.assertTrue(any(item["rule"] == "BUILD_TOOLCHAIN" for item in data["issues"]))

    def test_build_execute_uses_pyrite64_cli_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            sdk = root / "sdk"
            binary = root / "pyrite64"
            log_path = root / "argv.json"
            self.write_fake_sdk(sdk)
            self.write_minimal_project(project, {"pathN64Inst": str(sdk)})
            self.write_fake_pyrite64(binary, log_path)

            proc, data = self.run_json(
                "build",
                "--execute",
                "--project",
                str(project),
                "--pyrite64-binary",
                str(binary),
                "--json",
            )
            argv = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["mode"], "execute")
        self.assertFalse(data["dry_run"])
        self.assertTrue(data["execute"]["executed"])
        self.assertEqual(data["execute"]["returncode"], 0)
        self.assertIn("fake build ok", data["execute"]["stdout_tail"])
        self.assertEqual(argv[:3], ["--cli", "--cmd", "build"])
        self.assertEqual(Path(argv[3]).name, "project.p64proj")

    def test_build_execute_preserves_absolute_project_config_from_unrelated_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            outside = root / "outside"
            sdk = root / "sdk"
            binary = root / "pyrite64"
            log_path = root / "argv.json"
            outside.mkdir()
            self.write_fake_sdk(sdk)
            self.write_minimal_project(project, {"pathN64Inst": str(sdk)})
            self.write_fake_pyrite64(binary, log_path)
            config_path = (project / "project.p64proj").resolve()

            proc = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "build",
                    "--execute",
                    "--project",
                    str(config_path),
                    "--pyrite64-binary",
                    str(binary),
                    "--json",
                ],
                cwd=outside,
                text=True,
                capture_output=True,
                check=False,
            )
            data = json.loads(proc.stdout)
            argv = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(Path(data["project"]["config_path"]), config_path)
        self.assertEqual(Path(data["execute"]["argv"][4]), config_path)
        self.assertEqual(Path(argv[3]), config_path)

    def test_build_execute_missing_binary_uses_exit_code_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            sdk = root / "sdk"
            self.write_fake_sdk(sdk)
            self.write_minimal_project(project, {"pathN64Inst": str(sdk)})
            proc, data = self.run_json(
                "build",
                "--execute",
                "--project",
                str(project),
                "--pyrite64-binary",
                str(root / "missing-pyrite64"),
                "--json",
            )

        self.assertEqual(proc.returncode, 2)
        self.assertFalse(data["ok"])
        self.assertFalse(data["execute"]["executed"])
        self.assertTrue(any(item["rule"] == "BUILD_BINARY" for item in data["issues"]))

    def test_run_launches_existing_rom_with_emulator_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            emulator = root / "emu"
            log_path = root / "emu-argv.json"
            self.write_minimal_project(project)
            (project / "fixture.z64").write_bytes(b"rom")
            self.write_fake_emulator(emulator, log_path)

            proc, data = self.run_json("run", "--project", str(project), "--emulator", str(emulator), "--json")
            argv = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["mode"], "run")
        self.assertTrue(data["run"]["executed"])
        self.assertEqual(data["run"]["returncode"], 0)
        self.assertIn("fake emulator ok", data["run"]["stdout_tail"])
        self.assertEqual(Path(argv[-1]).name, "fixture.z64")

    def test_run_timeout_decodes_non_utf8_emulator_output_into_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            emulator = root / "emu"
            self.write_minimal_project(project)
            (project / "fixture.z64").write_bytes(b"rom")
            emulator.write_text(
                "#!/usr/bin/env python3\n"
                "import os\n"
                "import time\n"
                "os.write(1, b'BF64 byte output: \\xff marker\\n')\n"
                "time.sleep(60)\n",
                encoding="utf-8",
            )
            emulator.chmod(0o755)

            proc, data = self.run_json(
                "run", "--project", str(project), "--emulator", str(emulator),
                "--timeout", "1", "--json",
            )

        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertFalse(data["ok"])
        self.assertIn("RUN_TIMEOUT", {item["rule"] for item in data["issues"]})
        self.assertIsInstance(data["run"]["stdout_tail"], str)
        self.assertIn("BF64 byte output:", data["run"]["stdout_tail"])
        self.assertIn("marker", data["run"]["stdout_tail"])

    def test_run_completed_process_replaces_non_utf8_emulator_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            emulator = root / "emu"
            self.write_minimal_project(project)
            (project / "fixture.z64").write_bytes(b"rom")
            emulator.write_text(
                "#!/usr/bin/env python3\n"
                "import os\n"
                "os.write(2, b'completed \\xff output\\n')\n",
                encoding="utf-8",
            )
            emulator.chmod(0o755)

            proc, data = self.run_json(
                "run", "--project", str(project), "--emulator", str(emulator), "--json",
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertIsInstance(data["run"]["stderr_tail"], str)
        self.assertIn("completed", data["run"]["stderr_tail"])
        self.assertIn("output", data["run"]["stderr_tail"])

    def test_run_missing_rom_returns_user_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            proc, data = self.run_json("run", "--project", str(project), "--emulator", "echo", "--json")

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertFalse(data["run"]["executed"])
        self.assertTrue(any(item["rule"] == "RUN_ROM" for item in data["issues"]))

    def test_run_missing_emulator_returns_environment_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            self.write_minimal_project(project)
            (project / "fixture.z64").write_bytes(b"rom")
            proc, data = self.run_json("run", "--project", str(project), "--emulator", str(root / "missing-emu"), "--json")

        self.assertEqual(proc.returncode, 2)
        self.assertFalse(data["ok"])
        self.assertFalse(data["run"]["executed"])
        self.assertTrue(any(item["rule"] == "RUN_EMULATOR" for item in data["issues"]))

    def test_run_build_first_then_launches_rom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            sdk = root / "sdk"
            pyrite = root / "pyrite64"
            emulator = root / "emu"
            build_log = root / "build-argv.json"
            emu_log = root / "emu-argv.json"
            self.write_fake_sdk(sdk)
            self.write_minimal_project(project, {"pathN64Inst": str(sdk)})
            self.write_fake_pyrite64(pyrite, build_log)
            self.write_fake_emulator(emulator, emu_log)
            (project / "fixture.z64").write_bytes(b"rom")

            proc, data = self.run_json(
                "run",
                "--build",
                "--project",
                str(project),
                "--pyrite64-binary",
                str(pyrite),
                "--emulator",
                str(emulator),
                "--json",
            )
            emu_argv = json.loads(emu_log.read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["mode"], "build_then_run")
        self.assertTrue(data["build"]["execute"]["executed"])
        self.assertTrue(data["run"]["executed"])
        self.assertEqual(Path(emu_argv[-1]).name, "fixture.z64")

    def test_run_profile_captures_runtime_metrics_and_build_sizes_to_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            emulator = root / "emu"
            emu_log = root / "emu-argv.json"
            profile_path = root / "profile.json"
            self.write_minimal_project(project)
            (project / "build").mkdir()
            (project / "fixture.z64").write_bytes(b"rom-data")
            (project / "build" / "fixture.elf").write_bytes(b"elf-data-123")
            (project / "build" / "fixture.dfs").write_bytes(b"dfs-data")
            runtime_profile = self.write_fake_profile_emulator(emulator, emu_log)

            proc, data = self.run_json(
                "run",
                "--profile",
                "--profile-warmup",
                "30",
                "--profile-frames",
                "120",
                "--profile-output",
                str(profile_path),
                "--timeout",
                "5",
                "--project",
                str(project),
                "--emulator",
                str(emulator),
                "--json",
            )
            artifact = json.loads(profile_path.read_text(encoding="utf-8"))
            emu_argv = json.loads(emu_log.read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(data["profile"]["captured"])
        self.assertEqual(data["profile"]["runtime"], runtime_profile)
        self.assertEqual(artifact["schema"], "bf64.profile")
        self.assertEqual(artifact["version"], 1)
        self.assertEqual(artifact["emulator"]["version"], "fake-emu 1.2.3")
        self.assertEqual(artifact["files"]["rom"]["size_bytes"], 8)
        self.assertEqual(artifact["files"]["elf"]["size_bytes"], 12)
        self.assertEqual(artifact["files"]["dfs"]["size_bytes"], 8)
        self.assertEqual(artifact["runtime"]["frame_time_ms"]["p95"], 18.0)
        self.assertEqual(Path(emu_argv[-1]).name, "fixture.z64")
        self.assertTrue(any(item["kind"] == "profile" for item in data["artifacts"]))

    def test_profile_launch_enables_the_versioned_ares_homebrew_debug_channel(self) -> None:
        spec = importlib.util.spec_from_file_location("bf64_profile_argv_test", ROOT / "tools" / "bf64.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        project = ROOT / "n64" / "examples" / "empty"
        rom = project / "fixture.z64"

        v148 = module.prepare_emulator_argv(
            ["flatpak", "run", "dev.ares.ares"],
            project,
            rom,
            homebrew_mode=True,
            emulator_version_text="v148",
        )
        current = module.prepare_emulator_argv(
            ["ares"],
            project,
            rom,
            homebrew_mode=True,
            emulator_version_text="ares version v149",
        )

        self.assertIn("General/HomebrewMode=true", v148)
        self.assertNotIn("Developer/HomebrewMode=true", v148)
        self.assertIn("Developer/HomebrewMode=true", current)
        self.assertNotIn("General/HomebrewMode=true", current)
        self.assertEqual(v148[-1], str(rom))
        self.assertEqual(current[-1], str(rom))

    def test_flatpak_launch_resolves_relative_filesystem_and_rom_paths(self) -> None:
        spec = importlib.util.spec_from_file_location("bf64_flatpak_paths_test", ROOT / "tools" / "bf64.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        project = Path("n64/examples/empty")
        rom = project / "fixture.z64"
        argv = module.prepare_emulator_argv(
            ["flatpak", "run", "dev.ares.ares"],
            project,
            rom,
        )

        self.assertIn(f"--filesystem={project.resolve()}", argv)
        self.assertEqual(argv[-1], str(rom.resolve()))

    def test_doctor_flatpak_discovery_reports_ares_version(self) -> None:
        spec = importlib.util.spec_from_file_location("bf64_doctor_ares_test", ROOT / "tools" / "bf64.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def fake_run(argv, **_kwargs):
            if "info" in argv:
                return types.SimpleNamespace(returncode=0, stdout="Version: 148\n", stderr="")
            return types.SimpleNamespace(returncode=0, stdout="\nv148\n", stderr="")

        with (
            mock.patch.object(
                module.shutil,
                "which",
                side_effect=lambda name: "/usr/bin/flatpak" if name == "flatpak" else None,
            ),
            mock.patch.object(module.subprocess, "run", side_effect=fake_run),
        ):
            available, detail, version = module.doctor_emulator_status()

        self.assertTrue(available)
        self.assertIn("dev.ares.ares", detail)
        self.assertEqual(version, "v148")

    def test_run_build_profile_passes_sampling_configuration_to_native_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            sdk = root / "sdk"
            pyrite = root / "pyrite64"
            emulator = root / "emu"
            build_log = root / "build.json"
            emu_log = root / "emu.json"
            self.write_fake_sdk(sdk)
            self.write_minimal_project(project, {"pathN64Inst": str(sdk)})
            self.write_fake_profile_pyrite64(pyrite, build_log)
            self.write_fake_profile_emulator(emulator, emu_log)
            (project / "fixture.z64").write_bytes(b"rom")

            proc, data = self.run_json(
                "run", "--build", "--profile", "--profile-warmup", "45", "--profile-frames", "180",
                "--profile-output", str(root / "profile.json"), "--project", str(project),
                "--pyrite64-binary", str(pyrite), "--emulator", str(emulator), "--json",
            )
            build_call = json.loads(build_log.read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["profile"]["captured"])
        self.assertEqual(build_call["profile"], "1")
        self.assertEqual(build_call["warmup"], "45")
        self.assertEqual(build_call["frames"], "180")

    def test_run_profile_fails_when_emulator_exits_without_runtime_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            emulator = root / "emu"
            self.write_minimal_project(project)
            (project / "fixture.z64").write_bytes(b"rom")
            self.write_fake_emulator(emulator, root / "emu.json")

            proc, data = self.run_json(
                "run", "--profile", "--project", str(project), "--emulator", str(emulator), "--json"
            )

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["profile"]["captured"])
        self.assertTrue(any(item["rule"] == "PROFILE_CAPTURE" for item in data["issues"]))

    def test_scene_ls_empty_project(self) -> None:
        proc, data = self.run_json("scene", "ls", "--project", "n64/examples/empty", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["project"]["name"], "Pyrite64 Project")
        self.assertEqual(data["scenes"][0]["id"], 1)
        self.assertEqual(data["scenes"][0]["object_count"], 4)

    def test_scene_show_includes_raw_document(self) -> None:
        proc, data = self.run_json("scene", "show", "1", "--project", "n64/examples/empty", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["scene"]["metadata"]["name"], "Scene")
        self.assertIn("conf", data["doc"])
        self.assertIn("graph", data["doc"])

    def test_scene_create_writes_a_valid_scene_visible_through_scene_show(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)

            create_proc, create_data = self.run_json(
                "scene", "create", "Gameplay", "--project", str(project), "--json"
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "2", "--project", str(project), "--json"
            )

        self.assertEqual(create_proc.returncode, 0, create_proc.stderr)
        self.assertTrue(create_data["ok"])
        self.assertFalse(create_data["dry_run"])
        self.assertEqual(create_data["scene"]["id"], 2)
        self.assertEqual(create_data["scene"]["name"], "Gameplay")
        self.assertTrue(create_data["validation"]["ok"])
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(show_data["scene"]["metadata"]["name"], "Gameplay")
        self.assertEqual(show_data["doc"]["graph"]["children"], [])

    def test_scene_duplicate_copies_the_graph_under_a_new_id_and_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            scene_path = project / "data" / "scenes" / "1" / "scene.json"
            source_doc = json.loads(scene_path.read_text(encoding="utf-8"))
            source_doc["graph"]["children"] = [
                {"name": "Player", "uuid": 42, "components": [], "children": []}
            ]
            scene_path.write_text(json.dumps(source_doc), encoding="utf-8")

            duplicate_proc, duplicate_data = self.run_json(
                "scene",
                "duplicate",
                "1",
                "--name",
                "Gameplay Copy",
                "--project",
                str(project),
                "--json",
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "2", "--project", str(project), "--json"
            )

        self.assertEqual(duplicate_proc.returncode, 0, duplicate_proc.stderr)
        self.assertTrue(duplicate_data["ok"])
        self.assertEqual(duplicate_data["source"]["id"], 1)
        self.assertEqual(duplicate_data["scene"]["id"], 2)
        self.assertEqual(duplicate_data["scene"]["name"], "Gameplay Copy")
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(show_data["doc"]["graph"]["children"][0]["uuid"], 42)
        self.assertEqual(show_data["scene"]["metadata"]["name"], "Gameplay Copy")

    def test_scene_rename_preserves_the_scene_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            scene_path = project / "data" / "scenes" / "1" / "scene.json"
            before = json.loads(scene_path.read_text(encoding="utf-8"))["graph"]

            rename_proc, rename_data = self.run_json(
                "scene", "rename", "1", "Opening", "--project", str(project), "--json"
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "Opening", "--project", str(project), "--json"
            )

        self.assertEqual(rename_proc.returncode, 0, rename_proc.stderr)
        self.assertTrue(rename_data["ok"])
        self.assertEqual(rename_data["scene"]["id"], 1)
        self.assertEqual(rename_data["scene"]["name"], "Opening")
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(show_data["doc"]["graph"], before)

    def test_scene_delete_removes_an_unreferenced_scene_and_revalidates_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            create_proc, _create_data = self.run_json(
                "scene", "create", "Temporary", "--project", str(project), "--json"
            )

            delete_proc, delete_data = self.run_json(
                "scene", "delete", "2", "--project", str(project), "--json"
            )
            list_proc, list_data = self.run_json(
                "scene", "ls", "--project", str(project), "--json"
            )
            deleted_exists = (project / "data" / "scenes" / "2").exists()

        self.assertEqual(create_proc.returncode, 0, create_proc.stderr)
        self.assertEqual(delete_proc.returncode, 0, delete_proc.stderr)
        self.assertTrue(delete_data["ok"])
        self.assertTrue(delete_data["validation"]["ok"])
        self.assertFalse(delete_data["rolled_back"])
        self.assertFalse(deleted_exists)
        self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
        self.assertEqual([scene["id"] for scene in list_data["scenes"]], [1])

    def test_scene_object_add_generates_and_persists_a_unique_object_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)

            add_proc, add_data = self.run_json(
                "scene",
                "object",
                "add",
                "1",
                "--name",
                "Player",
                "--position",
                "1",
                "2",
                "3",
                "--project",
                str(project),
                "--json",
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        self.assertEqual(add_proc.returncode, 0, add_proc.stderr)
        self.assertTrue(add_data["ok"])
        self.assertTrue(add_data["validation"]["ok"])
        object_uuid = add_data["object"]["uuid"]
        self.assertGreater(object_uuid, 0)
        self.assertLessEqual(object_uuid, 0xFFFFFFFF)
        stored = show_data["doc"]["graph"]["children"][0]
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(stored["uuid"], object_uuid)
        self.assertEqual(stored["name"], "Player")
        self.assertEqual(stored["pos"], [1.0, 2.0, 3.0])
        self.assertNotIn("id", stored)

    def test_scene_object_update_changes_authored_properties_without_changing_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            add_proc, _add_data = self.run_json(
                "scene",
                "object",
                "add",
                "1",
                "--name",
                "Player",
                "--uuid",
                "100",
                "--project",
                str(project),
                "--json",
            )

            update_proc, update_data = self.run_json(
                "scene",
                "object",
                "update",
                "1",
                "100",
                "--name",
                "Hero",
                "--position",
                "4",
                "5",
                "6",
                "--rotation",
                "0",
                "0",
                "1",
                "0",
                "--scale",
                "2",
                "3",
                "4",
                "--no-enabled",
                "--no-selectable",
                "--project",
                str(project),
                "--json",
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        self.assertEqual(add_proc.returncode, 0, add_proc.stderr)
        self.assertEqual(update_proc.returncode, 0, update_proc.stderr)
        self.assertTrue(update_data["ok"])
        stored = show_data["doc"]["graph"]["children"][0]
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(stored["uuid"], 100)
        self.assertEqual(stored["name"], "Hero")
        self.assertEqual(stored["pos"], [4.0, 5.0, 6.0])
        self.assertEqual(stored["rot"], [0.0, 0.0, 1.0, 0.0])
        self.assertEqual(stored["scale"], [2.0, 3.0, 4.0])
        self.assertFalse(stored["enabled"])
        self.assertFalse(stored["selectable"])

    def test_scene_object_reparent_moves_an_existing_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            parent_proc, _parent_data = self.run_json(
                "scene", "object", "add", "1", "--name", "Parent", "--uuid", "10",
                "--project", str(project), "--json"
            )
            child_proc, _child_data = self.run_json(
                "scene", "object", "add", "1", "--name", "Child", "--uuid", "20",
                "--position", "7", "8", "9", "--project", str(project), "--json"
            )

            move_proc, move_data = self.run_json(
                "scene", "object", "reparent", "1", "20", "--parent", "10",
                "--project", str(project), "--json"
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        self.assertEqual(parent_proc.returncode, 0, parent_proc.stderr)
        self.assertEqual(child_proc.returncode, 0, child_proc.stderr)
        self.assertEqual(move_proc.returncode, 0, move_proc.stderr)
        self.assertTrue(move_data["ok"])
        roots = show_data["doc"]["graph"]["children"]
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual([obj["uuid"] for obj in roots], [10])
        self.assertEqual(roots[0]["children"][0]["uuid"], 20)
        self.assertEqual(roots[0]["children"][0]["pos"], [7.0, 8.0, 9.0])

    def test_scene_object_reparent_rejects_cycles_without_changing_the_scene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            self.run_json(
                "scene", "object", "add", "1", "--name", "Parent", "--uuid", "10",
                "--project", str(project), "--json"
            )
            self.run_json(
                "scene", "object", "add", "1", "--name", "Child", "--uuid", "20",
                "--parent", "10", "--project", str(project), "--json"
            )
            scene_path = project / "data" / "scenes" / "1" / "scene.json"
            before = scene_path.read_bytes()

            proc, data = self.run_json(
                "scene", "object", "reparent", "1", "10", "--parent", "20",
                "--project", str(project), "--json"
            )
            after = scene_path.read_bytes()

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertTrue(any(item["rule"] == "SCENE_REPARENT_CYCLE" for item in data["issues"]))
        self.assertEqual(after, before)

    def test_scene_object_remove_deletes_the_selected_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            self.run_json(
                "scene", "object", "add", "1", "--name", "Parent", "--uuid", "10",
                "--project", str(project), "--json"
            )
            self.run_json(
                "scene", "object", "add", "1", "--name", "Child", "--uuid", "20",
                "--parent", "10", "--project", str(project), "--json"
            )

            remove_proc, remove_data = self.run_json(
                "scene", "object", "remove", "1", "10", "--project", str(project), "--json"
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        self.assertEqual(remove_proc.returncode, 0, remove_proc.stderr)
        self.assertTrue(remove_data["ok"])
        self.assertEqual(remove_data["removed"]["uuid"], 10)
        self.assertEqual(remove_data["removed"]["object_count"], 2)
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(show_data["doc"]["graph"]["children"], [])

    def test_scene_component_add_uses_the_stable_registry_and_editor_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            self.run_json(
                "scene", "object", "add", "1", "--name", "View", "--uuid", "100",
                "--project", str(project), "--json"
            )

            add_proc, add_data = self.run_json(
                "scene", "component", "add", "1", "100", "camera",
                "--project", str(project), "--json"
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        self.assertEqual(add_proc.returncode, 0, add_proc.stderr)
        self.assertTrue(add_data["ok"])
        component_uuid = add_data["component"]["uuid"]
        self.assertGreater(component_uuid, 0)
        self.assertLessEqual(component_uuid, 0xFFFFFFFFFFFFFFFF)
        component = show_data["doc"]["graph"]["children"][0]["components"][0]
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(component["id"], 3)
        self.assertEqual(component["name"], "Camera")
        self.assertEqual(component["uuid"], component_uuid)
        self.assertEqual(component["data"]["vpOffset"], [0, 0])
        self.assertEqual(component["data"]["vpSize"], [320, 240])
        self.assertEqual(component["data"]["mode"], 1)

    def test_scene_component_update_patches_data_without_changing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            self.run_json(
                "scene", "object", "add", "1", "--name", "View", "--uuid", "100",
                "--project", str(project), "--json"
            )
            self.run_json(
                "scene", "component", "add", "1", "100", "camera", "--uuid", "500",
                "--project", str(project), "--json"
            )

            update_proc, update_data = self.run_json(
                "scene", "component", "update", "1", "100", "500",
                "--name", "Main Camera", "--data", '{"fov":75,"near":10}',
                "--project", str(project), "--json"
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        self.assertEqual(update_proc.returncode, 0, update_proc.stderr)
        self.assertTrue(update_data["ok"])
        component = show_data["doc"]["graph"]["children"][0]["components"][0]
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(component["id"], 3)
        self.assertEqual(component["uuid"], 500)
        self.assertEqual(component["name"], "Main Camera")
        self.assertEqual(component["data"]["fov"], 75)
        self.assertEqual(component["data"]["near"], 10)
        self.assertEqual(component["data"]["far"], 4000.0)

    def test_scene_component_remove_targets_one_component_by_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            self.run_json(
                "scene", "object", "add", "1", "--name", "Actor", "--uuid", "100",
                "--project", str(project), "--json"
            )
            self.run_json(
                "scene", "component", "add", "1", "100", "camera", "--uuid", "500",
                "--project", str(project), "--json"
            )
            self.run_json(
                "scene", "component", "add", "1", "100", "light", "--uuid", "600",
                "--project", str(project), "--json"
            )

            remove_proc, remove_data = self.run_json(
                "scene", "component", "remove", "1", "100", "500",
                "--project", str(project), "--json"
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        self.assertEqual(remove_proc.returncode, 0, remove_proc.stderr)
        self.assertTrue(remove_data["ok"])
        self.assertEqual(remove_data["removed"]["uuid"], 500)
        components = show_data["doc"]["graph"]["children"][0]["components"]
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual([(component["id"], component["uuid"]) for component in components], [(2, 600)])

    def test_scene_attach_ui_resolves_the_document_asset_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            self.run_json(
                "scene", "object", "add", "1", "--name", "HUD", "--uuid", "100",
                "--project", str(project), "--json"
            )
            ui_proc, _ui_data = self.run_json(
                "ui", "new", "hud", "--project", str(project), "--json"
            )
            ui_path = project / "assets" / "hud.bfui"
            ui_uuid = json.loads(Path(str(ui_path) + ".conf").read_text(encoding="utf-8"))["uuid"]

            attach_proc, attach_data = self.run_json(
                "scene", "attach", "ui", "1", "100", "assets/hud.bfui",
                "--project", str(project), "--json"
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        self.assertEqual(ui_proc.returncode, 0, ui_proc.stderr)
        self.assertEqual(attach_proc.returncode, 0, attach_proc.stderr)
        self.assertTrue(attach_data["ok"])
        self.assertEqual(attach_data["command"], "scene attach")
        component = show_data["doc"]["graph"]["children"][0]["components"][0]
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(component["id"], 13)
        self.assertEqual(component["data"], {"document": ui_uuid, "layer": 0, "active": True})

    def test_scene_object_component_ui_round_trip_is_stable_and_removable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            ui_proc, _ui_data = self.run_json(
                "ui", "new", "hud", "--project", str(project), "--json"
            )
            add_proc, _add_data = self.run_json(
                "scene", "object", "add", "1", "--name", "HUD", "--uuid", "100",
                "--position", "1", "2", "3", "--project", str(project), "--json"
            )
            attach_proc, attach_data = self.run_json(
                "scene", "attach", "ui", "1", "100", "assets/hud.bfui",
                "--project", str(project), "--json"
            )
            component_uuid = attach_data["component"]["uuid"]
            update_object_proc, _update_object_data = self.run_json(
                "scene", "object", "update", "1", "100", "--name", "Gameplay HUD",
                "--position", "4", "5", "6", "--rotation", "0", "0", "0", "1",
                "--scale", "2", "2", "2", "--project", str(project), "--json"
            )
            update_component_proc, _update_component_data = self.run_json(
                "scene", "component", "update", "1", "100", str(component_uuid),
                "--data", '{"layer":2,"active":false}', "--project", str(project), "--json"
            )
            first_show_proc, first_show = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )
            second_show_proc, second_show = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )
            validate_proc, validate_data = self.run_json(
                "validate", str(project / "project.p64proj"), "--json"
            )
            remove_component_proc, _remove_component_data = self.run_json(
                "scene", "component", "remove", "1", "100", str(component_uuid),
                "--project", str(project), "--json"
            )
            remove_object_proc, _remove_object_data = self.run_json(
                "scene", "object", "remove", "1", "100", "--project", str(project), "--json"
            )
            final_show_proc, final_show = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        for proc in (
            ui_proc,
            add_proc,
            attach_proc,
            update_object_proc,
            update_component_proc,
            first_show_proc,
            second_show_proc,
            validate_proc,
            remove_component_proc,
            remove_object_proc,
            final_show_proc,
        ):
            self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(validate_data["ok"])
        self.assertEqual(first_show["doc"], second_show["doc"])
        stored = first_show["doc"]["graph"]["children"][0]
        self.assertEqual(stored["uuid"], 100)
        self.assertEqual(stored["name"], "Gameplay HUD")
        self.assertEqual(stored["pos"], [4.0, 5.0, 6.0])
        self.assertEqual(stored["rot"], [0.0, 0.0, 0.0, 1.0])
        self.assertEqual(stored["scale"], [2.0, 2.0, 2.0])
        self.assertEqual(len(stored["components"]), 1)
        self.assertEqual(stored["components"][0]["uuid"], component_uuid)
        self.assertEqual(stored["components"][0]["data"]["layer"], 2)
        self.assertIs(stored["components"][0]["data"]["active"], False)
        self.assertEqual(final_show["doc"]["graph"]["children"], [])

    def test_scene_attach_audio3d_resolves_audio_and_spatial_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            audio = project / "assets" / "sfx" / "dog.wav"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            Path(str(audio) + ".conf").write_text(json.dumps({"uuid": 7001}), encoding="utf-8")
            self.run_json(
                "scene", "object", "add", "1", "--name", "Dog", "--uuid", "100",
                "--project", str(project), "--json"
            )

            attach_proc, attach_data = self.run_json(
                "scene", "attach", "audio3d", "1", "100", "sfx/dog.wav",
                "--data", '{"maxDistance":750,"autoPlay":true}',
                "--project", str(project), "--json"
            )

        self.assertEqual(attach_proc.returncode, 0, attach_proc.stderr)
        self.assertTrue(attach_data["ok"])
        self.assertEqual(attach_data["component"]["id"], 14)
        self.assertEqual(attach_data["attachment"]["uuid"], 7001)
        self.assertEqual(
            attach_data["component"]["data"],
            {
                "audioUUID": 7001,
                "volume": 1.0,
                "loop": False,
                "autoPlay": True,
                "minDistance": 50.0,
                "maxDistance": 750,
                "rolloff": 1.0,
                "pitch": 1.0,
            },
        )

    def test_scene_attach_audio3d_rejects_xm_music_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            music = project / "assets" / "music" / "theme.xm"
            music.parent.mkdir(parents=True)
            music.write_bytes(b"Extended Module: fixture")
            Path(str(music) + ".conf").write_text(
                json.dumps({"uuid": 7002}), encoding="utf-8"
            )
            self.run_json(
                "scene", "object", "add", "1", "--name", "Radio", "--uuid", "100",
                "--project", str(project), "--json"
            )

            attach_proc, attach_data = self.run_json(
                "scene", "attach", "audio3d", "1", "100", "music/theme.xm",
                "--project", str(project), "--json"
            )

        self.assertEqual(attach_proc.returncode, 1, attach_proc.stderr)
        self.assertFalse(attach_data["ok"])
        self.assertTrue(
            any(issue["rule"] == "SCENE_COMPONENT_ASSET" for issue in attach_data["issues"])
        )

    def test_scene_attach_maps_camera_model_collision_and_light_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            assets = project / "assets"
            assets.mkdir()
            model = assets / "actor.glb"
            model.write_bytes(b"fixture")
            Path(str(model) + ".conf").write_text(json.dumps({"uuid": 9001}), encoding="utf-8")
            self.run_json(
                "scene", "object", "add", "1", "--name", "Actor", "--uuid", "100",
                "--project", str(project), "--json"
            )

            calls = [
                ("camera", None),
                ("model", "assets/actor.glb"),
                ("collision-mesh", "assets/actor.glb"),
                ("collider", None),
                ("light", None),
            ]
            results = []
            for kind, reference in calls:
                argv = ["scene", "attach", kind, "1", "100"]
                if reference:
                    argv.append(reference)
                argv.extend(["--project", str(project), "--json"])
                results.append(self.run_json(*argv))
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        for proc, data in results:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(data["ok"])
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        components = show_data["doc"]["graph"]["children"][0]["components"]
        self.assertEqual([component["id"] for component in components], [3, 1, 4, 5, 2])
        self.assertEqual(components[1]["data"]["model"], 9001)
        self.assertEqual(components[2]["data"]["modelUUID"], 9001)

    def test_scene_attach_code_resolves_object_script_uuid_and_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            script = project / "src" / "user" / "Player.cpp"
            script.parent.mkdir(parents=True)
            script.write_text(
                "namespace P64::Script::C0123456789ABCDE {\n"
                "P64_DATA(float speed;);\n"
                "}\n",
                encoding="utf-8",
            )
            self.run_json(
                "scene", "object", "add", "1", "--name", "Player", "--uuid", "100",
                "--project", str(project), "--json"
            )

            attach_proc, attach_data = self.run_json(
                "scene", "attach", "code", "1", "100", "src/user/Player.cpp",
                "--args", '{"speed":"3.5"}', "--project", str(project), "--json"
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        self.assertEqual(attach_proc.returncode, 0, attach_proc.stderr)
        self.assertTrue(attach_data["ok"])
        component = show_data["doc"]["graph"]["children"][0]["components"][0]
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(component["id"], 0)
        self.assertEqual(component["data"]["script"], int("C0123456789ABCDE", 16))
        self.assertEqual(component["data"]["args"], {"speed": "3.5"})

    def test_scene_component_update_reassigns_assets_by_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            assets = project / "assets"
            assets.mkdir()
            for name, asset_uuid in (("a.glb", 9001), ("b.glb", 9002)):
                asset = assets / name
                asset.write_bytes(b"fixture")
                Path(str(asset) + ".conf").write_text(json.dumps({"uuid": asset_uuid}), encoding="utf-8")
            self.run_json(
                "scene", "object", "add", "1", "--name", "Actor", "--uuid", "100",
                "--project", str(project), "--json"
            )
            self.run_json(
                "scene", "attach", "model", "1", "100", "assets/a.glb", "--uuid", "500",
                "--project", str(project), "--json"
            )

            update_proc, update_data = self.run_json(
                "scene", "component", "update", "1", "100", "500",
                "--asset", "assets/b.glb", "--project", str(project), "--json"
            )
            show_proc, show_data = self.run_json(
                "scene", "show", "1", "--project", str(project), "--json"
            )

        self.assertEqual(update_proc.returncode, 0, update_proc.stderr)
        self.assertTrue(update_data["ok"])
        component = show_data["doc"]["graph"]["children"][0]["components"][0]
        self.assertEqual(show_proc.returncode, 0, show_proc.stderr)
        self.assertEqual(component["id"], 1)
        self.assertEqual(component["uuid"], 500)
        self.assertEqual(component["data"]["model"], 9002)

    def test_scene_mutation_dry_run_records_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "game"
            history = root / "history.jsonl"
            self.write_minimal_project(project)
            scene_path = project / "data" / "scenes" / "1" / "scene.json"
            before = scene_path.read_bytes()

            proc, data = self.run_json(
                "scene", "object", "add", "1", "--name", "Preview", "--dry-run",
                "--record", "--history-path", str(history), "--project", str(project), "--json"
            )
            after = scene_path.read_bytes()
            records = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["changes"][0]["action"], "would_update")
        self.assertEqual(after, before)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["command"], "scene object add")
        self.assertEqual(records[0]["exit_code"], 0)

    @unittest.skipIf(sys.platform == "win32", "POSIX permissions are required to force a transactional write failure")
    def test_scene_delete_rolls_back_when_project_reference_update_cannot_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            create_proc, _create_data = self.run_json(
                "scene", "create", "Replacement", "--project", str(project), "--json"
            )
            config_path = project / "project.p64proj"
            original_config = config_path.read_bytes()
            project.chmod(0o555)
            try:
                proc, data = self.run_json(
                    "scene", "delete", "1", "--replacement", "2",
                    "--project", str(project), "--json"
                )
            finally:
                project.chmod(0o755)
            restored_config = config_path.read_bytes()
            scene_restored = (project / "data" / "scenes" / "1" / "scene.json").is_file()

        self.assertEqual(create_proc.returncode, 0, create_proc.stderr)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertTrue(data["rolled_back"])
        self.assertTrue(any(item["rule"] == "SCENE_ROLLBACK" for item in data["issues"]))
        self.assertTrue(scene_restored)
        self.assertEqual(restored_config, original_config)

    def test_scene_delete_atomically_retargets_project_scene_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "game"
            self.write_minimal_project(project)
            self.run_json("scene", "create", "Replacement", "--project", str(project), "--json")

            proc, data = self.run_json(
                "scene", "delete", "1", "--replacement", "2",
                "--project", str(project), "--json"
            )
            config = json.loads((project / "project.p64proj").read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertFalse(data["rolled_back"])
        self.assertEqual(data["replacement"]["id"], 2)
        self.assertEqual(config["sceneIdOnBoot"], 2)
        self.assertEqual(config["sceneIdOnReset"], 2)
        self.assertEqual(config["sceneIdLastOpened"], 2)
        self.assertTrue(data["validation"]["ok"])

    def test_bigtex_texture_wrong_pipeline_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.bci.png"
            self.write_png_header(path, 256, 256)
            proc, data = self.run_json("validate", str(path), "--scene-pipeline", "default", "--json")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertEqual(data["issues"][0]["rule"], "T6")

    def test_project_validation_catches_duplicate_scene_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_minimal_project(project)
            scene = {
                "conf": {"name": "Scene", "renderPipeline": 0},
                "graph": {
                    "children": [
                        {"name": "A", "uuid": 123, "components": [], "children": []},
                        {"name": "B", "uuid": 123, "components": [], "children": []},
                    ]
                },
            }
            (project / "data" / "scenes" / "1" / "scene.json").write_text(json.dumps(scene), encoding="utf-8")

            proc, data = self.run_json("validate", str(project / "project.p64proj"), "--json")

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(data["ok"])
        self.assertIn("Duplicate scene object uuid 123", data["issues"][0]["message"])

    def test_scene_validation_rejects_duplicate_component_uuids_and_malformed_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_minimal_project(project)
            scene_path = project / "data" / "scenes" / "1" / "scene.json"
            scene = json.loads(scene_path.read_text(encoding="utf-8"))
            scene["graph"]["children"] = [
                {
                    "name": "Actor",
                    "uuid": 123,
                    "components": [
                        {"id": 2, "uuid": 500, "name": "Light", "data": {}},
                        {"id": 3, "uuid": 500, "name": "Camera", "data": []},
                    ],
                    "children": [],
                }
            ]
            scene_path.write_text(json.dumps(scene), encoding="utf-8")

            proc, data = self.run_json(
                "scene", "validate", "1", "--project", str(project), "--json"
            )

        self.assertEqual(proc.returncode, 1)
        rules = [item["rule"] for item in data["issues"]]
        self.assertIn("SCENE_COMPONENT_UUID", rules)
        self.assertIn("SCENE_COMPONENT_DATA", rules)

    def test_doctor_default_keeps_optional_toolchain_as_warnings(self) -> None:
        proc, data = self.run_json("doctor", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(any(check["name"] == "python" for check in data["checks"]))

    def test_toolchain_detect_uses_explicit_sdk_without_requiring_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdk = Path(tmp) / "libdragon-sdk"
            self.write_fake_sdk(sdk)

            proc, data = self.run_json("toolchain", "detect", "--prefix", str(sdk), "--json")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(data["toolchain"]["build_ready"])
        self.assertEqual(data["toolchain"]["effective_N64_INST"], str(sdk.resolve()))
        self.assertEqual(data["toolchain"]["source"], "explicit")
        mksprite = next(check for check in data["toolchain"]["checks"] if check["name"] == "mksprite")
        self.assertEqual(mksprite["detail"], str(sdk.resolve() / "bin" / "mksprite"))

    def test_doctor_fix_persists_sdk_to_project_and_shell_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            self.write_minimal_project(project)
            sdk = Path(tmp) / "libdragon-sdk"
            self.write_fake_sdk(sdk)

            proc, data = self.run_json(
                "doctor",
                "--project",
                str(project),
                "--n64-inst",
                str(sdk),
                "--fix",
                "--json",
            )

            config = json.loads((project / "project.p64proj").read_text(encoding="utf-8"))
            env_text = (project / ".bf64" / "env.sh").read_text(encoding="utf-8")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(data["fix"]["applied"])
        self.assertEqual(config["pathN64Inst"], str(sdk.resolve()))
        self.assertIn(f"export N64_INST={str(sdk.resolve())!r}", env_text)
        self.assertIn('export PATH="$N64_INST/bin:$PATH"', env_text)
        self.assertTrue(data["toolchain"]["build_ready"])
        self.assertEqual(data["fix"]["environment_file"], str(project / ".bf64" / "env.sh"))

    def test_doctor_fix_rolls_back_both_files_when_post_write_validation_fails(self) -> None:
        spec = importlib.util.spec_from_file_location("bf64_tool_for_test", ROOT / "tools" / "bf64.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            self.write_minimal_project(project, {"pathN64Inst": "/keep/original/sdk"})
            sdk = Path(tmp) / "libdragon-sdk"
            self.write_fake_sdk(sdk)
            env_path = project / ".bf64" / "env.sh"
            env_path.parent.mkdir(parents=True)
            env_path.write_text("# keep original\n", encoding="utf-8")
            config_path = project / "project.p64proj"
            original_config = config_path.read_bytes()
            original_env = env_path.read_bytes()

            def reject_final_status(*_args, **_kwargs):
                return {
                    "build_ready": False,
                    "issues": [module.issue("error", "BUILD_TOOLCHAIN", "simulated final validation failure")],
                }

            module.build_toolchain_status = reject_final_status
            result, returned_config, _returned_path, issues = module.apply_doctor_fix(
                str(project), str(sdk), False
            )

            self.assertEqual(config_path.read_bytes(), original_config)
            self.assertEqual(env_path.read_bytes(), original_env)

        self.assertFalse(result["applied"])
        self.assertTrue(result["rolled_back"])
        self.assertEqual(returned_config["pathN64Inst"], "/keep/original/sdk")
        self.assertIn("DOCTOR_FIX_VALIDATION", {item["rule"] for item in issues})

    def test_toolchain_install_executes_auditable_libdragon_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "libdragon"
            source.mkdir()
            (source / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
            sdk = root / "libdragon-sdk"
            self.write_fake_sdk(sdk)
            log = root / "make-log.jsonl"
            fake_make = root / "fake-make"
            fake_make.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                f"path = Path({str(log)!r})\n"
                "with path.open('a', encoding='utf-8') as fh:\n"
                "    fh.write(json.dumps({'argv': sys.argv[1:], 'n64_inst': os.environ.get('N64_INST')}) + '\\n')\n",
                encoding="utf-8",
            )
            fake_make.chmod(0o755)

            proc, data = self.run_json(
                "toolchain",
                "install",
                "--source",
                str(source),
                "--prefix",
                str(sdk),
                "--make-binary",
                str(fake_make),
                "--skip-tiny3d",
                "--json",
            )
            rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertFalse(data["dry_run"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["argv"], ["-C", str(source), "install", "tools-install"])
        self.assertEqual(rows[0]["n64_inst"], str(sdk.resolve()))
        self.assertTrue(data["toolchain"]["build_ready"])
        self.assertTrue(data["steps"][0]["executed"])

    def test_toolchain_install_dry_run_never_executes_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "libdragon"
            source.mkdir()
            (source / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
            bootstrap = source / "tools" / "build-toolchain.sh"
            bootstrap.parent.mkdir()
            bootstrap.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            sdk = root / "sdk"
            log = root / "should-not-exist"
            fake_make = root / "fake-make"
            fake_make.write_text(
                "#!/bin/sh\n"
                f"touch {str(log)!r}\n",
                encoding="utf-8",
            )
            fake_make.chmod(0o755)

            proc, data = self.run_json(
                "toolchain",
                "install",
                "--source",
                str(source),
                "--prefix",
                str(sdk),
                "--make-binary",
                str(fake_make),
                "--dry-run",
                "--json",
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(data["dry_run"])
        self.assertFalse(log.exists())
        self.assertTrue(all(not step["executed"] for step in data["steps"]))

    def test_native_save_service_handles_slots_corruption_erase_and_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eeprom.h").write_text(
                "#pragma once\n"
                "#include <cstddef>\n"
                "#include <cstdint>\n"
                "enum eeprom_type_t { EEPROM_NONE = 0, EEPROM_4K = 1, EEPROM_16K = 2 };\n"
                "constexpr std::size_t EEPROM_BLOCK_SIZE = 8;\n"
                "extern \"C\" eeprom_type_t eeprom_present();\n"
                "extern \"C\" std::size_t eeprom_total_blocks();\n"
                "extern \"C\" void eeprom_read(std::uint8_t, std::uint8_t*);\n"
                "extern \"C\" std::uint8_t eeprom_write(std::uint8_t, const std::uint8_t*);\n"
                "extern \"C\" void eeprom_read_bytes(std::uint8_t*, std::size_t, std::size_t);\n"
                "extern \"C\" void eeprom_write_bytes(const std::uint8_t*, std::size_t, std::size_t);\n",
                encoding="utf-8",
            )
            harness = root / "save_test.cpp"
            harness.write_text(
                r'''
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include "save/saveManager.h"
#include "save/flashramDriver.h"
#include "eeprom.h"

namespace {
std::array<std::uint8_t, 2048> storage{};
eeprom_type_t type = EEPROM_4K;
std::size_t capacity() { return type == EEPROM_16K ? 2048 : type == EEPROM_4K ? 512 : 0; }

bool migrate(
    std::uint16_t fromVersion,
    const void *source,
    std::size_t sourceSize,
    std::uint16_t toVersion,
    void *destination,
    std::size_t destinationCapacity,
    std::size_t &destinationSize) {
  if(fromVersion != 1 || toVersion != 2 || sourceSize != sizeof(std::uint32_t)
      || destinationCapacity < sizeof(std::uint32_t) * 2) return false;
  auto oldValue = *static_cast<const std::uint32_t*>(source);
  auto *out = static_cast<std::uint32_t*>(destination);
  out[0] = oldValue;
  out[1] = 99;
  destinationSize = sizeof(std::uint32_t) * 2;
  return true;
}
}

extern "C" eeprom_type_t eeprom_present() { return type; }
extern "C" std::size_t eeprom_total_blocks() { return capacity() / EEPROM_BLOCK_SIZE; }
extern "C" void eeprom_read(std::uint8_t block, std::uint8_t *dest) {
  std::memcpy(dest, storage.data() + static_cast<std::size_t>(block) * EEPROM_BLOCK_SIZE, EEPROM_BLOCK_SIZE);
}
extern "C" std::uint8_t eeprom_write(std::uint8_t block, const std::uint8_t *src) {
  std::memcpy(storage.data() + static_cast<std::size_t>(block) * EEPROM_BLOCK_SIZE, src, EEPROM_BLOCK_SIZE);
  return 0;
}
extern "C" void eeprom_read_bytes(std::uint8_t *dest, std::size_t start, std::size_t len) {
  std::memcpy(dest, storage.data() + start, len);
}
extern "C" void eeprom_write_bytes(const std::uint8_t *src, std::size_t start, std::size_t len) {
  std::memcpy(storage.data() + start, src, len);
}
extern "C" bool bf64_flashram_init(const bf64_flashram_timings_t*, bf64_flashram_info_t*) { return false; }
extern "C" int bf64_flashram_read(void*, std::size_t, std::size_t) { return -1; }
extern "C" int bf64_flashram_write(const void*, std::size_t, std::size_t) { return -1; }

int main() {
  using namespace P64::Save;
  storage.fill(0xFF);

  Config config{};
  config.slotCount = 1;
  config.payloadCapacity = 232;
  config.schemaVersion = 1;
  assert(init(config) == Status::Ok);
  assert(info().eepromBytes == 512);
  assert(info().slotCount == 1);
  assert(info().payloadCapacity == 232);
  close();
  config.payloadCapacity = 233;
  assert(init(config) == Status::InvalidConfig);

  storage.fill(0xFF);
  config.payloadCapacity = 32;
  assert(init(config) == Status::Ok);
  std::array<std::uint8_t, 4> first{1, 2, 3, 4};
  std::array<std::uint8_t, 4> second{5, 6, 7, 8};
  assert(write(0, first.data(), first.size()) == Status::Ok);
  assert(write(0, second.data(), second.size()) == Status::Ok);
  std::array<std::uint8_t, 32> out{};
  auto readResult = read(0, out.data(), out.size());
  assert(readResult.status == Status::Ok && readResult.generation == 2);
  assert(readResult.size == second.size() && std::memcmp(out.data(), second.data(), second.size()) == 0);

  // Two 56-byte banks: corrupt the newest bank's payload and recover bank 0.
  storage[56 + 24] ^= 0x80;
  out.fill(0);
  readResult = read(0, out.data(), out.size());
  assert(readResult.status == Status::Ok && readResult.recovered && readResult.generation == 1);
  assert(std::memcmp(out.data(), first.data(), first.size()) == 0);

  assert(erase(0) == Status::Ok);
  readResult = read(0, out.data(), out.size());
  assert(readResult.status == Status::Empty);
  close();
  assert(init(config) == Status::Ok);
  assert(read(0, out.data(), out.size()).status == Status::Empty);

  storage.fill(0xFF);
  std::uint32_t oldValue = 42;
  assert(write(0, &oldValue, sizeof(oldValue)) == Status::Ok);
  close();
  config.schemaVersion = 2;
  config.migrate = migrate;
  assert(init(config) == Status::Ok);
  std::array<std::uint32_t, 2> migrated{};
  readResult = read(0, migrated.data(), sizeof(migrated));
  assert(readResult.status == Status::Ok && readResult.migrated);
  assert(readResult.storedVersion == 1 && readResult.version == 2);
  assert(migrated[0] == 42 && migrated[1] == 99);
  close();
  config.migrate = nullptr;
  assert(init(config) == Status::Ok);
  migrated.fill(0);
  readResult = read(0, migrated.data(), sizeof(migrated));
  assert(readResult.status == Status::Ok && !readResult.migrated && readResult.storedVersion == 2);
  assert(migrated[0] == 42 && migrated[1] == 99);

  storage.fill(0xFF);
  type = EEPROM_16K;
  close();
  config.payloadCapacity = 512;
  config.schemaVersion = 1;
  assert(init(config) == Status::Ok);
  assert(info().eepromBytes == 2048 && info().requiredBytes == 1072);

  type = EEPROM_NONE;
  close();
  assert(init(config) == Status::NoEeprom);
  assert(statusName(Status::Corrupt) != nullptr);
  return 0;
}
''',
                encoding="utf-8",
            )
            binary = root / "save_test"
            compile_proc = subprocess.run(
                [
                    "g++",
                    "-std=c++20",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(root),
                    "-I",
                    str(ROOT / "n64" / "engine" / "include"),
                    str(ROOT / "n64" / "engine" / "src" / "save" / "saveManager.cpp"),
                    str(harness),
                    "-o",
                    str(binary),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compile_proc.returncode, 0, compile_proc.stderr)
            run_proc = subprocess.run(
                [str(binary)], cwd=ROOT, text=True, capture_output=True, check=False
            )

        self.assertEqual(run_proc.returncode, 0, run_proc.stderr)

    def test_native_asset_conf_accepts_minimal_exclusion_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness = root / "asset_conf_test.cpp"
            harness.write_text(
                r'''
#include <cassert>
#include <cstdint>
#include "project/assetConf.h"

int main() {
  Project::AssetConf conf{};
  const std::uint64_t uuid = 18446744073709550001ULL;
  nlohmann::json minimal = {{"uuid", uuid}, {"exclude", true}};
  conf.deserialize(minimal);
  assert(conf.uuid == uuid);
  assert(conf.exclude);
  assert(conf.format == 0);
  assert(conf.baseScale == 16);
  assert(conf.compression == Project::ComprTypes::DEFAULT);
  assert(conf.data.is_object());

  conf.format = 7;
  conf.gltfBVH = true;
  conf.wavResampleRate.value = 22050;
  conf.fontId.value = 3;
  nlohmann::json wrongTypes = {
    {"uuid", -1},
    {"format", nullptr},
    {"baseScale", 1.5},
    {"gltfBVH", "not-a-boolean"},
    {"wavResampleRate", -1},
    {"fontId", -1},
    {"exclude", true},
    {"data", "not-an-object"},
  };
  conf.deserialize(wrongTypes);
  assert(conf.uuid == uuid);
  assert(conf.format == 7);
  assert(conf.baseScale == 16);
  assert(conf.gltfBVH);
  assert(conf.wavResampleRate.value == 22050);
  assert(conf.fontId.value == 3);
  assert(conf.exclude);
  assert(conf.data.is_object());
  return 0;
}
''',
                encoding="utf-8",
            )
            binary = root / "asset_conf_test"
            compile_proc = subprocess.run(
                [
                    "g++", "-std=c++23", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "src"),
                    "-I", str(ROOT / "vendored" / "glm"),
                    "-I", str(ROOT / "vendored" / "SHA256" / "include"),
                    "-I", str(ROOT / "vendored" / "tiny3d" / "tools" / "gltf_importer" / "src" / "lib"),
                    str(harness), "-o", str(binary),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compile_proc.returncode, 0, compile_proc.stderr)
            run_proc = subprocess.run(
                [str(binary)], cwd=ROOT, text=True, capture_output=True, check=False
            )

        self.assertEqual(run_proc.returncode, 0, run_proc.stderr)

    def test_native_spatial_audio_math_applies_distance_rolloff_and_stereo_pan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness = root / "spatial_test.cpp"
            harness.write_text(
                r'''
#include <cassert>
#include <cmath>
#include "audio/spatialAudio.h"

bool closeEnough(float a, float b) { return std::fabs(a - b) < 0.001f; }

int main() {
  using namespace P64::Audio::Spatial;
  Listener listener{};
  listener.position = {0, 0, 0};
  listener.forward = {0, 0, -1};
  listener.up = {0, 1, 0};
  Settings settings{};
  settings.minDistance = 10;
  settings.maxDistance = 110;
  settings.rolloff = 1;

  auto center = calculate({0, 0, -10}, listener, settings);
  assert(closeEnough(center.distance, 10));
  assert(closeEnough(center.attenuation, 1));
  assert(closeEnough(center.pan, 0.5f));
  assert(closeEnough(center.left, std::sqrt(0.5f)));
  assert(closeEnough(center.right, std::sqrt(0.5f)));

  auto right = calculate({60, 0, 0}, listener, settings);
  assert(closeEnough(right.attenuation, 0.5f));
  assert(closeEnough(right.pan, 1));
  assert(closeEnough(right.left, 0));
  assert(closeEnough(right.right, 0.5f));

  auto left = calculate({-60, 0, 0}, listener, settings);
  assert(closeEnough(left.pan, 0));
  assert(closeEnough(left.left, 0.5f));
  assert(closeEnough(left.right, 0));

  settings.rolloff = 2;
  auto curved = calculate({0, 0, -60}, listener, settings);
  assert(closeEnough(curved.attenuation, 0.25f));
  auto far = calculate({0, 0, -111}, listener, settings);
  assert(closeEnough(far.attenuation, 0));

  settings.minDistance = 20;
  settings.maxDistance = 20;
  auto invalidRange = calculate({0, 0, -20}, listener, settings);
  assert(closeEnough(invalidRange.attenuation, 1));
  auto outsideInvalidRange = calculate({0, 0, -21}, listener, settings);
  assert(closeEnough(outsideInvalidRange.attenuation, 0));
  return 0;
}
''',
                encoding="utf-8",
            )
            binary = root / "spatial_test"
            compile_proc = subprocess.run(
                [
                    "g++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "n64" / "engine" / "include"),
                    str(ROOT / "n64" / "engine" / "src" / "audio" / "spatialAudio.cpp"),
                    str(harness), "-o", str(binary),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compile_proc.returncode, 0, compile_proc.stderr)
            run_proc = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, check=False)

        self.assertEqual(run_proc.returncode, 0, run_proc.stderr)

    def test_native_ui_text_contract_and_utf8_input_editing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness = root / "ui_text_test.cpp"
            harness.write_text(
                r'''
#include <cassert>
#include <string>
#include "ui/documentFormat.h"
#include "ui/utf8.h"

int main() {
  using namespace P64::UI;
  using Format::ElementType;
  static_assert(Format::supportsText(ElementType::TEXT));
  static_assert(Format::supportsText(ElementType::BUTTON));
  static_assert(Format::supportsText(ElementType::TEXT_INPUT));
  static_assert(!Format::supportsText(ElementType::CONTAINER));
  static_assert(!Format::supportsText(ElementType::IMAGE));
  static_assert(!Format::supportsText(ElementType::PROGRESS_BAR));

  constexpr const char *charset = "A\xE2\x98\x95\xC3\xA9";
  assert(Utf8::count(charset) == 3);
  Utf8::Codepoint coffee{};
  assert(Utf8::at(charset, 1, coffee));
  assert(coffee.bytes == 3);
  assert(std::string(coffee.data, coffee.bytes) == "\xE2\x98\x95");

  std::string value = "\xC3\xA9";
  assert(Utf8::appendCodepoint(value, charset, 1, 2));
  assert(value == "\xC3\xA9\xE2\x98\x95");
  assert(!Utf8::appendCodepoint(value, charset, 0, 2));
  assert(Utf8::eraseLastCodepoint(value));
  assert(value == "\xC3\xA9");
  assert(Utf8::eraseLastCodepoint(value));
  assert(value.empty());
  assert(!Utf8::eraseLastCodepoint(value));
  return 0;
}
''',
                encoding="utf-8",
            )
            binary = root / "ui_text_test"
            compile_proc = subprocess.run(
                [
                    "g++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "n64" / "engine" / "include"),
                    str(ROOT / "n64" / "engine" / "src" / "ui" / "utf8.cpp"),
                    str(harness), "-o", str(binary),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compile_proc.returncode, 0, compile_proc.stderr)
            run_proc = subprocess.run(
                [str(binary)], cwd=ROOT, text=True, capture_output=True, check=False
            )

        self.assertEqual(run_proc.returncode, 0, run_proc.stderr)

    def test_native_dialogue_runner_sequences_utf8_text_and_auto_advance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness = root / "dialogue_test.cpp"
            harness.write_text(
                r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>
#include "ui/dialogue.h"

namespace {
struct SinkState {
  std::string speaker;
  std::string text;
  std::vector<P64::UI::DialogueEvent> events;
};

bool setText(void *context, std::uint32_t element, const char *value) {
  auto &state = *static_cast<SinkState*>(context);
  if(element == 10) state.text = value;
  else if(element == 11) state.speaker = value;
  else return false;
  return true;
}

void onEvent(void *context, P64::UI::DialogueEvent event, std::size_t) {
  static_cast<SinkState*>(context)->events.push_back(event);
}
}

int main() {
  using namespace P64::UI;
  SinkState sink{};
  DialogueRunner runner{};
  runner.bind(setText, &sink, 10, 11);
  runner.setEventSink(onEvent, &sink);
  DialogueLine lines[]{
    {.speaker="Ada", .text="Hi \xE2\x98\x95!", .charactersPerSecond=2.0f, .holdSeconds=-1.0f},
    {.speaker="", .text="Done", .charactersPerSecond=0.0f, .holdSeconds=0.5f},
  };
  DialogueSettings settings{};
  settings.charactersPerSecond = 4.0f;
  settings.holdSeconds = -1.0f;
  settings.clearOnComplete = true;

  assert(runner.start(lines, 2, settings));
  assert(runner.state() == DialogueState::Typing);
  assert(runner.currentLine() == 0);
  assert(sink.speaker == "Ada" && sink.text.empty());

  runner.update(0.49f);
  assert(sink.text.empty());
  runner.update(0.01f);
  assert(sink.text == "H");
  runner.update(1.0f);
  assert(sink.text == "Hi ");
  runner.update(0.5f);
  assert(sink.text == "Hi \xE2\x98\x95");
  assert(runner.visibleCharacters() == 4);

  // Advance while typing reveals the complete line; a second advance moves on.
  assert(runner.advance());
  assert(runner.state() == DialogueState::Waiting);
  assert(sink.text == "Hi \xE2\x98\x95!");
  assert(runner.advance());
  assert(runner.currentLine() == 1);
  assert(runner.state() == DialogueState::Typing);
  assert(sink.speaker.empty() && sink.text.empty());

  // A per-line CPS of zero uses the configured default.
  runner.update(1.0f);
  assert(sink.text == "Done");
  assert(runner.state() == DialogueState::Waiting);
  runner.update(0.49f);
  assert(runner.state() == DialogueState::Waiting);
  runner.update(0.01f);
  assert(runner.state() == DialogueState::Complete);
  assert(runner.finished());
  assert(sink.text.empty() && sink.speaker.empty());
  assert(!sink.events.empty());
  assert(sink.events.back() == DialogueEvent::Completed);

  assert(runner.start(lines, 2, settings));
  runner.cancel(true);
  assert(runner.state() == DialogueState::Idle);
  assert(sink.text.empty() && sink.speaker.empty());
  assert(sink.events.back() == DialogueEvent::Cancelled);

  DialogueLine emptyLine[]{
    {.speaker="Narrator", .text="", .charactersPerSecond=10.0f, .holdSeconds=-1.0f},
  };
  settings.clearOnComplete = false;
  assert(runner.start(emptyLine, 1, settings));
  assert(runner.state() == DialogueState::Waiting);
  assert(runner.visibleCharacters() == 0);
  assert(runner.advance());
  assert(runner.finished());
  return 0;
}
''',
                encoding="utf-8",
            )
            binary = root / "dialogue_test"
            compile_proc = subprocess.run(
                [
                    "g++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "n64" / "engine" / "include"),
                    str(ROOT / "n64" / "engine" / "src" / "ui" / "dialogue.cpp"),
                    str(ROOT / "n64" / "engine" / "src" / "ui" / "utf8.cpp"),
                    str(harness), "-o", str(binary),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compile_proc.returncode, 0, compile_proc.stderr)
            run_proc = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, check=False)

        self.assertEqual(run_proc.returncode, 0, run_proc.stderr)

    def test_history_v2_record_for_project_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.jsonl"
            proc, data = self.run_json(
                "project",
                "status",
                "--project",
                "n64/examples/empty",
                "--record",
                "--history-path",
                str(history),
                "--json",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(data["ok"])
            rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(rows), 1)
        record = rows[0]
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(record["command"], "project status")
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["tool"]["name"], "bf64")
        self.assertIn("--project", record["argv"])
        self.assertEqual(record["project_path"], "n64/examples/empty")

    def test_history_v2_record_for_asset_ls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.jsonl"
            proc, data = self.run_json(
                "asset",
                "ls",
                "--project",
                "n64/examples/empty",
                "--record",
                "--history-path",
                str(history),
                "--json",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(data["ok"])
            rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(rows), 1)
        record = rows[0]
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(record["command"], "asset ls")
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["path"], "n64/examples/empty/project.p64proj")
        self.assertEqual(record["project_path"], "n64/examples/empty")


if __name__ == "__main__":
    unittest.main()
