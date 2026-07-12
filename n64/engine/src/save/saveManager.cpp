/**
 * @copyright 2026 - BF64 contributors
 * @license MIT
 */
#include "save/saveManager.h"
#include "save/flashramDriver.h"

#include <cstdlib>
#include <cstring>
#include <eeprom.h>

namespace P64::Save
{
  namespace
  {
    constexpr std::size_t HEADER_SIZE = 24;
    constexpr std::uint8_t FORMAT_VERSION = 1;
    constexpr std::uint8_t STATE_WRITING = 0x5A;
    constexpr std::uint8_t STATE_COMMITTED = 0xA5;
    constexpr std::uint8_t FLAG_DELETED = 0x01;
    constexpr std::uint8_t MAGIC[4] = {'B', 'F', '6', '4'};

    Config activeConfig{};
    Info activeInfo{};

    enum class RecordState : std::uint8_t
    {
      Blank,
      Valid,
      Corrupt,
    };

    struct Record
    {
      RecordState state{RecordState::Blank};
      bool deleted{};
      std::uint16_t schemaVersion{};
      std::uint16_t payloadSize{};
      std::uint32_t generation{};
      const std::uint8_t *payload{};
    };

    struct Scan
    {
      Record records[2]{};
      int latest{-1};
      bool hasCorruption{};
      bool ioError{};
    };

    constexpr std::size_t alignUp(std::size_t value, std::size_t alignment)
    {
      if(alignment == 0)return 0;
      const std::size_t remainder = value % alignment;
      return remainder == 0 ? value : value + alignment - remainder;
    }

    bool storageRead(void *destination, std::size_t offset, std::size_t size)
    {
      if(activeInfo.device == Device::FlashRam) {
        return bf64_flashram_read(destination, offset, size) == static_cast<int>(size);
      }
      eeprom_read_bytes(static_cast<std::uint8_t*>(destination), offset, size);
      return true;
    }

    bool storageWrite(const void *source, std::size_t offset, std::size_t size)
    {
      if(activeInfo.device == Device::FlashRam) {
        return bf64_flashram_write(source, offset, size) == static_cast<int>(size);
      }
      eeprom_write_bytes(static_cast<const std::uint8_t*>(source), offset, size);
      return true;
    }

    bool storageCommitHeader(const std::uint8_t *source, std::size_t offset)
    {
      return eeprom_write(static_cast<std::uint8_t>(offset / EEPROM_BLOCK_SIZE), source) == 0;
    }

    std::uint16_t readU16(const std::uint8_t *data)
    {
      return static_cast<std::uint16_t>(
        static_cast<std::uint16_t>(data[0]) << 8U |
        static_cast<std::uint16_t>(data[1])
      );
    }

    std::uint32_t readU32(const std::uint8_t *data)
    {
      return
        static_cast<std::uint32_t>(data[0]) << 24U |
        static_cast<std::uint32_t>(data[1]) << 16U |
        static_cast<std::uint32_t>(data[2]) << 8U |
        static_cast<std::uint32_t>(data[3]);
    }

    void writeU16(std::uint8_t *data, std::uint16_t value)
    {
      data[0] = static_cast<std::uint8_t>(value >> 8U);
      data[1] = static_cast<std::uint8_t>(value);
    }

    void writeU32(std::uint8_t *data, std::uint32_t value)
    {
      data[0] = static_cast<std::uint8_t>(value >> 24U);
      data[1] = static_cast<std::uint8_t>(value >> 16U);
      data[2] = static_cast<std::uint8_t>(value >> 8U);
      data[3] = static_cast<std::uint8_t>(value);
    }

    std::uint32_t crc32(const std::uint8_t *data, std::size_t size)
    {
      std::uint32_t crc = 0xFFFFFFFFU;
      for(std::size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for(std::uint8_t bit = 0; bit < 8; ++bit) {
          const std::uint32_t mask = 0U - (crc & 1U);
          crc = (crc >> 1U) ^ (0xEDB88320U & mask);
        }
      }
      return crc ^ 0xFFFFFFFFU;
    }

    bool isBlank(const std::uint8_t *data, std::size_t size)
    {
      bool allZero = true;
      bool allOnes = true;
      for(std::size_t i = 0; i < size; ++i) {
        allZero = allZero && data[i] == 0x00;
        allOnes = allOnes && data[i] == 0xFF;
      }
      return allZero || allOnes;
    }

