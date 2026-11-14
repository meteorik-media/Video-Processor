# Video Processor v0.1.0

🌐 English | [Versión en español](README-ES.md) | 📝 [Changelog](CHANGELOG.md)

Compresses raw video into lightweight proxies so an AI (or a person) can watch it and give you the exact minute of everything, without ever touching your originals. A single Python script with no dependencies and a local web interface, built to run by hand or on a schedule. It's the sibling of [Image Processor](https://github.com/meteorik-gaming/Image-Processor): same look, same ideas (named presets, recursive folder mode, failures are skipped and counted), but on native ffmpeg behind a tiny local server, because hours of raw footage don't fit in a browser tab.

## 🧰 What it does

- **Local web interface** (`python video_processor.py serve`): pick folders with a built-in browser, choose a preset, tweak settings, watch live progress, save your own presets with a name, and see the results table. It runs only on your machine (`127.0.0.1`), works in English and Spanish, and does exactly what the command line does.
- **Named presets**
  - `ai-log`: 360p, 2 fps, no audio, CRF 34. About 99% smaller and still readable for an AI.
  - `ai-log-480`: same at 480p, in case there is small on-screen text.
  - `ai-log-fine` / `ai-log-480-fine`: the same two at 5 fps, for very fast action.
  - `human-proxy`: 540p, up to 30 fps, with audio, for editing or reviewing.
  - Save your own from the interface (they go to `presets.user.json`), or edit `presets.user.json` by hand (see `presets.user.example.json`) or with `--preset-file`. Any value can be overridden from the command line: `--height`, `--fps`, `--crf`, `--audio/--no-audio`.
- **Burned-in clock** showing the ORIGINAL video's time (`hh:mm:ss.mmm`, top-left). The AI reads the minute off the screen instead of trusting the player, and it stays correct even when the video is split into parts.
- **Chunking** (`--chunk 30m`) for long videos: every part keeps the original's time, and `manifest.json` stores each part's start and end.
- **Scene changes** (`--scenes 0.3`) as candidates to review, in `markers.csv`. They are detected on the already-reduced proxies (fast) and treating the parts as one continuous stream, so changes right at a cut between parts aren't lost.
- **Folder mode**: takes files and folders (with subfolders) and mirrors the structure in the output.
- **Idempotent**: anything already processed is skipped (same file, size, date and settings). Change the settings and it reprocesses by itself.
- **Originals are never touched.** Each output is written to a temp file and renamed when done, so an interrupted run doesn't leave broken videos.
- **Log template** (`log_raw.csv`, header only) and a **ready-made prompt** for the AI in `prompts/ai-log.en.md` (or `prompts/log-ia.es.md` in Spanish).
- `watch` monitors a folder, and `doctor` checks that your ffmpeg has everything needed.

## 🚀 Usage

**With the interface:** double-click `Video Processor.bat` (Windows) or run `./start.sh` (macOS/Linux). Your browser opens at `http://127.0.0.1:8765`. Closing the terminal window closes the app.

**From the command line:**

```
python video_processor.py serve            # web interface (--port N, --no-open)
python video_processor.py doctor
python video_processor.py run RAW/ -o PROXIES/ --preset ai-log --chunk 30m --scenes 0.3
python video_processor.py run RAW/ -o PROXIES/ --dry-run
python video_processor.py watch RAW/ -o PROXIES/ --interval 300
```

What ends up in `PROXIES/`:

```
cards_0007.ai-log.mp4            (or .part01.mp4, .part02.mp4… when chunked)
manifest.json                    everything processed: settings, parts with start/end, sizes, errors
markers.csv                      scene changes (only with --scenes)
log_raw.csv                      empty log template, header only
```

Workflow with an AI: process with `ai-log`, upload the `.ai-log.mp4` files to the AI along with the prompt in `prompts/ai-log.en.md`, and save the CSV it returns into `log_raw.csv`. Name your videos like `cards_0007` (no dots): that id is what the log uses.

### ⏰ Scheduling

`run` exits on its own and is idempotent, so it can be scheduled as is (adjust the paths):

- **Windows:** `schtasks /Create /SC HOURLY /TN "Video Processor" /TR "python C:\path\video_processor.py run C:\raw -o C:\proxies --settle 120"`
- **Linux/macOS (cron):** `0 * * * * python3 /path/video_processor.py run /raw -o /proxies --settle 120`

`--settle 120` skips files modified less than 2 minutes ago, in case they're still being recorded or copied. If any file fails, `run` exits with code 1 (and retries it on the next pass).

## 📋 Requirements

- Python 3.8 or later (standard library only; keep the `web/` folder next to the script for the interface)
- `ffmpeg` and `ffprobe` on the PATH, with `libx264` and the `drawtext` filter. `python video_processor.py doctor` checks everything
- A `.ttf` font for the clock. It's found automatically on Windows, macOS and Linux; if not, use `--font PATH` (or `--no-timecode`)

## ⚠️ Known limits

- Tested with synthetic clips; real multi-hour recordings are still to be tried.
- At 2 fps the clock moves in 0.5 s steps: that's the best precision for any minute the AI reads. Check them before cutting.
- Scene changes are candidates, not truth: a fast camera pan triggers them too.
- Console output is in Spanish only for now (the web interface is bilingual).
- The web interface is for one person on one machine: it has no login and only listens on `127.0.0.1`. Don't expose it to a network.

## 🧪 Tests

```
python -m unittest -v
```

The integration tests generate synthetic videos with ffmpeg and skip themselves if it isn't available. They also cover the web server (token and host checks, a full job through the API).

## 📝 License

[MIT](LICENSE) © Meteori-K Media.

---

Made with 💜 by Meteori-K Media
