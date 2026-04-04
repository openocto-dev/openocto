@echo off
REM Build pywhispercpp wheel for Windows ARM64.
REM Requires: LLVM, CMake, VS 2022 Build Tools with ARM64 component, Ninja.
REM
REM Usage: run from repo root or any directory.
REM Output: wheels\pywhispercpp-*.whl

setlocal

set REPO=%~dp0..\..
set WHEELS=%REPO%\wheels
set SRC=C:\src\pywhispercpp
set BUILD=C:\src\build_pywhispercpp_arm64

REM Use the repo venv if it exists, otherwise fall back to system python
if exist "%REPO%\.venv\Scripts\python.exe" (
    set PYTHON=%REPO%\.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" arm64
if errorlevel 1 (
    echo FAILED: could not init VS ARM64 build tools.
    echo Install: winget install Microsoft.VisualStudio.2022.BuildTools
    exit /b 1
)

REM Short temp path avoids MAX_PATH issues
set TEMP=C:\tmp
set TMP=C:\tmp
if not exist C:\tmp mkdir C:\tmp

REM Clear env vars that pywhispercpp setup.py leaks into cmake -D flags
set MSYSTEM=
set ANTHROPIC_API_KEY=
set CLAUDE_CODE_OAUTH_TOKEN=
set ANTHROPIC_BASE_URL=

set PATH=C:\Program Files\LLVM\bin;%PATH%

if not exist "%SRC%" (
    echo Cloning pywhispercpp...
    git clone --recurse-submodules https://github.com/abdeladim-s/pywhispercpp "%SRC%"
)

echo.
echo === Configuring (Clang + Ninja, no OpenMP) ===
if exist "%BUILD%" rmdir /s /q "%BUILD%"
mkdir "%BUILD%"

"C:\Program Files\CMake\bin\cmake.exe" "%SRC%" -B "%BUILD%" ^
    -G Ninja ^
    -DCMAKE_C_COMPILER="C:\Program Files\LLVM\bin\clang.exe" ^
    -DCMAKE_CXX_COMPILER="C:\Program Files\LLVM\bin\clang++.exe" ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DPython3_EXECUTABLE="%PYTHON%" ^
    -DPython3_FIND_REGISTRY=NEVER ^
    -DPython3_FIND_STRATEGY=LOCATION ^
    -DPYBIND11_FINDPYTHON=NEW ^
    -DGGML_CCACHE=OFF ^
    -DGGML_OPENMP=OFF
if errorlevel 1 ( echo CMake configure FAILED & exit /b 1 )

echo.
echo === Building ===
"C:\Program Files\CMake\bin\cmake.exe" --build "%BUILD%" --config Release --parallel
if errorlevel 1 ( echo CMake build FAILED & exit /b 1 )

echo.
echo === Packaging wheel ===
mkdir "%WHEELS%" 2>nul
"%PYTHON%" "%~dp0package_pywhispercpp.py" --build "%BUILD%" --src "%SRC%" --out "%WHEELS%"

echo.
echo Done. Wheel is in: %WHEELS%
