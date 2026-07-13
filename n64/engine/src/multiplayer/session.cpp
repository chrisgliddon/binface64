/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "multiplayer/session.h"

#include <algorithm>
#include "input/input.h"

namespace
{
  P64::Multiplayer::Player invalidPlayer{};
}

P64::Multiplayer::Session::Session()
{
  reset(false);
}

void P64::Multiplayer::Session::configure(const Config &config)
{
  config_ = config;
  config_.roundsToWin = std::max<std::uint8_t>(1, config_.roundsToWin);
  config_.respawnDelaySeconds = std::max(0.0f, config_.respawnDelaySeconds);
  if(config_.teamAssignment == TeamAssignment::Alternating) {
    for(std::uint8_t player=0; player<MAX_PLAYERS; ++player)players_[player].team = player & 1u;
  }
}

void P64::Multiplayer::Session::reset(bool preserveConnections)
{
  Input::stopAllRumble();
  std::array<bool, MAX_PLAYERS> connections{};
  if(preserveConnections) {
    for(std::uint8_t player=0; player<MAX_PLAYERS; ++player)connections[player] = players_[player].connected;
  }
  players_ = {};
  for(std::uint8_t player=0; player<MAX_PLAYERS; ++player) {
    players_[player].connected = connections[player];
    players_[player].stocks = config_.startingStocks;
    if(config_.teamAssignment == TeamAssignment::Alternating)players_[player].team = player & 1u;
  }
  state_ = State::Lobby;
  resumeState_ = State::Playing;
  pauseReason_ = PauseReason::None;
  stateTimeRemaining_ = 0.0f;
  matchTimeRemaining_ = config_.timeLimitSeconds;
  nextPlacement_ = 1;
  emit(EventType::StateChanged);
}

void P64::Multiplayer::Session::rematch()
{
  reset(true);
}

void P64::Multiplayer::Session::update(float unscaledDeltaTime)
{
  const float dt = std::max(0.0f, unscaledDeltaTime);
  for(std::uint8_t player=0; player<MAX_PLAYERS; ++player) {
    auto &entry = players_[player];
    if(!entry.respawnPending || entry.respawnReady || state_ == State::Paused)continue;
    entry.respawnRemaining -= dt;
    if(entry.respawnRemaining <= 0.0f) {
      entry.respawnRemaining = 0.0f;
      entry.respawnReady = true;
      emit(EventType::RespawnReady, player);
    }
  }

  if(state_ == State::Countdown) {
    stateTimeRemaining_ -= dt;
    if(stateTimeRemaining_ <= 0.0f)startPlaying();
  } else if(state_ == State::Playing && config_.timeLimitSeconds > 0.0f) {
    matchTimeRemaining_ -= dt;
    if(matchTimeRemaining_ <= 0.0f) {
      matchTimeRemaining_ = 0.0f;
      completeAutomaticRanking();
    }
  }
}

void P64::Multiplayer::Session::syncControllers()
{
  for(std::uint8_t player=0; player<MAX_PLAYERS; ++player) {
    const bool nowConnected = Input::connected(player);
    auto &entry = players_[player];
    if(nowConnected == entry.connected)continue;
    entry.connected = nowConnected;
    entry.reconnectConfirmed = false;
    emit(nowConnected ? EventType::Connected : EventType::Disconnected, player);
    if(!nowConnected && entry.active &&
       (state_ == State::Playing || state_ == State::Countdown || state_ == State::Paused)) {
      bool shouldPause = config_.disconnectPolicy == DisconnectPolicy::PauseOnAnyActive;
      if(config_.disconnectPolicy == DisconnectPolicy::PauseWhenAllActiveDisconnected) {
        shouldPause = true;
        for(const auto &candidate : players_) {
          if(candidate.active && candidate.connected) { shouldPause = false; break; }
        }
      }
      if(shouldPause)pauseForDisconnect();
    }
    if(nowConnected && state_ != State::Lobby && config_.lateJoin == LateJoinPolicy::AllowDuringMatch) {
      entry.active = true;
      entry.stocks = config_.startingStocks;
    }
  }
}

const P64::Multiplayer::Player& P64::Multiplayer::Session::getPlayer(std::uint8_t player) const
{
  return playerValid(player) ? players_[player] : invalidPlayer;
}

P64::Multiplayer::Player& P64::Multiplayer::Session::getPlayer(std::uint8_t player)
{
  return playerValid(player) ? players_[player] : invalidPlayer;
}

std::uint8_t P64::Multiplayer::Session::activeMask() const
{
  std::uint8_t result{};
  for(std::uint8_t player=0; player<MAX_PLAYERS; ++player)if(players_[player].active)result |= 1u << player;
  return result;
}

