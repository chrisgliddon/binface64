# BF64 QA Debugging Reference

## Standard Evidence Bundle

For a real acceptance claim, capture:

- Command that was run.
- Exit code.
- JSON result or stdout/stderr tail.
- Artifact paths: ROM, imported asset, sidecar, generated output.
- Emulator used and version if available.
- Screenshot or log excerpt for visual/runtime behavior.

## Command Ladder

```bash
./bf64 project status --project <project> --json
./bf64 asset validate-all --project <project> --json
./bf64 scene validate --project <project> --json
./bf64 build --project <project> --json
./bf64 build --execute --project <project> --pyrite64-binary ./pyrite64 --record --json
./bf64 run --project <project> --emulator ares --record --json
```

## Failure Triage

| Symptom | First Check |
|---|---|
| Asset missing in ROM | `asset ls`, sidecar `.conf`, build output list. |
| Texture wrong | `validate --texture-format`, material config, scene pipeline. |
| Model wrong | Fast64 material extras, importer warnings, generated `.t3dm`. |
| Audio missing | asset kind, `.wav64`/`.xm64` output, mixer channel pressure. |
| Node graph wrong | generated `src/p64/<uuid>.cpp`, source graph/node spec. |
| Emulator-only issue | rerun in Ares and gopher64; check hardware-sensitive docs. |

## Automation Gap To Fill

Future BF64 QA tooling should add:

- Emulator process harness with timeout.
- ISViewer/debug log capture.
- Screenshot capture per scene.
- Structured hardware test report format.
- Regression comparison for expected logs/screenshots.

Until then, agents should explicitly say which rung of the evidence ladder they reached.
