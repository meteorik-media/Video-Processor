#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Video Processor — comprime vídeo raw a proxies ligeros para que una IA (o una persona)
pueda leerlo y devolver minutos exactos, sin tocar nunca los originales.

Un solo archivo, sin dependencias de Python: solo necesita ffmpeg y ffprobe en el PATH.
Pensado para correr a mano o en un schedule (es idempotente: lo ya procesado se salta).

Uso rápido:
    python video_processor.py serve          (interfaz web local, la forma más cómoda)
    python video_processor.py doctor
    python video_processor.py run  RAW/ -o SALIDA/ --preset ai-log --chunk 30m --scenes 0.3
    python video_processor.py watch RAW/ -o SALIDA/ --interval 300
    python video_processor.py frames RAW/ -o FRAMES/ --fps 24 --format png --zip
    python video_processor.py assemble FRAMES/ -o VIDEOS/ --format mp4 --audio
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

__version__ = "0.2.0"

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".ts", ".m4v", ".wmv"}
MANIFEST_NAME = "manifest.json"
MARKERS_NAME = "markers.csv"
LOG_NAME = "log_raw.csv"
LOG_HEADER = ["archivo", "entrada", "salida", "que_se_ve", "tipo", "calidad", "uso_sugerido", "notas"]
USER_PRESETS_NAME = "presets.user.json"
FRAME_FORMATS = ("png", "jpg")
ASSEMBLE_FORMATS = ("mp4", "webm", "gif")

# Presets nombrados (igual que en Image Processor, pero en JSON). Se pueden añadir o pisar con
# presets.user.json junto al script, o con --preset-file.
BUILTIN_PRESETS = {
    "ai-log": {
        "description": "Para que una IA lea el vídeo: 360p, 2 fps, sin audio, CRF 34.",
        "description_en": "For an AI to read the video: 360p, 2 fps, no audio, CRF 34.",
        "height": 360, "fps": 2, "crf": 34, "audio": False, "timecode": True,
        "x264_preset": "veryfast",
    },
    "ai-log-480": {
        "description": "Como ai-log pero a 480p, por si hay texto pequeño en pantalla.",
        "description_en": "Like ai-log but at 480p, in case there is small on-screen text.",
        "height": 480, "fps": 2, "crf": 34, "audio": False, "timecode": True,
        "x264_preset": "veryfast",
    },
    "ai-log-fine": {
        "description": "Como ai-log pero a 5 fps, para acción muy rápida o combates cortos.",
        "description_en": "Like ai-log but at 5 fps, for very fast action or short fights.",
        "height": 360, "fps": 5, "crf": 34, "audio": False, "timecode": True,
        "x264_preset": "veryfast",
    },
    "ai-log-480-fine": {
        "description": "480p a 5 fps: texto pequeño en pantalla y acción rápida (el más pesado de los ai-log).",
        "description_en": "480p at 5 fps: small on-screen text and fast action (the heaviest ai-log).",
        "height": 480, "fps": 5, "crf": 34, "audio": False, "timecode": True,
        "x264_preset": "veryfast",
    },
    "human-proxy": {
        "description": "Proxy ligero para editar o revisar: 540p, hasta 30 fps, con audio.",
        "description_en": "Light proxy for editing or reviewing: 540p, up to 30 fps, with audio.",
        "height": 540, "fps": 30, "crf": 28, "audio": True, "audio_bitrate": "96k",
        "timecode": True, "x264_preset": "veryfast",
    },
}

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]


# ───────────────────────── utilidades ─────────────────────────

