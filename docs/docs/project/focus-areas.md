# Dedicated focus areas

BF64 divides game production into explicit focus areas so humans and agents can work from the same inventory in the editor and the headless CLI. The shared catalog is `data/focus-areas.json`; every catalog entry declares its label, compatible asset kinds, GUI workspace, CLI namespace, and availability.

The currently available areas are:

| Focus area | GUI | CLI | Primary content |
|---|---|---|---|
| UI | Dedicated hierarchy/canvas/inspector editor | `bf64 ui` | `.bfui`, images, fonts |
| Music | Tagged-asset workspace | `bf64 music` | XM songs and long-form audio |
| SFX | Tagged-asset workspace | `bf64 sfx` | WAV/MP3 sound effects and voices |
| 3D Environment | Tagged-asset workspace | `bf64 environment` | Models and textures for world content |
| 3D Avatars | Tagged-asset workspace | `bf64 avatar` | Character models, rigs, and animations |
| Cutscenes | Tagged-asset workspace | `bf64 cutscene` | Node graphs, UI documents, music, and SFX |

## GUI workflow

Open the editor's **Focus** menu. **UI** opens its purpose-built document editor. Music, SFX, 3D Environment, 3D Avatars, and Cutscenes each open a dedicated inventory window that:

- shows only compatible project assets;
- displays the asset kind and project path;
- adds or removes focus membership;
- opens models, node graphs, and UI documents in their native editor on double click;
- persists membership in the normal asset `.conf` sidecar.

The focus windows are organizational views, not new asset formats. Existing model, audio, node-graph, image, and UI editors remain the authoritative authoring surfaces.

## CLI workflow

List the catalog, then inspect compatible and selected assets:

```bash
./bf64 focus list --json
./bf64 music ls --project ./game --json
./bf64 sfx ls --project ./game --json
./bf64 environment ls --project ./game --json
./bf64 avatar ls --project ./game --json
./bf64 cutscene ls --project ./game --json
```

Assign membership and validate the selected slice:

```bash
./bf64 music tag assets/audio/title.xm --project ./game --dry-run --json
./bf64 music tag assets/audio/title.xm --project ./game --json
./bf64 music validate --project ./game --json
./bf64 music tag assets/audio/title.xm --clear --project ./game --json
```

Every non-UI namespace supports `ls`, `tag`, and `validate`, stable JSON, `--record`, and exclusion-aware selection. `tag` also supports `--dry-run`. `validate` skips excluded assets by default and accepts `--include-excluded` for a complete source audit.

Membership is stored as a list so one asset can participate in more than one area:

```json
{
  "data": {
    "focusAreas": ["sfx", "cutscene"]
  }
}
```

Use focus tags to define ownership and review slices. Use project `assetExclusions` for drafts or reference trees that should not enter normal validation/build selection at all.
