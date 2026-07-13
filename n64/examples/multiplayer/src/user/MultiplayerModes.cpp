#include "input/input.h"
#include "debug/debugDraw.h"
#include "multiplayer/session.h"
#include "multiplayer/spawns.h"
#include "scene/object.h"
#include "scene/scene.h"
#include "scene/sceneManager.h"
#include "script/globalScript.h"

#include <algorithm>

namespace MultiplayerExample
{
  enum class Mode { ArenaFFA, ArenaTeams, CheckpointRace };
  Mode currentMode{Mode::ArenaFFA};

  constexpr color_t PLAYER_COLORS[4]{
    {0x4D,0xA3,0xFF,0xFF}, {0xFF,0x5A,0x5A,0xFF},
    {0x62,0xD2,0x6F,0xFF}, {0xFF,0xD2,0x4D,0xFF}
  };

  const char* stateName(P64::Multiplayer::State state)
  {
    using enum P64::Multiplayer::State;
    switch(state) {
      case Lobby: return "LOBBY";
      case Countdown: return "COUNTDOWN";
      case Playing: return "PLAYING";
      case Paused: return "PAUSED - RECONNECT + A";
      case RoundEnd: return "ROUND END - A FOR NEXT ROUND";
      case MatchEnd: return "MATCH END - START TO REMATCH";
      case Tiebreak: return "TIEBREAK - FIRST A WINS";
    }
    return "";
  }

  void configure(Mode mode)
  {
    currentMode = mode;
    P64::Multiplayer::Config config{};
    config.scoreLimit = mode == Mode::CheckpointRace ? 0 : 5;
    config.timeLimitSeconds = mode == Mode::CheckpointRace ? 90.0f : 120.0f;
    config.startingStocks = mode == Mode::CheckpointRace ? 0 : 3;
    config.roundsToWin = 2;
    config.respawnDelaySeconds = 1.25f;
    config.teams = mode == Mode::ArenaTeams;
    config.teamAssignment = mode == Mode::ArenaTeams
      ? P64::Multiplayer::TeamAssignment::Alternating
      : P64::Multiplayer::TeamAssignment::Manual;
    P64::Multiplayer::getSession().configure(config);
    P64::Multiplayer::getSession().reset(true);
  }

  void updateLobby()
  {
    auto &session = P64::Multiplayer::getSession();
    for(uint8_t player=0; player<P64::Input::PLAYER_COUNT; ++player) {
      if(P64::Input::pressed(player, "ready"_action, true))session.setReady(player, true);
    }
    if(session.activeCount() > 0 && (session.readyMask() & session.activeMask()) == session.activeMask()) {
      session.beginCountdown(3.0f);
    }
  }

  void updatePauseAndReconnect()
  {
    auto &session = P64::Multiplayer::getSession();
    for(uint8_t player=0; player<P64::Input::PLAYER_COUNT; ++player) {
      if(session.getState() == P64::Multiplayer::State::Paused &&
         P64::Input::pressed(player, "confirm"_action, true)) {
        if(session.getPauseReason() == P64::Multiplayer::PauseReason::ControllerDisconnected)session.confirmReconnect(player);
        else session.resume();
      }
    }
  }

  void arenaScore(uint8_t player)
  {
    if(P64::Multiplayer::getSession().addScore(player))P64::Input::rumble(player, 0.12f);
  }

  void arenaStockLost(uint8_t player)
  {
    if(P64::Multiplayer::getSession().loseStock(player))P64::Input::rumble(player, 0.30f);
  }

  P64::Object* consumeRespawn(uint8_t player)
  {
    auto &session = P64::Multiplayer::getSession();
    if(!session.consumeRespawn(player))return nullptr;
    if(auto *spawn = session.resolveSpawn(player))return spawn;
    return P64::Multiplayer::Spawns::select(player);
  }

  void raceFinish(uint8_t player)
  {
    P64::Multiplayer::getSession().finish(player);
    P64::Input::rumble(player, 0.18f);
  }

  void rematch()
  {
    P64::Input::stopAllRumble();
    P64::Multiplayer::getSession().rematch();
  }

