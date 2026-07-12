import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeAudioTests(unittest.TestCase):
    def write_stubs(self, root: Path) -> None:
        (root / "scene").mkdir()
        (root / "fgeom.h").write_text(
            "#pragma once\n"
            "struct fm_vec3_t { float x{}; float y{}; float z{}; };\n",
            encoding="utf-8",
        )
        (root / "scene" / "camera.h").write_text(
            "#pragma once\n"
            "#include <fgeom.h>\n"
            "namespace P64 { class Camera { public:\n"
            "const fm_vec3_t& getPos() const { static fm_vec3_t value{}; return value; }\n"
            "fm_vec3_t getViewDir() const { return {}; }\n"
            "const fm_vec3_t& getUp() const { static fm_vec3_t value{0,1,0}; return value; }\n"
            "}; }\n",
            encoding="utf-8",
        )
        (root / "scene" / "object.h").write_text(
            "#pragma once\n"
            "#include <fgeom.h>\n"
            "namespace P64 { class Object { public: fm_vec3_t pos{}; }; }\n",
            encoding="utf-8",
        )
        (root / "libdragon.h").write_text(
            "#pragma once\n"
            "#include <cstdarg>\n"
            "#include <cstdint>\n"
            "struct waveform_t { int channels{}; float frequency{}; };\n"
            "struct wav64_t { waveform_t wave{}; };\n"
            "struct xm64player_t { bool playing{}; int channels{}; };\n"
            "void debugf(const char*, ...);\n"
            "std::uint64_t get_ticks();\n"
            "void audio_init(int, int);\n"
            "void audio_close();\n"
            "void mixer_init(int);\n"
            "void mixer_close();\n"
            "void mixer_try_play();\n"
            "bool mixer_ch_playing(int);\n"
            "void mixer_ch_set_vol(int, float, float);\n"
            "void mixer_ch_set_freq(int, float);\n"
            "void mixer_ch_stop(int);\n"
            "void wav64_play(wav64_t*, int);\n"
            "void wav64_set_loop(wav64_t*, bool);\n"
            "int xm64player_num_channels(xm64player_t*);\n"
            "void xm64player_play(xm64player_t*, int);\n"
            "void xm64player_stop(xm64player_t*);\n"
            "void xm64player_set_vol(xm64player_t*, float);\n",
            encoding="utf-8",
        )
        (root / "audio_test_support.h").write_text(
            r'''#pragma once
#include <array>
#include <cassert>
#include <cstdint>
#include "assets/assetManager.h"
#include "assets/assetTypes.h"
#include "audio/audioManager.h"

namespace AudioTest {
inline void *asset{};
inline std::uint8_t assetType{};
inline std::array<bool, 32> channelPlaying{};
inline int wavPlayCount{};
inline int xmPlayCount{};
inline int xmStopCount{};
inline int sequence{};
inline int xmStopSequence{};
inline int assetFreeSequence{};
inline std::array<float, 32> channelFrequency{};
}

void debugf(const char*, ...) {}
std::uint64_t get_ticks() { static std::uint64_t ticks{}; return ++ticks; }
void audio_init(int, int) {}
void audio_close() {}
void mixer_init(int) {}
void mixer_close() {}
void mixer_try_play() {}
bool mixer_ch_playing(int channel) {
  return AudioTest::channelPlaying[static_cast<std::size_t>(channel)];
}
void mixer_ch_set_vol(int, float, float) {}
void mixer_ch_set_freq(int channel, float frequency) {
  AudioTest::channelFrequency[static_cast<std::size_t>(channel)] = frequency;
}
void mixer_ch_stop(int channel) {
  AudioTest::channelPlaying[static_cast<std::size_t>(channel)] = false;
}
void wav64_play(wav64_t *value, int channel) {
  assert(value == AudioTest::asset);
  ++AudioTest::wavPlayCount;
  AudioTest::channelPlaying[static_cast<std::size_t>(channel)] = true;
}
void wav64_set_loop(wav64_t*, bool) {}
int xm64player_num_channels(xm64player_t *value) { return value->channels; }
void xm64player_play(xm64player_t *value, int channel) {
  assert(value == AudioTest::asset);
  ++AudioTest::xmPlayCount;
  value->playing = true;
  AudioTest::channelPlaying[static_cast<std::size_t>(channel)] = true;
}
void xm64player_stop(xm64player_t *value) {
  assert(value != nullptr);
  ++AudioTest::xmStopCount;
  AudioTest::xmStopSequence = ++AudioTest::sequence;
  value->playing = false;
}
void xm64player_set_vol(xm64player_t*, float) {}

void P64::AssetManager::init() {}
void P64::AssetManager::freeAll() {
  AudioTest::assetFreeSequence = ++AudioTest::sequence;
}
void *P64::AssetManager::getByIndex(std::uint32_t) { return AudioTest::asset; }
std::uint8_t P64::AssetManager::getTypeByIndex(std::uint32_t) { return AudioTest::assetType; }
const char *P64::AssetManager::getPathByIndex(std::uint32_t) { return "fixture"; }
''',
            encoding="utf-8",
        )

    def compile_and_run(self, harness_source: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_stubs(root)
            harness = root / "audio_test.cpp"
            harness.write_text(harness_source, encoding="utf-8")
            binary = root / "audio_test"
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
                    "-I",
                    str(ROOT / "n64" / "engine" / "src"),
                    str(ROOT / "n64" / "engine" / "src" / "audio" / "audioManager.cpp"),
                    str(ROOT / "n64" / "engine" / "src" / "audio" / "spatialAudio.cpp"),
                    str(ROOT / "n64" / "engine" / "src" / "scene" / "components" / "audio3d.cpp"),
                    str(harness),
                    "-o",
                    str(binary),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compile_proc.returncode, 0, compile_proc.stdout + compile_proc.stderr)
            return subprocess.run(
                [str(binary)], cwd=ROOT, text=True, capture_output=True, check=False
            )

    def test_asset_id_playback_dispatches_wav_xm_and_rejects_non_audio(self) -> None:
        run_proc = self.compile_and_run(
            r'''
#include "audio_test_support.h"

int main() {
  using namespace AudioTest;
  wav64_t wav{};
  wav.wave.channels = 1;
  wav.wave.frequency = 32000.0f;
  asset = &wav;
  assetType = P64::Assets::Type::AUDIO;
  auto wavHandle = P64::AudioManager::play2D(1);
  assert(wavPlayCount == 1 && xmPlayCount == 0);
  wavHandle.stop();

  xm64player_t xm{};
  xm.channels = 4;
  asset = &xm;
  assetType = P64::Assets::Type::MUSIC_XM;
  auto xmHandle = P64::AudioManager::play2D(2);
  assert(wavPlayCount == 1 && xmPlayCount == 1 && !xmHandle.isDone());
  xmHandle.stop();

  asset = &wav;
  assetType = P64::Assets::Type::IMAGE;
  auto invalid = P64::AudioManager::play2D(3);
  assert(invalid.isDone());
  assert(wavPlayCount == 1 && xmPlayCount == 1);
  return 0;
}
'''
        )

        self.assertEqual(run_proc.returncode, 0, run_proc.stdout + run_proc.stderr)

    def test_xm_handles_and_stop_all_stop_players_before_asset_release(self) -> None:
        run_proc = self.compile_and_run(
            r'''
#include "audio_test_support.h"

int main() {
  using namespace AudioTest;
  wav64_t wav{};
  wav.wave.channels = 2;
  wav.wave.frequency = 32000.0f;
  xm64player_t xm{};
  xm.channels = 4;

  for(int iteration=0; iteration<8; ++iteration) {
    asset = &xm;
    assetType = P64::Assets::Type::MUSIC_XM;
    auto music = P64::AudioManager::play2D(1);
    assert(!music.isDone() && xm.playing);
    music.stop();
    assert(music.isDone() && !xm.playing);

    asset = &wav;
    assetType = P64::Assets::Type::AUDIO;
    auto recovery = P64::AudioManager::play2D(2);
    assert(!recovery.isDone());
    recovery.stop();
    assert(recovery.isDone());
  }
  assert(xmStopCount == 8);

  asset = &xm;
  assetType = P64::Assets::Type::MUSIC_XM;
  auto finalMusic = P64::AudioManager::play2D(3);
  assert(!finalMusic.isDone());
  P64::AudioManager::stopAll();
  assert(finalMusic.isDone() && !xm.playing && xmStopCount == 9);
  P64::AssetManager::freeAll();
  assert(xmStopSequence > 0);
  assert(assetFreeSequence > xmStopSequence);
  return 0;
}
'''
        )

        self.assertEqual(run_proc.returncode, 0, run_proc.stdout + run_proc.stderr)

    def test_wav_handle_pitch_updates_every_channel_and_clamps_unsafe_ratios(self) -> None:
        run_proc = self.compile_and_run(
            r'''
#include "audio_test_support.h"

int main() {
  using namespace AudioTest;
  wav64_t stereo{};
  stereo.wave.channels = 2;
  stereo.wave.frequency = 32000.0f;
  asset = &stereo;
  assetType = P64::Assets::Type::AUDIO;
  auto handle = P64::AudioManager::play2D(1);

  handle.setPitch(1.25f);
  assert(channelFrequency[0] == 40000.0f && channelFrequency[1] == 40000.0f);
  handle.setPitch(0.0f);
  assert(channelFrequency[0] == 4000.0f && channelFrequency[1] == 4000.0f);
  handle.setSpeed(20.0f);
  assert(channelFrequency[0] == 256000.0f && channelFrequency[1] == 256000.0f);
  return 0;
}
'''
        )

        self.assertEqual(run_proc.returncode, 0, run_proc.stdout + run_proc.stderr)

    def test_audio3d_component_applies_authored_pitch_on_autoplay(self) -> None:
        run_proc = self.compile_and_run(
            r'''
#include "audio_test_support.h"
#include "scene/components/audio3d.h"

int main() {
  using namespace AudioTest;
  wav64_t wav{};
  wav.wave.channels = 1;
  wav.wave.frequency = 32000.0f;
  asset = &wav;
  assetType = P64::Assets::Type::AUDIO;

  P64::Object object{};
  object.pos = {10.0f, 0.0f, 0.0f};
  P64::Comp::Audio3D::InitData init{};
  init.assetIdx = 1;
  init.volume = 65535;
  init.minDistance = 20.0f;
  init.maxDistance = 400.0f;
  init.rolloff = 1.0f;
  init.pitchQ12 = 5120;
  init.flags = P64::Comp::Audio3D::FLAG_AUTO_PLAY;

  alignas(P64::Comp::Audio3D) unsigned char storage[sizeof(P64::Comp::Audio3D)]{};
  auto *component = reinterpret_cast<P64::Comp::Audio3D*>(storage);
  P64::Comp::Audio3D::initDelete(object, component, &init);
  assert(component->pitch == 1.25f);
  assert(channelFrequency[0] == 40000.0f);
  P64::Comp::Audio3D::initDelete(object, component, nullptr);

  xm64player_t music{};
  music.channels = 4;
  asset = &music;
  assetType = P64::Assets::Type::MUSIC_XM;
  P64::Comp::Audio3D::initDelete(object, component, &init);
  assert(component->audio == nullptr);
  assert(xmPlayCount == 0);
  P64::Comp::Audio3D::initDelete(object, component, nullptr);
  return 0;
}
'''
        )

        self.assertEqual(run_proc.returncode, 0, run_proc.stdout + run_proc.stderr)


if __name__ == "__main__":
    unittest.main()