def tool(name):
    """Ruta de ffmpeg/ffprobe: variable de entorno FFMPEG/FFPROBE o el PATH."""
    return os.environ.get(name.upper()) or shutil.which(name)


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_rate(text):
    """'30000/1001' -> 29.97; '0/0' o basura -> 0."""
    try:
        if text and "/" in text:
            a, b = text.split("/", 1)
            return float(a) / float(b) if float(b) else 0.0
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def parse_span(text):
    """'30m' -> 1800, '90s' -> 90, '1h' -> 3600, '1800' -> 1800, '0'/None -> 0."""
    if text is None or str(text).strip() in ("", "0"):
        return 0.0
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*", str(text).lower())
    if not m:
        raise ValueError(f"duración no válida: {text!r} (ej.: 30m, 90s, 1h)")
    n, unit = float(m.group(1)), m.group(2) or "s"
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def fmt_hms(seconds):
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def fmt_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write_text(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def esc_filter_path(p):
    """Escapa una ruta para usarla dentro de un filtro de ffmpeg (sobre todo C:\\... en Windows)."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def find_font(explicit=None):
    if explicit:
        return explicit if Path(explicit).is_file() else None
    for c in FONT_CANDIDATES:
        if Path(c).is_file():
            return c
    return None


_filter_cache = {}


def has_filter(name):
    if name not in _filter_cache:
        ff = tool("ffmpeg")
        ok = False
        if ff:
            r = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True,
                               errors="replace")
            ok = re.search(rf"\b{re.escape(name)}\b", r.stdout or "") is not None
        _filter_cache[name] = ok
    return _filter_cache[name]


# ───────────────────────── presets y planificación ─────────────────────────

def load_presets(extra_file=None):
    presets = {k: dict(v) for k, v in BUILTIN_PRESETS.items()}
    candidates = [user_presets_path()]
    if extra_file:
        candidates.append(Path(extra_file))
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as err:
                raise SystemExit(f"✗ No se pudo leer {path}: {err}")
            for name, cfg in data.items():
                presets[name] = {**presets.get(name, {}), **cfg}
    return presets


def resolve_settings(args, presets):
    if args.preset not in presets:
        raise SystemExit(f"✗ Preset desconocido: {args.preset}. Disponibles: {', '.join(sorted(presets))}")
    s = dict(presets[args.preset])
    if args.height is not None:
        s["height"] = args.height
    if args.fps is not None:
        s["fps"] = args.fps
    if args.crf is not None:
        s["crf"] = args.crf
    if args.audio is not None:
        s["audio"] = args.audio
    if args.timecode is not None:
        s["timecode"] = args.timecode
    s["chunk_seconds"] = parse_span(args.chunk)
    s["scenes"] = args.scenes or 0
    s.pop("description", None)
    s.pop("description_en", None)
    return s


def target_size(w, h, short_side):
    """Reduce para que el lado corto mida `short_side` (sin ampliar nunca), con medidas pares."""
    s = min(w, h)
    if not short_side or s <= short_side:
        return w - w % 2, h - h % 2
    k = short_side / s
    return int(round(w * k / 2) * 2), int(round(h * k / 2) * 2)


def plan_chunks(duration, chunk_seconds):
    """[(inicio, duración|None)]. Si el último trozo sale diminuto (<10%) se une al anterior."""
    if not chunk_seconds or duration <= chunk_seconds * 1.1:
        return [(0.0, None)]
    n = int(duration // chunk_seconds)
    if duration - n * chunk_seconds > chunk_seconds * 0.1:
        n += 1
    out = []
    for i in range(n):
        start = i * chunk_seconds
        last = i == n - 1
        out.append((start, None if last else chunk_seconds))
    return out


def build_vf(info, settings, offset, font):
    parts = []
    want = settings.get("fps")
    if want and want < info["fps"] - 0.01:
        parts.append(f"fps={want:g}")
    w, h = target_size(info["width"], info["height"], settings.get("height"))
    if (w, h) != (info["width"], info["height"]):
        parts.append(f"scale={w}:{h}:flags=bicubic")
    if settings.get("timecode") and font:
        fs = max(16, round(min(w, h) / 14))
        text = "%{pts\\:hms\\:" + f"{offset:.3f}" + "}"
        parts.append(
            f"drawtext=fontfile='{esc_filter_path(font)}':text='{text}':x=10:y=8:fontsize={fs}"
            f":fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=6"
        )
    return ",".join(parts) if parts else "null"


# ───────────────────────── ffprobe / ffmpeg ─────────────────────────

def probe(path):
    r = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,avg_frame_rate,r_frame_rate,duration:stream_tags=rotate"
         ":stream_side_data=rotation:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise RuntimeError("ffprobe no pudo leer el archivo: " + clean_err(r.stderr))
    data = json.loads(r.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError("el archivo no tiene pista de vídeo")
    s = streams[0]
    fps = parse_rate(s.get("avg_frame_rate")) or parse_rate(s.get("r_frame_rate")) or 30.0
    duration = to_float(s.get("duration")) or to_float((data.get("format") or {}).get("duration"))
    if duration <= 0:
        raise RuntimeError("no se pudo leer la duración")
    w, h = int(s["width"]), int(s["height"])
    # Vídeo de móvil: se guarda en horizontal con metadatos de rotación. ffmpeg lo gira solo al
    # codificar, así que las medidas que importan son las ya giradas.
    rotation = to_float((s.get("tags") or {}).get("rotate"))
    for sd in s.get("side_data_list") or []:
        if "rotation" in sd:
            rotation = to_float(sd["rotation"])
    if round(rotation / 90) % 2:
        w, h = h, w
    return {"width": w, "height": h, "fps": fps, "duration": duration}


def show_progress(label, pct, state):
    if os.environ.get("VP_PROGRESS") == "1":  # lo usa la interfaz web: líneas fáciles de leer
        if pct != state.get("last_pct"):
            state["last_pct"] = pct
            print(f"@progress {pct} {label}", flush=True)
    elif sys.stdout.isatty():
        print(f"\r  {label}  {pct:3d}%", end="", flush=True)
    elif pct // 25 > state.get("last", -1):
        state["last"] = pct // 25
        print(f"  {label}  {pct}%", flush=True)


def run_ffmpeg(cmd, out_duration, label):
    err_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err_file, text=True, errors="replace")
    state = {}
    for line in proc.stdout:
        if line.startswith(("out_time_us=", "out_time_ms=")):
            try:
                us = int(line.split("=", 1)[1])
            except ValueError:
                continue
            if out_duration > 0:
                show_progress(label, max(0, min(99, int(us / 1e6 / out_duration * 100))), state)
    proc.stdout.close()
    rc = proc.wait()
    err_file.seek(0)
    err = err_file.read()
    err_file.close()
    if sys.stdout.isatty():
        print("\r" + " " * 70 + "\r", end="")
    return rc, err


def encode_range(src, dst, info, settings, start, dur, font, label):
    out_dur = dur if dur else max(0.0, info["duration"] - start)
    audio = bool(settings.get("audio"))
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(src), "-map", "0:v:0"]
    if audio:
        cmd += ["-map", "0:a:0?"]
    cmd += ["-vf", build_vf(info, settings, start, font),
            "-c:v", "libx264", "-preset", settings.get("x264_preset", "veryfast"),
            "-crf", str(settings.get("crf", 28)), "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", settings.get("audio_bitrate", "96k"), "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", "-f", "mp4", str(dst)]
    rc, err = run_ffmpeg(cmd, out_dur, label)
    if rc != 0:
        raise RuntimeError("ffmpeg falló: " + clean_err(err, 500))


def clean_err(text, limit=300):
    """Una sola línea legible a partir de la salida de error de ffmpeg/ffprobe."""
    return re.sub(r"\s+", " ", text or "").strip()[-limit:]


def detect_scenes(files, starts, threshold):
    """Cambios de escena sobre los proxies ya reducidos (rápido), tratando todos los trozos como un
    solo flujo continuo para no perder los cambios justo en el corte entre trozos.
    Devuelve [(tiempo_en_el_original, score)]."""
    durations = []
    for f in files:
        r = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(f)], capture_output=True, text=True, errors="replace")
        durations.append(to_float(r.stdout.strip()))
    cum = [0.0]
    for d in durations:
        cum.append(cum[-1] + d)
    list_file = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    try:
        for f in files:
            safe = Path(f).resolve().as_posix().replace("'", "'\\''")
            list_file.write(f"file '{safe}'\n")
        list_file.close()
        cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-f", "concat", "-safe", "0",
               "-i", list_file.name, "-an",
               "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-", "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    finally:
        try:
            os.unlink(list_file.name)
        except OSError:
            pass
    if r.returncode != 0:
        raise RuntimeError("detección de escenas falló: " + clean_err(r.stderr))
    marks, t = [], None
    for line in r.stdout.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
        if m and t is not None:
            i = max(0, min(len(files) - 1, next((k for k in range(len(files)) if t < cum[k + 1]), len(files) - 1)))
            marks.append((round(starts[i] + (t - cum[i]), 2), round(float(m.group(1)), 3)))
            t = None
    return marks


# ───────────────────────── manifest ─────────────────────────

def load_manifest(out_dir):
    path = out_dir / MANIFEST_NAME
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("entries"), dict):
                return data
        except (OSError, ValueError):
            backup = path.with_name(f"{MANIFEST_NAME}.corrupto-{int(time.time())}")
            shutil.copy2(path, backup)
            print(f"! manifest.json ilegible, copia guardada en {backup.name}; se empieza de cero")
    return {"version": 1, "tool": f"video-processor {__version__}", "entries": {}}


def save_manifest(out_dir, manifest):
    manifest["tool"] = f"video-processor {__version__}"
    atomic_write_text(out_dir / MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))


def write_markers_csv(out_dir, manifest):
    rows = []
    for entry in manifest["entries"].values():
        for t, score in entry.get("markers", []):
            rows.append((entry["id"], t, fmt_hms(t), "escena", score))
    if not rows:
        return
    rows.sort(key=lambda r: (r[0], r[1]))
    tmp = out_dir / (MARKERS_NAME + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["archivo", "tiempo_s", "tiempo_hms", "tipo", "score"])
        w.writerows(rows)
    os.replace(tmp, out_dir / MARKERS_NAME)


def ensure_log_template(out_dir):
    path = out_dir / LOG_NAME
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(LOG_HEADER)


# ───────────────────────── proceso principal ─────────────────────────

def collect_files(inputs, out_dir):
    out_res = out_dir.resolve()
    found = []
    for inp in inputs:
        p = Path(inp)
        if p.is_file():
            if p.suffix.lower() in VIDEO_EXTS:
                found.append((p.parent, p, False))
            else:
                print(f"! Ignorado (no parece vídeo): {p}")
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if (f.is_file() and f.suffix.lower() in VIDEO_EXTS and not f.name.startswith(".")
                        and out_res not in f.resolve().parents):
                    found.append((p, f, True))
        else:
            print(f"! No existe: {p}")
    return found


def entry_is_current(entry, st, settings, out_dir):
    return (entry and entry.get("status") == "ok"
            and entry.get("size") == st.st_size and abs(entry.get("mtime", 0) - st.st_mtime) < 1
            and entry.get("settings") == settings
            and all((out_dir / o["file"]).exists() for o in entry.get("outputs", [])))


def process_file(src, rel, st, settings, preset_name, out_dir, font, label, args):
    info = probe(src)
    chunks = plan_chunks(info["duration"], settings["chunk_seconds"])
    stem = src.stem
    outputs, markers = [], []
    rel_parent = rel.parent
    (out_dir / rel_parent).mkdir(parents=True, exist_ok=True)
    for i, (start, dur) in enumerate(chunks, 1):
        suffix = f".part{i:02d}" if len(chunks) > 1 else ""
        name = f"{stem}.{preset_name}{suffix}.mp4"
        final = out_dir / rel_parent / name
        tmp = final.with_name(final.name + ".part")
        end = start + dur if dur else info["duration"]
        tag = f"{label} {stem}" + (f" · trozo {i}/{len(chunks)}" if len(chunks) > 1 else "")
        try:
            encode_range(src, tmp, info, settings, start, dur, font, tag)
            os.replace(tmp, final)
        finally:
            if tmp.exists():
                tmp.unlink()
        outputs.append({"file": (rel_parent / name).as_posix(), "start": round(start, 3),
                        "end": round(end, 3), "size": final.stat().st_size})
    if settings["scenes"]:
        markers = detect_scenes([out_dir / o["file"] for o in outputs], [o["start"] for o in outputs],
                                settings["scenes"])
    return info, outputs, markers


def run_once(args, presets):
    out_dir = Path(args.output)
    settings = resolve_settings(args, presets)
    font = find_font(args.font)
    if settings.get("timecode") and not font:
        print("! No encontré una fuente para el reloj en pantalla: se procesa SIN timecode quemado "
              "(usa --font RUTA.ttf). Los tiempos del manifest siguen siendo exactos.")
        settings["timecode"] = False
    elif settings.get("timecode") and not has_filter("drawtext"):
        print("! Tu ffmpeg no trae el filtro drawtext: se procesa SIN timecode quemado.")
        settings["timecode"] = False

    files = collect_files(args.inputs, out_dir)
    if not files:
        print("No hay vídeos que procesar.")
        return 0
    multi_input = len(args.inputs) > 1
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(out_dir) if out_dir.exists() else {"version": 1, "entries": {}}

    done = skipped = failed = waiting = 0
    total_in = total_out = 0
    t0 = time.time()
    for n, (root, src, is_dir_root) in enumerate(files, 1):
        rel = src.relative_to(root)
        if is_dir_root and multi_input:
            rel = Path(root.name) / rel
        key = f"{rel.as_posix()}|{args.preset}"
        st = src.stat()
        label = f"[{n}/{len(files)}]"
        if args.settle and time.time() - st.st_mtime < args.settle:
            waiting += 1
            print(f"{label} {src.name}: se modificó hace poco, lo dejo para la próxima pasada")
            continue
        entry = manifest["entries"].get(key)
        if not args.force and entry_is_current(entry, st, settings, out_dir):
            skipped += 1
            continue
        if args.dry_run:
            try:
                info = probe(src)
            except RuntimeError as err:
                print(f"{label} {src.name}: ✗ {err}")
                failed += 1
                continue
            chunks = plan_chunks(info["duration"], settings["chunk_seconds"])
            w, h = target_size(info["width"], info["height"], settings.get("height"))
            print(f"{label} {src.name}: {fmt_hms(info['duration'])} {info['width']}x{info['height']} "
                  f"@{info['fps']:.0f} -> {w}x{h} @{min(info['fps'], settings.get('fps') or info['fps']):g}, "
                  f"{len(chunks)} trozo(s)")
            continue
        try:
            info, outputs, markers = process_file(src, rel, st, settings, args.preset, out_dir, font, label, args)
        except Exception as err:  # noqa: BLE001 - un fallo no debe parar el lote
            failed += 1
            print(f"{label} {src.name}: ✗ {err}")
            manifest["entries"][key] = {
                "id": src.stem, "source": str(src), "size": st.st_size, "mtime": st.st_mtime,
                "preset": args.preset, "settings": settings, "status": "failed",
                "error": str(err)[-500:], "processed_at": now_iso(), "outputs": []}
            save_manifest(out_dir, manifest)
            continue
        out_size = sum(o["size"] for o in outputs)
        total_in += st.st_size
        total_out += out_size
        done += 1
        manifest["entries"][key] = {
            "id": src.stem, "source": str(src), "size": st.st_size, "mtime": st.st_mtime,
            "duration": round(info["duration"], 3), "fps": round(info["fps"], 3),
            "width": info["width"], "height": info["height"], "preset": args.preset,
            "settings": settings, "status": "ok", "processed_at": now_iso(),
            "outputs": outputs, "markers": markers,
            **({"id_warning": "el id lleva puntos; usa nombres tipo cards_0007"} if "." in src.stem else {}),
        }
        save_manifest(out_dir, manifest)
        saving = (1 - out_size / st.st_size) * 100 if st.st_size else 0
        print(f"{label} {src.name}: ✓ {fmt_size(st.st_size)} → {fmt_size(out_size)} (−{saving:.1f}%)"
              + (f", {len(markers)} cambios de escena" if settings["scenes"] else ""))

    if not args.dry_run and out_dir.exists():
        write_markers_csv(out_dir, manifest)
        if done or manifest["entries"]:
            ensure_log_template(out_dir)
    secs = time.time() - t0
    print(f"\nListo en {secs:.0f}s · procesados {done} · ya al día {skipped} · pendientes {waiting} · con error {failed}")
    if total_in:
        print(f"Peso: {fmt_size(total_in)} → {fmt_size(total_out)} (−{(1 - total_out / total_in) * 100:.1f}%)")
    return 1 if failed else 0


def frames_settings(args):
    if args.format not in FRAME_FORMATS:
        raise SystemExit(f"✗ Formato no válido: {args.format}. Usa {' o '.join(FRAME_FORMATS)}")
    if args.fps is not None and args.fps <= 0:
        raise SystemExit("✗ --fps debe ser mayor que 0")
    return {"mode": "frames", "fps": args.fps if args.fps is not None else 24.0, "format": args.format,
            "height": args.height or 0, "zip": bool(args.zip)}


def extract_frames(src, dst_dir, info, settings, label):
    """Un frame cada 1/fps segundos en dst_dir (frame_0001.png…). Devuelve cuántos frames salieron."""
    fps = settings["fps"]
    pad = len(str(max(1, int(info["duration"] * fps))))
    parts = [f"fps={fps:g}"]
    w, h = target_size(info["width"], info["height"], settings.get("height"))
    if (w, h) != (info["width"], info["height"]):
        parts.append(f"scale={w}:{h}:flags=bicubic")
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats",
           "-i", str(src), "-map", "0:v:0", "-an", "-vf", ",".join(parts)]
    cmd += ["-q:v", "2"] if settings["format"] == "jpg" else []
    cmd += [str(dst_dir / f"frame_%0{pad}d.{settings['format']}")]
    rc, err = run_ffmpeg(cmd, info["duration"], label)
    if rc != 0:
        raise RuntimeError("ffmpeg falló: " + clean_err(err, 500))
    n = sum(1 for _ in dst_dir.glob(f"frame_*.{settings['format']}"))
    if not n:
        raise RuntimeError("ffmpeg no sacó ningún frame")
    return n


def process_frames(src, rel, settings, out_dir, label):
    info = probe(src)
    final_name = f"{src.stem}.frames" + (".zip" if settings["zip"] else "")
    final = out_dir / rel.parent / final_name
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = final.with_name(final.name + ".part")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir()
    try:
        n = extract_frames(src, tmp_dir, info, settings, f"{label} {src.stem}")
        if settings["zip"]:
            tmp_zip = final.with_name(final.name + ".tmp")
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_STORED) as z:  # PNG/JPG ya van comprimidos
                for f in sorted(tmp_dir.iterdir()):
                    z.write(f, f.name)
            os.replace(tmp_zip, final)
            size = final.stat().st_size
        else:
            if final.exists():
                shutil.rmtree(final)
            os.replace(tmp_dir, final)
            size = sum(f.stat().st_size for f in final.iterdir())
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        final.with_name(final.name + ".tmp").unlink(missing_ok=True)
    return info, [{"file": (rel.parent / final_name).as_posix(), "start": 0.0, "end": round(info["duration"], 3),
                   "size": size, "frames": n}]


def run_frames(args):
    out_dir = Path(args.output)
    settings = frames_settings(args)
    files = collect_files(args.inputs, out_dir)
    if not files:
        print("No hay vídeos que procesar.")
        return 0
    multi_input = len(args.inputs) > 1
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(out_dir) if out_dir.exists() else {"version": 1, "entries": {}}
    done = skipped = failed = waiting = 0
    t0 = time.time()
    for n, (root, src, is_dir_root) in enumerate(files, 1):
        rel = src.relative_to(root)
        if is_dir_root and multi_input:
            rel = Path(root.name) / rel
        key = f"{rel.as_posix()}|frames"
        st = src.stat()
        label = f"[{n}/{len(files)}]"
        if args.settle and time.time() - st.st_mtime < args.settle:
            waiting += 1
            print(f"{label} {src.name}: se modificó hace poco, lo dejo para la próxima pasada")
            continue
        if not args.force and entry_is_current(manifest["entries"].get(key), st, settings, out_dir):
            skipped += 1
            continue
        if args.dry_run:
            try:
                info = probe(src)
            except RuntimeError as err:
                print(f"{label} {src.name}: ✗ {err}")
                failed += 1
                continue
            w, h = target_size(info["width"], info["height"], settings["height"])
            print(f"{label} {src.name}: {fmt_hms(info['duration'])} {info['width']}x{info['height']} -> {w}x{h}, "
                  f"~{max(1, int(info['duration'] * settings['fps']))} frames {settings['format'].upper()} "
                  f"a {settings['fps']:g} fps")
            continue
        try:
            info, outputs = process_frames(src, rel, settings, out_dir, label)
        except Exception as err:  # noqa: BLE001 - un fallo no debe parar el lote
            failed += 1
            print(f"{label} {src.name}: ✗ {err}")
            manifest["entries"][key] = {
                "id": src.stem, "source": str(src), "size": st.st_size, "mtime": st.st_mtime,
                "preset": "frames", "settings": settings, "status": "failed",
                "error": str(err)[-500:], "processed_at": now_iso(), "outputs": []}
            save_manifest(out_dir, manifest)
            continue
        done += 1
        manifest["entries"][key] = {
            "id": src.stem, "source": str(src), "size": st.st_size, "mtime": st.st_mtime,
            "duration": round(info["duration"], 3), "fps": round(info["fps"], 3),
            "width": info["width"], "height": info["height"], "preset": "frames",
            "settings": settings, "status": "ok", "processed_at": now_iso(), "outputs": outputs, "markers": []}
        save_manifest(out_dir, manifest)
        print(f"{label} {src.name}: ✓ {outputs[0]['frames']} frames {settings['format'].upper()} "
              f"a {settings['fps']:g} fps ({fmt_size(outputs[0]['size'])})")
    print(f"\nListo en {time.time() - t0:.0f}s · procesados {done} · ya al día {skipped} · pendientes {waiting} · con error {failed}")
    return 1 if failed else 0


FRAME_RE = re.compile(r"frame_(\d+)\.(png|jpg)$")


def sequence_frames(folder):
    """Frames numerados de una carpeta: [(número, ruta)] ordenados, de una sola extensión."""
    found = [(int(m.group(1)), f, m.group(2)) for f in Path(folder).iterdir()
             if f.is_file() and (m := FRAME_RE.fullmatch(f.name))]
    if not found:
        return []
    ext = sorted({e for _, _, e in found})[0]
    return sorted((n, f) for n, f, e in found if e == ext)


def find_sequences(inputs):
    """[(raíz, ruta, es_carpeta_raíz)]: carpetas con frames_NNNN.png/jpg o .zip de frames, recorriendo subcarpetas."""
    found = []
    for inp in inputs:
        p = Path(inp)
        if p.is_file() and p.suffix.lower() == ".zip":
            found.append((p.parent, p, False))
        elif p.is_dir():
            if sequence_frames(p):
                found.append((p.parent, p, False))
                continue
            seen = set()
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() == ".zip" and not f.name.startswith("."):
                    found.append((p, f, True))
                elif f.is_file() and FRAME_RE.fullmatch(f.name) and f.parent not in seen:
                    seen.add(f.parent)
                    found.append((p, f.parent, True))
        else:
            print(f"! No existe o no sirve: {p}")
    return found


def sequence_origin(root, seq):
    """(fps, vídeo original) de una secuencia sacada por este programa, según el manifest.json de su carpeta."""
    mpath = Path(root) / MANIFEST_NAME
    if not mpath.is_file():
        return None, None
    try:
        entries = json.loads(mpath.read_text(encoding="utf-8")).get("entries", {})
    except (OSError, ValueError):
        return None, None
    rel = Path(seq).relative_to(root).as_posix()
    for e in entries.values():
        if e.get("status") == "ok" and any(o.get("file") == rel for o in e.get("outputs", [])):
            src = e.get("source")
            return (e.get("settings") or {}).get("fps"), (src if src and Path(src).is_file() else None)
    return None, None


def assemble_sequence(folder, dst, fmt, fps, audio_src, crf, label):
    frames = sequence_frames(folder)
    if not frames:
        raise RuntimeError("no hay frames frame_NNNN.png/jpg")
    first = frames[0][1]
    digits = len(FRAME_RE.fullmatch(first.name).group(1))
    ext = first.suffix
    pattern = str(Path(folder) / f"frame_%0{digits}d{ext}")
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats",
           "-framerate", f"{fps:g}", "-start_number", str(frames[0][0]), "-i", pattern]
    use_audio = bool(audio_src) and fmt != "gif"
    if use_audio:
        cmd += ["-i", str(audio_src)]
    even = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    if fmt == "gif":
        cmd += ["-vf", f"{even},split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0", "-f", "gif"]
    elif fmt == "webm":
        cmd += ["-map", "0:v:0", "-vf", even, "-c:v", "libvpx-vp9", "-crf", str(max(crf, 20) + 10),
                "-b:v", "0", "-pix_fmt", "yuv420p"]
        cmd += ["-map", "1:a:0?", "-c:a", "libopus", "-shortest"] if use_audio else ["-an"]
        cmd += ["-f", "webm"]
    else:
        cmd += ["-map", "0:v:0", "-vf", even, "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-pix_fmt", "yuv420p"]
        cmd += ["-map", "1:a:0?", "-c:a", "aac", "-b:a", "128k", "-shortest"] if use_audio else ["-an"]
        cmd += ["-movflags", "+faststart", "-f", "mp4"]
    tmp = dst.with_name(dst.name + ".part")
    try:
        rc, err = run_ffmpeg(cmd + [str(tmp)], len(frames) / fps, label)
        if rc != 0:
            raise RuntimeError("ffmpeg falló: " + clean_err(err, 500))
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return len(frames), dst.stat().st_size


def run_assemble(args):
    if args.format not in ASSEMBLE_FORMATS:
        raise SystemExit(f"✗ Formato no válido: {args.format}. Usa {', '.join(ASSEMBLE_FORMATS)}")
    if args.fps is not None and args.fps <= 0:
        raise SystemExit("✗ --fps debe ser mayor que 0")
    out_dir = Path(args.output)
    seqs = find_sequences(args.inputs)
    if not seqs:
        print("No encontré carpetas de frames (frame_0001.png…) ni .zip.")
        return 0
    multi_input = len(args.inputs) > 1
    done = skipped = failed = 0
    t0 = time.time()
    for n, (root, seq, is_dir_root) in enumerate(seqs, 1):
        label = f"[{n}/{len(seqs)}]"
        rel = seq.relative_to(root)
        stem = re.sub(r"\.frames$", "", seq.stem if seq.is_file() else seq.name)
        rel_parent = (Path(root.name) / rel.parent) if multi_input and is_dir_root else rel.parent
        dst = out_dir / rel_parent / f"{stem}.assembled.{args.format}"
        if dst.exists() and not args.force:
            skipped += 1
            continue
        known_fps, origin = sequence_origin(root, seq)
        fps = args.fps or known_fps or 24.0
        audio_src = None
        if args.audio:
            audio_src = origin
            if not origin and not args.dry_run:
                print(f"! {label} {stem}: no encuentro el vídeo original en el manifest, sale sin audio")
        if args.dry_run:
            print(f"{label} {seq.name}: -> {dst.name} a {fps:g} fps" + (" con audio" if audio_src else ""))
            continue
        tmp_dir = None
        try:
            folder = seq
            if seq.is_file():
                tmp_dir = Path(tempfile.mkdtemp(prefix="vp-asm-"))
                with zipfile.ZipFile(seq) as z:
                    for name in z.namelist():
                        if FRAME_RE.fullmatch(Path(name).name):  # solo frames, sin rutas raras
                            (tmp_dir / Path(name).name).write_bytes(z.read(name))
                folder = tmp_dir
            dst.parent.mkdir(parents=True, exist_ok=True)
            count, size = assemble_sequence(folder, dst, args.format, fps, audio_src, args.crf, f"{label} {stem}")
            done += 1
            print(f"{label} {seq.name}: ✓ {count} frames a {fps:g} fps -> {dst.name} ({fmt_size(size)})"
                  + (" con audio" if audio_src else ""))
        except Exception as err:  # noqa: BLE001 - un fallo no debe parar el lote
            failed += 1
            print(f"{label} {seq.name}: ✗ {err}")
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"\nListo en {time.time() - t0:.0f}s · armados {done} · ya al día {skipped} · con error {failed}")
    return 1 if failed else 0


def cmd_watch(args, presets):
    print(f"Vigilando {', '.join(args.inputs)} cada {args.interval}s (Ctrl+C para parar)")
    try:
        while True:
            run_once(args, presets)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nParado.")
        return 0


def cmd_doctor(args, presets):
    ok = True

    def line(good, text):
        nonlocal ok
        ok = ok and good
        print(("✓ " if good else "✗ ") + text)

    for name in ("ffmpeg", "ffprobe"):
        path = tool(name)
        if path:
            ver = subprocess.run([path, "-version"], capture_output=True, text=True, errors="replace").stdout
            line(True, f"{name}: {ver.splitlines()[0] if ver else path}")
        else:
            line(False, f"{name} no está en el PATH (instálalo o usa la variable {name.upper()})")
    if tool("ffmpeg"):
        enc = subprocess.run([tool("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True,
                             errors="replace").stdout
        line(" libx264 " in enc, "codificador libx264")
        line(" aac " in enc, "codificador aac (solo hace falta con audio)")
        line(has_filter("drawtext"), "filtro drawtext (reloj en pantalla)")
        line(has_filter("select") and has_filter("metadata"), "filtros select/metadata (cambios de escena)")
    font = find_font(args.font)
    line(bool(font), f"fuente para el reloj: {font or 'no encontrada, usa --font RUTA.ttf'}")
    print("\nPresets:")
    for name, cfg in sorted(presets.items()):
        print(f"  {name:12s} {cfg.get('description', '')}")
    return 0 if ok else 1


def cmd_presets(args, presets):
    print(json.dumps(presets, indent=2, ensure_ascii=False))
    return 0



# ───────────────────────── interfaz web local ─────────────────────────
# Servidor de la biblioteca estándar, solo en 127.0.0.1. La interfaz (web/index.html) lanza este mismo
# script como subproceso (`run`/`watch`), así que hace exactamente lo mismo que la línea de comandos.

WEB_DIR = Path(__file__).with_name("web")
SCRIPT = Path(__file__).resolve()


class JobRunner:
    """Un único trabajo a la vez: el subproceso, su log y el progreso."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.reset()

    def reset(self):
        self.lines, self.state, self.mode = [], "idle", None
        self.progress = {"pct": 0, "label": ""}
        self.exit_code, self.output, self.cmd = None, None, ""

    def running(self):
        return self.state == "running"

    def start(self, mode, argv, output):
        with self.lock:
            if self.running():
                raise RuntimeError("ya hay un trabajo en marcha")
            self.reset()
            self.state, self.mode, self.output = "running", mode, output
            self.cmd = " ".join(["python", SCRIPT.name] + argv)
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", VP_PROGRESS="1")
            kw = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)} if os.name == "nt" \
                else {"start_new_session": True}
            self.proc = subprocess.Popen([sys.executable, "-u", str(SCRIPT), *argv], stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                         errors="replace", env=env, **kw)
            threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()

    def _pump(self, proc):
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            m = re.match(r"@progress (\d+) (.*)", line)
            if m:
                self.progress = {"pct": int(m.group(1)), "label": m.group(2)}
            elif line.strip():
                self.lines.append(line)
        proc.stdout.close()
        code = proc.wait()
        self.exit_code = code
        if self.state != "cancelled":
            self.state = "done" if code == 0 else "failed"
        self.progress = {"pct": 100 if code == 0 else self.progress["pct"], "label": self.progress["label"]}

    def cancel(self):
        proc = self.proc
        if not (proc and self.running()):
            return False
        self.state = "cancelled"
        try:
            if os.name == "nt":  # sin /T quedaría ffmpeg huérfano escribiendo
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            else:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        return True

    def snapshot(self, since):
        return {"state": self.state, "mode": self.mode, "cmd": self.cmd, "exit_code": self.exit_code,
                "output": self.output, "progress": self.progress,
                "total": len(self.lines), "lines": self.lines[since:]}


