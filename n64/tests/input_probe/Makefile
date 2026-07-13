BUILD_DIR = build

include $(N64_INST)/include/n64.mk

N64_CXXFLAGS += -std=gnu++20 -fno-exceptions -Os -I../../engine/include \
	-Wall -Wextra -Werror -Wformat-signedness -Wshadow -Wdouble-promotion \
	-Wformat-security -Wformat-overflow -Wformat-truncation -Wfatal-errors

OBJS = $(BUILD_DIR)/input_probe.o $(BUILD_DIR)/input.o

all: input_probe.z64

input_probe.z64: N64_ROM_TITLE = "BF64 4-Port Probe"
$(BUILD_DIR)/input_probe.elf: $(OBJS)

$(BUILD_DIR)/input.o: ../../engine/src/input/input.cpp ../../engine/include/input/input.h
	@mkdir -p $(dir $@)
	@echo "    [CXX] $<"
	$(CXX) -c $(CXXFLAGS) -o $@ $<

clean:
	rm -rf $(BUILD_DIR) *.z64 *.v64

-include $(wildcard $(BUILD_DIR)/*.d)

.PHONY: all clean
