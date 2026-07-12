/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "ui/dialogue.h"
#include "ui/utf8.h"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace
{
  bool positiveFinite(float value)
  {
    return value > 0.0f && std::isfinite(value);
  }
}

void P64::UI::DialogueRunner::bind(
  DialogueTextSink sink,
  void *context,
  uint32_t textElement,
  uint32_t speakerElement)
{
  textSink_ = sink;
  textContext_ = context;
  textElement_ = textElement;
  speakerElement_ = speakerElement;
}

void P64::UI::DialogueRunner::setEventSink(DialogueEventSink sink, void *context)
{
  eventSink_ = sink;
  eventContext_ = context;
}

bool P64::UI::DialogueRunner::start(
  const DialogueLine *lines,
  size_t lineCount,
  const DialogueSettings &settings)
{
  if(!lines || lineCount == 0)return false;
  lines_ = lines;
  lineCount_ = lineCount;
  settings_ = settings;
  beginLine(0);
  return true;
}

void P64::UI::DialogueRunner::update(float deltaTime)
{
  if(!active() || !(deltaTime > 0.0f) || !std::isfinite(deltaTime))return;
  float remaining = deltaTime;
  constexpr float EPSILON = 0.00001f;

  while(active() && remaining > EPSILON) {
    if(state_ == DialogueState::Typing) {
      const float speed = currentCharactersPerSecond();
      if(!positiveFinite(speed)) {
        revealLine();
        continue;
      }
      const float secondsToNext = (1.0f - characterProgress_) / speed;
      if(remaining + EPSILON < secondsToNext) {
        characterProgress_ += remaining * speed;
        return;
      }
      remaining = std::max(0.0f, remaining - secondsToNext);
      characterProgress_ = 0.0f;
      revealNextCharacter();
      continue;
    }

    const float hold = currentHoldSeconds();
    if(!(hold >= 0.0f) || !std::isfinite(hold))return;
    const float untilAdvance = std::max(0.0f, hold - waitElapsed_);
    if(remaining + EPSILON < untilAdvance) {
      waitElapsed_ += remaining;
      return;
    }
    remaining = std::max(0.0f, remaining - untilAdvance);
    waitElapsed_ = hold;
    moveNext();
  }
}

bool P64::UI::DialogueRunner::advance()
{
  if(state_ == DialogueState::Typing) {
    revealLine();
    return true;
  }
  if(state_ == DialogueState::Waiting) {
    moveNext();
    return true;
  }
  return false;
}

void P64::UI::DialogueRunner::cancel(bool clear)
{
  if(state_ == DialogueState::Idle)return;
  if(clear) {
    visibleText_.clear();
    publishText(textElement_, "");
    publishText(speakerElement_, "");
  }
  notify(DialogueEvent::Cancelled);
  lines_ = nullptr;
  lineCount_ = 0;
  currentLine_ = NO_LINE;
  currentBytes_ = 0;
  visibleBytes_ = 0;
  visibleCharacters_ = 0;
  characterProgress_ = 0.0f;
  waitElapsed_ = 0.0f;
  state_ = DialogueState::Idle;
}

void P64::UI::DialogueRunner::beginLine(size_t line)
{
  currentLine_ = line;
  const char *text = lines_[line].text ? lines_[line].text : "";
  currentBytes_ = std::strlen(text);
  visibleBytes_ = 0;
  visibleCharacters_ = 0;
  characterProgress_ = 0.0f;
  waitElapsed_ = 0.0f;
  visibleText_.clear();
  visibleText_.reserve(currentBytes_);
  publishText(speakerElement_, lines_[line].speaker ? lines_[line].speaker : "");
  publishText(textElement_, "");
  state_ = DialogueState::Typing;
  notify(DialogueEvent::LineStarted);
  if(currentBytes_ == 0) {
    state_ = DialogueState::Waiting;
    notify(DialogueEvent::LineRevealed);
  }
}

void P64::UI::DialogueRunner::revealNextCharacter()
{
  if(state_ != DialogueState::Typing)return;
  const char *text = lines_[currentLine_].text ? lines_[currentLine_].text : "";
  visibleBytes_ = Utf8::nextOffset(text, currentBytes_, visibleBytes_);
  ++visibleCharacters_;
  visibleText_.assign(text, visibleBytes_);
  publishText(textElement_, visibleText_.c_str());
  if(visibleBytes_ >= currentBytes_) {
    state_ = DialogueState::Waiting;
    waitElapsed_ = 0.0f;
    notify(DialogueEvent::LineRevealed);
  }
}

void P64::UI::DialogueRunner::revealLine()
{
  if(state_ != DialogueState::Typing)return;
  while(state_ == DialogueState::Typing)revealNextCharacter();
}

void P64::UI::DialogueRunner::moveNext()
{
  if(state_ != DialogueState::Waiting)return;
  notify(DialogueEvent::LineAdvanced);
  if(currentLine_ + 1 >= lineCount_) {
    complete();
    return;
  }
  beginLine(currentLine_ + 1);
}

void P64::UI::DialogueRunner::complete()
{
  state_ = DialogueState::Complete;
  if(settings_.clearOnComplete) {
    visibleText_.clear();
    publishText(textElement_, "");
    publishText(speakerElement_, "");
  }
  notify(DialogueEvent::Completed);
}

void P64::UI::DialogueRunner::publishText(uint32_t element, const char *value) const
{
  if(textSink_ && element != NO_ELEMENT)textSink_(textContext_, element, value);
}

void P64::UI::DialogueRunner::notify(DialogueEvent event) const
{
  if(eventSink_)eventSink_(eventContext_, event, currentLine_);
}

float P64::UI::DialogueRunner::currentCharactersPerSecond() const
{
  const float lineSpeed = lines_[currentLine_].charactersPerSecond;
  return positiveFinite(lineSpeed) ? lineSpeed : settings_.charactersPerSecond;
}

float P64::UI::DialogueRunner::currentHoldSeconds() const
{
  const float lineHold = lines_[currentLine_].holdSeconds;
  return lineHold >= 0.0f ? lineHold : settings_.holdSeconds;
}
