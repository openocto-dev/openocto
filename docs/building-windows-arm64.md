# Building native wheels for Windows ARM64

OpenOcto uses `pywhispercpp` (STT) and `piper-tts` (TTS) which have no prebuilt
wheels for `win_arm64`. This guide explains how to build them locally and publish
to GitHub Releases so the installer can download them.

---

## Prerequisites

Install once:

```powershell
# C++ compiler with ARM64 support
winget install Microsoft.VisualStudio.2022.BuildTools `
    --override "--add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.Tools.ARM64 --includeRecommended --passive"

# CMake
winget install Kitware.CMake

# Clang/LLVM (required by whisper.cpp — MSVC not supported for ARM)
winget install LLVM.LLVM

# Enable long paths (run as admin)
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
    -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

---

## pywhispercpp

### Why not `pip wheel pywhispercpp`?

Several issues make the standard pip build fail on win_arm64:
- pip bundles its own x64 cmake which cannot detect ARM64 Python
- `MSYSTEM=CLANGARM64` (set by Git for Windows) confuses CMake's FindPython
- whisper.cpp explicitly rejects MSVC for ARM: "use clang"
- The resulting `.dll` links against `libomp140.aarch64.dll` which has no
  redistributable runtime on Windows ARM64

### Solution: manual cmake + Ninja + Clang

```bat
@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" arm64

set MSYSTEM=
set ANTHROPIC_API_KEY=
set CLAUDE_CODE_OAUTH_TOKEN=

set PATH=C:\Program Files\LLVM\bin;%PATH%

git clone --recurse-submodules https://github.com/abdeladim-s/pywhispercpp C:\src\pywhispercpp

cmake C:\src\pywhispercpp -B C:\src\build_arm64 ^
    -G Ninja ^
    -DCMAKE_C_COMPILER="C:\Program Files\LLVM\bin\clang.exe" ^
    -DCMAKE_CXX_COMPILER="C:\Program Files\LLVM\bin\clang++.exe" ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DPython3_EXECUTABLE="<venv>\Scripts\python.exe" ^
    -DPython3_FIND_REGISTRY=NEVER ^
    -DPython3_FIND_STRATEGY=LOCATION ^
    -DPYBIND11_FINDPYTHON=NEW ^
    -DGGML_CCACHE=OFF ^
    -DGGML_OPENMP=OFF

cmake --build C:\src\build_arm64 --parallel
```

Key flags:
- `-DGGML_OPENMP=OFF` — avoids runtime dependency on `libomp140.aarch64.dll`
- `-DMSYSTEM=` (cleared) — prevents CMake FindPython from seeing wrong arch
- `Ninja` generator — required because MSVC generator rejects ARM clang

### Packaging the wheel

pip's `bdist_wheel` re-triggers cmake and fails. Use `scripts/package_pywhispercpp.py`:

```python
# Creates pywhispercpp-1.4.1-cp313-cp313-win_arm64.whl containing:
#   - _pywhispercpp.cp313-win_arm64.pyd  (in package dir AND at top-level)
#   - whisper.dll, ggml.dll, ggml-base.dll, ggml-cpu.dll
#   - patched __init__.py with os.add_dll_directory() for Windows
```

The `.pyd` must be present at top-level site-packages because `model.py` does
`import _pywhispercpp` (not a relative import). The patched `__init__.py` calls
`os.add_dll_directory(pkg_dir)` so the bundled DLLs are found.

---

## piper-tts (piper-phonemize + piper_tts)

`piper-tts 1.4.2` uses `scikit-build` and has a C++ extension (`espeakbridge`)
that is missing from the PyPI wheel. It must be built from the GitHub source.

### piper-phonemize (espeak-ng + onnxruntime wrapper)

`piper-phonemize` is a pybind11 C++ extension that wraps espeak-ng and
onnxruntime. The PyPI wheel is Linux-only; for ARM64 Windows we build from source.

```bat
@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" arm64

set TEMP=C:\tmp
set TMP=C:\tmp
set MSYSTEM=
set ANTHROPIC_API_KEY=
set CLAUDE_CODE_OAUTH_TOKEN=

set CMAKE=C:\Program Files\CMake\bin\cmake.exe
set SRC=C:\src\piper-phonemize
set BUILD=C:\src\build_piper_phonemize
set PYTHON=<venv>\Scripts\python.exe

git clone https://github.com/rhasspy/piper-phonemize %SRC%

REM Patch onnxruntime download: win-x64 -> win-arm64
powershell -Command "(Get-Content '%SRC%\CMakeLists.txt') -replace 'onnxruntime-win-x64-', 'onnxruntime-win-arm64-' | Set-Content '%SRC%\CMakeLists.txt'"

"%CMAKE%" "%SRC%" -B "%BUILD%" -G "Visual Studio 17 2022" -A ARM64 ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DPython3_EXECUTABLE="%PYTHON%" ^
    -DPython3_FIND_REGISTRY=NEVER -DPython3_FIND_STRATEGY=LOCATION
"%CMAKE%" --build "%BUILD%" --config Release --parallel
```

