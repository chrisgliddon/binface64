import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
N64_INST_ENV = os.environ.get("N64_INST", "")
N64_INST = Path(N64_INST_ENV).expanduser().resolve() if N64_INST_ENV else None
N64_CXX = N64_INST / "bin" / "mips64-elf-g++" if N64_INST is not None else None
N64_CC = N64_INST / "bin" / "mips64-elf-gcc" if N64_INST is not None else None


@unittest.skipUnless(N64_CXX is not None and N64_CXX.is_file(), "set N64_INST to the installed libdragon SDK")
class N64IntegrationTests(unittest.TestCase):
    def compile_engine_source(self, relative_source: str) -> subprocess.CompletedProcess[str]:
        return self.compile_cpp_source(ROOT / "n64" / "engine" / "src" / relative_source)

    def compile_cpp_source(self, source: Path) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source.o"
            return subprocess.run(
                [
                    str(N64_CXX),
                    "-c",
                    "-march=vr4300",
                    "-mtune=vr4300",
                    "-mabi=o64",
                    "-I",
                    str(N64_INST / "include" / "newlib_overrides"),
                    "-I",
                    str(N64_INST / "include"),
                    "-include",
                    "ktls.h",
                    "-std=gnu++20",
                    "-fno-exceptions",
                    "-Os",
                    "-I",
                    str(ROOT / "n64" / "engine" / "include"),
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wformat-signedness",
                    "-fno-common",
                    "-Wshadow",
                    "-Wdouble-promotion",
                    "-Wformat-security",
                    "-Wformat-overflow",
                    "-Wformat-truncation",
                    "-Wfatal-errors",
                    str(source),
                    "-o",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    def compile_engine_c_source(self, relative_source: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source.o"
            return subprocess.run(
                [
                    str(N64_CC),
                    "-c",
                    "-march=vr4300",
                    "-mtune=vr4300",
                    "-mabi=o64",
                    "-std=gnu23",
                    "-Os",
                    "-I",
                    str(ROOT / "n64" / "engine" / "include"),
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wformat-signedness",
                    "-Wshadow",
                    "-Wdouble-promotion",
                    "-Wformat-security",
                    "-Wformat-overflow",
                    "-Wformat-truncation",
                    "-Wfatal-errors",
                    str(ROOT / "n64" / "engine" / "src" / relative_source),
                    "-o",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_structured_profiler_compiles_with_engine_werror_policy(self) -> None:
        proc = self.compile_engine_source("debug/profiler.cpp")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_typed_audio_manager_compiles_with_engine_werror_policy(self) -> None:
        proc = self.compile_engine_source("audio/audioManager.cpp")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_dynamic_ui_and_reflow_compile_with_engine_werror_policy(self) -> None:
        layout_proc = self.compile_engine_source("ui/layout.cpp")
        component_proc = self.compile_engine_source("scene/components/ui.cpp")

        self.assertEqual(layout_proc.returncode, 0, layout_proc.stdout + layout_proc.stderr)
        self.assertEqual(component_proc.returncode, 0, component_proc.stdout + component_proc.stderr)

    def test_save_backends_compile_with_installed_libdragon(self) -> None:
        proc = self.compile_engine_source("save/saveManager.cpp")
        driver_proc = self.compile_engine_c_source("save/flashramDriver.c")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(driver_proc.returncode, 0, driver_proc.stdout + driver_proc.stderr)

    def test_chunk_mesh_compiles_with_engine_werror_policy(self) -> None:
        proc = self.compile_engine_source("renderer/chunkMesh.cpp")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_multiplayer_runtime_compiles_with_engine_werror_policy(self) -> None:
        for source in (
            "input/input.cpp",
            "multiplayer/session.cpp",
            "multiplayer/viewports.cpp",
            "multiplayer/spawns.cpp",
            "multiplayer/groupCamera.cpp",
            "scene/components/playerSpawn.cpp",
        ):
            with self.subTest(source=source):
                proc = self.compile_engine_source(source)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_multiplayer_scene_ui_and_audio_compile_with_engine_werror_policy(self) -> None:
        for source in (
            "scene/camera.cpp",
            "scene/components/camera.cpp",
            "scene/components/ui.cpp",
            "scene/scene.cpp",
            "audio/spatialAudio.cpp",
            "audio/audioManager.cpp",
        ):
            with self.subTest(source=source):
                proc = self.compile_engine_source(source)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_multiplayer_reference_mode_compiles_with_engine_werror_policy(self) -> None:
        proc = self.compile_cpp_source(
            ROOT / "n64" / "examples" / "multiplayer" / "src" / "user" / "MultiplayerModes.cpp"
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
