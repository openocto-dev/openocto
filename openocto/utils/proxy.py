"""Auto-start and manage claude-max-proxy for Claude subscription users."""

from __future__ import annotations

import atexit
import logging
import shutil
import subprocess
import time

import requests

logger = logging.getLogger(__name__)

PROXY_URL = "http://localhost:3456/v1"
STARTUP_TIMEOUT = 15  # seconds


def is_proxy_running() -> bool:
    """Check if claude-max-proxy is already responding."""
    try:
        r = requests.get(f"{PROXY_URL}/models", timeout=2)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


def start_proxy() -> subprocess.Popen | None:
    """Start claude-max-proxy in the background. Returns the process, or None on failure."""
    if not shutil.which("claude-max-api"):
        logger.warning("claude-max-api not found — install with: npm install -g claude-max-api-proxy")
        return None

    logger.info("Starting claude-max-api-proxy...")
    proc = subprocess.Popen(
        ["claude-max-api"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
