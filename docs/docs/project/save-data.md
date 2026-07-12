# Save data

BF64 exposes a game-facing EEPROM service in `save/saveManager.h`. Version 1 supports both 4-kilobit (512-byte) and 16-kilobit (2048-byte) EEPROM devices selected by the project's ROM save type.

## Slot model

Each logical slot has two alternating physical banks. A write fills the inactive bank with a checksummed record in an invalid `writing` state, then commits it with one final 8-byte EEPROM block write. Until that commit succeeds, the prior bank remains readable. Reads validate the format header, schema version, payload CRC32, header CRC32, and generation; if one bank is damaged, BF64 returns the valid peer with `ReadResult::recovered = true`.

Erase writes a committed tombstone rather than merely zeroing bytes. This prevents an older valid generation from reappearing after an erase. EEPROM writes are synchronous and can stall audio, so games should save at explicit checkpoints rather than every frame.

The redundancy cost is intentional. A bank uses `align8(24 + payloadCapacity)` bytes, and a slot uses two banks. Therefore:

- EEPROM 4K supports one slot with at most 232 payload bytes, or multiple smaller slots.
- EEPROM 16K supports one 512-byte slot using 1072 bytes, leaving room for another smaller slot only if the configured common payload capacity permits it.

`Save::init` returns `Status::InvalidConfig` when the requested layout cannot fit the detected device.

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

## Migration

Set `Config::migrate` when increasing `schemaVersion`. A migration callback receives the stored version and bytes and writes the current payload into the supplied destination. On success, `read` returns the migrated data and, by default, commits it as a new current-version generation. Pass `rewriteMigrated = false` to defer that rewrite.

If there is no callback, `read` returns `VersionMismatch`. A failed conversion returns `MigrationFailed`; a successful conversion whose rewrite cannot be verified returns `MigrationWriteFailed`.

## Verification

The host regression test uses an in-memory EEPROM backend to cover 4K/16K layout bounds, generation selection, CRC corruption fallback, committed erase, missing hardware, and migration/rewrite. The reproducible Ares/flashcart ROM is under `n64/tests/save_probe`; its README describes the two-boot persistence and manual corruption-recovery checks.
