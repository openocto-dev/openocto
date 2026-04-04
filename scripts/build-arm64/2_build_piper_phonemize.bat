@echo off
REM Build piper_phonemize wheel for Windows ARM64.
REM Requires: VS 2022 Build Tools with ARM64 component, CMake.
REM
REM Step 1: cmake build (espeak-ng + onnxruntime download)
REM Step 2: Python extension build (MSVC ARM64)
REM Output: wheels\piper_phonemize-*.whl

setlocal

set REPO=%~dp0..\..
set WHEELS=%REPO%\wheels
set SRC=C:\src\piper-phonemize
set BUILD=C:\src\build_piper_phonemize

if exist "%REPO%\.venv\Scripts\python.exe" (
    set PYTHON=%REPO%\.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" arm64
if errorlevel 1 (
    echo FAILED: could not init VS ARM64 build tools.
    exit /b 1
)

set TEMP=C:\tmp
set TMP=C:\tmp
if not exist C:\tmp mkdir C:\tmp

set MSYSTEM=
set ANTHROPIC_API_KEY=
set CLAUDE_CODE_OAUTH_TOKEN=
set SETUPTOOLS_SCM_PRETEND_VERSION=1.2.0

REM Add rc.exe to PATH (needed by link.exe on ARM64)
set PATH=C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\arm64;%PATH%

if not exist "%SRC%" (
    echo Cloning piper-phonemize...
    git clone https://github.com/rhasspy/piper-phonemize "%SRC%"
)

echo.
echo === Patching CMakeLists.txt: win-x64 to win-arm64 ===
powershell -Command "(Get-Content '%SRC%\CMakeLists.txt') -replace 'onnxruntime-win-x64-', 'onnxruntime-win-arm64-' | Set-Content '%SRC%\CMakeLists.txt'"

echo.
echo === Step 1: cmake (builds espeak-ng, downloads onnxruntime) ===
if exist "%BUILD%" rmdir /s /q "%BUILD%"
mkdir "%BUILD%"

"C:\Program Files\CMake\bin\cmake.exe" "%SRC%" -B "%BUILD%" ^
    -G "Visual Studio 17 2022" ^
    -A ARM64 ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DPython3_EXECUTABLE="%PYTHON%" ^
    -DPython3_FIND_REGISTRY=NEVER ^
    -DPython3_FIND_STRATEGY=LOCATION ^
    -DCMAKE_INSTALL_PREFIX="%BUILD%\install"
if errorlevel 1 ( echo CMake configure FAILED & exit /b 1 )

"C:\Program Files\CMake\bin\cmake.exe" --build "%BUILD%" --config Release --parallel
if errorlevel 1 ( echo CMake build FAILED & exit /b 1 )

echo.
echo === Step 2: Python extension + wheel ===
"%PYTHON%" -m pip install pybind11 wheel --quiet
mkdir "%WHEELS%" 2>nul
"%PYTHON%" "%~dp0package_piper_phonemize.py" --build "%BUILD%" --src "%SRC%" --out "%WHEELS%"

echo.
echo Done. Wheel is in: %WHEELS%