def list_roots():
    roots = [str(Path.home())]
    if os.name == "nt":
        roots += [f"{c}:\\" for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{c}:\\").exists()]
    else:
        roots.append("/")
    return roots


def browse_dir(path):
    p = (Path(path).expanduser() if path else Path.home()).resolve()
    if not p.is_dir():
        raise ValueError(f"no es una carpeta: {p}")
    dirs, vids = [], []
    try:
        entries = sorted(os.scandir(p), key=lambda e: e.name.lower())
    except OSError as err:
        raise ValueError(f"no se puede leer {p}: {err.strerror or err}")
    for e in entries:
        try:
            if e.name.startswith("."):
                continue
            if e.is_dir():
                dirs.append(e.name)
            elif Path(e.name).suffix.lower() in VIDEO_EXTS:
                vids.append({"name": e.name, "size": e.stat().st_size})
        except OSError:
            continue
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "dirs": dirs, "videos": vids}


def doctor_info():
    ff = tool("ffmpeg")
    enc = ""
    if ff:
        enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True,
                             errors="replace").stdout
    info = {"ffmpeg": bool(ff), "ffprobe": bool(tool("ffprobe")), "libx264": " libx264 " in enc,
            "aac": " aac " in enc, "drawtext": bool(ff) and has_filter("drawtext"),
            "scene": bool(ff) and has_filter("select") and has_filter("metadata"), "font": find_font(None)}
    info["ok"] = all(info[k] for k in ("ffmpeg", "ffprobe", "libx264"))
    return info