    Record parseRecord(const std::uint8_t *data)
    {
      Record record{};
      if(isBlank(data, activeInfo.bankBytes)) return record;
      record.state = RecordState::Corrupt;
      if(std::memcmp(data, MAGIC, sizeof(MAGIC)) != 0) return record;
      if(data[4] != FORMAT_VERSION || data[5] != STATE_COMMITTED) return record;
      if((data[6] & ~FLAG_DELETED) != 0 || data[7] != 0) return record;
      const std::uint16_t payloadSize = readU16(data + 10);
      if(payloadSize > activeInfo.payloadCapacity || HEADER_SIZE + payloadSize > activeInfo.bankBytes) return record;
      if(readU32(data + 20) != crc32(data, 20)) return record;
      if(readU32(data + 16) != crc32(data + HEADER_SIZE, payloadSize)) return record;
      const bool deleted = (data[6] & FLAG_DELETED) != 0;
      if(deleted && payloadSize != 0) return record;
      record.state = RecordState::Valid;
      record.deleted = deleted;
      record.schemaVersion = readU16(data + 8);
      record.payloadSize = payloadSize;
      record.generation = readU32(data + 12);
      record.payload = data + HEADER_SIZE;
      return record;
    }

    bool isNewer(std::uint32_t lhs, std::uint32_t rhs)
    {
      return static_cast<std::int32_t>(lhs - rhs) > 0;
    }

    Scan scanBanks(std::uint8_t slot, std::uint8_t *buffers)
    {
      Scan scan{};
      const std::size_t slotOffset = static_cast<std::size_t>(slot) * activeInfo.bankBytes * 2;
      for(std::size_t bank = 0; bank < 2; ++bank) {
        auto *buffer = buffers + bank * activeInfo.bankBytes;
        if(!storageRead(buffer, slotOffset + bank * activeInfo.bankBytes, activeInfo.bankBytes)) {
          scan.ioError = true;
          break;
        }
        scan.records[bank] = parseRecord(buffer);
        if(scan.records[bank].state == RecordState::Corrupt) scan.hasCorruption = true;
        if(scan.records[bank].state != RecordState::Valid) continue;
        if(scan.latest < 0 || isNewer(scan.records[bank].generation, scan.records[scan.latest].generation)) {
          scan.latest = static_cast<int>(bank);
        }
      }
      return scan;
    }

    Status validateAccess(std::uint8_t slot)
    {
      if(!activeInfo.initialized) return Status::NotInitialized;
      if(slot >= activeInfo.slotCount) return Status::InvalidSlot;
      return Status::Ok;
    }

    void encodeRecord(
      std::uint8_t *buffer,
      const void *source,
      std::size_t size,
      std::uint16_t schemaVersion,
      std::uint32_t generation,
      bool deleted
    )
    {
      std::memset(buffer, 0xFF, activeInfo.bankBytes);
      std::memcpy(buffer, MAGIC, sizeof(MAGIC));
      buffer[4] = FORMAT_VERSION;
      buffer[5] = STATE_COMMITTED;
      buffer[6] = deleted ? FLAG_DELETED : 0;
      buffer[7] = 0;
      writeU16(buffer + 8, schemaVersion);
      writeU16(buffer + 10, static_cast<std::uint16_t>(size));
      writeU32(buffer + 12, generation);
      if(size != 0) std::memcpy(buffer + HEADER_SIZE, source, size);
      writeU32(buffer + 16, crc32(buffer + HEADER_SIZE, size));
      writeU32(buffer + 20, crc32(buffer, 20));
    }