std::uint8_t P64::Multiplayer::Session::connectedMask() const
{
  std::uint8_t result{};
  for(std::uint8_t player=0; player<MAX_PLAYERS; ++player)if(players_[player].connected)result |= 1u << player;
  return result;
}

std::uint8_t P64::Multiplayer::Session::readyMask() const
{
  std::uint8_t result{};
  for(std::uint8_t player=0; player<MAX_PLAYERS; ++player)if(players_[player].ready)result |= 1u << player;
  return result;
}

std::uint8_t P64::Multiplayer::Session::activeCount() const
{
  return static_cast<std::uint8_t>(__builtin_popcount(activeMask()));
}

bool P64::Multiplayer::Session::setActive(std::uint8_t player, bool active)
{
  if(!playerValid(player))return false;
  if(state_ != State::Lobby && config_.lateJoin != LateJoinPolicy::AllowDuringMatch)return false;
  if(active && !players_[player].connected)return false;
  players_[player].active = active;
  players_[player].ready = active && players_[player].ready;
  players_[player].stocks = config_.startingStocks;
  players_[player].eliminated = false;
  if(config_.teamAssignment == TeamAssignment::Alternating)players_[player].team = player & 1u;
  return true;
}

bool P64::Multiplayer::Session::setReady(std::uint8_t player, bool ready)
{
  if(!playerValid(player) || state_ != State::Lobby || !players_[player].connected)return false;
  players_[player].active = ready || players_[player].active;
  players_[player].ready = ready;
  emit(EventType::ReadyChanged, player, ready ? 1 : 0);
  return true;
}

bool P64::Multiplayer::Session::setTeam(std::uint8_t player, std::uint8_t team)
{
  if(!playerValid(player) || team >= MAX_PLAYERS || state_ != State::Lobby ||
     config_.teamAssignment != TeamAssignment::Manual)return false;
  players_[player].team = team;
  return true;
}

bool P64::Multiplayer::Session::bindObject(std::uint8_t player, Object *object)
{
  if(!playerValid(player))return false;
  players_[player].boundObject = object;
  return true;
}

bool P64::Multiplayer::Session::beginCountdown(float seconds)
{
  if((state_ != State::Lobby && state_ != State::RoundEnd) || activeCount() == 0)return false;
  const std::uint8_t active = activeMask();
  if(state_ == State::Lobby && (readyMask() & active) != active)return false;
  for(std::uint8_t player=0; player<MAX_PLAYERS; ++player) {
    if(players_[player].active) {
      players_[player].score = 0;
      players_[player].stocks = config_.startingStocks;
      players_[player].placement = 0;
      players_[player].eliminated = false;
      players_[player].respawnPending = false;
      players_[player].respawnReady = false;
      players_[player].respawnRemaining = 0.0f;
    }
  }
  stateTimeRemaining_ = std::max(0.0f, seconds);
  nextPlacement_ = 1;
  changeState(State::Countdown);
  if(stateTimeRemaining_ == 0.0f)return startPlaying();
  return true;
}

bool P64::Multiplayer::Session::startPlaying()
{
  if(state_ != State::Countdown && state_ != State::RoundEnd)return false;
  stateTimeRemaining_ = 0.0f;
  matchTimeRemaining_ = config_.timeLimitSeconds;
  changeState(State::Playing);
  return true;
}

bool P64::Multiplayer::Session::pause()
{
  if(state_ != State::Playing && state_ != State::Countdown)return false;
  resumeState_ = state_;
  pauseReason_ = PauseReason::Manual;
  changeState(State::Paused);
  return true;
}

bool P64::Multiplayer::Session::resume()
{
  if(state_ != State::Paused || pauseReason_ != PauseReason::Manual)return false;
  pauseReason_ = PauseReason::None;
  changeState(resumeState_);
  return true;
}

bool P64::Multiplayer::Session::confirmReconnect(std::uint8_t player)
{
  if(!playerValid(player) || state_ != State::Paused || pauseReason_ != PauseReason::ControllerDisconnected ||
     !players_[player].active || !players_[player].connected)return false;
  players_[player].reconnectConfirmed = true;
  if(config_.disconnectPolicy == DisconnectPolicy::PauseWhenAllActiveDisconnected) {
    pauseReason_ = PauseReason::None;
    changeState(resumeState_);
    return true;
  }
  for(const auto &entry : players_) {
    if(entry.active && (!entry.connected || !entry.reconnectConfirmed))return true;
  }
  pauseReason_ = PauseReason::None;
  changeState(resumeState_);
  return true;
}

bool P64::Multiplayer::Session::setScore(std::uint8_t player, std::int32_t score)
{
  if(!canMutatePlayer(player))return false;
  players_[player].score = score;
  emit(EventType::ScoreChanged, player);
  checkScoreWinner();
  return true;
}