def read_results(out):
    d = Path(out)
    manifest = load_manifest(d) if (d / MANIFEST_NAME).is_file() else {"entries": {}}
    items = []
    for e in manifest["entries"].values():
        items.append({"id": e.get("id"), "status": e.get("status"), "source": e.get("source"),
                      "duration": e.get("duration"), "src_size": e.get("size"), "preset": e.get("preset"),
                      "outputs": e.get("outputs", []), "markers": len(e.get("markers", [])),
                      "error": e.get("error"), "processed_at": e.get("processed_at")})
    items.sort(key=lambda i: i.get("processed_at") or "", reverse=True)
    return {"items": items, "markers_csv": (d / MARKERS_NAME).is_file(), "log_csv": (d / LOG_NAME).is_file(),
            "dir": str(d.resolve())}


PRESET_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
PRESET_KEYS = ("height", "fps", "crf", "audio", "timecode", "x264_preset", "audio_bitrate")


def user_presets_path():
    return Path(__file__).with_name(USER_PRESETS_NAME)


def read_user_presets():
    path = user_presets_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise ValueError(f"no se pudo leer {path.name}: {err}")
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} debe ser un objeto JSON")
    return data


def save_user_preset(body):
    """Guarda un preset propio en presets.user.json: parte del preset base elegido y aplica el formulario."""
    name = str(body.get("name") or "").strip()
    if not PRESET_NAME_RE.fullmatch(name):
        raise ValueError("el nombre solo puede llevar letras, números, - y _ (máx. 40)")
    base = load_presets(None).get(str(body.get("base") or "ai-log"))
    if base is None:
        raise ValueError("preset base desconocido")
    cfg = {k: base[k] for k in PRESET_KEYS if k in base}
    for key, kind in (("height", int), ("fps", float), ("crf", int)):
        v = body.get(key)
        if v not in (None, ""):
            cfg[key] = kind(float(v))
    for key in ("audio", "timecode"):
        if isinstance(body.get(key), bool):
            cfg[key] = body[key]
    if cfg.get("audio") is True:
        cfg.setdefault("audio_bitrate", "96k")
    desc = str(body.get("description") or "").strip()
    if desc:
        cfg["description"] = desc[:200]
    data = read_user_presets()
    data[name] = cfg
    atomic_write_text(user_presets_path(), json.dumps(data, indent=2, ensure_ascii=False))
    return name


