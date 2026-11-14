# Changelog

🌐 English | [Versión en español](CHANGELOG-ES.md)

All notable changes to this project are documented here.

## v0.1.0 — First release

- Local web interface (`serve`): folder browser, presets, live progress, results table, English/Spanish.
  Standard library only, bound to `127.0.0.1`, guarded by a per-session token and host check
- `Video Processor.bat` and `start.sh` launchers
- Commands `run` (single pass, ideal for a schedule), `watch`, `doctor` and `presets`
- Presets `ai-log` (360p, 2 fps, no audio, CRF 34), `ai-log-480` and `human-proxy`; custom presets
  via `presets.user.json` or `--preset-file`, and any value can be overridden from the command line
- Burned-in clock with the original video's time, also correct on split videos
- Chunking for long videos (`--chunk`) with each part's start and end in `manifest.json`
- Scene-change detection (`--scenes`) over the continuous proxy stream, written to `markers.csv`
- Recursive folder mode; failures are skipped and counted; idempotent; atomic writes
- Vertical phone video (rotation metadata) is sized correctly
- `log_raw.csv` template and AI prompts in `prompts/ai-log.en.md` and `prompts/log-ia.es.md`
- Unit and integration tests using synthetic video
- MIT license
