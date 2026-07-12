# Structured Runtime Profiling

BF64 can build a bounded profiling ROM, run it in an emulator, stop after the requested sample window, and write one machine-readable artifact:

```bash
./bf64 run --build --profile --project . --json
```

The default window discards 120 warm-up frames and measures the next 300. Override it and choose an attachment path when needed:

```bash
./bf64 run --build --profile \
  --profile-warmup 180 \
  --profile-frames 600 \
  --profile-output .bf64/profiles/first-playable.json \
  --project . --json
```

`--profile-frames` accepts 1 through 2048 frames. `--timeout` bounds emulator startup and sampling; profiling uses 60 seconds when it is omitted. Normal `run` behavior is unchanged.

## Artifact contract

The artifact uses `schema: "bf64.profile"`, `version: 1`, and contains:

- project identity, BF64 version/revision, N64 target and detected RDRAM size;
- emulator command, complete argv, and emulator version;
- ROM, DFS, and ELF paths and byte sizes;
- average, worst, and percentile frame times and FPS;
- total/average/peak rendered T3D triangles, model-object draw submissions, and material changes;
- peak static/heap/top-down/stack-reserved RDRAM footprint;
- average and peak active audio mixer voices.

The default artifact path is `<project>/.bf64/profiles/<rom>-<UTC timestamp>.json`. It is written atomically and is suitable for attaching directly to a tracker record.

## Metric definitions and limits

Frame time comes from BF64's swap-chain delta after the warm-up window. Percentiles are nearest-rank values over the bounded sample.

Triangle and draw counters cover T3D model objects actually submitted after BF64 culling, once per active camera. Material changes count transitions between submitted model materials. Custom raw RDP commands, sprite rectangles, particles, and user-authored draw callbacks are not inferred as triangles; profile consumers should treat these fields as the engine's model-render workload, not a hardware command-stream disassembly.

`peak_rdram_used_bytes` is a conservative allocation footprint: static image + libdragon's reserved stack + live heap allocations + top-down allocations such as the depth buffer. It does not attempt to measure transient stack depth within the reserved stack.

The CLI auto-detects the `dev.ares.ares` Flatpak when `ares` is not on `PATH`, grants that invocation access only to the project directory, and captures libdragon debug output. Other emulators must forward debug output to stdout for the `BF64_PROFILE_JSON:` protocol marker to be visible.
