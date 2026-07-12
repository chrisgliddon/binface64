# Audio (3D)

The Audio (3D) component plays a WAV/SFX asset at its object's world position. BF64 uses the first scene camera as the listener, applies distance attenuation, and pans the sound across the stereo output from the listener's right axis.

## Options

- **Audio** selects a WAV asset. Tracker music is intentionally unsupported for positional playback.
- **Volume** is the source gain before spatial attenuation.
- **Loop** repeats the waveform.
- **Auto-Play** starts it when the component is initialized.
- **Min Distance** is the full-volume radius.
- **Max Distance** is the silence radius.
- **Rolloff** shapes the fade between those radii. `1` is linear; values above `1` fade faster.

At runtime, retrieve `P64::Comp::Audio3D` from the object and call `play`, `stop`, or `setVolume`. Moving objects update the live handle's position each frame. For sounds created directly from code, use `P64::AudioManager::play3D` and update the returned handle with `setPosition`.

## See also

- {cpp:struct}`P64::Comp::Audio3D`
- [Positional audio](../../../project/audio3d.md)
