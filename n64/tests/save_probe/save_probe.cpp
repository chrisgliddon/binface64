#include <cstdint>
#include <libdragon.h>

#include "save/flashramDriver.h"
#include "save/saveManager.h"

namespace
{
  constexpr std::uint32_t PAYLOAD_TAG = 0x53415645;

  struct Payload
  {
    std::uint32_t tag;
    std::uint32_t launches;
  };

  P64::Save::Status lastAction{P64::Save::Status::Ok};
  P64::Save::ReadResult lastRead{};
  Payload payload{};

  void readPayload()
  {
    payload = {};
    lastRead = P64::Save::read(0, payload);
    if(lastRead.status != P64::Save::Status::Ok || payload.tag != PAYLOAD_TAG) {
      payload = {.tag = PAYLOAD_TAG, .launches = 0};
    }
  }

  void writeIncrement()
  {
    readPayload();
    ++payload.launches;
    lastAction = P64::Save::write(0, payload);
    readPayload();
  }

  void emitMarker(bool persisted)
  {
    debugf(
      "BF64_SAVE_TEST_JSON:{\"init\":\"ok\",\"read\":\"%s\",\"action\":\"%s\","
      "\"persisted\":%s,\"recovered\":%s,\"launches\":%lu}\n",
      P64::Save::statusName(lastRead.status),
      P64::Save::statusName(lastAction),
      persisted ? "true" : "false",
      lastRead.recovered ? "true" : "false",
      static_cast<unsigned long>(payload.launches)
    );
  }

  void drawStatus()
  {
    console_clear();
    const auto saveInfo = P64::Save::info();
    printf("BF64 Save Probe\n\n");
    printf(
      "Device: %s (%lu bytes)\n",
      saveInfo.device == P64::Save::Device::FlashRam ? "FlashRAM" : "EEPROM",
      static_cast<unsigned long>(saveInfo.storageBytes)
    );
    printf("Layout: %u slot, %lu-byte payload\n", saveInfo.slotCount, static_cast<unsigned long>(saveInfo.payloadCapacity));
    printf("Read: %s%s\n", P64::Save::statusName(lastRead.status), lastRead.recovered ? " (recovered)" : "");
    printf("Last action: %s\n", P64::Save::statusName(lastAction));
    printf("Launch counter: %lu\n\n", static_cast<unsigned long>(payload.launches));
    printf("A: erase slot\n");
    printf("B: write another generation\n");
    printf("C-Down: corrupt newest bank\n\n");
    printf("Close/power off, then boot again to\nverify persistence. Reset after C-Down\nto verify fallback to the older bank.\n");
  }

  void corruptNewestBank()
  {
    readPayload();
    if(lastRead.status != P64::Save::Status::Ok || lastRead.generation == 0) {
      lastAction = lastRead.status;
      return;
    }
    const auto saveInfo = P64::Save::info();
    const std::size_t bank = (lastRead.generation - 1U) & 1U;
    const std::size_t byteOffset = bank * saveInfo.bankBytes + 24;
#ifdef BF64_SAVE_FLASHRAM
    std::uint8_t bytes[2]{};
    const std::size_t evenOffset = byteOffset & ~std::size_t{1};
    bf64_flashram_read(bytes, evenOffset, sizeof(bytes));
    bytes[byteOffset - evenOffset] ^= 0x80;
    lastAction = bf64_flashram_write(bytes, evenOffset, sizeof(bytes)) == sizeof(bytes)
      ? P64::Save::Status::Ok
      : P64::Save::Status::IoError;
#else
    std::uint8_t block[EEPROM_BLOCK_SIZE]{};
    const auto blockIndex = static_cast<std::uint8_t>(byteOffset / EEPROM_BLOCK_SIZE);
    eeprom_read(blockIndex, block);
    block[byteOffset % EEPROM_BLOCK_SIZE] ^= 0x80;
    lastAction = eeprom_write(blockIndex, block) == 0
      ? P64::Save::Status::Ok
      : P64::Save::Status::IoError;
#endif
    readPayload();
  }
}

int main()
{
  debug_init_isviewer();
  debug_init_usblog();
  console_init();
  console_set_render_mode(RENDER_AUTOMATIC);
  joypad_init();

  P64::Save::Config config{};
#ifdef BF64_SAVE_FLASHRAM
  config.backend = P64::Save::Backend::FlashRam;
#else
  config.backend = P64::Save::Backend::Eeprom;
#endif
  config.slotCount = 1;
  config.payloadCapacity = 512;
  config.schemaVersion = 1;
  lastAction = P64::Save::init(config);
  if(lastAction != P64::Save::Status::Ok) {
    printf("Save init failed: %s\n", P64::Save::statusName(lastAction));
    for(;;) {}
  }

  readPayload();
  const bool persisted = lastRead.status == P64::Save::Status::Ok && payload.tag == PAYLOAD_TAG;
  writeIncrement();
  emitMarker(persisted);
  drawStatus();

  for(;;) {
    joypad_poll();
    const auto pressed = joypad_get_buttons_pressed(JOYPAD_PORT_1);
    bool changed = false;
    if(pressed.a) {
      lastAction = P64::Save::erase(0);
      readPayload();
      changed = true;
    } else if(pressed.b) {
      writeIncrement();
      changed = true;
    } else if(pressed.c_down) {
      corruptNewestBank();
      changed = true;
    }
    if(changed) {
      emitMarker(false);
      drawStatus();
    }
  }
}
