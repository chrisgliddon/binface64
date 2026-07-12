import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeSaveTests(unittest.TestCase):
    def write_stubs(self, root: Path) -> None:
        (root / "save").mkdir()
        (root / "eeprom.h").write_text(
            "#pragma once\n"
            "#include <cstddef>\n"
            "#include <cstdint>\n"
            "enum eeprom_type_t { EEPROM_NONE = 0, EEPROM_4K = 1, EEPROM_16K = 2 };\n"
            "constexpr std::size_t EEPROM_BLOCK_SIZE = 8;\n"
            "extern \"C\" eeprom_type_t eeprom_present();\n"
            "extern \"C\" std::size_t eeprom_total_blocks();\n"
            "extern \"C\" void eeprom_read_bytes(std::uint8_t*, std::size_t, std::size_t);\n"
            "extern \"C\" void eeprom_write_bytes(const std::uint8_t*, std::size_t, std::size_t);\n"
            "extern \"C\" std::uint8_t eeprom_write(std::uint8_t, const std::uint8_t*);\n",
            encoding="utf-8",
        )
        (root / "save" / "flashramDriver.h").write_text(
            "#pragma once\n"
            "#include <cstddef>\n"
            "#include <cstdint>\n"
            "struct bf64_flashram_timings_t {};\n"
            "struct bf64_flashram_layout_t { std::uint8_t unit_bits{}, offset_bits{}, page_bits{}, sector_bits{}, read_page_bits{}; };\n"
            "struct bf64_flashram_info_t {\n"
            "  std::uint32_t type_id{}; std::uint16_t manufacturer_id{}, device_id{};\n"
            "  bf64_flashram_layout_t layout{}; const char *name{}; std::size_t total_size{}, sector_size{}, page_size{};\n"
            "  unsigned int num_sectors{}, num_pages{};\n"
            "};\n"
            "extern \"C\" bool bf64_flashram_init(const bf64_flashram_timings_t*, bf64_flashram_info_t*);\n"
            "extern \"C\" int bf64_flashram_read(void*, std::size_t, std::size_t);\n"
            "extern \"C\" int bf64_flashram_write(const void*, std::size_t, std::size_t);\n",
            encoding="utf-8",
        )

    def compile_and_run(self, harness_source: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_stubs(root)
            harness = root / "save_test.cpp"
            harness.write_text(harness_source, encoding="utf-8")
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
            self.assertEqual(compile_proc.returncode, 0, compile_proc.stdout + compile_proc.stderr)
            return subprocess.run(
                [str(binary)], cwd=ROOT, text=True, capture_output=True, check=False
            )

    def test_flashram_backend_round_trips_a_512_byte_record(self) -> None:
        run_proc = self.compile_and_run(
            r'''
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include "save/saveManager.h"
#include "eeprom.h"
#include "save/flashramDriver.h"

namespace {
std::array<std::uint8_t, 128 * 1024> flashStorage{};
int flashReads{};
int flashWrites{};
bool failNextWrite{};
std::size_t lastWriteOffset{};
}

extern "C" eeprom_type_t eeprom_present() { return EEPROM_NONE; }
extern "C" std::size_t eeprom_total_blocks() { return 0; }
extern "C" void eeprom_read_bytes(std::uint8_t*, std::size_t, std::size_t) {}
extern "C" void eeprom_write_bytes(const std::uint8_t*, std::size_t, std::size_t) {}
extern "C" std::uint8_t eeprom_write(std::uint8_t, const std::uint8_t*) { return 1; }

extern "C" bool bf64_flashram_init(const bf64_flashram_timings_t*, bf64_flashram_info_t *info) {
  if(info != nullptr) {
    info->total_size = flashStorage.size();
    info->sector_size = 16 * 1024;
    info->page_size = 128;
  }
  return true;
}
extern "C" int bf64_flashram_read(void *destination, std::size_t offset, std::size_t size) {
  ++flashReads;
  std::memcpy(destination, flashStorage.data() + offset, size);
  return static_cast<int>(size);
}
extern "C" int bf64_flashram_write(const void *source, std::size_t offset, std::size_t size) {
  ++flashWrites;
  lastWriteOffset = offset;
  if(failNextWrite) {
    failNextWrite = false;
    std::memcpy(flashStorage.data() + offset, source, 12);
    return -1;
  }
  std::memcpy(flashStorage.data() + offset, source, size);
  return static_cast<int>(size);
}

int main() {
  using namespace P64::Save;
  flashStorage.fill(0xFF);
  Config config{};
  config.backend = Backend::FlashRam;
  config.slotCount = 1;
  config.payloadCapacity = 512;
  config.schemaVersion = 7;

  assert(init(config) == Status::Ok);
  const Info saveInfo = info();
  assert(saveInfo.device == Device::FlashRam);
  assert(saveInfo.storageBytes == flashStorage.size());
  assert(saveInfo.eepromBytes == 0);
  assert(saveInfo.bankBytes == 16 * 1024);
  assert(saveInfo.requiredBytes == 32 * 1024);

  std::array<std::uint8_t, 512> expected{};
  for(std::size_t i = 0; i < expected.size(); ++i) expected[i] = static_cast<std::uint8_t>(i);
  assert(write(0, expected) == Status::Ok);

  std::array<std::uint8_t, 512> actual{};
  const ReadResult result = read(0, actual);
  assert(result.status == Status::Ok);
  assert(result.version == 7 && result.storedVersion == 7);
  assert(actual == expected);
  assert(flashReads > 0 && flashWrites == 1);

  failNextWrite = true;
  expected[0] ^= 0xFF;
  assert(write(0, expected) == Status::IoError);
  assert(lastWriteOffset == saveInfo.bankBytes);
  actual.fill(0);
  const ReadResult recovered = read(0, actual);
  assert(recovered.status == Status::Ok && recovered.recovered);
  expected[0] ^= 0xFF;
  assert(actual == expected);
  return 0;
}
'''
        )

        self.assertEqual(run_proc.returncode, 0, run_proc.stdout + run_proc.stderr)

    def test_flashram_read_failure_is_reported_as_io_error(self) -> None:
        run_proc = self.compile_and_run(
            r'''
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include "save/saveManager.h"
#include "eeprom.h"
#include "save/flashramDriver.h"

extern "C" eeprom_type_t eeprom_present() { return EEPROM_NONE; }
extern "C" std::size_t eeprom_total_blocks() { return 0; }
extern "C" void eeprom_read_bytes(std::uint8_t*, std::size_t, std::size_t) {}
extern "C" void eeprom_write_bytes(const std::uint8_t*, std::size_t, std::size_t) {}
extern "C" std::uint8_t eeprom_write(std::uint8_t, const std::uint8_t*) { return 1; }

extern "C" bool bf64_flashram_init(const bf64_flashram_timings_t*, bf64_flashram_info_t *info) {
  info->total_size = 128 * 1024;
  info->sector_size = 16 * 1024;
  return true;
}
extern "C" int bf64_flashram_read(void*, std::size_t, std::size_t) { return -1; }
extern "C" int bf64_flashram_write(const void*, std::size_t, std::size_t size) {
  return static_cast<int>(size);
}

int main() {
  using namespace P64::Save;
  Config config{};
  config.backend = Backend::FlashRam;
  config.slotCount = 1;
  config.payloadCapacity = 64;
  assert(init(config) == Status::Ok);

  std::array<std::uint8_t, 64> payload{};
  assert(read(0, payload).status == Status::IoError);
  assert(write(0, payload) == Status::IoError);
  return 0;
}
'''
        )

        self.assertEqual(run_proc.returncode, 0, run_proc.stdout + run_proc.stderr)

    def test_auto_backend_prefers_eeprom_then_falls_back_to_flashram(self) -> None:
        run_proc = self.compile_and_run(
            r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include "save/saveManager.h"
#include "eeprom.h"
#include "save/flashramDriver.h"

namespace {
bool eepromAvailable{true};
int flashInitCount{};
}

extern "C" eeprom_type_t eeprom_present() {
  return eepromAvailable ? EEPROM_16K : EEPROM_NONE;
}
extern "C" std::size_t eeprom_total_blocks() { return eepromAvailable ? 256 : 0; }
extern "C" void eeprom_read_bytes(std::uint8_t*, std::size_t, std::size_t) {}
extern "C" void eeprom_write_bytes(const std::uint8_t*, std::size_t, std::size_t) {}
extern "C" std::uint8_t eeprom_write(std::uint8_t, const std::uint8_t*) { return 0; }

extern "C" bool bf64_flashram_init(const bf64_flashram_timings_t*, bf64_flashram_info_t *info) {
  ++flashInitCount;
  info->total_size = 128 * 1024;
  info->sector_size = 16 * 1024;
  return true;
}
extern "C" int bf64_flashram_read(void*, std::size_t, std::size_t size) {
  return static_cast<int>(size);
}
extern "C" int bf64_flashram_write(const void*, std::size_t, std::size_t size) {
  return static_cast<int>(size);
}

int main() {
  using namespace P64::Save;
  Config config{};
  config.backend = Backend::Auto;
  config.payloadCapacity = 64;

  assert(init(config) == Status::Ok);
  assert(info().device == Device::Eeprom16K && flashInitCount == 0);
  close();

  eepromAvailable = false;
  assert(init(config) == Status::Ok);
  assert(info().device == Device::FlashRam && flashInitCount == 1);
  assert(info().bankBytes == 16 * 1024);
  return 0;
}
'''
        )

        self.assertEqual(run_proc.returncode, 0, run_proc.stdout + run_proc.stderr)


if __name__ == "__main__":
    unittest.main()