    Status commitRecord(
      std::uint8_t slot,
      int bank,
      const void *source,
      std::size_t size,
      std::uint32_t generation,
      bool deleted
    )
    {
      auto *buffer = static_cast<std::uint8_t*>(std::malloc(activeInfo.bankBytes));
      if(buffer == nullptr) return Status::OutOfMemory;
      encodeRecord(buffer, source, size, activeConfig.schemaVersion, generation, deleted);
      const std::size_t offset =
        static_cast<std::size_t>(slot) * activeInfo.bankBytes * 2 +
        static_cast<std::size_t>(bank) * activeInfo.bankBytes;
      // EEPROM can commit its first 8-byte block independently, so write an
      // invalid state first and publish STATE_COMMITTED last. FlashRAM banks
      // occupy separate erase sectors; one committed full-bank write is both
      // safer and lower-wear, and CRC rejects a torn target sector.
      const bool flashRam = activeInfo.device == Device::FlashRam;
      if(!flashRam)buffer[5] = STATE_WRITING;
      if(!storageWrite(buffer, offset, activeInfo.bankBytes)) {
        std::free(buffer);
        return Status::IoError;
      }
      if(!flashRam) {
        buffer[5] = STATE_COMMITTED;
        if(!storageCommitHeader(buffer, offset)) {
          std::free(buffer);
          return Status::IoError;
        }
      }
      if(!storageRead(buffer, offset, activeInfo.bankBytes)) {
        std::free(buffer);
        return Status::IoError;
      }
      const Record verify = parseRecord(buffer);
      const bool valid =
        verify.state == RecordState::Valid &&
        verify.deleted == deleted &&
        verify.generation == generation &&
        verify.schemaVersion == activeConfig.schemaVersion &&
        verify.payloadSize == size &&
        (deleted || size == 0 || std::memcmp(verify.payload, source, size) == 0);
      std::free(buffer);
      return valid ? Status::Ok : Status::VerifyFailed;
    }

    Status commitNext(std::uint8_t slot, const void *source, std::size_t size, bool deleted)
    {
      auto *buffers = static_cast<std::uint8_t*>(std::malloc(activeInfo.bankBytes * 2));
      if(buffers == nullptr) return Status::OutOfMemory;
      const Scan scan = scanBanks(slot, buffers);
      if(scan.ioError) {
        std::free(buffers);
        return Status::IoError;
      }
      const int targetBank = scan.latest < 0 ? 0 : 1 - scan.latest;
      std::uint32_t generation = scan.latest < 0 ? 1 : scan.records[scan.latest].generation + 1;
      if(generation == 0) generation = 1;
      std::free(buffers);
      return commitRecord(slot, targetBank, source, size, generation, deleted);
    }
  }

  Status init(const Config &config)
  {
    close();
    if(
      config.slotCount == 0 ||
      config.payloadCapacity == 0 ||
      config.payloadCapacity > 0xFFFF ||
      config.schemaVersion == 0
    ) return Status::InvalidConfig;
    Device device = Device::None;
    std::size_t storageBytes = 0;
    std::size_t eepromBytes = 0;
    std::size_t bankAlignment = EEPROM_BLOCK_SIZE;

    if(config.backend != Backend::FlashRam) {
      const eeprom_type_t type = eeprom_present();
      if(type != EEPROM_NONE) {
        device = type == EEPROM_16K ? Device::Eeprom16K : Device::Eeprom4K;
        eepromBytes = eeprom_total_blocks() * EEPROM_BLOCK_SIZE;
        storageBytes = eepromBytes;
      } else if(config.backend == Backend::Eeprom) {
        return Status::NoEeprom;
      }
    }

    if(device == Device::None && config.backend != Backend::Eeprom) {
      bf64_flashram_info_t flashInfo{};
      if(!bf64_flashram_init(nullptr, &flashInfo)) {
        return config.backend == Backend::FlashRam ? Status::NoFlashRam : Status::NoSaveDevice;
      }
      if(
        flashInfo.total_size == 0 ||
        flashInfo.sector_size == 0 ||
        flashInfo.sector_size > flashInfo.total_size ||
        flashInfo.total_size % flashInfo.sector_size != 0
      ) {
        return config.backend == Backend::FlashRam ? Status::NoFlashRam : Status::NoSaveDevice;
      }
      device = Device::FlashRam;
      storageBytes = flashInfo.total_size;
      bankAlignment = flashInfo.sector_size;
    }

    const std::size_t bankBytes = alignUp(HEADER_SIZE + config.payloadCapacity, bankAlignment);
    const std::size_t requiredBytes = bankBytes * 2 * config.slotCount;
    if(requiredBytes > storageBytes) return Status::InvalidConfig;

    activeConfig = config;
    activeInfo = {
      .initialized = true,
      .device = device,
      .storageBytes = storageBytes,
      .eepromBytes = eepromBytes,
      .slotCount = config.slotCount,
      .payloadCapacity = config.payloadCapacity,
      .bankBytes = bankBytes,
      .requiredBytes = requiredBytes,
      .schemaVersion = config.schemaVersion,
    };
    return Status::Ok;
  }

