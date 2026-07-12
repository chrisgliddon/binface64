# Dialogue and typewriter sequencing

`P64::UI::DialogueRunner` is a reusable runtime sequencer for `.bfui` text elements. It owns line progression and reveal timing but deliberately does not read controller input, change scenes, play voices, or own authored strings. Game code decides when to advance and can coordinate audio, portraits, cameras, and cutscene node graphs through events.

## Basic use

Create `Text` elements with stable IDs such as `speaker` and `dialogue` in a `.bfui` document, then bind a runner to the component:

```cpp
#include <iterator>
#include "scene/components/ui.h"
#include "ui/dialogue.h"

static constexpr P64::UI::DialogueLine LINES[]{
  {.speaker="Mara", .text="The gate is open.", .charactersPerSecond=24.0f},
  {.speaker="Mara", .text="Stay close.", .holdSeconds=0.75f},
};

P64::UI::DialogueRunner dialogue;

auto *ui = object.getComponent<P64::Comp::UI>();
if(ui && ui->bindDialogue(dialogue, "dialogue"_ui, "speaker"_ui)) {
  P64::UI::DialogueSettings settings{};
  settings.charactersPerSecond = 30.0f;
  settings.holdSeconds = -1.0f; // wait for advance() by default
  dialogue.start(LINES, std::size(LINES), settings);
}
```

Call `dialogue.update(deltaTime)` once per game update. Map the game's chosen confirm input to `dialogue.advance()`:

- while `Typing`, advance reveals the rest of the current line;
- while `Waiting`, advance starts the next line;
- the final advance enters `Complete`;
- `cancel(true)` returns to `Idle` and clears bound text.

A line with `charactersPerSecond <= 0` uses the configured default. A non-negative per-line `holdSeconds` automatically advances after that delay; a negative value inherits the configured hold, where a negative configured value means manual advance. Reveal counts UTF-8 code points and never publishes a partial multibyte sequence, though the selected N64 font must still contain the requested glyphs.

## Events and other text sinks

Register `setEventSink` to receive `LineStarted`, `LineRevealed`, `LineAdvanced`, `Completed`, and `Cancelled` with the current line index. Use those events to trigger voice clips, portraits, or gameplay state.

The runner is independent of `Comp::UI`. `bind` accepts a small callback `(context, elementId, value)`, so code can drive another text surface or test the sequence on a host without libdragon. The line array and all referenced strings must remain alive until completion or cancellation.

## Deliberate boundaries

The runner does not yet define a JSON dialogue asset, branching choices, localization tables, inline color/icon control codes, voice timing, or a visual timeline. Those can build on the runner and stable `.bfui` IDs without changing the UI document format.
