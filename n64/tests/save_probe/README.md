# BF64 EEPROM save probe

This ROM exercises the public `P64::Save` API against a 16-kilobit EEPROM. It is intentionally independent of an authored BF64 project so the same binary can run in Ares and on a flashcart.

Build it with:

```sh
N64_INST="$HOME/Documents/libdragon-sdk" make -C n64/tests/save_probe
```

Run `save_probe.z64`, close the emulator normally after the launch counter appears, and run it again. The second boot must show counter `2` and emit a debug marker containing `"persisted":true`. Ares writes `save_probe.eeprom` next to the ROM when its game window closes normally.

On hardware, configure the flashcart save type as EEPROM 16K if it does not infer the ROM header. Boot once, wait for counter `1`, power off, and boot again; counter `2` proves persistence. The controller actions are:

- A commits an erased-slot tombstone.
- B writes another generation.
- C-Down corrupts the newest bank. Reset afterward; the read should report `(recovered)` and fall back to the prior generation.

The host regression test in `tests/test_bf64_cli.py` additionally simulates interrupted/corrupt writes and schema migration without consuming EEPROM write cycles.
