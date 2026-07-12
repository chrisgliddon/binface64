# Linux toolchain setup

BF64 exposes a supported CLI path for discovering, installing, and persisting the libdragon/tiny3d N64 toolchain on Linux. The commands do not use `sudo` and do not edit shell startup files.

## Detect an installation

```bash
./bf64 toolchain detect --project ./game --json
./bf64 doctor --project ./game --strict --json
```

SDK discovery uses this precedence:

1. explicit `--prefix` or `--n64-inst`;
2. the project's `pathN64Inst`;
3. the `N64_INST` environment variable;
4. conventional local SDK locations, including `~/Documents/libdragon-sdk`.

`toolchain detect` reports the selected source and verifies the cross-compiler plus the libdragon asset/build tools. `doctor` additionally checks BF64's build binary and emulator availability, including the `dev.ares.ares` Flatpak, and reports the resolved emulator version (for example `v148`) in machine-readable JSON.

## Install from a libdragon checkout

Preview every command before executing it:

```bash
./bf64 toolchain install \
  --source ~/Documents/libdragon \
  --prefix ~/Documents/libdragon-sdk \
  --dry-run --json
```

Then install:

```bash
./bf64 toolchain install \
  --source ~/Documents/libdragon \
  --prefix ~/Documents/libdragon-sdk \
  --json
```

When the prefix has no `mips64-elf-gcc`, the installer first invokes libdragon's toolchain bootstrap. It then installs libdragon, its host tools, and BF64's pinned Tiny3D. `--skip-toolchain` and `--skip-tiny3d` are available for deliberate partial installs; `--make-binary` and `--timeout` support non-default build environments.

## Persist a project-local configuration

```bash
./bf64 doctor \
  --project ./game \
  --n64-inst ~/Documents/libdragon-sdk \
  --fix --dry-run --json

./bf64 doctor \
  --project ./game \
  --n64-inst ~/Documents/libdragon-sdk \
  --fix --json
```

`--fix` first validates the SDK, then atomically updates `project.p64proj` and writes `.bf64/env.sh`. If either write or final validation fails, both files are rolled back. Source the helper for direct Makefile work:

```bash
. .bf64/env.sh
```

The project setting is sufficient for normal BF64 editor/CLI builds; sourcing is only needed for manual tool invocation.
