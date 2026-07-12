BUILD_DIR = build

include $(N64_INST)/include/n64.mk
include $(N64_INST)/include/t3d.mk

N64_CXXFLAGS += -std=gnu++20 -fno-exceptions -Os -I../../engine/include \
	-Wall -Wextra -Werror -Wformat-signedness -Wshadow -Wdouble-promotion \
	-Wformat-security -Wformat-overflow -Wformat-truncation -Wfatal-errors

OBJS = $(BUILD_DIR)/chunk_mesh_probe.o $(BUILD_DIR)/chunkMesh.o

all: chunk_mesh_probe.z64

chunk_mesh_probe.z64: N64_ROM_TITLE = "BF64 Chunk Mesh"
$(BUILD_DIR)/chunk_mesh_probe.elf: $(OBJS)

$(BUILD_DIR)/chunkMesh.o: ../../engine/src/renderer/chunkMesh.cpp ../../engine/include/renderer/chunkMesh.h
	@mkdir -p $(dir $@)
	@echo "    [CXX] $<"
	$(CXX) -c $(CXXFLAGS) -o $@ $<

clean:
	rm -rf $(BUILD_DIR) *.z64 *.v64

-include $(wildcard $(BUILD_DIR)/*.d)

.PHONY: all clean
