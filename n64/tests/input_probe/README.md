# Four-port input probe

This standalone 4 MB-safe ROM exercises the reusable input snapshot service without game join rules. It displays all four fixed physical ports and emits structured `BF64_INPUT_PROBE_JSON` records for connect, stick/button state, probe join/leave, disconnect, and reconnect events.

```sh
make -C n64/tests/input_probe
ares n64/tests/input_probe/input_probe.z64
```

Use Ares v147+ or gopher64. Production readiness still requires the same disconnect/reconnect sequence with four physical N64 controllers on real hardware.
