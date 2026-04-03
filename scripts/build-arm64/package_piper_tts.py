"""
Build a custom piper-tts wheel for Windows ARM64.

Takes the official piper-tts sdist, replaces the skbuild setup.py with
regular setuptools, and injects our pure-Python espeakbridge shim that
delegates to piper_phonemize_cpp (pre-built for ARM64).
"""
import hashlib
import base64
import os
import re
import sys
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

import argparse as _argparse
_p = _argparse.ArgumentParser()
_p.add_argument("--out", default=str(Path(__file__).parent.parent.parent / "wheels"),
                help="output directory for wheel")
_args, _ = _p.parse_known_args()

WHEELS_DIR = Path(_args.out)
SDIST = WHEELS_DIR / "piper_tts-1.4.2.tar.gz"
OUT_WHEEL = WHEELS_DIR / "piper_tts-1.4.2-cp313-cp313-win_arm64.whl"

ESPEAKBRIDGE_PY = """\
\"\"\"
Pure-Python espeakbridge shim for Windows ARM64.

The real espeakbridge is a C++ extension built via scikit-build (piper1-gpl).
On Windows ARM64, we instead use piper_phonemize_cpp which wraps the same
espeak-ng library and provides an equivalent phonemization API.
\"\"\"

import os as _os
from pathlib import Path as _Path


def _get_piper_phonemize_data_dir() -> str:
    try:
        import piper_phonemize
        return str(_Path(piper_phonemize._DIR) / "espeak-ng-data")
    except Exception:
        return ""


_data_dir: str = ""
_voice: str = "en-us"


def initialize(data_dir: str) -> None:
    \"\"\"Initialize espeak-ng with data directory.\"\"\"
    global _data_dir
    if not data_dir or not _os.path.isdir(data_dir):
        data_dir = _get_piper_phonemize_data_dir()
    _data_dir = data_dir


def set_voice(voice: str) -> None:
    \"\"\"Set the espeak-ng voice by name.\"\"\"
    global _voice
    _voice = voice


def get_phonemes(text: str) -> list:
    \"\"\"
    Convert input text to a list of (phonemes, terminator, end_of_sentence) tuples.

    Returns:
        A list where each item is:
            phonemes: str - IPA phonemes for a clause
            terminator: str - punctuation mark indicating clause type
            end_of_sentence: bool - True if the clause ends a sentence
    \"\"\"
    from piper_phonemize import _phonemize_espeak

    data = _data_dir
    if not data:
        data = _get_piper_phonemize_data_dir()

    sentences = _phonemize_espeak(text, _voice, data)
    result = []
    for sentence in sentences:
        phonemes_str = "".join(sentence)
        # piper_phonemize includes terminal punctuation in the phoneme sequence,
        # so use empty terminator to avoid doubling it.
        result.append((phonemes_str, "", True))
    return result
"""

# Files to include from sdist (relative paths inside piper_tts-1.4.2/src/)
# We collect everything from src/piper/ plus the entry point script

def record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).decode().rstrip("=")


def build_wheel():
    version = "1.4.2"
    tag = "cp313-cp313-win_arm64"
    dist_name = f"piper_tts-{version}"
    wheel_name = f"{dist_name}-{tag}.whl"

    records = []  # (arcname, hash, size)

    with tarfile.open(SDIST, "r:gz") as sdist:
        with zipfile.ZipFile(OUT_WHEEL, "w", zipfile.ZIP_DEFLATED) as whl:

            def add_bytes(arcname: str, data: bytes):
                whl.writestr(arcname, data)
                records.append((arcname, record_hash(data), len(data)))

            # Collect files from src/piper/ in the sdist
            prefix = f"piper_tts-{version}/src/"
            for member in sdist.getmembers():
                if not member.isfile():
                    continue
                name = member.name
                if not name.startswith(prefix):
                    continue

                rel = name[len(prefix):]  # e.g. "piper/__init__.py"

                # Skip egg-info, train subpackage (heavy, not needed for runtime)
                if rel.startswith("piper_tts.egg-info"):
                    continue

                # Skip the .pyi stub — we'll add the real .py
                if rel == "piper/espeakbridge.pyi":
                    continue

                data = sdist.extractfile(member).read()
                add_bytes(rel, data)

            # Add our espeakbridge.py shim
            add_bytes("piper/espeakbridge.py", ESPEAKBRIDGE_PY.encode())

            # Write dist-info
            dist_info = f"piper_tts-{version}.dist-info"

            wheel_meta = "\n".join([
                "Wheel-Version: 1.0",
                "Generator: package_piper_tts.py",
                f"Root-Is-Purelib: false",
                f"Tag: {tag}",
                "",
            ])
            add_bytes(f"{dist_info}/WHEEL", wheel_meta.encode())

            metadata = f"Metadata-Version: 2.1\nName: piper-tts\nVersion: {version}\n"
            add_bytes(f"{dist_info}/METADATA", metadata.encode())

            top_level = "piper\n"
            add_bytes(f"{dist_info}/top_level.txt", top_level.encode())

            entry_points = "[console_scripts]\npiper = piper.__main__:main\n"
            add_bytes(f"{dist_info}/entry_points.txt", entry_points.encode())

            # RECORD
            record_lines = [f"{arc},{h},{s}" for arc, h, s in records]
            record_lines.append(f"{dist_info}/RECORD,,")
            record_data = "\n".join(record_lines) + "\n"
            whl.writestr(f"{dist_info}/RECORD", record_data)

    size_mb = OUT_WHEEL.stat().st_size / 1024 / 1024
    print(f"Written: {OUT_WHEEL}")
    print(f"Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    build_wheel()
