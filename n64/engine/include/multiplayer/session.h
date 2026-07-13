/**
 * Genre-neutral persistent local multiplayer match state.
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#pragma once

#include <array>
#include <cstdint>

namespace P64 { class Object; }

namespace P64::Multiplayer
{
  constexpr std::uint8_t MAX_PLAYERS = 4;
  constexpr std::uint8_t MAX_EVENT_CALLBACKS = 8;
  constexpr std::uint8_t MAX_SPAWN_CALLBACKS = 4;

  enum class State : std::uint8_t
  {
    Lobby,
    Countdown,
    Playing,
    Paused,
    RoundEnd,
    MatchEnd,
    Tiebreak,
  };

  enum class LateJoinPolicy : std::uint8_t
  {
    LobbyOnly,
    AllowDuringMatch,
  };

  enum class TeamAssignment : std::uint8_t
  {
    Manual,
    Alternating,
  };

  enum class PauseReason : std::uint8_t
  {
    None,
    Manual,
    ControllerDisconnected,
  };

  enum class DisconnectPolicy : std::uint8_t
  {
    PauseOnAnyActive,
    PauseWhenAllActiveDisconnected,
    Continue,
  };

  struct Config
  {
    std::int32_t scoreLimit{};
    float timeLimitSeconds{};
    std::int16_t startingStocks{};
    std::uint8_t roundsToWin{1};
    float respawnDelaySeconds{1.0f};
    bool teams{};
    TeamAssignment teamAssignment{TeamAssignment::Manual};
    LateJoinPolicy lateJoin{LateJoinPolicy::LobbyOnly};
    DisconnectPolicy disconnectPolicy{DisconnectPolicy::PauseOnAnyActive};
  };

  struct Player
  {
    Object *boundObject{};
    std::int32_t score{};
    std::int16_t stocks{};
    std::uint8_t roundWins{};
    std::uint8_t placement{};
    std::uint8_t team{};
    bool connected{};
    bool active{};
    bool ready{};
    bool eliminated{};
    bool reconnectConfirmed{};
    bool respawnPending{};
    bool respawnReady{};
    float respawnRemaining{};
  };

  enum class EventType : std::uint8_t
  {
    StateChanged,
    Connected,
    Disconnected,
    ReadyChanged,
    ScoreChanged,
    StockLost,
    Eliminated,
    RespawnReady,
    Finished,
    RoundCompleted,
    MatchCompleted,
  };

  struct Event
  {
    EventType type{};
    State state{};
    std::uint8_t player{0xFF};
    std::uint8_t value{};
  };

  using EventCallback = void(*)(const Event &event, void *context);
  using SpawnCallback = Object*(*)(std::uint8_t player, void *context);

  class Session
  {
    public:
      Session();

      void configure(const Config &config);
      void reset(bool preserveConnections = true);
      void rematch();
      void update(float unscaledDeltaTime);
      void syncControllers();

      [[nodiscard]] const Config& getConfig() const { return config_; }
      [[nodiscard]] State getState() const { return state_; }
      [[nodiscard]] PauseReason getPauseReason() const { return pauseReason_; }
      [[nodiscard]] float getStateTimeRemaining() const { return stateTimeRemaining_; }
      [[nodiscard]] float getMatchTimeRemaining() const { return matchTimeRemaining_; }
      [[nodiscard]] const Player& getPlayer(std::uint8_t player) const;
      [[nodiscard]] Player& getPlayer(std::uint8_t player);
      [[nodiscard]] std::uint8_t activeMask() const;
      [[nodiscard]] std::uint8_t connectedMask() const;
      [[nodiscard]] std::uint8_t readyMask() const;
      [[nodiscard]] std::uint8_t activeCount() const;
      [[nodiscard]] bool gameplayPaused() const { return state_ == State::Paused; }

      bool setActive(std::uint8_t player, bool active);
      bool setReady(std::uint8_t player, bool ready = true);
      bool setTeam(std::uint8_t player, std::uint8_t team);
      bool bindObject(std::uint8_t player, Object *object);
      bool beginCountdown(float seconds = 3.0f);
      bool startPlaying();
      bool pause();
      bool resume();
      bool confirmReconnect(std::uint8_t player);

      bool setScore(std::uint8_t player, std::int32_t score);
      bool addScore(std::uint8_t player, std::int32_t amount = 1);
      bool loseStock(std::uint8_t player, std::int16_t amount = 1);
      bool eliminate(std::uint8_t player);
      bool finish(std::uint8_t player, std::uint8_t placement = 0);
      bool requestRespawn(std::uint8_t player, float delaySeconds = -1.0f);
      bool consumeRespawn(std::uint8_t player);
      bool completeRound(std::uint8_t winnerPlayer);
      bool resolveTiebreak(std::uint8_t winnerPlayer);

      bool addEventCallback(EventCallback callback, void *context = nullptr);
      void removeEventCallback(EventCallback callback, void *context = nullptr);
      bool addSpawnCallback(SpawnCallback callback, void *context = nullptr);
      void removeSpawnCallback(SpawnCallback callback, void *context = nullptr);
      [[nodiscard]] Object* resolveSpawn(std::uint8_t player) const;

    private:
      struct CallbackEntry { EventCallback callback{}; void *context{}; };
      struct SpawnCallbackEntry { SpawnCallback callback{}; void *context{}; };

      Config config_{};
      std::array<Player, MAX_PLAYERS> players_{};
      std::array<CallbackEntry, MAX_EVENT_CALLBACKS> callbacks_{};
      std::array<SpawnCallbackEntry, MAX_SPAWN_CALLBACKS> spawnCallbacks_{};
      State state_{State::Lobby};
      State resumeState_{State::Playing};
      PauseReason pauseReason_{PauseReason::None};
      float stateTimeRemaining_{};
      float matchTimeRemaining_{};
      std::uint8_t nextPlacement_{1};

      void changeState(State state);
      void emit(EventType type, std::uint8_t player = 0xFF, std::uint8_t value = 0);
      bool playerValid(std::uint8_t player) const { return player < MAX_PLAYERS; }
      bool canMutatePlayer(std::uint8_t player) const;
      void checkScoreWinner();
      void checkStockWinner();
      void completeAutomaticRanking();
      void pauseForDisconnect();
  };

  /** Process-lifetime state; scenes may bind/unbind objects without resetting the match. */
  Session& getSession();
}
