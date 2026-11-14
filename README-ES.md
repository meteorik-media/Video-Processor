# Video Processor v0.1.0

🌐 [English version](README.md) | Español | 📝 [Changelog](CHANGELOG-ES.md)

Comprime vídeo raw a proxies ligeros para que una IA (o una persona) pueda mirarlo y devolverte los minutos exactos de cada cosa, sin tocar nunca los originales. Un solo script de Python, sin dependencias y con interfaz web local, pensado para correr a mano o en un schedule. Es el hermano de [Image Processor](https://github.com/meteorik-gaming/Image-Processor): mismo aspecto, mismas ideas (presets con nombre, modo carpeta recursivo, lo que falla se salta y se cuenta), pero con ffmpeg nativo detrás de un servidor local diminuto, porque horas de raw no caben en una pestaña del navegador.

## 🧰 Qué hace

- **Interfaz web local** (`python video_processor.py serve`): eliges carpetas con un explorador integrado, un preset, ajustas lo que quieras, ves el progreso en vivo guardas presets propios con nombre y ves la tabla de resultados. Corre solo en tu equipo (`127.0.0.1`), está en español e inglés y hace exactamente lo mismo que la línea de comandos.
- **Presets con nombre**
  - `ai-log`: 360p, 2 fps, sin audio, CRF 34. Pesa un 99% menos y sigue siendo legible para una IA.
  - `ai-log-480`: igual pero a 480p, por si hay texto pequeño en pantalla.
  - `ai-log-fine` / `ai-log-480-fine`: los mismos dos a 5 fps, para acción muy rápida.
  - `human-proxy`: 540p, hasta 30 fps, con audio, para editar o revisar.
  - Guarda los tuyos desde la interfaz (van a `presets.user.json`), edita ese archivo a mano (hay un ejemplo en `presets.user.example.json`) o usa `--preset-file`. Cualquier valor se puede pisar por línea de comandos: `--height`, `--fps`, `--crf`, `--audio/--no-audio`.
- **Reloj quemado** con el tiempo del vídeo ORIGINAL (`hh:mm:ss.mmm`, esquina superior izquierda). Así la IA lee el minuto en pantalla en vez de fiarse del reproductor, y sigue siendo correcto aunque el vídeo vaya troceado.
- **Troceado** (`--chunk 30m`) para vídeos largos: cada trozo conserva el tiempo del original, y el `manifest.json` guarda el inicio y el final de cada uno.
- **Cambios de escena** (`--scenes 0.3`) como candidatos a revisar, en `markers.csv`. Se detectan sobre los proxies ya reducidos (rápido) y tratando los trozos como un solo flujo, así que no se pierden los cambios justo en el corte.
- **Modo carpeta**: acepta archivos y carpetas (con subcarpetas) y respeta la estructura en la salida.
- **Idempotente**: lo ya procesado se salta (mismo archivo, mismo tamaño y fecha, mismos ajustes). Si cambias los ajustes, se reprocesa solo.
- **Los originales no se tocan** nunca. Cada salida se escribe a un archivo temporal y se renombra al terminar, así que un corte a medias no deja vídeos rotos.
- **Plantilla de log** (`log_raw.csv`, solo cabecera) y un **prompt listo** para la IA en `prompts/log-ia.es.md` (en inglés: `prompts/ai-log.en.md`).
- `watch` vigila una carpeta, y `doctor` comprueba que tu ffmpeg trae todo lo necesario.

## 🚀 Uso

**Con la interfaz:** doble clic en `Video Processor.bat` (Windows) o `./start.sh` (macOS/Linux). El navegador se abre en `http://127.0.0.1:8765`. Al cerrar la ventana de la terminal se cierra la app.

**Por línea de comandos:**

```
python video_processor.py serve            # interfaz web (--port N, --no-open)
python video_processor.py doctor
python video_processor.py run RAW/ -o PROXIES/ --preset ai-log --chunk 30m --scenes 0.3
python video_processor.py run RAW/ -o PROXIES/ --dry-run
python video_processor.py watch RAW/ -o PROXIES/ --interval 300
```

Qué sale en `PROXIES/`:

```
cards_0007.ai-log.mp4            (o .part01.mp4, .part02.mp4… si hay troceado)
manifest.json                    todo lo procesado: ajustes, trozos con inicio y final, pesos, errores
markers.csv                      cambios de escena (solo con --scenes)
log_raw.csv                      plantilla vacía del log, con la cabecera
```

Flujo con una IA: procesa con `ai-log`, sube los `.ai-log.mp4` a la IA con el prompt de `prompts/log-ia.es.md`, y guarda el CSV que te devuelva en `log_raw.csv`. Ponle a los vídeos nombres tipo `cards_0007` (sin puntos): ese id es lo que se usa en el log.

### ⏰ Schedule

`run` termina solo y es idempotente, así que se programa tal cual (ajusta las rutas):

- **Windows:** `schtasks /Create /SC HOURLY /TN "Video Processor" /TR "python C:\ruta\video_processor.py run C:\raw -o C:\proxies --settle 120"`
- **Linux/macOS (cron):** `0 * * * * python3 /ruta/video_processor.py run /raw -o /proxies --settle 120`

`--settle 120` salta los archivos modificados hace menos de 2 minutos, por si todavía se están grabando o copiando. Si algún archivo falla, `run` termina con código 1 (y lo reintenta en la pasada siguiente).

## 📋 Requisitos

- Python 3.8 o superior (solo biblioteca estándar; deja la carpeta `web/` junto al script para la interfaz)
- `ffmpeg` y `ffprobe` en el PATH, con `libx264` y el filtro `drawtext`. `python video_processor.py doctor` lo comprueba todo
- Una fuente `.ttf` para el reloj. Se busca sola en Windows, macOS y Linux; si no la encuentra, usa `--font RUTA` (o `--no-timecode`)

## ⚠️ Límites conocidos

- Probado con clips sintéticos; falta probarlo con grabaciones reales de varias horas.
- A 2 fps el reloj avanza de 0,5 s en 0,5 s: es la precisión máxima de cualquier minuto que lea la IA. Compruébalos antes de cortar.
- Los cambios de escena son candidatos, no verdades: una cámara que gira rápido también los dispara.
- Los mensajes de la consola están solo en español por ahora (la interfaz web sí es bilingüe).
- La interfaz web es para una persona en un equipo: no tiene login y solo escucha en `127.0.0.1`. No la expongas a una red.

## 🧪 Pruebas

```
python -m unittest -v
```

Las de integración generan vídeos sintéticos con ffmpeg y se saltan solas si no hay. También cubren el servidor web (token y host, un trabajo completo por la API).

## 📝 Licencia

[MIT](LICENSE) © Meteori-K Media.

---

Hecho con 💜 por Meteori-K Media
