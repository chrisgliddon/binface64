# BF64 EEPROM and FlashRAM save probe

These ROMs exercise the public `P64::Save` API against a 16-kilobit EEPROM or 128-KiB FlashRAM. They are intentionally independent of an authored BF64 project so the same binaries can run in Ares and on a flashcart.

Build it with:

```sh
N64_INST="$HOME/Documents/libdragon-sdk" make -C n64/tests/save_probe
N64_INST="$HOME/Documents/libdragon-sdk" make -C n64/tests/save_probe flash
```

Run `save_probe.z64` or `save_flashram_probe.z64`, close the emulator normally after the launch counter appears, and run it again. The second boot must show counter `2` and emit a debug marker containing `"persisted":true`. Ares persists the selected ROM-header save type when its game window closes normally.

On hardware, configure the flashcart save type as EEPROM 16K or FlashRAM if it does not infer the ROM header. Boot once, wait for counter `1`, power off, and boot again; counter `2` proves persistence. The controller actions are:

- A commits an erased-slot tombstone.
- B writes another generation.
- C-Down corrupts the newest bank. Reset afterward; the read should report `(recovered)` and fall back to the prior generation.

The host regression tests additionally simulate interrupted/corrupt writes, FlashRAM I/O failures, a 512-byte FlashRAM payload, and schema migration without consuming cartridge write cycles.