def delete_user_preset(name):
    data = read_user_presets()
    if name not in data:
        raise ValueError("ese preset no es uno de los tuyos (los integrados no se borran)")
    del data[name]
    atomic_write_text(user_presets_path(), json.dumps(data, indent=2, ensure_ascii=False))


def build_cli_args(body):
    """Del formulario de la web a los argumentos de `run`/`watch` (nada pasa por una shell)."""
    if body.get("task") == "frames":
        return build_frames_args(body)
    if body.get("task") == "assemble":
        return build_assemble_args(body)
    mode = {"run": "run", "dry": "run", "watch": "watch"}.get(body.get("mode"))
    inputs = [str(x) for x in body.get("inputs") or [] if str(x).strip()]
    output = str(body.get("output") or "").strip()
    if not mode:
        raise ValueError("modo desconocido")
    if not inputs:
        raise ValueError("elige al menos un archivo o carpeta de origen")
    if not output:
        raise ValueError("elige la carpeta de salida")
    argv = [mode, *inputs, "-o", output, "--preset", str(body.get("preset") or "ai-log")]
    for key, flag in (("height", "--height"), ("fps", "--fps"), ("crf", "--crf"), ("scenes", "--scenes"),
                      ("settle", "--settle"), ("interval", "--interval")):
        v = body.get(key)
        if v in (None, "") or (key == "interval" and mode != "watch"):
            continue
        float(v)  # valida que sea un número
        argv += [flag, str(v)]
    if str(body.get("chunk") or "").strip() not in ("", "0"):
        parse_span(body["chunk"])
        argv += ["--chunk", str(body["chunk"]).strip()]
    for key, on, off in (("audio", "--audio", "--no-audio"), ("timecode", "--timecode", "--no-timecode")):
        if body.get(key) is True:
            argv.append(on)
        elif body.get(key) is False:
            argv.append(off)
    if str(body.get("font") or "").strip():
        argv += ["--font", str(body["font"]).strip()]
    if body.get("force"):
        argv.append("--force")
    if body.get("mode") == "dry":
        argv.append("--dry-run")
    return mode, argv, output


