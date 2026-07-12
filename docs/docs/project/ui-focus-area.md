# UI Focus Area

BF64's first dedicated product focus area is 2D game UI. It provides the same document through a visual editor, a headless CLI, the ROM build, and the N64 runtime.

## Source and runtime formats

UI source assets use versioned, human-editable `.bfui` JSON. The editor build compiles them to `.ui64`; generated `.ui64` files must not be edited.

A v1 document declares a target canvas, safe area, integer snap size, and a rooted element tree. Supported elements are `Container`, `Image`, `Text`, `Button`, `TextInput`, and `ProgressBar`. Every element has a unique stable string `id`, anchored layout, pixel offsets, visibility/enabled state, style colors, and optional children. Images and fonts may be referenced by asset UUID or by an `assets/<path>` string. Image fit can be `stretch` or `native`; text inputs declare their controller keyboard `charset`, maximum length, and whether Start submits the value.

`ProgressBar` stores integer `value` and `max` fields in the unsigned 16-bit range, a `style.fillColor`, and up to three optional thresholds. Thresholds are absolute upper bounds, must be strictly ascending in `0..max`, and select the first matching color:

```json
{
  "id": "health",
  "type": "ProgressBar",
  "layout": {"anchors": [0, 0, 0, 0], "offsets": [8, 8, 108, 20]},
  "value": 75,
  "max": 100,
  "style": {"color": "#202020FF", "fillColor": "#40C060FF"},
  "thresholds": [
    {"max": 25, "color": "#D04040FF"},
    {"max": 50, "color": "#E0B030FF"}
  ]
}
```

The build rejects unsupported versions, duplicate IDs, runtime CRC32 ID collisions, malformed layouts, unresolved image/font references, more than 256 elements, oversized string tables, and fonts that do not have an auto-load ID from 1 through 15.

## GUI workflow

Open **Focus → UI** in the editor. The UI workspace lists `.bfui` documents and opens them in a dedicated hierarchy/canvas/inspector view. It supports:

- N64-resolution canvas preview and safe-area overlay;
- anchored positioning, pixel offsets, snap-aware drag and resize;
- element creation, deletion, and sibling reordering;
- source image/font assignment and text/input properties;
- progress values, fill color, and ordered color thresholds;
- automatic or explicit controller-focus links;
- validation feedback, save/reload, and unsaved-close confirmation.

The desktop preview uses source PNG/TTF assets and is approximate. Ares, gopher64, or hardware output remains authoritative for font rasterization, filtering, and RDP blending.

## CLI workflow

```bash
./bf64 focus list --json
./bf64 ui new menus/title --project ./game --json
./bf64 ui ls --project ./game --json
./bf64 ui show assets/menus/title.bfui --project ./game --json
./bf64 ui validate --all --project ./game --json
./bf64 build --execute --project ./game --json
```

`ui new`, `ls`, `show`, and `validate` support stable JSON. Mutation is document-oriented: agents edit `.bfui` JSON as a whole rather than issuing a command for each property.

## Scene and runtime API

Attach a **UI Document** component to a scene object and select the `.bfui` asset. UI components update with the scene and render once in the 2D pass after all cameras, including in multi-camera scenes.

Runtime element IDs use the `_ui` literal, which matches the builder's CRC32 value:

```cpp
#include <scene/components/ui.h>

auto *ui = obj.getComponent<P64::Comp::UI>();
ui->setText("score"_ui, "100");
ui->setValue("health"_ui, 75, 100);
ui->setVisible("pausePanel"_ui, true);
ui->focus("nameInput"_ui);
const char *name = ui->getText("nameInput"_ui);
```

`setValue` rejects missing/non-ProgressBar IDs and a zero maximum. Values above the supplied maximum are clamped.

Buttons emit `EVENT_TYPE_UI_ACTIVATE`. Text edits emit `EVENT_TYPE_UI_CHANGE`, and Start submits with `EVENT_TYPE_UI_SUBMIT`. The event value is the stable element ID; query the UI component for current input text.

Controller behavior is D-pad navigation, A to activate/select a keyboard character, C-left to erase, B to cancel editing, and Start to submit. Explicit focus links override spatial navigation when present. Keyboard selection, maximum length, and erase all operate on complete UTF-8 code points rather than raw bytes; programmatic `setText` also enforces the TextInput character limit. Text APIs reject Container, Image, and ProgressBar IDs.

## Dialogue sequencing

`P64::UI::DialogueRunner` layers reusable typewriter and line sequencing over any text/speaker element pair. It supports per-line or default characters-per-second, manual skip/advance, optional timed holds, UTF-8-safe reveal, completion/cancellation events, and a callback sink for non-UI tests or alternate text surfaces.

```cpp
#include <iterator>
#include <ui/dialogue.h>

static constexpr P64::UI::DialogueLine lines[]{
  {.speaker="Guide", .text="Press A when you are ready."},
  {.speaker="Guide", .text="Let's go!", .holdSeconds=0.75f},
};

P64::UI::DialogueRunner dialogue;
ui->bindDialogue(dialogue, "dialogue"_ui, "speaker"_ui);
dialogue.start(lines, std::size(lines));

// Once per update:
dialogue.update(deltaTime);
if(confirmPressed)dialogue.advance();
```

The runner is input-agnostic: game code chooses the confirm button and coordinates portraits, voices, cameras, or cutscene state through its event callback. See [Dialogue and typewriter sequencing](dialogue.md) for the full contract.

## V1 boundaries

V1 intentionally excludes expression data binding, localization tables, authored branching-dialogue assets, inline control codes/choices, flex/grid layout, nine-slice images, and node-graph UI bindings. Runtime typewriter sequencing is available through `DialogueRunner`; richer authored tracks can layer onto the stable document, component, and event interfaces without changing element IDs.
