"""Assemble pywhispercpp wheel for Windows ARM64 from pre-built cmake output."""
import argparse
import sys
import zipfile
from pathlib import Path

VERSION = "1.4.1"
PYTHON_TAG = "cp313"
PLATFORM_TAG = "win_arm64"


def build(build_dir: Path, src_dir: Path, out_dir: Path):
    wheel_name = f"pywhispercpp-{VERSION}-{PYTHON_TAG}-{PYTHON_TAG}-{PLATFORM_TAG}.whl"
    wheel_path = out_dir / wheel_name
    dist_info = f"pywhispercpp-{VERSION}.dist-info"

    pyd_files = list(build_dir.rglob("_pywhispercpp*.pyd"))
    if not pyd_files:
        print("ERROR: no _pywhispercpp*.pyd found in build dir")
        sys.exit(1)
    pyd_file = pyd_files[0]
    print(f"Found .pyd: {pyd_file}")

    dll_dir = build_dir / "bin"
    dll_files = list(dll_dir.glob("*.dll")) if dll_dir.exists() else []
    print(f"Found {len(dll_files)} DLLs: {[d.name for d in dll_files]}")

    record_lines = []
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Python package files (skip __init__.py — patched below)
        pkg_dir = src_dir / "pywhispercpp"
        for py_file in pkg_dir.rglob("*.py"):
            if py_file.name == "__init__.py" and py_file.parent == pkg_dir:
                continue
            arc = "pywhispercpp/" + py_file.relative_to(pkg_dir).as_posix()
            zf.write(py_file, arc)
            record_lines.append(f"{arc},,")

        # Patched __init__.py: call os.add_dll_directory so bundled DLLs are found
        init_src = (pkg_dir / "__init__.py").read_text(encoding="utf-8")
        patched_init = (
            "import os as _os, sys as _sys\n"
            "if _sys.platform == 'win32':\n"
            "    _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))\n"
            "    _os.add_dll_directory(_pkg_dir)\n\n"
        ) + init_src
        zf.writestr("pywhispercpp/__init__.py", patched_init)
        record_lines.append("pywhispercpp/__init__.py,,")

        # .pyd in package dir AND at top-level: model.py does `import _pywhispercpp`
        zf.write(pyd_file, f"pywhispercpp/{pyd_file.name}")
        zf.write(pyd_file, pyd_file.name)
        record_lines.append(f"pywhispercpp/{pyd_file.name},,")
        record_lines.append(f"{pyd_file.name},,")

        # DLLs inside package dir (found by add_dll_directory)
        for dll in dll_files:
            arc = f"pywhispercpp/{dll.name}"
            zf.write(dll, arc)
            record_lines.append(f"{arc},,")

        zf.writestr(f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: pywhispercpp\nVersion: {VERSION}\n")
        zf.writestr(f"{dist_info}/WHEEL",
            f"Wheel-Version: 1.0\nGenerator: package_pywhispercpp.py\n"
            f"Root-Is-Purelib: false\nTag: {PYTHON_TAG}-{PYTHON_TAG}-{PLATFORM_TAG}\n")
        record_lines += [f"{dist_info}/METADATA,,", f"{dist_info}/WHEEL,,",
                         f"{dist_info}/RECORD,,"]
        zf.writestr(f"{dist_info}/RECORD", "\n".join(record_lines))

    print(f"\nCreated: {wheel_path}")
    print(f"Size: {wheel_path.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True, help="cmake build directory")
    p.add_argument("--src", required=True, help="pywhispercpp source directory")
    p.add_argument("--out", required=True, help="output directory for wheel")
    args = p.parse_args()
    build(Path(args.build), Path(args.src), Path(args.out))
