@echo off
setlocal ENABLEDELAYEDEXPANSION

REM Create virtual environment (optional)
REM python -m venv .venv
REM call .venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt

REM Clean previous build
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist app.spec del /q app.spec

REM Optional: If you want to bundle ffmpeg.exe and ffprobe.exe, copy them into .\bin first
REM md bin 2>nul
REM copy C:\path\to\ffmpeg.exe bin\ffmpeg.exe
REM copy C:\path\to\ffprobe.exe bin\ffprobe.exe

REM Build single-file exe
pyinstaller ^
 --name video_slicer ^
 --onefile ^
 --noconsole ^
 --add-data "README.md;." ^
 --add-data "requirements.txt;." ^
 app.py

REM If you bundled ffmpeg, also add them via --add-binary, like:
REM --add-binary "bin/ffmpeg.exe;." --add-binary "bin/ffprobe.exe;."

if %ERRORLEVEL% NEQ 0 (
  echo Build failed.
  exit /b %ERRORLEVEL%
)

echo Build completed. Find your exe in .\dist\video_slicer.exe
endlocal
