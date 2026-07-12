BUILD_DIR = build
SOURCE_DIR = .

include $(N64_INST)/include/n64.mk

N64_CXXFLAGS += -std=gnu++20 -I../../engine/include

OBJS = $(BUILD_DIR)/save_probe.o $(BUILD_DIR)/saveManager.o

all: save_probe.z64

save_probe.z64: N64_ROM_TITLE = "BF64 Save Probe"
save_probe.z64: N64_ROM_SAVETYPE = eeprom16k
$(BUILD_DIR)/save_probe.elf: $(OBJS)

$(BUILD_DIR)/saveManager.o: ../../engine/src/save/saveManager.cpp ../../engine/include/save/saveManager.h
	@mkdir -p $(dir $@)
	@echo "    [CXX] $<"
	$(CXX) -c $(CXXFLAGS) -o $@ $<

clean:
	rm -rf $(BUILD_DIR) *.z64 *.v64 *.eeprom

-include $(wildcard $(BUILD_DIR)/*.d)

.PHONY: all clean
