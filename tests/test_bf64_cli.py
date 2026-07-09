import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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

    def write_fake_sdk(self, sdk: Path) -> None:
        for rel in (
            "include/n64.mk",
            "include/t3d.mk",
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

    def test_constraints_list_json(self) -> None:
        proc, data = self.run_json("constraints", "list", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertIn("texture", data["topics"])
        self.assertIn("scene", data["topics"])

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

    def test_asset_validate_all_empty_project_skips_unknown_sources(self) -> None:
        proc, data = self.run_json("asset", "validate-all", "--project", "n64/examples/empty", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["validated"], 2)
        self.assertEqual(data["summary"]["skipped"], 1)
        skipped = [item for item in data["results"] if item["metadata"].get("skipped")]
        self.assertEqual(skipped[0]["kind"], "unknown")

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

    def test_doctor_default_keeps_optional_toolchain_as_warnings(self) -> None:
        proc, data = self.run_json("doctor", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertTrue(any(check["name"] == "python" for check in data["checks"]))

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
