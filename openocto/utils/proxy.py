"""Auto-start and manage claude-max-proxy for Claude subscription users."""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import subprocess
import time

import requests

logger = logging.getLogger(__name__)

PROXY_URL = "http://localhost:3456/v1"
STARTUP_TIMEOUT = 15  # seconds

# Common directories where node/npm binaries live (Homebrew, nvm, volta, npm on Windows)
_EXTRA_PATH_DIRS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    os.path.expanduser("~/.volta/bin"),
    os.path.join(os.environ.get("APPDATA", ""), "npm"),  # Windows npm global
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "npm"),  # Windows alt
]

_PATH_SEP = ";" if os.name == "nt" else ":"


def _enriched_env() -> dict[str, str]:
    """Return a copy of os.environ with common Node.js directories on PATH."""
    env = os.environ.copy()
    current = env.get("PATH", "")
    dirs_to_add = [d for d in _EXTRA_PATH_DIRS if d and d not in current and os.path.isdir(d)]

    # Explicitly find where claude lives and ensure that dir is on PATH.
    # On Windows, 'claude' is a .cmd script; Node.js child_process.spawn with
    # shell:false won't find it unless its directory is explicitly in PATH.
    claude_exe = shutil.which("claude")
    if claude_exe:
        claude_dir = os.path.dirname(claude_exe)
        if claude_dir not in current:
            dirs_to_add.insert(0, claude_dir)

    if dirs_to_add:
        env["PATH"] = _PATH_SEP.join(dirs_to_add) + _PATH_SEP + current
    return env


def is_proxy_running() -> bool:
    """Check if claude-max-proxy is already responding."""
    try:
        r = requests.get(f"{PROXY_URL}/models", timeout=2)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


def start_proxy() -> subprocess.Popen | None:
    """Start claude-max-proxy in the background. Returns the process, or None on failure."""
    env = _enriched_env()
    cmd = shutil.which("claude-max-api", path=env.get("PATH"))
    if not cmd:
        logger.warning("claude-max-api not found — install with: npm install -g claude-max-api-proxy")
        return None

    logger.info("Starting claude-max-api-proxy...")
    log_path = os.path.join(os.path.expanduser("~"), ".openocto", "proxy.log")
    log_file = open(log_path, "w")  # noqa: SIM115
    proc = subprocess.Popen(
        [cmd],
        stdout=log_file,
        stderr=log_file,
        env=env,
    )

    # Wait for the proxy to become responsive
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            logger.error("claude-max-proxy exited with code %d", proc.returncode)
            return None
        if is_proxy_running():
            logger.info("claude-max-proxy is ready")
            atexit.register(_stop_proxy, proc)
            return proc
        time.sleep(0.5)

    # Timed out
    proc.terminate()
    logger.error("claude-max-proxy did not start within %ds", STARTUP_TIMEOUT)
    return None


def _stop_proxy(proc: subprocess.Popen) -> None:
    """Terminate the proxy process on exit."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        logger.info("claude-max-proxy stopped")


def ensure_proxy() -> bool:
    """Make sure claude-max-proxy is running. Returns True if ready."""
    if is_proxy_running():
        return True
    proc = start_proxy()
    return proc is not None
