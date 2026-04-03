@echo off
REM Build piper_tts wheel for Windows ARM64.
REM Requires: piper_phonemize wheel already built (step 2).
REM No C++ compilation needed — uses a pure-Python espeakbridge shim.
REM Output: wheels\piper_tts-*.whl

setlocal

set REPO=%~dp0..\..
set WHEELS=%REPO%\wheels

if exist "%REPO%\.venv\Scripts\python.exe" (
    set PYTHON=%REPO%\.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

mkdir "%WHEELS%" 2>nul
"%PYTHON%" "%~dp0package_piper_tts.py" --out "%WHEELS%"

echo.
echo Done. Wheel is in: %WHEELS%
