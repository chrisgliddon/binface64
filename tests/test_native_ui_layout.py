import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeUILayoutTests(unittest.TestCase):
    def test_vertical_flow_collapses_hidden_rows_and_reflows_visible_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness = root / "layout_test.cpp"
            harness.write_text(
                r'''
#include <cassert>
#include <cstdint>
#include "ui/documentFormat.h"
#include "ui/layout.h"

int main() {
  namespace Format = P64::UI::Format;
  namespace Layout = P64::UI::Layout;
  Format::Header header{};
  header.elementCount = 4;
  header.canvasWidth = 320;
  header.canvasHeight = 240;
  Format::Element elements[4]{};
  elements[0].type = Format::ElementType::CONTAINER;
  elements[0].parent = Format::NO_INDEX;
  elements[0].offsets[0] = 10;
  elements[0].offsets[1] = 10;
  elements[0].offsets[2] = 110;
  elements[0].offsets[3] = 100;
  elements[0].focus[0] = static_cast<std::uint16_t>(Format::Flow::VERTICAL);
  elements[0].focus[1] = 4;
  for(std::uint16_t index=1; index<4; ++index) {
    elements[index].type = Format::ElementType::CONTAINER;
    elements[index].parent = 0;
    elements[index].offsets[2] = 100;
    elements[index].offsets[3] = 12;
  }
  std::uint8_t visible[4]{1, 1, 1, 1};
  Layout::Rect rects[4]{};

  Layout::calculate(header, elements, visible, rects);
  assert(rects[1].y0 == 10 && rects[1].y1 == 22);
  assert(rects[2].y0 == 26 && rects[2].y1 == 38);
  assert(rects[3].y0 == 42 && rects[3].y1 == 54);

  visible[2] = 0;
  Layout::calculate(header, elements, visible, rects);
  assert(rects[1].y0 == 10 && rects[1].y1 == 22);
  assert(rects[2].y0 == 26 && rects[2].y1 == 26);
  assert(rects[3].y0 == 26 && rects[3].y1 == 38);
  return 0;
}
''',
                encoding="utf-8",
            )
            binary = root / "layout_test"
            compile_proc = subprocess.run(
                [
                    "g++",
                    "-std=c++20",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(ROOT / "n64" / "engine" / "include"),
                    str(ROOT / "n64" / "engine" / "src" / "ui" / "layout.cpp"),
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
            run_proc = subprocess.run(
                [str(binary)], cwd=ROOT, text=True, capture_output=True, check=False
            )

        self.assertEqual(run_proc.returncode, 0, run_proc.stdout + run_proc.stderr)


if __name__ == "__main__":
    unittest.main()
