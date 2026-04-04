"""Platform-aware icons and symbols.

On macOS / Linux the console handles emoji natively.
On Windows the legacy codepage (cp1251, cp866, etc.) cannot encode them,
so we fall back to plain ASCII equivalents.
"""

from __future__ import annotations

import sys


def _can_use_emoji() -> bool:
    """Return True when stdout can render emoji without errors."""
    if sys.platform != "win32":
        return True
    # Windows with UTF-8 mode (PYTHONIOENCODING=utf-8 or -X utf8)
    enc = getattr(sys.stdout, "encoding", "") or ""
    return enc.lower().replace("-", "") in ("utf8", "utf_8")


EMOJI = _can_use_emoji()

# ── Status ────────────────────────────────────────────────────────
OK = "\u2713" if EMOJI else "[OK]"           # ✓
FAIL = "\u2717" if EMOJI else "[FAIL]"       # ✗
WARN = "\u26a0\ufe0f" if EMOJI else "[!!]"   # ⚠️
CHECK = "\u2705" if EMOJI else "[v]"         # ✅
CROSS = "\u274c" if EMOJI else "[x]"         # ❌
STAR = "\u2b50" if EMOJI else "*"            # ⭐

# ── UI / Actions ──────────────────────────────────────────────────
MIC = "\U0001f3a4" if EMOJI else "[mic]"     # 🎤
MIC2 = "\U0001f399\ufe0f" if EMOJI else "[mic]"  # 🎙️
WRENCH = "\U0001f527" if EMOJI else "[~]"    # 🔧
PLUG = "\U0001f50c" if EMOJI else "[>]"      # 🔌
USER = "\U0001f464" if EMOJI else "[user]"   # 👤
GLOBE = "\U0001f310" if EMOJI else "[w]"     # 🌐
BULB = "\U0001f4a1" if EMOJI else "[i]"      # 💡
MUTE = "\U0001f507" if EMOJI else "[mute]"   # 🔇
REC = "\U0001f534" if EMOJI else "[REC]"     # 🔴
BOLT = "\u26a1" if EMOJI else "[!]"          # ⚡
DOWN = "\u2b07\ufe0f" if EMOJI else "[v]"    # ⬇️
OCTOPUS = "\U0001f419" if EMOJI else "[*]"   # 🐙

# ── Flags ─────────────────────────────────────────────────────────
FLAG_US = "\U0001f1fa\U0001f1f8" if EMOJI else "[US]"  # 🇺🇸
FLAG_RU = "\U0001f1f7\U0001f1fa" if EMOJI else "[RU]"  # 🇷🇺