def build_frames_args(body):
    """Del formulario (pestaña «Frames») a los argumentos de `frames`."""
    if body.get("mode") not in ("run", "dry"):
        raise ValueError("modo desconocido")
    inputs = [str(x) for x in body.get("inputs") or [] if str(x).strip()]
    output = str(body.get("output") or "").strip()
    if not inputs:
        raise ValueError("elige al menos un archivo o carpeta de origen")
    if not output:
        raise ValueError("elige la carpeta de salida")
    fmt = str(body.get("format") or "png")
    if fmt not in FRAME_FORMATS:
        raise ValueError("formato no válido")
    argv = ["frames", *inputs, "-o", output, "--format", fmt]
    for key, flag in (("fps", "--fps"), ("height", "--height"), ("settle", "--settle")):
        v = body.get(key)
        if v in (None, ""):
            continue
        float(v)  # valida que sea un número
        argv += [flag, str(v)]
    if body.get("zip"):
        argv.append("--zip")
    if body.get("force"):
        argv.append("--force")
    if body.get("mode") == "dry":
        argv.append("--dry-run")
    return "frames", argv, output


def build_assemble_args(body):
    """Del formulario (pestaña «Ensamblar») a los argumentos de `assemble`."""
    if body.get("mode") not in ("run", "dry"):
        raise ValueError("modo desconocido")
    inputs = [str(x) for x in body.get("inputs") or [] if str(x).strip()]
    output = str(body.get("output") or "").strip()
    if not inputs:
        raise ValueError("elige al menos una carpeta de frames o un .zip")
    if not output:
        raise ValueError("elige la carpeta de salida")
    fmt = str(body.get("format") or "mp4")
    if fmt not in ASSEMBLE_FORMATS:
        raise ValueError("formato no válido")
    argv = ["assemble", *inputs, "-o", output, "--format", fmt]
    for key, flag in (("fps", "--fps"), ("crf", "--crf")):
        v = body.get(key)
        if v in (None, ""):
            continue
        float(v)  # valida que sea un número
        argv += [flag, str(v)]
    for key, flag in (("audio", "--audio"), ("force", "--force")):
        if body.get(key):
            argv.append(flag)
    if body.get("mode") == "dry":
        argv.append("--dry-run")
    return "assemble", argv, output