bool P64::Multiplayer::Session::addScore(std::uint8_t player, std::int32_t amount)
{
  if(!canMutatePlayer(player))return false;
  return setScore(player, players_[player].score + amount);
}

bool P64::Multiplayer::Session::loseStock(std::uint8_t player, std::int16_t amount)
{
  if(!canMutatePlayer(player) || amount <= 0 || config_.startingStocks <= 0)return false;
  auto &entry = players_[player];
  entry.stocks = std::max<std::int16_t>(0, entry.stocks - amount);
  emit(EventType::StockLost, player);
  if(entry.stocks == 0)eliminate(player);
  else requestRespawn(player);
  checkStockWinner();
  return true;
}

bool P64::Multiplayer::Session::eliminate(std::uint8_t player)
{
  if(!canMutatePlayer(player) || players_[player].eliminated)return false;
  players_[player].eliminated = true;
  players_[player].respawnPending = false;
  players_[player].respawnReady = false;
  emit(EventType::Eliminated, player);
  checkStockWinner();
  return true;
}

bool P64::Multiplayer::Session::finish(std::uint8_t player, std::uint8_t placement)
{
  if(!canMutatePlayer(player) || players_[player].placement != 0)return false;
  players_[player].placement = placement ? placement : nextPlacement_++;
  nextPlacement_ = std::max<std::uint8_t>(nextPlacement_, players_[player].placement + 1);
  emit(EventType::Finished, player, players_[player].placement);
  std::uint8_t finished{};
  for(const auto &entry : players_)if(entry.active && entry.placement != 0)++finished;
  if(finished == activeCount()) {
    std::uint8_t winner = 0xFF;
    for(std::uint8_t index=0; index<MAX_PLAYERS; ++index)if(players_[index].active && players_[index].placement == 1) {
      if(winner != 0xFF) { changeState(State::Tiebreak); return true; }
      winner = index;
    }
    if(winner == 0xFF)changeState(State::Tiebreak);
    else completeRound(winner);
  }
  return true;
}

bool P64::Multiplayer::Session::requestRespawn(std::uint8_t player, float delaySeconds)
{
  if(!canMutatePlayer(player) || players_[player].eliminated)return false;
  auto &entry = players_[player];
  entry.respawnPending = true;
  entry.respawnReady = false;
  entry.respawnRemaining = delaySeconds < 0.0f ? config_.respawnDelaySeconds : std::max(0.0f, delaySeconds);
  if(entry.respawnRemaining == 0.0f) {
    entry.respawnReady = true;
    emit(EventType::RespawnReady, player);
  }
  return true;
}

bool P64::Multiplayer::Session::consumeRespawn(std::uint8_t player)
{
  if(!playerValid(player) || !players_[player].respawnPending || !players_[player].respawnReady)return false;
  players_[player].respawnPending = false;
  players_[player].respawnReady = false;
  return true;
}

bool P64::Multiplayer::Session::completeRound(std::uint8_t winnerPlayer)
{
  if(!playerValid(winnerPlayer) || !players_[winnerPlayer].active)return false;
  const std::uint8_t winningTeam = players_[winnerPlayer].team;
  for(std::uint8_t player=0; player<MAX_PLAYERS; ++player) {
    if(players_[player].active && (!config_.teams || players_[player].team == winningTeam))++players_[player].roundWins;
  }
  emit(EventType::RoundCompleted, winnerPlayer);
  if(players_[winnerPlayer].roundWins >= config_.roundsToWin) {
    changeState(State::MatchEnd);
    emit(EventType::MatchCompleted, winnerPlayer);
  } else {
    changeState(State::RoundEnd);
  }
  return true;
}

bool P64::Multiplayer::Session::resolveTiebreak(std::uint8_t winnerPlayer)
{
  if(state_ != State::Tiebreak)return false;
  return completeRound(winnerPlayer);
}

bool P64::Multiplayer::Session::addEventCallback(EventCallback callback, void *context)
{
  if(callback == nullptr)return false;
  for(auto &entry : callbacks_) {
    if(entry.callback == nullptr) { entry = {callback, context}; return true; }
  }
  return false;
}

void P64::Multiplayer::Session::removeEventCallback(EventCallback callback, void *context)
{
  for(auto &entry : callbacks_)if(entry.callback == callback && entry.context == context)entry = {};
}

bool P64::Multiplayer::Session::addSpawnCallback(SpawnCallback callback, void *context)
{
  if(callback == nullptr)return false;
  for(auto &entry : spawnCallbacks_) {
    if(entry.callback == nullptr) { entry = {callback, context}; return true; }
  }
  return false;
}

void P64::Multiplayer::Session::removeSpawnCallback(SpawnCallback callback, void *context)
{
  for(auto &entry : spawnCallbacks_)if(entry.callback == callback && entry.context == context)entry = {};
}

