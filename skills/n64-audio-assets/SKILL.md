---
name: n64-audio-assets
description: Use when creating, converting, validating, or budgeting BF64 SFX, WAV64, XM64 music, sample rates, mixer channels, MIDI-derived arrangements, or audio memory.
license: MIT
compatibility: opencode,claude-code,cursor,codex
metadata:
  tier: "2"
  area: audio
  target_version: "BF64"
---

# N64 Audio Assets

Use this for SFX, voice, ambience, music, and MIDI-to-module workflows.

## Quick Start

```bash
./bf64 constraints audio --json
./bf64 validate ./jump.wav --role sfx --json
./bf64 validate ./theme.xm --role music --json
./bf64 import ./theme.xm --project <project> --dest audio/music/theme.xm --dry-run --json
```

## Runtime Formats

- Import `.wav` or `.mp3` for WAV64-style audio conversion.
- Import `.xm` for XM64 music conversion.
- MIDI is a composition/source format, not a BF64 runtime import format. Export or convert fixed-tempo music to `.xm`, then validate/import the `.xm`.
- BF64 exposes WAV settings for force-mono, resample rate, and compression; deeper `audioconv64` flags are manual-only until surfaced.
- XM64 consumes one mixer channel per XM channel; keep background music arrangements lean.
- WAV/SFX can use the editor's Audio3D component or `AudioManager::play3D`; XM remains 2D. Spatial min/max distance and rolloff do not change the 32-channel mixer budget.

## Workflow

1. Pick SFX vs music role before validating.
2. For MIDI-derived music, preserve the `.mid` or song JSON as source if useful, but import `.xm`.
3. Validate channel count and sample-rate/memory tradeoffs.
4. Import with `--dry-run`, then real import.
5. Build with the N64 toolchain so `audioconv64` produces `.wav64` or `.xm64`.
6. For world sounds, validate in Ares with the first scene camera as listener and move the returned handle when the source moves.

## Reference

- See [REFERENCE.md](REFERENCE.md) for source-to-runtime mapping, MIDI-derived music workflow, playback pattern, and the missing BF64-native converter spec.

## Grounding

- `docs/docs/n64/audio.md`
- `docs/docs/n64/audio-assets.md`
- `docs/docs/n64/rom-budgets.md`
- `docs/docs/n64/limits.json`
- `docs/docs/agent/CODEMAP.md` `src/build/audioBuilder.cpp`.
- `docs/docs/project/audio3d.md`.

## Common Agent Mistakes

- Importing `.mid` directly and expecting BF64 to build it.
- Letting XM music use too many mixer channels.
- Shipping prototype soundfonts or samples without license review.
- Assuming MP3 saves runtime CPU; BF64 re-encodes through the asset pipeline.
