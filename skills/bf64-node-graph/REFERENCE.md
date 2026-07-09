# BF64 Node Graph Reference

## Source Layout

- Builtin JS node specs: `data/nodes/builtin/*.js`.
- Value types: `data/nodes/_types.js`.
- JS prelude helpers: `data/nodes/_prelude.js`.
- Editor graph model: `src/project/graph/graph.{cpp,h}`.
- Codegen node context: `src/project/graph/nodes/baseNode.h`.
- Generated graph builder: `src/build/nodeGraphBuilder.cpp`.

## Node Spec Shape

Builtin nodes use `node({...})` declarations. Example from `data/nodes/builtin/flow.js`:

```js
node({
  id: "core.wait",
  name: icon("clock-outline") + " Wait",
  category: "Flow",
  inputs: [logicIn()],
  outputs: [logicOut()],
  props: { time: Float({ label: "sec.", width: 50 }) },
  build(n, ctx) {
    ctx.localConst("uint64_t", "t_time", Math.floor(n.time * 1000))
       .line("coro_sleep(TICKS_FROM_MS(t_time));");
  },
});
```

Rules:

- Keep `id` stable forever once used by saved graphs.
- Use value pins for data and logic pins for flow.
- Use `ctx.inputExpr(index)` for connected or fallback value inputs.
- Emit runtime C++ that matches `n64/engine/include` APIs.

## Generated Code Model

Graph codegen emits goto-labeled coroutine-style C++ under project `src/p64/<uuid>.cpp`. That file is build output. Inspect it when debugging, but fix the graph asset or node spec.

## Safe Debug Loop

1. Save the graph in the editor.
2. Run `./bf64 build --project <project> --json` to inspect expected generated files.
3. Run `./bf64 build --execute --project <project> --pyrite64-binary ./pyrite64 --json`.
4. If generated C++ is wrong, update the node spec or graph source.
5. Rebuild and compare the regenerated C++.

## Gotchas

- Unknown node ids become placeholders to preserve graph data.
- Value resolver cycles can produce fallback expressions or bad generated code.
- Hot reload updates existing `NodeSpec` objects in place; do not design logic that depends on pointer replacement.
