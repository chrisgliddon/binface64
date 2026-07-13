import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bf64"


class MultiplayerCliTests(unittest.TestCase):
    def run_json(self, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        proc = subprocess.run([str(CLI), *args], cwd=ROOT, text=True, capture_output=True, check=False)
        return proc, json.loads(proc.stdout)

    def write_project(self, root: Path) -> None:
        (root / "data" / "scenes" / "1").mkdir(parents=True)
        (root / "project.p64proj").write_text(json.dumps({
            "name": "Four", "romName": "four", "sceneIdOnBoot": 1, "sceneIdOnReset": 1,
            "multiplayer": {
                "targetRdramMB": 4,
                "controllers": [{"name": f"P{i}", "rumble": True} for i in range(1, 5)],
            },
            "input": {
                "deadZone": 0.18,
                "actions": [{"name": "ready", "bindings": [{"buttons": 8, "chord": 0}]}],
                "axes": [{"name": "move_x", "bindings": [{"source": "stick_x", "scale": 1, "deadZone": 0.18}]}],
            },
        }), encoding="utf-8")
        children = []
        def object_base(name: str, uuid: int) -> dict:
            return {
                "name": name, "uuid": uuid, "enabled": True, "selectable": True, "viewMask": 31,
                "proportionalScale": False, "uuidPrefab": 0, "pos": [0, 0, 0],
                "rot": [0, 0, 0, 1], "scale": [1, 1, 1], "propOverrides": {}, "children": [],
            }
        for player in range(4):
            camera = object_base(f"Camera {player + 1}", player + 1)
            camera["components"] = [{"id": 3, "uuid": 100 + player, "name": "Camera", "data": {
                    "target": 2, "player": player, "vpOffset": [0, 0], "vpSize": [320, 240]
                }}]
            children.append(camera)
            spawn = object_base(f"Spawn {player + 1}", player + 10)
            spawn["components"] = [{"id": 15, "uuid": 200 + player, "name": "Player Spawn", "data": {"target": 1, "index": player}}]
            children.append(spawn)
        graph = object_base("Scene", 0)
        graph["components"] = []
        graph["children"] = children
        scene = {
            "conf": {"name": "Arena", "fbWidth": 320, "fbHeight": 240, "renderPipeline": 0},
            "graph": graph,
        }
        (root / "data" / "scenes" / "1" / "scene.json").write_text(json.dumps(scene), encoding="utf-8")

    def test_status_and_validate_have_stable_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_project(root)
            status_proc, status = self.run_json("multiplayer", "status", "--project", str(root), "--json")
            validate_proc, validate = self.run_json("multiplayer", "validate", "--project", str(root), "--json")
        self.assertEqual(status_proc.returncode, 0, status_proc.stderr)
        self.assertEqual(validate_proc.returncode, 0, validate_proc.stderr)
        self.assertEqual(status["schema"], "bf64.multiplayer")
        self.assertEqual(status["version"], 1)
        self.assertEqual(validate["configuration"]["input"]["action_count"], 1)
        self.assertEqual(validate["scenes"][0]["cameras"]["players"], [1, 1, 1, 1])

    def test_validate_reports_metadata_binding_and_memory_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_project(root)
            config_path = root / "project.p64proj"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["multiplayer"]["controllers"] = config["multiplayer"]["controllers"][:2]
            config["input"]["actions"][0]["bindings"][0]["buttons"] = 0
            config_path.write_text(json.dumps(config), encoding="utf-8")
            scene_path = root / "data" / "scenes" / "1" / "scene.json"
            scene = json.loads(scene_path.read_text(encoding="utf-8"))
            scene["conf"]["renderPipeline"] = 2
            scene_path.write_text(json.dumps(scene), encoding="utf-8")
            proc, data = self.run_json("multiplayer", "validate", "--project", str(root), "--json")
        self.assertEqual(proc.returncode, 1)
        rules = {item["rule"] for item in data["issues"]}
        self.assertIn("MULTIPLAYER_CONTROLLERS", rules)
        self.assertIn("INPUT_BINDING", rules)
        self.assertIn("MULTIPLAYER_MEMORY", rules)

    def test_scene_attach_player_spawn_and_ares_rdram_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_project(root)
            proc, data = self.run_json(
                "scene", "attach", "player-spawn", "1", "1", "--spawn-target", "neutral", "--spawn-index", "0",
                "--project", str(root), "--json",
            )
            invalid_proc, invalid_data = self.run_json(
                "scene", "attach", "player-spawn", "1", "2", "--spawn-target", "player", "--spawn-index", "4",
                "--project", str(root), "--json",
            )
        self.assertEqual(proc.returncode, 0, proc.stderr + json.dumps(data, indent=2))
        self.assertEqual(data["component"]["id"], 15)
        self.assertEqual(data["component"]["data"], {"target": 0, "index": 0})
        self.assertEqual(invalid_proc.returncode, 1)
        self.assertIn("SCENE_PLAYER_SPAWN", {item["rule"] for item in invalid_data["issues"]})

        spec = importlib.util.spec_from_file_location("bf64_multiplayer_cli", ROOT / "tools" / "bf64.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        argv = module.prepare_emulator_argv(["ares"], ROOT, ROOT / "game.z64", rdram_mb=4)
        self.assertIn("Nintendo64/ExpansionPak=false", argv)
        argv = module.prepare_emulator_argv(["ares"], ROOT, ROOT / "game.z64", rdram_mb=8)
        self.assertIn("Nintendo64/ExpansionPak=true", argv)


if __name__ == "__main__":
    unittest.main()
