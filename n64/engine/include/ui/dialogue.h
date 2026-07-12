/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace P64::UI
{
  enum class DialogueState : uint8_t
  {
    Idle,
    Typing,
    Waiting,
    Complete,
  };

  enum class DialogueEvent : uint8_t
  {
    LineStarted,
    LineRevealed,
    LineAdvanced,
    Completed,
    Cancelled,
  };

  struct DialogueLine
  {
    const char *speaker{};
    const char *text{};
    float charactersPerSecond{};
    float holdSeconds{-1.0f};
  };

  struct DialogueSettings
  {
    float charactersPerSecond{30.0f};
    float holdSeconds{-1.0f};
    bool clearOnComplete{};
  };

  using DialogueTextSink = bool(*)(void *context, uint32_t element, const char *value);
  using DialogueEventSink = void(*)(void *context, DialogueEvent event, size_t line);

  /**
   * Drives typewriter text independently of input and rendering.
   *
   * DialogueLine strings and the line array must remain alive until the runner
   * completes or is cancelled. A negative hold time waits for advance().
   */
  class DialogueRunner
  {
  public:
    static constexpr uint32_t NO_ELEMENT = 0;
    static constexpr size_t NO_LINE = static_cast<size_t>(-1);

    void bind(
      DialogueTextSink sink,
      void *context,
      uint32_t textElement,
      uint32_t speakerElement=NO_ELEMENT);
    void setEventSink(DialogueEventSink sink, void *context);

    bool start(
      const DialogueLine *lines,
      size_t lineCount,
      const DialogueSettings &settings={});
    void update(float deltaTime);
    bool advance();
    void cancel(bool clear=false);

    [[nodiscard]] DialogueState state() const { return state_; }
    [[nodiscard]] bool active() const { return state_ == DialogueState::Typing || state_ == DialogueState::Waiting; }
    [[nodiscard]] bool finished() const { return state_ == DialogueState::Complete; }
    [[nodiscard]] size_t currentLine() const { return currentLine_; }
    [[nodiscard]] size_t visibleCharacters() const { return visibleCharacters_; }
    [[nodiscard]] const char* visibleText() const { return visibleText_.c_str(); }

  private:
    void beginLine(size_t line);
    void revealNextCharacter();
    void revealLine();
    void moveNext();
    void complete();
    void publishText(uint32_t element, const char *value) const;
    void notify(DialogueEvent event) const;
    [[nodiscard]] float currentCharactersPerSecond() const;
    [[nodiscard]] float currentHoldSeconds() const;

    const DialogueLine *lines_{};
    size_t lineCount_{};
    size_t currentLine_{NO_LINE};
    size_t currentBytes_{};
    size_t visibleBytes_{};
    size_t visibleCharacters_{};
    float characterProgress_{};
    float waitElapsed_{};
    DialogueSettings settings_{};
    DialogueState state_{DialogueState::Idle};
    std::string visibleText_{};

    DialogueTextSink textSink_{};
    void *textContext_{};
    uint32_t textElement_{NO_ELEMENT};
    uint32_t speakerElement_{NO_ELEMENT};
    DialogueEventSink eventSink_{};
    void *eventContext_{};
  };
}