  void updateMatch()
  {
    auto &session = P64::Multiplayer::getSession();
    updatePauseAndReconnect();
    if(session.getState() == P64::Multiplayer::State::Lobby) {
      if(currentMode != Mode::CheckpointRace && session.activeCount() == 0) {
        for(std::uint8_t player=0; player<P64::Input::PLAYER_COUNT; ++player) {
          if(P64::Input::buttonPressed(player, P64::Input::Button::D_LEFT))configure(Mode::ArenaFFA);
          if(P64::Input::buttonPressed(player, P64::Input::Button::D_RIGHT))configure(Mode::ArenaTeams);
        }
      }
      updateLobby();
      return;
    }
    for(std::uint8_t player=0; player<P64::Input::PLAYER_COUNT; ++player) {
      if(!session.getPlayer(player).active)continue;
      if(session.getState() == P64::Multiplayer::State::Playing) {
        if(P64::Input::pressed(player, "pause"_action, true))session.pause();
        if(P64::Input::pressed(player, "primary"_action, true)) {
          if(currentMode == Mode::CheckpointRace)raceFinish(player);
          else arenaScore(player);
        }
        if(currentMode != Mode::CheckpointRace && P64::Input::buttonPressed(player, P64::Input::Button::B))arenaStockLost(player);
        if(session.getPlayer(player).respawnReady)consumeRespawn(player);
      } else if(session.getState() == P64::Multiplayer::State::Tiebreak &&
                P64::Input::pressed(player, "confirm"_action, true)) {
        session.resolveTiebreak(player);
      } else if(session.getState() == P64::Multiplayer::State::RoundEnd &&
                P64::Input::pressed(player, "confirm"_action, true)) {
        session.beginCountdown(3.0f);
      } else if(session.getState() == P64::Multiplayer::State::MatchEnd &&
                P64::Input::pressed(player, "ready"_action, true)) {
        rematch();
      }
    }
  }

  void drawStatus()
  {
    using namespace P64;
    auto &session = Multiplayer::getSession();
    Debug::printStart();
    Debug::isMonospace = true;
    Debug::setColor({0xFF,0xFF,0xFF,0xFF});
    Debug::printf(8, 8, "%s | %s", currentMode == Mode::CheckpointRace ? "CHECKPOINT RACE" :
      currentMode == Mode::ArenaTeams ? "TEAM ARENA" : "FFA ARENA", stateName(session.getState()));
    if(session.getState() == Multiplayer::State::Lobby) {
      Debug::print(8, 20, "START: READY   LEFT/RIGHT: FFA/TEAMS");
    } else if(session.getState() == Multiplayer::State::Playing) {
      Debug::print(8, 20, currentMode == Mode::CheckpointRace ? "A/Z: FINISH" : "A/Z: SCORE   B: LOSE STOCK");
    }

    for(std::uint8_t player=0; player<Input::PLAYER_COUNT; ++player) {
      const auto &entry = session.getPlayer(player);
      const auto *camera = Object::getScene().getCameraForPlayer(player);
      std::uint16_t x = 8;
      std::uint16_t y = static_cast<std::uint16_t>(40 + player*12);
      if(camera && camera->isActive()) {
        const auto &area = camera->getScreenArea();
        x = static_cast<std::uint16_t>(std::max(0, area.x + 6));
        y = static_cast<std::uint16_t>(std::max(0, area.y + 34));
      }
      Debug::setColor(PLAYER_COLORS[player]);
      Debug::printf(x, y, "P%d %s S:%ld K:%d W:%d F:%d", player+1,
        entry.connected ? entry.ready ? "READY" : "JOIN" : "OFF",
        static_cast<long>(entry.score), entry.stocks, entry.roundWins, entry.placement);
    }
    Debug::setColor();
  }
}

namespace P64::GlobalScript::C000000000000001
{
  void onScenePostLoad()
  {
    MultiplayerExample::configure(
      SceneManager::getCurrent().getId() == 2
        ? MultiplayerExample::Mode::CheckpointRace
        : MultiplayerExample::Mode::ArenaFFA
    );
  }

  void onSceneUnscaledUpdate()
  {
    MultiplayerExample::updateMatch();
  }

  void onSceneDraw2D()
  {
    MultiplayerExample::drawStatus();
  }
}
