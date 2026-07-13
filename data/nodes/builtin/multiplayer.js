// Fixed-port input and genre-neutral local multiplayer session nodes.

function _quoted(value) {
  return '"' + ("" + value).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
}

node({
  id: "multiplayer.player",
  name: icon("account") + " Player",
  color: Color.orange,
  category: "Multiplayer",
  outputs: [valueOut("u32")],
  props: { player: Enum({ values: ["Player 1", "Player 2", "Player 3", "Player 4"] }) },
  value(n, ctx) { return "uint32_t{" + n.player.index + "}"; },
});

node({
  id: "input.action",
  name: icon("gamepad") + " Action State",
  color: typeColor("i32"),
  category: "Input",
  inputs: [valueIn("Player", "u32")],
  outputs: [valueOut("i32")],
  props: {
    action: Str({ label: "Action", default: "confirm", width: 100 }),
    state: Enum({ values: ["Pressed", "Held", "Released"] }),
  },
  value(n, ctx) {
    ctx.include("<input/input.h>");
    const calls = ["pressed", "held", "released"];
    return "P64::Input::" + calls[n.state.index] + "((uint8_t)(" + ctx.inputExpr(0) + "), P64::Input::id(" + _quoted(n.action) + "))";
  },
});

node({
  id: "input.axis",
  name: icon("axis-arrow") + " Input Axis",
  color: typeColor("f32"),
  category: "Input",
  inputs: [valueIn("Player", "u32")],
  outputs: [valueOut("f32")],
  props: { axis: Str({ label: "Axis", default: "move_x", width: 100 }) },
  value(n, ctx) {
    ctx.include("<input/input.h>");
    return "P64::Input::axis((uint8_t)(" + ctx.inputExpr(0) + "), P64::Input::id(" + _quoted(n.axis) + "))";
  },
});

node({
  id: "multiplayer.ready",
  name: icon("check") + " Set Ready",
  color: Color.green,
  category: "Multiplayer",
  inputs: [logicIn(), valueIn("Player", "u32")],
  outputs: [logicOut()],
  props: { ready: Bool({ label: "Ready", default: true }) },
  build(n, ctx) {
    ctx.include("<multiplayer/session.h>");
    ctx.line("P64::Multiplayer::getSession().setReady((uint8_t)(" + ctx.inputExpr(0) + "), " + (n.ready ? "true" : "false") + ");");
  },
});

node({
  id: "multiplayer.isReady",
  name: icon("check-circle-outline") + " Is Ready",
  color: typeColor("i32"),
  category: "Multiplayer",
  inputs: [valueIn("Player", "u32")],
  outputs: [valueOut("i32")],
  value(n, ctx) {
    ctx.include("<multiplayer/session.h>");
    return "P64::Multiplayer::getSession().getPlayer((uint8_t)(" + ctx.inputExpr(0) + ")).ready";
  },
});

node({
  id: "multiplayer.playerScore",
  name: icon("counter") + " Player Score",
  color: typeColor("i32"),
  category: "Multiplayer",
  inputs: [valueIn("Player", "u32")],
  outputs: [valueOut("i32")],
  value(n, ctx) {
    ctx.include("<multiplayer/session.h>");
    return "P64::Multiplayer::getSession().getPlayer((uint8_t)(" + ctx.inputExpr(0) + ")).score";
  },
});

node({
  id: "multiplayer.score",
  name: icon("counter") + " Add Score",
  color: Color.green,
  category: "Multiplayer",
  inputs: [logicIn(), valueIn("Player", "u32"), valueIn("Amount", "i32", 1)],
  outputs: [logicOut()],
  build(n, ctx) {
    ctx.include("<multiplayer/session.h>");
    ctx.line("P64::Multiplayer::getSession().addScore((uint8_t)(" + ctx.inputExpr(0) + "), " + ctx.inputExpr(1) + ");");
  },
});

node({
  id: "multiplayer.eliminate",
  name: icon("account-remove") + " Eliminate Player",
  color: Color.red,
  category: "Multiplayer",
  inputs: [logicIn(), valueIn("Player", "u32")],
  outputs: [logicOut()],
  build(n, ctx) {
    ctx.include("<multiplayer/session.h>");
    ctx.line("P64::Multiplayer::getSession().eliminate((uint8_t)(" + ctx.inputExpr(0) + ")); ");
  },
});

node({
  id: "multiplayer.finish",
  name: icon("flag-checkered") + " Finish Player",
  color: Color.green,
  category: "Multiplayer",
  inputs: [logicIn(), valueIn("Player", "u32")],
  outputs: [logicOut()],
  build(n, ctx) {
    ctx.include("<multiplayer/session.h>");
    ctx.line("P64::Multiplayer::getSession().finish((uint8_t)(" + ctx.inputExpr(0) + ")); ");
  },
});

node({
  id: "multiplayer.state",
  name: icon("call-split") + " Match State",
  color: Color.orange,
  category: "Multiplayer",
  inputs: [logicIn()],
  outputs: [
    logicOut("Lobby"), logicOut("Countdown"), logicOut("Playing"), logicOut("Paused"),
    logicOut("Round End"), logicOut("Match End"), logicOut("Tiebreak")
  ],
  build(n, ctx) {
    ctx.include("<multiplayer/session.h>");
    ctx.line("switch(P64::Multiplayer::getSession().getState()) {");
    const states = ["Lobby", "Countdown", "Playing", "Paused", "RoundEnd", "MatchEnd", "Tiebreak"];
    for(let i=0; i<states.length; ++i) {
      ctx.line("case P64::Multiplayer::State::" + states[i] + ":").jump(i).line("break;");
    }
    ctx.line("}");
  },
});
