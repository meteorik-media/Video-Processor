# Changelog

🌐 [English version](CHANGELOG.md) | Español

Todos los cambios importantes del proyecto quedan documentados acá.

## v0.2.0 — Frames y ensamblar

- Comando nuevo `assemble` (y un interruptor **Ensamblar** en la interfaz web): rearma un vídeo desde carpetas de frames
  o `.zip` en MP4, WebM o GIF. Si los frames los sacó esta herramienta, el FPS y (con `--audio`) el audio del original
  salen de `manifest.json`, así que ir de frames a vídeo no pide ningún ajuste a mano
- Comando nuevo `frames` (y un interruptor **Frames** en la interfaz web): saca un frame cada 1/fps segundos
  (24 por defecto) de cada vídeo en PNG o JPG, en una carpeta `nombre.frames/` o un `.zip` por vídeo (`--zip`),
  con reducción opcional (`--height`). Viene de la pestaña «Video (frames)» de Image Processor, pero sobre ffmpeg
  nativo (rápido, resolución original, sin límites del navegador). Es idempotente y anota cada salida en `manifest.json`

## v0.1.0 — Primera versión

- Interfaz web local (`serve`): explorador de carpetas, presets, progreso en vivo, tabla de resultados, español/inglés.
  Solo biblioteca estándar, en `127.0.0.1`, protegida con token por sesión y comprobación de host
- Guardar y borrar presets propios con nombre desde la interfaz (se guardan en `presets.user.json`)
- Lanzadores `Video Processor.bat` y `start.sh`
- Comandos `run` (una pasada, ideal para schedule), `watch`, `doctor` y `presets`
- Presets `ai-log` (360p, 2 fps, sin audio, CRF 34), `ai-log-480`, `ai-log-fine` / `ai-log-480-fine` (5 fps) y `human-proxy`; presets propios
  con `presets.user.json` o `--preset-file`, y cualquier valor se puede pisar por línea de comandos
- Reloj quemado con el tiempo del vídeo original, también correcto en vídeos troceados
- Troceado de vídeos largos (`--chunk`) con el inicio y el final de cada trozo en `manifest.json`
- Detección de cambios de escena (`--scenes`) sobre el flujo continuo de proxies, a `markers.csv`
- Modo carpeta recursivo; lo que falla se salta y se cuenta; idempotente; escritura atómica
- Vídeo vertical de móvil (metadato de rotación) con la medida correcta
- Plantilla `log_raw.csv` y prompts para IA en `prompts/log-ia.es.md` y `prompts/ai-log.en.md`
- Pruebas unitarias y de integración con vídeo sintético
- Licencia MIT
