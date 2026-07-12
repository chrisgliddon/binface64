# Save data

BF64 exposes a game-facing cartridge-save service in `save/saveManager.h`.
It supports 4-kilobit EEPROM (512 bytes), 16-kilobit EEPROM (2048 bytes),
and 1-megabit FlashRAM (128 KiB). Set the matching project ROM save type and
select `Save::Backend::Eeprom`, `FlashRam`, or `Auto` at runtime. EEPROM is the
backward-compatible default; `Auto` probes EEPROM first and then FlashRAM.

FlashRAM support is built into BF64 through the prefixed
`save/flashramDriver.h` driver, adapted from libdragon PR #925. It therefore
works with the currently pinned libdragon toolchain and does not depend on that
upstream PR being merged or installed separately.

## Slot model

Each logical slot has two alternating physical banks. EEPROM fills the inactive
bank with a checksummed record in an invalid `writing` state, then commits it
with one final 8-byte header update. FlashRAM aligns each bank to a different
16-KiB erase sector and writes one committed, checksummed sector; a torn target
sector fails CRC while the prior generation remains in its separate sector.
Reads validate the format header, schema version, payload CRC32, header CRC32,
and generation; if one bank is damaged, BF64 returns the valid peer with
`ReadResult::recovered = true`. Short FlashRAM reads/writes and verification
failures are reported as `IoError` or `VerifyFailed`, never parsed as valid
records.

Erase writes a committed tombstone rather than merely zeroing bytes. This
prevents an older valid generation from reappearing after an erase. Cartridge
writes are synchronous and can stall audio, so games should save at explicit
checkpoints rather than every frame. FlashRAM erases and programs a full 16-KiB
target sector and can take hundreds of milliseconds; it is especially
unsuitable for per-frame writes.

The redundancy cost is intentional. An EEPROM bank uses
`align8(24 + payloadCapacity)` bytes. A FlashRAM bank uses
`align16KiB(24 + payloadCapacity)` so the redundant generations never share an
erase sector. A slot uses two banks. Therefore:

- EEPROM 4K supports one slot with at most 232 payload bytes, or multiple smaller slots.
- EEPROM 16K supports one 512-byte slot using 1072 bytes, leaving room for another smaller slot only if the configured common payload capacity permits it.
- FlashRAM uses 32 KiB per 512-byte slot and supports up to four such slots.

`Info::storageBytes` reports the selected capacity; the legacy `eepromBytes`
field is zero for FlashRAM. `Save::init` returns `Status::InvalidConfig` when
the requested layout cannot fit, and distinguishes `NoEeprom`, `NoFlashRam`,
and `NoSaveDevice` probe failures.

## Basic use

Set `romHeader.saveType` to EEPROM 4K or EEPROM 16K in Project Settings, then initialize from a global script after BF64 has initialized Joybus:

```cpp
#include "save/saveManager.h"

struct CampaignSave {
  uint32_t completedJobs;
  uint16_t reputation;
  uint8_t options;
};

P64::Save::Config config{};
config.backend = P64::Save::Backend::Eeprom;
config.slotCount = 1;
config.payloadCapacity = sizeof(CampaignSave);
config.schemaVersion = 1;

if(P64::Save::init(config) == P64::Save::Status::Ok) {
  CampaignSave save{};
  auto result = P64::Save::read(0, save);
  if(result.status == P64::Save::Status::Empty) {
    save = {};
  }
  // ...change game state...
  P64::Save::write(0, save);
}
```

Payloads are opaque bytes. Typed helpers require trivially copyable types, but games remain responsible for stable field sizes, byte representation, and schema evolution.

For a 512-byte FlashRAM campaign record, set the project save type to
`flashram` and initialize with:

```cpp
P64::Save::Config config{};
config.backend = P64::Save::Backend::FlashRam;
config.slotCount = 1;
config.payloadCapacity = 512;
config.schemaVersion = 1;
auto status = P64::Save::init(config);
```

## Migration

Set `Config::migrate` when increasing `schemaVersion`. A migration callback receives the stored version and bytes and writes the current payload into the supplied destination. On success, `read` returns the migrated data and, by default, commits it as a new current-version generation. Pass `rewriteMigrated = false` to defer that rewrite.

If there is no callback, `read` returns `VersionMismatch`. A failed conversion returns `MigrationFailed`; a successful conversion whose rewrite cannot be verified returns `MigrationWriteFailed`.

## Verification

Host regressions use in-memory EEPROM and FlashRAM backends to cover 4K/16K
layout bounds, a 512-byte sector-isolated FlashRAM record, recovery from a torn
target-sector write, backend selection, generation selection, CRC corruption
fallback, committed erase, I/O failures, missing hardware, and
migration/rewrite. The reproducible Ares/flashcart ROMs are under
`n64/tests/save_probe`; `make` builds EEPROM 16K and `make flash` builds
FlashRAM. Both use the same public API and emit `BF64_SAVE_TEST_JSON` for the
two-boot persistence gate. Ares v148 has been exercised with the FlashRAM ROM:
the second boot reported `"persisted":true` and launch generation 2.
