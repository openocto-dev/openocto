"""
Assemble piper_phonemize wheel for Windows ARM64.

Builds the Python extension from source using setup_arm64.py, then repacks
the wheel to bundle espeak-ng.dll, onnxruntime.dll and patches __init__.py
to call os.add_dll_directory() so the DLLs are found at runtime.
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

VERSION = "1.2.0"
PYTHON_TAG = "cp313"
PLATFORM_TAG = "win_arm64"


SETUP_ARM64 = """\
\"\"\"ARM64 Windows build of piper-phonemize.\"\"\"
from pathlib import Path
from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

_DIR = Path(__file__).parent

__version__ = "{version}"

ext_modules = [
    Pybind11Extension(
        "piper_phonemize_cpp",
        [
            "src/python.cpp",
            "src/phonemize.cpp",
            "src/phoneme_ids.cpp",
            "src/tashkeel.cpp",
        ],
        define_macros=[("VERSION_INFO", __version__)],
        include_dirs=[
            r"{espeak_include}",
            r"{onnx_include}",
        ],
        library_dirs=[
            r"{espeak_lib}",
            r"{onnx_lib}",
        ],
        libraries=["espeak-ng", "onnxruntime"],
        extra_compile_args=["/utf-8"],
        extra_link_args=["/MANIFEST:NO"],
    ),
]

setup(
    name="piper_phonemize",
    version=__version__,
    packages=["piper_phonemize"],
    package_data={{
        "piper_phonemize": (
            [str(p.relative_to(_DIR)) for p in (_DIR / "piper_phonemize" / "espeak-ng-data").rglob("*")]
            + ["libtashkeel_model.ort"]
        )
    }},
    include_package_data=True,
    ext_modules=ext_modules,
    cmdclass={{"build_ext": build_ext}},
    zip_safe=False,
    python_requires=">=3.7",
)
"""

DLL_INIT_PATCH = """\
import os as _os, sys as _sys
if _sys.platform == 'win32':
    _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
    _os.add_dll_directory(_pkg_dir)

"""


def build(build_dir: Path, src_dir: Path, out_dir: Path, python: str):
    espeak_dir = build_dir / "ei"
    onnx_dir = next(src_dir.glob("lib/onnxruntime-win-arm64-*"), None)
    if onnx_dir is None:
        print("ERROR: onnxruntime dir not found in src/lib/. Run cmake step first.")
        sys.exit(1)

    # Write setup_arm64.py into the source tree
    setup_path = src_dir / "setup_arm64.py"
    setup_path.write_text(
        SETUP_ARM64.format(
            version=VERSION,
            espeak_include=espeak_dir / "include",
            espeak_lib=espeak_dir / "lib",
            onnx_include=onnx_dir / "include",
            onnx_lib=onnx_dir / "lib",
        ),
        encoding="utf-8",
    )
    print(f"Written: {setup_path}")

    env = os.environ.copy()
    env["SETUPTOOLS_SCM_PRETEND_VERSION"] = VERSION
    env["MSYSTEM"] = ""

    print("\n=== Building Python extension ===")
    result = subprocess.run(
        [python, "setup_arm64.py", "bdist_wheel", "--dist-dir", str(out_dir)],
        cwd=src_dir,
        env=env,
    )
    if result.returncode != 0:
        print("ERROR: bdist_wheel failed")
        sys.exit(1)

    # Find the built wheel
    wheels = list(out_dir.glob(f"piper_phonemize-{VERSION}-*.whl"))
    if not wheels:
        print("ERROR: wheel not found after build")
        sys.exit(1)
    src_wheel = wheels[0]

    # DLLs to bundle
    dlls = [
        espeak_dir / "bin" / "espeak-ng.dll",
        onnx_dir / "lib" / "onnxruntime.dll",
        onnx_dir / "lib" / "onnxruntime_providers_shared.dll",
    ]
    missing = [d for d in dlls if not d.exists()]
    if missing:
        print(f"WARNING: DLLs not found: {missing}")
        dlls = [d for d in dlls if d.exists()]

    out_wheel = out_dir / src_wheel.name.replace(".whl", "_bundled.whl")

    print("\n=== Repacking wheel with bundled DLLs ===")
    with zipfile.ZipFile(src_wheel, "r") as src, \
         zipfile.ZipFile(out_wheel, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "piper_phonemize/__init__.py":
                data = DLL_INIT_PATCH.encode() + data
                print(f"  Patched: {item.filename}")
            out.writestr(item, data)
        for dll in dlls:
            arc = f"piper_phonemize/{dll.name}"
            out.write(dll, arc)
            print(f"  Added: {arc} ({dll.stat().st_size // 1024} KB)")

    src_wheel.unlink()
    out_wheel.rename(src_wheel)
    print(f"\nCreated: {src_wheel}")
    print(f"Size: {src_wheel.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True, help="cmake build dir (contains ei/ subdir)")
    p.add_argument("--src", required=True, help="piper-phonemize source directory")
    p.add_argument("--out", required=True, help="output directory for wheel")
    p.add_argument("--python", default=sys.executable, help="python interpreter")
    args = p.parse_args()
    build(Path(args.build), Path(args.src), Path(args.out), args.python)
