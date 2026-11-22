# Changelog

🌐 English | [Versión en español](CHANGELOG-ES.md)

All notable changes to this project are documented here.

## v0.2.0 — Frames and assemble

- New `assemble` command (and an **Assemble** switch in the web interface): rebuilds a video from frame folders or
  `.zip` files as MP4, WebM or GIF. For frames extracted by this tool, the FPS and (with `--audio`) the original's
  audio are taken from `manifest.json`, so a frames → video round trip needs no manual settings
- New `frames` command (and a **Frames** switch in the web interface): extracts one frame every 1/fps seconds
  (default 24) from each video as PNG or JPG, into a `name.frames/` folder or one `.zip` per video (`--zip`),
  optionally downscaled (`--height`). Ported from Image Processor's "Video (frames)" tab, but on native ffmpeg
  (fast, original resolution, no browser limits). It's idempotent and records each output in `manifest.json`

## v0.1.0 — First release

- Local web interface (`serve`): folder browser, presets, live progress, results table, English/Spanish.
  Standard library only, bound to `127.0.0.1`, guarded by a per-session token and host check
- Save and delete your own named presets from the interface (stored in `presets.user.json`)
- `Video Processor.bat` and `start.sh` launchers
- Commands `run` (single pass, ideal for a schedule), `watch`, `doctor` and `presets`
- Presets `ai-log` (360p, 2 fps, no audio, CRF 34), `ai-log-480`, `ai-log-fine` / `ai-log-480-fine` (5 fps) and `human-proxy`; custom presets
  via `presets.user.json` or `--preset-file`, and any value can be overridden from the command line
- Burned-in clock with the original video's time, also correct on split videos
- Chunking for long videos (`--chunk`) with each part's start and end in `manifest.json`
- Scene-change detection (`--scenes`) over the continuous proxy stream, written to `markers.csv`
- Recursive folder mode; failures are skipped and counted; idempotent; atomic writes
- Vertical phone video (rotation metadata) is sized correctly
- `log_raw.csv` template and AI prompts in `prompts/ai-log.en.md` and `prompts/log-ia.es.md`
- Unit and integration tests using synthetic video
- MIT license
