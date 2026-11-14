# Changelog

🌐 [English version](CHANGELOG.md) | Español

Todos los cambios importantes del proyecto quedan documentados acá.

## v0.1.0 — Primera versión

- Interfaz web local (`serve`): explorador de carpetas, presets, progreso en vivo, tabla de resultados, español/inglés.
  Solo biblioteca estándar, en `127.0.0.1`, protegida con token por sesión y comprobación de host
- Guardar y borrar presets propios con nombre desde la interfaz (se guardan en `presets.user.json`)
- Lanzadores `Video Processor.bat` y `start.sh`
- Comandos `run` (una pasada, ideal para schedule), `watch`, `doctor` y `presets`
- Presets `ai-log` (360p, 2 fps, sin audio, CRF 34), `ai-log-480` y `human-proxy`; presets propios
  con `presets.user.json` o `--preset-file`, y cualquier valor se puede pisar por línea de comandos
- Reloj quemado con el tiempo del vídeo original, también correcto en vídeos troceados
- Troceado de vídeos largos (`--chunk`) con el inicio y el final de cada trozo en `manifest.json`
- Detección de cambios de escena (`--scenes`) sobre el flujo continuo de proxies, a `markers.csv`
- Modo carpeta recursivo; lo que falla se salta y se cuenta; idempotente; escritura atómica
- Vídeo vertical de móvil (metadato de rotación) con la medida correcta
- Plantilla `log_raw.csv` y prompts para IA en `prompts/log-ia.es.md` y `prompts/ai-log.en.md`
- Pruebas unitarias y de integración con vídeo sintético
- Licencia MIT
