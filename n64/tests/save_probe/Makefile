BUILD_DIR ?= build
SOURCE_DIR = .
ROM_NAME ?= save_probe
SAVE_TYPE ?= eeprom16k

include $(N64_INST)/include/n64.mk

N64_CXXFLAGS += -std=gnu++20 -I../../engine/include $(EXTRA_CXXFLAGS)

OBJS = $(BUILD_DIR)/save_probe.o $(BUILD_DIR)/saveManager.o $(BUILD_DIR)/flashramDriver.o

all: $(ROM_NAME).z64

$(ROM_NAME).z64: N64_ROM_TITLE = "BF64 Save Probe"
$(ROM_NAME).z64: N64_ROM_SAVETYPE = $(SAVE_TYPE)
$(BUILD_DIR)/$(ROM_NAME).elf: $(OBJS)

$(BUILD_DIR)/saveManager.o: ../../engine/src/save/saveManager.cpp ../../engine/include/save/saveManager.h
	@mkdir -p $(dir $@)
	@echo "    [CXX] $<"
	$(CXX) -c $(CXXFLAGS) -o $@ $<

$(BUILD_DIR)/flashramDriver.o: ../../engine/src/save/flashramDriver.c ../../engine/src/save/flashramDriverInternal.h ../../engine/include/save/flashramDriver.h
	@mkdir -p $(dir $@)
	@echo "    [CC] $<"
	$(CC) -c $(CFLAGS) -I../../engine/include -o $@ $<

flash:
	$(MAKE) BUILD_DIR=build-flash ROM_NAME=save_flashram_probe SAVE_TYPE=flashram EXTRA_CXXFLAGS=-DBF64_SAVE_FLASHRAM

clean:
	rm -rf build build-flash *.z64 *.v64 *.eeprom *.flash

-include $(wildcard $(BUILD_DIR)/*.d)

.PHONY: all flash clean
