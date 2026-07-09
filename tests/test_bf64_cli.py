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
