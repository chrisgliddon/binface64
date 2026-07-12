/**
 * @copyright 2026 - BF64 contributors
 * @license MIT
 *
 * Versioned, checksummed EEPROM save slots with power-loss recovery.
 */
#pragma once

#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace P64::Save
{
  enum class Status : std::uint8_t
  {
    Ok,
    NotInitialized,
    NoEeprom,
    InvalidConfig,
    InvalidSlot,
    InvalidArgument,
    TooLarge,
    BufferTooSmall,
    Empty,
    Corrupt,
    VersionMismatch,
    MigrationFailed,
    MigrationWriteFailed,
    OutOfMemory,
    IoError,
    VerifyFailed,
  };

  enum class Device : std::uint8_t
  {
    None,
    Eeprom4K,
    Eeprom16K,
  };

  /**
   * Upgrade an older payload into the current schema.
   *
   * Return true and set destinationSize on success. The source remains valid
   * only for the duration of the callback. Payload serialization is owned by
   * the game, so migrations should decode the old schema explicitly rather
   * than assuming current struct layout.
   */
  using Migration = bool (*)(
    std::uint16_t fromVersion,
    const void *source,
    std::size_t sourceSize,
    std::uint16_t toVersion,
    void *destination,
    std::size_t destinationCapacity,
    std::size_t &destinationSize
  );

  struct Config
  {
    /** Number of logical save slots. Each slot owns two physical banks. */
    std::uint8_t slotCount{1};
    /** Maximum bytes in one game payload. */
    std::size_t payloadCapacity{};
    /** Current game-owned payload schema. Zero is reserved and rejected. */
    std::uint16_t schemaVersion{1};
    /** Optional older-schema upgrade callback. */
    Migration migrate{};
  };

  struct Info
  {
    bool initialized{};
    Device device{Device::None};
    std::size_t eepromBytes{};
    std::uint8_t slotCount{};
    std::size_t payloadCapacity{};
    std::size_t bankBytes{};
    std::size_t requiredBytes{};
    std::uint16_t schemaVersion{};
  };

  struct ReadResult
  {
    Status status{Status::NotInitialized};
    std::size_t size{};
    std::uint16_t storedVersion{};
    std::uint16_t version{};
    std::uint32_t generation{};
    /** True when one damaged bank was ignored in favor of its valid peer. */
    bool recovered{};
    /** True when Config::migrate produced the returned payload. */
    bool migrated{};
  };

  /** Probe EEPROM and validate that the redundant slot layout fits. */
  Status init(const Config &config);
  /** Forget runtime configuration. EEPROM contents are not changed. */
  void close();
  [[nodiscard]] Info info();

  /** Read the newest committed generation of a logical slot. */
  ReadResult read(
    std::uint8_t slot,
    void *destination,
    std::size_t destinationCapacity,
    bool rewriteMigrated = true
  );

  /** Atomically commit a new generation while preserving the prior bank. */
  Status write(std::uint8_t slot, const void *source, std::size_t size);

  /** Commit an empty tombstone so older generations cannot reappear. */
  Status erase(std::uint8_t slot);

  [[nodiscard]] const char *statusName(Status status);

  template<typename T>
    requires std::is_trivially_copyable_v<T>
  Status write(std::uint8_t slot, const T &value)
  {
    return write(slot, &value, sizeof(T));
  }

  template<typename T>
    requires std::is_trivially_copyable_v<T>
  ReadResult read(std::uint8_t slot, T &value, bool rewriteMigrated = true)
  {
    return read(slot, &value, sizeof(T), rewriteMigrated);
  }
}
