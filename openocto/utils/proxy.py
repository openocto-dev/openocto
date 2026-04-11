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


def _patch_proxy_for_windows() -> None:
    """
    Patch claude-max-api-proxy's manager.js for Windows.

    Two issues on Windows:
    1. Node.js spawn() cannot execute .cmd files without shell:true
    2. cmd.exe mangles UTF-8 arguments (Cyrillic, CJK, etc.)

    The fix bypasses cmd.exe entirely: instead of spawning "claude" (a .cmd shim),
    we spawn node.exe directly with the claude-code cli.js script path.
    """
    if os.name != "nt":
        return
    manager_js = os.path.join(
        os.environ.get("APPDATA", ""),
        "npm", "node_modules", "claude-max-api-proxy",
        "dist", "subprocess", "manager.js",
    )
    if not os.path.isfile(manager_js):
        return
    with open(manager_js, encoding="utf-8") as f:
        content = f.read()
    if "_spawnCmd" in content:
        return  # already patched

    # Patch 1: start() — spawn node.exe with cli.js directly (preserves UTF-8)
    patched = content.replace(
        'this.process = spawn("claude", args, {',
        '// Windows: bypass cmd.exe to preserve UTF-8 in arguments\n'
        '                let _spawnCmd = "claude";\n'
        '                let _spawnArgs = args;\n'
        '                if (process.platform === "win32") {\n'
        '                    const npmDir = process.env.APPDATA ? process.env.APPDATA + "\\\\npm" : "";\n'
        '                    const cliJs = npmDir + "\\\\node_modules\\\\@anthropic-ai\\\\claude-code\\\\cli.js";\n'
        '                    _spawnCmd = process.execPath;\n'
        '                    _spawnArgs = [cliJs, ...args];\n'
        '                }\n'
        '                this.process = spawn(_spawnCmd, _spawnArgs, {',
    )
    # Patch 2: verifyClaude() — same approach for version check
    patched = patched.replace(
        'const proc = spawn("claude", ["--version"], { stdio: "pipe" });',
        'const _vCmd = process.platform === "win32" ? process.execPath : "claude";\n'
        '        const _vArgs = process.platform === "win32"\n'
        '            ? [(process.env.APPDATA || "") + "\\\\npm\\\\node_modules\\\\@anthropic-ai\\\\claude-code\\\\cli.js", "--version"]\n'
        '            : ["--version"];\n'
        '        const proc = spawn(_vCmd, _vArgs, { stdio: "pipe" });',
    )
    if patched == content:
        logger.debug("proxy patch: nothing to replace in manager.js")
        return

    with open(manager_js, "w", encoding="utf-8") as f:
        f.write(patched)
    logger.info("Patched claude-max-api-proxy manager.js for Windows")


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


def _patch_normalize_model() -> None:
    """Patch claude-max-api-proxy to handle missing model name gracefully.

    The proxy crashes with ``TypeError: Cannot read properties of undefined
    (reading 'includes')`` when ``result.modelUsage`` is an empty object,
    causing ``Object.keys(...)[0]`` to return ``undefined``.
    """
    # Find the adapter file relative to the proxy binary
    proxy_bin = shutil.which("claude-max-api")
    if not proxy_bin:
        return
    proxy_dir = os.path.dirname(os.path.dirname(os.path.realpath(proxy_bin)))
    adapter_js = os.path.join(
        proxy_dir, "lib", "node_modules", "claude-max-api-proxy",
        "dist", "adapter", "cli-to-openai.js",
    )
    if not os.path.isfile(adapter_js):
        # Try npm global on macOS/Linux (Homebrew layout)
        for base in ("/opt/homebrew/lib", "/usr/local/lib", "/usr/lib"):
            candidate = os.path.join(
                base, "node_modules", "claude-max-api-proxy",
                "dist", "adapter", "cli-to-openai.js",
            )
            if os.path.isfile(candidate):
                adapter_js = candidate
                break
        else:
            return

    with open(adapter_js, encoding="utf-8") as f:
        content = f.read()

    if "if (!model)" in content:
        return  # already patched

    patched = content.replace(
        "function normalizeModelName(model) {\n"
        '    if (model.includes("opus"))',
        "function normalizeModelName(model) {\n"
        '    if (!model) return "claude-sonnet-4";\n'
        '    if (model.includes("opus"))',
    )
    patched = patched.replace(
        "const modelName = result.modelUsage\n"
        "        ? Object.keys(result.modelUsage)[0]\n"
        '        : "claude-sonnet-4";',
        "const modelKeys = result.modelUsage ? Object.keys(result.modelUsage) : [];\n"
        '    const modelName = modelKeys.length > 0 ? modelKeys[0] : "claude-sonnet-4";',
    )

    if patched == content:
        return  # nothing to patch

    with open(adapter_js, "w", encoding="utf-8") as f:
        f.write(patched)
    logger.info("Patched claude-max-api-proxy normalizeModelName for undefined model")


def start_proxy() -> subprocess.Popen | None:
    """Start claude-max-proxy in the background. Returns the process, or None on failure."""
    env = _enriched_env()
    cmd = shutil.which("claude-max-api", path=env.get("PATH"))
    if not cmd:
        logger.warning("claude-max-api not found — install with: npm install -g claude-max-api-proxy")
        return None

    # On Windows, .cmd scripts must be run via cmd.exe /c
    if os.name == "nt" and cmd.lower().endswith(".cmd"):
        popen_args = ["cmd.exe", "/c", cmd]
    else:
        popen_args = [cmd]

    logger.info("Starting claude-max-api-proxy...")
    log_path = os.path.join(os.path.expanduser("~"), ".openocto", "proxy.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_file = open(log_path, "w")  # noqa: SIM115
    proc = subprocess.Popen(
        popen_args,
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
    # Always apply patches regardless of proxy state
    _patch_proxy_for_windows()
    _patch_normalize_model()

    if is_proxy_running():
        return True
    proc = start_proxy()
    return proc is not None
