# Positional audio

BF64 provides listener-relative distance attenuation and stereo panning for WAV/SFX assets. XM tracker players remain non-positional because one song can occupy several mixer channels and should use `Audio2D`.

## Authored component

Add **Audio (3D)** to an object in the editor, or attach it headlessly:

```bash
./bf64 scene attach audio3d 1 Dog assets/audio/bark.wav \
  --data '{"volume":0.8,"minDistance":40,"maxDistance":800,"rolloff":1.5,"autoPlay":true}' \
  --project ./game --json
```

The component follows its object's world position every frame. Its fields are source volume, pitch ratio, loop, auto-play, full-volume minimum distance, silence distance, and rolloff exponent. Rolloff `1` is linear; larger values fade more quickly. Pitch is clamped to `0.125x..8x`.

The first camera in the active scene becomes the listener automatically. Code that manages a different listener can call `AudioManager::setListener(position, forward, up)` or its camera overload.

## Runtime API

```cpp
#include "audio/audioManager.h"

P64::Audio::Spatial::Settings spatial{
  .minDistance = 40.0f,
  .maxDistance = 800.0f,
  .rolloff = 1.5f,
};

auto handle = P64::AudioManager::play3D(audio, sourcePosition, spatial);
handle.setVolume(0.8f);
handle.setPitch(1.1f);
handle.setPosition(movingSource);
handle.setSpatialSettings(spatial);
handle.stop();
```

`Audio::Handle` remains safe to call after playback ends; stale handles are ignored. A handle can switch between centered 2D and spatial mixing with `setSpatial`. `setPitch` updates every channel occupied by a WAV; the older `setSpeed` name remains an alias. XM players intentionally reject per-handle pitch because tracker playback owns its own note timing.

## Mixing behavior

Attenuation is `1` inside `minDistance`, `0` beyond `maxDistance`, and an exponent-shaped fade between them. Pan is calculated from the listener's right axis and uses equal-power left/right gains. Degenerate listener vectors and invalid distance ranges have deterministic fallbacks.

The mixer still has 32 channels. Multi-channel WAVs occupy contiguous channels, and XM playback consumes one channel per tracker channel, so positional effects must be budgeted alongside music.