  void close()
  {
    activeConfig = {};
    activeInfo = {};
  }

  Info info()
  {
    return activeInfo;
  }

  ReadResult read(
    std::uint8_t slot,
    void *destination,
    std::size_t destinationCapacity,
    bool rewriteMigrated
  )
  {
    ReadResult result{};
    result.status = validateAccess(slot);
    result.version = activeConfig.schemaVersion;
    if(result.status != Status::Ok) return result;
    if(destination == nullptr && destinationCapacity != 0) {
      result.status = Status::InvalidArgument;
      return result;
    }

    auto *buffers = static_cast<std::uint8_t*>(std::malloc(activeInfo.bankBytes * 2));
    if(buffers == nullptr) {
      result.status = Status::OutOfMemory;
      return result;
    }
    const Scan scan = scanBanks(slot, buffers);
    if(scan.ioError) {
      result.status = Status::IoError;
      std::free(buffers);
      return result;
    }
    if(scan.latest < 0) {
      result.status = scan.hasCorruption ? Status::Corrupt : Status::Empty;
      std::free(buffers);
      return result;
    }
    const Record &record = scan.records[scan.latest];
    result.generation = record.generation;
    result.storedVersion = record.schemaVersion;
    result.size = record.payloadSize;
    result.recovered = scan.hasCorruption;
    if(record.deleted) {
      result.status = Status::Empty;
      result.size = 0;
      std::free(buffers);
      return result;
    }
    if(record.payloadSize > destinationCapacity) {
      result.status = Status::BufferTooSmall;
      std::free(buffers);
      return result;
    }
    if(record.schemaVersion == activeConfig.schemaVersion) {
      if(record.payloadSize != 0) std::memcpy(destination, record.payload, record.payloadSize);
      result.status = Status::Ok;
      std::free(buffers);
      return result;
    }
    if(activeConfig.migrate == nullptr) {
      result.status = Status::VersionMismatch;
      std::free(buffers);
      return result;
    }

    std::size_t migratedSize = 0;
    const bool migrated = activeConfig.migrate(
      record.schemaVersion,
      record.payload,
      record.payloadSize,
      activeConfig.schemaVersion,
      destination,
      destinationCapacity,
      migratedSize
    );
    if(!migrated || migratedSize > destinationCapacity || migratedSize > activeInfo.payloadCapacity) {
      result.status = Status::MigrationFailed;
      std::free(buffers);
      return result;
    }
    result.status = Status::Ok;
    result.size = migratedSize;
    result.migrated = true;
    std::free(buffers);
    if(rewriteMigrated) {
      const Status writeStatus = write(slot, destination, migratedSize);
      if(writeStatus != Status::Ok) result.status = Status::MigrationWriteFailed;
    }
    return result;
  }

  Status write(std::uint8_t slot, const void *source, std::size_t size)
  {
    const Status access = validateAccess(slot);
    if(access != Status::Ok) return access;
    if(source == nullptr && size != 0) return Status::InvalidArgument;
    if(size > activeInfo.payloadCapacity || size > 0xFFFF) return Status::TooLarge;
    return commitNext(slot, source, size, false);
  }

  Status erase(std::uint8_t slot)
  {
    const Status access = validateAccess(slot);
    if(access != Status::Ok) return access;
    return commitNext(slot, nullptr, 0, true);
  }

  const char *statusName(Status status)
  {
    switch(status) {
      case Status::Ok: return "ok";
      case Status::NotInitialized: return "not_initialized";
      case Status::NoSaveDevice: return "no_save_device";
      case Status::NoEeprom: return "no_eeprom";
      case Status::NoFlashRam: return "no_flashram";
      case Status::InvalidConfig: return "invalid_config";
      case Status::InvalidSlot: return "invalid_slot";
      case Status::InvalidArgument: return "invalid_argument";
      case Status::TooLarge: return "too_large";
      case Status::BufferTooSmall: return "buffer_too_small";
      case Status::Empty: return "empty";
      case Status::Corrupt: return "corrupt";
      case Status::VersionMismatch: return "version_mismatch";
      case Status::MigrationFailed: return "migration_failed";
      case Status::MigrationWriteFailed: return "migration_write_failed";
      case Status::OutOfMemory: return "out_of_memory";
      case Status::IoError: return "io_error";
      case Status::VerifyFailed: return "verify_failed";
    }
    return "unknown";
  }
}