def open_in_file_manager(path):
    p = Path(path)
    if not p.exists():
        raise ValueError("esa carpeta todavía no existe")
    if os.name == "nt":
        os.startfile(str(p))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def make_handler(job, presets_file, token, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "VideoProcessor"

        def log_message(self, *a):  # silencio
            pass

        def send_json(self, obj, code=200):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def guard(self, api):
            """Defensa contra otras webs: solo el host exacto y, para /api, el token de esta sesión."""
            if self.headers.get("Host", "") not in allowed_hosts:
                self.send_json({"error": "host no permitido"}, 403)
                return False
            if api and self.headers.get("X-VP-Token") != token:
                self.send_json({"error": "token no válido: recarga la página"}, 403)
                return False
            return True

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            api = url.path.startswith("/api/")
            if not self.guard(api):
                return
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/", "/index.html"):
                page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
                data = page.replace("__TOKEN__", token).replace("__VERSION__", __version__).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            try:
                if url.path == "/api/state":
                    self.send_json({"version": __version__, "doctor": doctor_info(),
                                    "presets": load_presets(presets_file), "roots": list_roots(),
                                    "user_presets": sorted(read_user_presets()),
                                    "script": SCRIPT.name})
                elif url.path == "/api/browse":
                    self.send_json(browse_dir(q.get("path")))
                elif url.path == "/api/job":
                    self.send_json(job.snapshot(int(q.get("since", 0))))
                elif url.path == "/api/results":
                    self.send_json(read_results(q.get("output", "")))
                else:
                    self.send_json({"error": "no existe"}, 404)
            except (ValueError, OSError, SystemExit) as err:
                self.send_json({"error": str(err)}, 400)

        def do_POST(self):  # noqa: N802
            if not self.guard(True):
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                path = urlparse(self.path).path
                if path == "/api/start":
                    _, argv, output = build_cli_args(body)
                    if presets_file:
                        argv += ["--preset-file", str(presets_file)]
                    job.start(body.get("mode"), argv, output)
                    self.send_json({"ok": True})
                elif path == "/api/preset/save":
                    self.send_json({"ok": True, "name": save_user_preset(body)})
                elif path == "/api/preset/delete":
                    delete_user_preset(str(body.get("name") or ""))
                    self.send_json({"ok": True})
                elif path == "/api/cancel":
                    self.send_json({"ok": job.cancel()})
                elif path == "/api/open":
                    open_in_file_manager(body.get("path", ""))
                    self.send_json({"ok": True})
                else:
                    self.send_json({"error": "no existe"}, 404)
            except (ValueError, TypeError, RuntimeError, OSError) as err:
                self.send_json({"error": str(err)}, 400)

    return Handler


def cmd_serve(args, presets):
    if not (WEB_DIR / "index.html").is_file():
        print(f"✗ Falta {WEB_DIR / 'index.html'} (la carpeta web/ debe ir junto al script).", file=sys.stderr)
        return 2
    token, job, server, port = secrets.token_urlsafe(24), JobRunner(), None, args.port
    for port in range(args.port, args.port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(job, args.preset_file, token, port))
            break
        except OSError:
            continue
    if not server:
        print(f"✗ No pude abrir ningún puerto entre {args.port} y {args.port + 19}.", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{port}/"
    print(f"Video Processor {__version__} · interfaz en {url}  (Ctrl+C para cerrar)")
    if not args.no_open:
        import webbrowser
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando…")
    finally:
        job.cancel()
        server.server_close()
    return 0


# ───────────────────────── CLI ─────────────────────────

def add_common(p):
    p.add_argument("inputs", nargs="+", help="archivos y/o carpetas (se recorren con subcarpetas)")
    p.add_argument("-o", "--output", required=True, help="carpeta de salida (se crea si no existe)")
    p.add_argument("--preset", default="ai-log", help="preset a usar (por defecto: ai-log)")
    p.add_argument("--preset-file", help="JSON con presets propios")
    p.add_argument("--height", type=int, help="lado corto en px (pisa el preset)")
    p.add_argument("--fps", type=float, help="fotogramas por segundo máximos (pisa el preset)")
    p.add_argument("--crf", type=int, help="calidad x264, más alto = más pequeño (pisa el preset)")
    p.add_argument("--audio", dest="audio", action="store_true", default=None, help="conservar audio")
    p.add_argument("--no-audio", dest="audio", action="store_false", help="quitar audio")
    p.add_argument("--timecode", dest="timecode", action="store_true", default=None,
                   help="quemar el reloj del vídeo original")
    p.add_argument("--no-timecode", dest="timecode", action="store_false", help="no quemar reloj")
    p.add_argument("--font", help="fuente .ttf/.otf para el reloj")
    p.add_argument("--chunk", default="0", help="trocear en partes de esta duración (ej. 30m); 0 = no")
    p.add_argument("--scenes", type=float, default=0,
                   help="detectar cambios de escena con este umbral (ej. 0.3) y guardarlos en markers.csv")
    p.add_argument("--force", action="store_true", help="reprocesar aunque ya esté al día")
    p.add_argument("--dry-run", action="store_true", help="solo mostrar qué se haría")
    p.add_argument("--settle", type=float, default=0,
                   help="saltar archivos modificados hace menos de N segundos (por si aún se graban)")


def build_parser():
    ap = argparse.ArgumentParser(prog="video_processor",
                                 description="Comprime vídeo raw a proxies ligeros para IA y humanos.")
    ap.add_argument("--version", action="version", version=f"video-processor {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="procesa una vez y termina (ideal para un schedule)")
    add_common(run)
    watch = sub.add_parser("watch", help="vigila la carpeta y procesa lo nuevo cada cierto tiempo")
    add_common(watch)
    watch.add_argument("--interval", type=float, default=300, help="segundos entre pasadas (por defecto 300)")
    fr = sub.add_parser("frames", help="saca frames sueltos (PNG/JPG) de cada vídeo, uno cada 1/fps segundos")
    fr.add_argument("inputs", nargs="+", help="archivos y/o carpetas (se recorren con subcarpetas)")
    fr.add_argument("-o", "--output", required=True, help="carpeta de salida (se crea si no existe)")
    fr.add_argument("--fps", type=float, help="un frame cada 1/fps segundos (por defecto 24)")
    fr.add_argument("--format", default="png", help="png (por defecto) o jpg")
    fr.add_argument("--height", type=int, help="lado corto en px (por defecto: tamaño original)")
    fr.add_argument("--zip", action="store_true", help="un .zip por vídeo en vez de una carpeta de frames")
    fr.add_argument("--force", action="store_true", help="reprocesar aunque ya esté al día")
    fr.add_argument("--dry-run", action="store_true", help="solo mostrar qué se haría")
    fr.add_argument("--settle", type=float, default=0,
                    help="saltar archivos modificados hace menos de N segundos")
    asm = sub.add_parser("assemble", help="rearma un vídeo (mp4/webm/gif) desde carpetas o .zip de frames")
    asm.add_argument("inputs", nargs="+", help="carpetas con frame_0001.png… o .zip (se recorren subcarpetas)")
    asm.add_argument("-o", "--output", required=True, help="carpeta de salida (se crea si no existe)")
    asm.add_argument("--fps", type=float, help="fotogramas por segundo (por defecto el de `frames`, o 24)")
    asm.add_argument("--format", default="mp4", help="mp4 (por defecto), webm o gif")
    asm.add_argument("--crf", type=int, default=18, help="calidad (mp4/webm), más alto = más pequeño; por defecto 18")
    asm.add_argument("--audio", action="store_true",
                     help="añadir el audio del vídeo original (lo busca en el manifest.json de los frames)")
    asm.add_argument("--force", action="store_true", help="rehacer aunque la salida ya exista")
    asm.add_argument("--dry-run", action="store_true", help="solo mostrar qué se haría")
    doc = sub.add_parser("doctor", help="comprueba ffmpeg, filtros y fuente")
    doc.add_argument("--font")
    doc.add_argument("--preset-file")
    srv = sub.add_parser("serve", help="abre la interfaz web local (solo en tu equipo)")
    srv.add_argument("--port", type=int, default=8765, help="puerto (por defecto 8765; si está ocupado prueba los siguientes)")
    srv.add_argument("--no-open", action="store_true", help="no abrir el navegador automáticamente")
    srv.add_argument("--preset-file")
    pre = sub.add_parser("presets", help="muestra los presets disponibles en JSON")
    pre.add_argument("--preset-file")
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    presets = load_presets(getattr(args, "preset_file", None))
    if args.cmd in ("run", "watch", "frames", "assemble") and not (tool("ffmpeg") and tool("ffprobe")):
        print("✗ No encuentro ffmpeg/ffprobe. Ejecuta `doctor` para más detalles.", file=sys.stderr)
        return 2
    try:
        if args.cmd == "run":
            return run_once(args, presets)
        if args.cmd == "frames":
            return run_frames(args)
        if args.cmd == "assemble":
            return run_assemble(args)
        if args.cmd == "watch":
            if args.settle == 0:
                args.settle = 60
            return cmd_watch(args, presets)
        if args.cmd == "doctor":
            return cmd_doctor(args, presets)
        if args.cmd == "serve":
            return cmd_serve(args, presets)
        return cmd_presets(args, presets)
    except ValueError as err:
        print(f"✗ {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
