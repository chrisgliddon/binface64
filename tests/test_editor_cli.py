import json
import os
import shutil
import shlex
import stat
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EDITOR_ENV = os.environ.get("BF64_EDITOR_BINARY", "")
EDITOR = Path(EDITOR_ENV).expanduser().resolve() if EDITOR_ENV else None


@unittest.skipUnless(EDITOR is not None and EDITOR.is_file(), "set BF64_EDITOR_BINARY to the built editor")
class EditorCliIntegrationTests(unittest.TestCase):
    def write_executable(self, path: Path, source: str) -> None:
        path.write_text(source, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def write_fake_toolchain(self, root: Path) -> tuple[Path, Path]:
        sdk = root / "sdk"
        bin_dir = sdk / "bin"
        include_dir = sdk / "include"
        fake_path = root / "path"
        bin_dir.mkdir(parents=True)
        include_dir.mkdir()
        fake_path.mkdir()
        (include_dir / "n64.mk").write_text("", encoding="utf-8")
        (include_dir / "t3d.mk").write_text("", encoding="utf-8")
        success = "#!/bin/sh\nexit 0\n"
        for name in ("mips64-elf-gcc", "mkasset", "mksprite", "audioconv64", "mkfont", "mkdfs", "n64tool"):
            self.write_executable(bin_dir / name, success)
        self.write_executable(fake_path / "make", success)
        return sdk, fake_path

    def write_project(self, project: Path, sdk: Path) -> None:
        shutil.copytree(
            ROOT / "n64" / "examples" / "empty",
            project,
            ignore=shutil.ignore_patterns("build", "engine", "filesystem", "Makefile", "*.z64", "p64"),
        )
        config_path = project / "project.p64proj"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.update(
            {
                "name": "Editor CLI fixture",
                "romName": "fixture",
                "editorVersion": "0.8.0",
                "pathN64Inst": str(sdk),
            }
        )
        config_path.write_text(json.dumps(config), encoding="utf-8")

    def run_build(self, project: Path, fake_path: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{fake_path}{os.pathsep}{env.get('PATH', '')}"
        return subprocess.run(
            [str(EDITOR), "--cli", "--cmd", "build", str(project / "project.p64proj")],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_build_accepts_a_minimal_excluded_asset_sidecar_without_rewriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk, fake_path = self.write_fake_toolchain(root)
            project = root / "game"
            self.write_project(project, sdk)
            asset = project / "assets" / "optional.png"
            asset.write_bytes(b"excluded source does not need decoding")
            sidecar = Path(str(asset) + ".conf")
            original = '{"exclude":true}'
            sidecar.write_text(original, encoding="utf-8")

            proc = self.run_build(project, fake_path)

            self.assertEqual(sidecar.read_text(encoding="utf-8"), original)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Build done!", proc.stdout)

    def test_build_prunes_excluded_audio_output_and_continues_with_included_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk, fake_path = self.write_fake_toolchain(root)
            project = root / "game"
            self.write_project(project, sdk)
            audio_dir = project / "assets" / "music"
            audio_dir.mkdir(parents=True)
            excluded = audio_dir / "00-old.wav"
            included = audio_dir / "10-current.wav"
            excluded.write_bytes(b"excluded")
            included.write_bytes(b"included")
            Path(str(excluded) + ".conf").write_text(
                json.dumps({"uuid": 100, "exclude": True}), encoding="utf-8"
            )
            Path(str(included) + ".conf").write_text(
                json.dumps({"uuid": 101, "exclude": False}), encoding="utf-8"
            )
            stale_output = project / "filesystem" / "music" / "00-old.wav64"
            stale_output.parent.mkdir(parents=True)
            stale_output.write_bytes(b"stale converted audio")
            converter_log = root / "audioconv.log"
            self.write_executable(
                sdk / "bin" / "audioconv64",
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" >> {shlex.quote(str(converter_log))}\n"
                "exit 0\n",
            )

            proc = self.run_build(project, fake_path)
            converted = converter_log.read_text(encoding="utf-8")

            self.assertFalse(stale_output.exists())

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("10-current.wav", converted)
        self.assertNotIn("00-old.wav", converted)

    def test_build_prunes_stream_data_owned_by_an_excluded_model_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk, fake_path = self.write_fake_toolchain(root)
            project = root / "game"
            self.write_project(project, sdk)
            model = project / "assets" / "models" / "retired.glb"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"excluded model")
            Path(str(model) + ".conf").write_text(
                json.dumps({"uuid": 200, "exclude": True}), encoding="utf-8"
            )
            output_dir = project / "filesystem" / "models"
            output_dir.mkdir(parents=True)
            retired_model = output_dir / "retired.t3dm"
            retired_stream_0 = output_dir / "retired.0.sdata"
            retired_stream_1 = output_dir / "retired.1.sdata"
            unrelated_stream = output_dir / "active.0.sdata"
            for output in (retired_model, retired_stream_0, retired_stream_1, unrelated_stream):
                output.write_bytes(b"stale")

            proc = self.run_build(project, fake_path)

            self.assertFalse(retired_model.exists())
            self.assertFalse(retired_stream_0.exists())
            self.assertFalse(retired_stream_1.exists())
            self.assertTrue(unrelated_stream.exists())

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_build_prunes_outputs_selected_by_project_exclusion_globs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk, fake_path = self.write_fake_toolchain(root)
            project = root / "game"
            self.write_project(project, sdk)
            config_path = project / "project.p64proj"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["assetExclusions"] = ["retired/**"]
            config_path.write_text(json.dumps(config), encoding="utf-8")
            document = project / "assets" / "retired" / "hud.bfui"
            document.parent.mkdir(parents=True)
            document.write_text("not parsed when excluded", encoding="utf-8")
            Path(str(document) + ".conf").write_text(
                json.dumps({"uuid": 300, "exclude": False}), encoding="utf-8"
            )
            stale_output = project / "filesystem" / "retired" / "hud.ui64"
            stale_output.parent.mkdir(parents=True)
            stale_output.write_bytes(b"stale UI")

            proc = self.run_build(project, fake_path)

            self.assertFalse(stale_output.exists())

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_build_encodes_container_flow_and_gap_in_the_runtime_ui_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk, fake_path = self.write_fake_toolchain(root)
            project = root / "game"
            self.write_project(project, sdk)
            document = project / "assets" / "hud.bfui"
            document.write_text(
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
                            "children": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            Path(str(document) + ".conf").write_text(
                json.dumps({"uuid": 400, "exclude": False}), encoding="utf-8"
            )

            proc = self.run_build(project, fake_path)
            runtime_document = (project / "filesystem" / "hud.ui64").read_bytes()
            elements_offset = struct.unpack_from(">I", runtime_document, 12)[0]
            flow = struct.unpack_from(">H", runtime_document, elements_offset + 46)[0]
            gap = struct.unpack_from(">H", runtime_document, elements_offset + 48)[0]

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(flow, 1)
        self.assertEqual(gap, 4)


if __name__ == "__main__":
    unittest.main()
