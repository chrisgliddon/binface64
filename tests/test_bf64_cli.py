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
