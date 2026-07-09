import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "bf64.py"


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

    def test_constraints_list_json(self) -> None:
        proc, data = self.run_json("constraints", "list", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["ok"])
        self.assertIn("texture", data["topics"])
        self.assertIn("scene", data["topics"])

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
            (project / "data" / "scenes" / "1").mkdir(parents=True)
            (project / "project.p64proj").write_text(
                json.dumps(
                    {
                        "name": "Fixture",
                        "romName": "fixture",
                        "sceneIdOnBoot": 1,
                        "sceneIdOnReset": 1,
                        "sceneIdLastOpened": 1,
                    }
                ),
                encoding="utf-8",
            )
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


if __name__ == "__main__":
    unittest.main()