P64::Object* P64::Multiplayer::Session::resolveSpawn(std::uint8_t player) const
{
  if(!playerValid(player))return nullptr;
  for(const auto &entry : spawnCallbacks_)if(entry.callback) {
    if(auto *object = entry.callback(player, entry.context))return object;
  }
  return nullptr;
}

void P64::Multiplayer::Session::changeState(State state)
{
  if(state_ == state)return;
  state_ = state;
  emit(EventType::StateChanged);
}

void P64::Multiplayer::Session::emit(EventType type, std::uint8_t player, std::uint8_t value)
{
  const Event event{type, state_, player, value};
  for(const auto &entry : callbacks_)if(entry.callback)entry.callback(event, entry.context);
}

bool P64::Multiplayer::Session::canMutatePlayer(std::uint8_t player) const
{
  return playerValid(player) && state_ == State::Playing && players_[player].active && !players_[player].eliminated;
}

void P64::Multiplayer::Session::checkScoreWinner()
{
  if(config_.scoreLimit <= 0 || state_ != State::Playing)return;
  if(config_.teams) {
    std::array<std::int32_t, MAX_PLAYERS> teamScores{};
    for(const auto &entry : players_)if(entry.active)teamScores[entry.team % MAX_PLAYERS] += entry.score;
    for(std::uint8_t team=0; team<MAX_PLAYERS; ++team)if(teamScores[team] >= config_.scoreLimit) {
      completeAutomaticRanking(); return;
    }
  } else {
    for(const auto &entry : players_)if(entry.active && entry.score >= config_.scoreLimit) {
      completeAutomaticRanking(); return;
    }
  }
}

void P64::Multiplayer::Session::checkStockWinner()
{
  if(config_.startingStocks <= 0 || state_ != State::Playing)return;
  std::uint8_t competitionCount = activeCount();
  if(config_.teams) {
    std::array<bool, MAX_PLAYERS> teams{};
    competitionCount = 0;
    for(const auto &entry : players_)if(entry.active && !teams[entry.team % MAX_PLAYERS]) {
      teams[entry.team % MAX_PLAYERS] = true;
      ++competitionCount;
    }
  }
  std::uint8_t contender = 0xFF;
  std::uint8_t contenderTeam = 0xFF;
  for(std::uint8_t player=0; player<MAX_PLAYERS; ++player) {
    const auto &entry = players_[player];
    if(!entry.active || entry.eliminated)continue;
    if(contender == 0xFF) { contender = player; contenderTeam = entry.team; continue; }
    if(!config_.teams || entry.team != contenderTeam)return;
  }
  if(competitionCount <= 1) {
    if(contender == 0xFF)changeState(State::Tiebreak);
    return;
  }
  if(contender == 0xFF)changeState(State::Tiebreak);
  else completeRound(contender);
}

void P64::Multiplayer::Session::completeAutomaticRanking()
{
  std::int32_t best = INT32_MIN;
  std::uint8_t winner = 0xFF;
  bool tied = false;
  std::array<std::int32_t, MAX_PLAYERS> teamScores{};
  if(config_.teams)for(const auto &entry : players_)if(entry.active)teamScores[entry.team % MAX_PLAYERS] += entry.score;

  for(std::uint8_t player=0; player<MAX_PLAYERS; ++player) {
    const auto &entry = players_[player];
    if(!entry.active)continue;
    if(config_.teams) {
      bool firstOnTeam = true;
      for(std::uint8_t earlier=0; earlier<player; ++earlier)if(players_[earlier].active && players_[earlier].team == entry.team)firstOnTeam = false;
      if(!firstOnTeam)continue;
    }
    const std::int32_t score = config_.teams ? teamScores[entry.team % MAX_PLAYERS] : entry.score;
    if(score > best) { best = score; winner = player; tied = false; }
    else if(score == best) { tied = true; }
  }
  if(winner == 0xFF || tied)changeState(State::Tiebreak);
  else completeRound(winner);
}

void P64::Multiplayer::Session::pauseForDisconnect()
{
  if(state_ == State::Paused) {
    if(pauseReason_ != PauseReason::ControllerDisconnected) {
      pauseReason_ = PauseReason::ControllerDisconnected;
      for(auto &entry : players_)entry.reconnectConfirmed = entry.active && entry.connected;
      emit(EventType::StateChanged);
    }
    return;
  }
  resumeState_ = state_;
  pauseReason_ = PauseReason::ControllerDisconnected;
  for(auto &entry : players_)entry.reconnectConfirmed = entry.active && entry.connected;
  changeState(State::Paused);
}

P64::Multiplayer::Session& P64::Multiplayer::getSession()
{
  static P64::Multiplayer::Session persistentSession{};
  return persistentSession;
}
