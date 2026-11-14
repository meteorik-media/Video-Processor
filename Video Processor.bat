@echo off
cd /d "%~dp0"
where python >nul 2>nul && (python video_processor.py serve) || (py video_processor.py serve)
if errorlevel 1 pause