Then build the Python extension using `setup_arm64.py` (see
`C:\src\piper-phonemize\setup_arm64.py`), which uses:
- `/utf-8` compile flag (required for IPA constants on MSVC)
- `/MANIFEST:NO` link flag (skips rc.exe which is missing on ARM64)

Repack the wheel with `C:\src\package_piper_phonemize.py` to bundle the DLLs
and patch `__init__.py` with `os.add_dll_directory()`.

### piper-tts (espeakbridge shim)

`piper-tts 1.4.2` from PyPI is missing its compiled `espeakbridge.pyd`
extension. Rather than building it (requires cmake + scikit-build), we provide
a **pure-Python shim** that delegates to `piper_phonemize_cpp`:

The shim is bundled in our custom `piper_tts-1.4.2-cp313-cp313-win_arm64.whl`
built by `C:\src\package_piper_tts.py`. It implements the same interface:

```python
def initialize(data_dir: str) -> None: ...
def set_voice(voice: str) -> None: ...
def get_phonemes(text: str) -> list[tuple[str, str, bool]]: ...
```

The shim uses `piper_phonemize._phonemize_espeak()` internally and falls back
to `piper_phonemize`'s bundled `espeak-ng-data` if the piper package's copy
is not found.

**Testing TTS locally:**

```python
import wave
from piper import PiperVoice

voice = PiperVoice.load("en_US-lessac-medium.onnx")
with wave.open("output.wav", "w") as f:
    voice.synthesize_wav("Hello, I am Octo.", f)
```

Download voice models from: https://huggingface.co/rhasspy/piper-voices

---

## Publishing to GitHub Releases

Once wheels are built, upload all three:

```powershell
gh release create wheels-arm64-v1 `
    wheels/piper_phonemize-1.2.0-cp313-cp313-win_arm64.whl `
    wheels/piper_tts-1.4.2-cp313-cp313-win_arm64.whl `
    wheels/pywhispercpp-1.4.1-cp313-cp313-win_arm64.whl `
    --title "Windows ARM64 prebuilt wheels" `
    --notes "Prebuilt wheels for win_arm64 (Python 3.13). Used by install.ps1."
```

The installer (`install.ps1`) downloads these automatically on ARM64 Windows.

---

## Runtime issues on Windows ARM64

### claude-max-api-proxy: UTF-8 broken via cmd.exe

`claude-max-api-proxy` uses `spawn("claude", args)` to call Claude CLI.
On Windows, `claude` is a `.cmd` shim and Node.js `spawn()` can't execute
`.cmd` files without `shell:true`. The initial fix wrapped it with
`cmd.exe /c claude`, but **cmd.exe converts UTF-8 arguments to the local
codepage** (cp866/cp1251), destroying Cyrillic and other non-ASCII text.

**Fix:** `proxy.py` auto-patches `manager.js` on first run. Instead of
`cmd.exe /c claude`, it spawns `node.exe` directly with the cli.js path:

```javascript
// Before (broken UTF-8):
spawn("cmd.exe", ["/c", "claude", ...args])

// After (preserves UTF-8):
const cliJs = process.env.APPDATA + "\\npm\\node_modules\\@anthropic-ai\\claude-code\\cli.js";
spawn(process.execPath, [cliJs, ...args])  // process.execPath = node.exe
```

### Silero VAD unreliable on ARM64 onnxruntime

Silero VAD v5 produces near-zero speech probabilities on ARM64 onnxruntime
(0.001-0.004 even on loud speech). This is likely an onnxruntime ARM64 issue.

**Fix:** `SileroVAD.is_speech()` uses **raw RMS** (before mic gain) as a
fallback: `prob > threshold OR rms_raw > rms_speech_threshold`. The calibration
wizard measures raw RMS levels and sets the threshold between silence and speech.

### High noise floor in VMs (UTM, Parallels)

Virtual machines often have a high noise floor on the emulated microphone
(raw RMS 100-200 during silence vs 10-20 on bare metal). The calibration
wizard accounts for this by setting `rms_speech_threshold` at 60% between
measured silence and speech RMS levels.

### AudioCapture mic_gain

`mic_gain` is applied in the audio callback before data reaches VAD and the
recording buffer. This ensures both wake word detection and whisper
transcription see the amplified signal. The `mic_gain` value is stored in
`~/.openocto/config.yaml` under `vad.mic_gain` and set by the calibration
wizard (`openocto setup --from-step 6`).
