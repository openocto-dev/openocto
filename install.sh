#!/usr/bin/env bash
# OpenOcto installer for macOS and Linux.
#
# Works in two modes:
#   Remote:  curl -sSL https://raw.githubusercontent.com/.../install.sh | bash
#   Local:   ./install.sh   (from the project root)

set -euo pipefail

# --- Self-download when piped (curl | bash) ---
# When run via pipe, stdin is the script itself — interactive prompts and
# subprocesses (brew, etc.) break. Re-execute from a temp file instead.
if [ -z "${OPENOCTO_INSTALLER_RUNNING:-}" ] && ! [ -t 0 ]; then
    TMPSCRIPT=$(mktemp /tmp/openocto-install-XXXXXX)
    curl -sSL "https://raw.githubusercontent.com/openocto-dev/openocto/main/install.sh" -o "$TMPSCRIPT"
    export OPENOCTO_INSTALLER_RUNNING=1
    exec bash "$TMPSCRIPT" </dev/tty
fi

INSTALLER_VERSION="1.0.2"
REPO_URL="https://github.com/openocto-dev/openocto.git"
MIN_PYTHON="3.10"

# --- Ensure Homebrew is in PATH (macOS) ---
if [ "$(uname)" = "Darwin" ]; then
    if ! command -v brew &>/dev/null; then
        if [ -f /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [ -f /usr/local/bin/brew ]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi
    fi
fi

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}$*${NC}"; }
ok()    { echo -e "${GREEN}✓ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $*${NC}"; }
fail()  { echo -e "${RED}✗ $*${NC}"; exit 1; }

# --- Safe interactive read (returns default when no TTY) ---
# Usage: ask VARNAME "prompt" "default"
ask() {
    local varname="$1" prompt="$2" default="${3:-}"
    if [ -t 0 ] || [ -e /dev/tty ]; then
        read -r -p "$(echo -e "${CYAN}${prompt}${NC}")" "$varname" </dev/tty 2>/dev/null || eval "$varname='$default'"
    else
        eval "$varname='$default'"
    fi
}

# --- Check Python ---
find_python() {
    for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            local major minor
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

# --- Detect project root ---
find_project_root() {
    # If running from within the repo, find pyproject.toml
    local dir="$PWD"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/pyproject.toml" ] && grep -q "openocto" "$dir/pyproject.toml" 2>/dev/null; then
            echo "$dir"
            return 0
        fi
        dir=$(dirname "$dir")
    done
    return 1
}

# --- Main ---
echo ""
echo -e "${BOLD}${CYAN}🐙 OpenOcto Installer${NC}  ${CYAN}v${INSTALLER_VERSION}${NC}"
echo ""

# 1. Check Python (offer to install via Homebrew on macOS)
info "Checking Python..."
if ! PYTHON=$(find_python); then
    if [ "$(uname)" = "Darwin" ]; then
        # macOS: offer to install via Homebrew
        if ! command -v brew &>/dev/null; then
            echo ""
            warn "Python $MIN_PYTHON+ is required but not found."
            info "The easiest way to install it on macOS is via Homebrew."
            echo ""
            ask INSTALL_BREW "Install Homebrew and Python? [Y/n]: " "Y"
            if [[ ! "$INSTALL_BREW" =~ ^[Nn]$ ]]; then
                info "Installing Homebrew..."
                if ! /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; then
                    echo ""
                    fail "Homebrew installation failed.\n  Make sure your user has admin rights (System Settings → Users & Groups).\n  Then try again, or install manually:\n    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"\n    brew install python@3.13"
                fi
                # Add brew to PATH for this session (Apple Silicon vs Intel)
                if [ -f /opt/homebrew/bin/brew ]; then
                    eval "$(/opt/homebrew/bin/brew shellenv)"
                elif [ -f /usr/local/bin/brew ]; then
                    eval "$(/usr/local/bin/brew shellenv)"
                fi
                ok "Homebrew installed"
            else
                fail "Python $MIN_PYTHON+ is required. Install manually:\n  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"\n  brew install python@3.13"
            fi
        fi
        # Homebrew is available — install Python
        echo ""
        ask INSTALL_PY "Install Python 3.13 via Homebrew? [Y/n]: " "Y"
        if [[ ! "$INSTALL_PY" =~ ^[Nn]$ ]]; then
            info "Installing Python 3.13..."
            brew install python@3.13
            ok "Python installed"
        else
            fail "Python $MIN_PYTHON+ is required. Install it with: brew install python@3.13"
        fi
        PYTHON=$(find_python) || fail "Python installation failed. Try: brew install python@3.13"
    elif command -v apt-get &>/dev/null; then
        fail "Python $MIN_PYTHON+ is required. Install it with:\n  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    elif command -v dnf &>/dev/null; then
        fail "Python $MIN_PYTHON+ is required. Install it with:\n  sudo dnf install -y python3 python3-pip"
    else
        fail "Python $MIN_PYTHON+ is required. Install it from https://python.org"
    fi
fi
PYTHON_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
ok "Found Python $PYTHON_VER ($PYTHON)"

# 2. Determine project directory (local or remote)
if PROJECT_DIR=$(find_project_root 2>/dev/null); then
    info "Found project at $PROJECT_DIR"
    cd "$PROJECT_DIR"
else
    # Remote mode: clone the repo
    if ! command -v git &>/dev/null; then
        if [ "$(uname)" = "Darwin" ]; then
            fail "git is required. Install Xcode Command Line Tools:\n  xcode-select --install"
        else
            fail "git is required. Install it first."
        fi
    fi
    INSTALL_DIR="${OPENOCTO_DIR:-$HOME/openocto}"

    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Updating existing installation in $INSTALL_DIR..."
        git -C "$INSTALL_DIR" fetch --quiet origin
        git -C "$INSTALL_DIR" reset --hard origin/main --quiet
        # Clear stale bytecode cache to avoid running outdated code after update
        find "$INSTALL_DIR" -name "__pycache__" -not -path "*/.venv/*" -exec rm -rf {} + 2>/dev/null
        ok "Updated"
    else
        info "Cloning OpenOcto to $INSTALL_DIR..."
        git clone --quiet "$REPO_URL" "$INSTALL_DIR"
        ok "Cloned"
    fi

    cd "$INSTALL_DIR"
fi

# 3. Install system dependencies (audio libraries)
if [ "$(uname)" != "Darwin" ]; then
    if command -v apt-get &>/dev/null; then
        if ! dpkg -s libportaudio2 &>/dev/null 2>&1; then
            info "Installing system audio libraries (PortAudio)..."
            sudo apt-get update -qq && sudo apt-get install -y -qq libportaudio2 portaudio19-dev
            ok "PortAudio installed"
        fi
    elif command -v dnf &>/dev/null; then
        if ! rpm -q portaudio &>/dev/null 2>&1; then
            info "Installing system audio libraries (PortAudio)..."
            sudo dnf install -y portaudio portaudio-devel
            ok "PortAudio installed"
        fi
    fi
fi

# 4. Create venv
if [ ! -d ".venv" ]; then
    info "Creating virtual environment..."
    "$PYTHON" -m venv .venv
    ok "Virtual environment created"
fi

# 5. Install
info "Installing dependencies..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[audio,web]"
ok "Installed (with audio + web admin)"

# 6. Verify
VERSION=$(.venv/bin/openocto --version 2>&1 | tail -1)
ok "$VERSION"

# 7. Make `openocto` available system-wide
OCTO_BIN="$(pwd)/.venv/bin/openocto"
SYMLINK_PLACED=false

# Try /usr/local/bin first (always in PATH, no restart needed)
if [ -d /usr/local/bin ] && [ -w /usr/local/bin ]; then
    ln -sf "$OCTO_BIN" /usr/local/bin/openocto
    ok "Symlink created: /usr/local/bin/openocto"
    SYMLINK_PLACED=true
elif [ -d /usr/local/bin ]; then
    info "Creating symlink in /usr/local/bin (requires sudo)..."
    if sudo ln -sf "$OCTO_BIN" /usr/local/bin/openocto; then
        ok "Symlink created: /usr/local/bin/openocto"
        SYMLINK_PLACED=true
    fi
fi

# Fallback: write to shell rc file
if [ "$SYMLINK_PLACED" = false ]; then
    OCTO_BIN_DIR="$(pwd)/.venv/bin"
    SHELL_NAME=$(basename "$SHELL")
    case "$SHELL_NAME" in
        zsh)  RC_FILE="$HOME/.zshrc" ;;
        bash) RC_FILE="$HOME/.bashrc" ;;
        *)    RC_FILE="" ;;
    esac

    if [ -n "$RC_FILE" ]; then
        if ! grep -qF "$OCTO_BIN_DIR" "$RC_FILE" 2>/dev/null; then
            printf '\n# OpenOcto\nexport PATH="%s:$PATH"\n' "$OCTO_BIN_DIR" >> "$RC_FILE"
        fi
        export PATH="$OCTO_BIN_DIR:$PATH"
        ok "Added openocto to PATH in $RC_FILE"
        echo ""
        warn "Restart your terminal or run:  source $RC_FILE"
    else
        export PATH="$(pwd)/.venv/bin:$PATH"
        warn "Unknown shell — add manually:  export PATH=\"$(pwd)/.venv/bin:\$PATH\""
    fi
fi

# 8. Install openwakeword (optional, for always-on wake word mode)
echo ""
ask INSTALL_WW "Install wake word detection (\"Hey Octo!\")? [y/N]: " "N"
if [[ "$INSTALL_WW" =~ ^[Yy]$ ]]; then
    info "Installing openwakeword..."
    .venv/bin/pip install --quiet "openwakeword>=0.6.0" && ok "openwakeword installed" || warn "Failed to install openwakeword (optional — wake word won't work)"
else
    info "Skipping wake word detection (you can enable it later with: pip install openwakeword)"
fi

# 8. Install torch for Silero TTS (needed for Russian voice synthesis)
echo ""
ask INSTALL_TORCH "Install Russian voice synthesis (Silero TTS, ~200 MB)? [Y/n]: " "Y"
if [[ ! "$INSTALL_TORCH" =~ ^[Nn]$ ]]; then
    info "Installing PyTorch (CPU) for Silero TTS..."
    .venv/bin/pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu && ok "torch installed (Silero TTS ready)" || warn "Failed to install torch (Russian TTS won't work)"
else
    info "Skipping Silero TTS (Russian voice will fall back to piper)"
fi

# 9. Ensure Node.js/npm is available (needed for Claude proxy)
# Check if Node.js exists and is v18+ (required by Claude Code CLI)
NODE_OK=false
if command -v node &>/dev/null; then
    NODE_MAJOR=$(node -e "console.log(process.versions.node.split('.')[0])" 2>/dev/null || echo "0")
    if [ "$NODE_MAJOR" -ge 18 ] 2>/dev/null; then
        NODE_OK=true
    else
        warn "Node.js v$NODE_MAJOR found but v18+ is required."
    fi
fi

if [ "$NODE_OK" = false ]; then
    echo ""
    if [ "$(uname)" = "Darwin" ]; then
        if command -v brew &>/dev/null; then
            ask INSTALL_NODE "Node.js is required for Claude proxy. Install via Homebrew? [Y/n]: " "Y"
            if [[ ! "$INSTALL_NODE" =~ ^[Nn]$ ]]; then
                info "Installing Node.js..."
                brew install node
                ok "Node.js installed"
            fi
        else
            warn "npm not found. Install Node.js for Claude proxy support:"
            echo "     brew install node   (macOS with Homebrew)"
            echo "     https://nodejs.org  (manual install)"
        fi
    elif command -v apt-get &>/dev/null; then
        ask INSTALL_NODE "Node.js is required for Claude proxy. Install via NodeSource? [Y/n]: " "Y"
        if [[ ! "$INSTALL_NODE" =~ ^[Nn]$ ]]; then
            info "Installing Node.js 22 via NodeSource..."
            if curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - &>/dev/null; then
                sudo apt-get install -y -qq nodejs
                ok "Node.js $(node --version 2>/dev/null || echo '') installed"
            else
                warn "NodeSource setup failed, trying system package..."
                sudo apt-get update -qq && sudo apt-get install -y -qq nodejs npm
                ok "Node.js installed (system version)"
            fi
        fi
    elif command -v dnf &>/dev/null; then
        ask INSTALL_NODE "Node.js is required for Claude proxy. Install via dnf? [Y/n]: " "Y"
        if [[ ! "$INSTALL_NODE" =~ ^[Nn]$ ]]; then
            info "Installing Node.js..."
            sudo dnf install -y nodejs npm
            ok "Node.js installed"
        fi
    else
        warn "npm not found. Install Node.js from https://nodejs.org for Claude proxy support."
    fi
fi

# 10. Install claude-api-proxy (for Claude subscription users)
if command -v npm &>/dev/null; then
    if ! command -v claude-max-api &>/dev/null; then
        info "Installing claude-api-proxy (for Claude subscription users)..."
        # Fix npm cache permissions (common issue on macOS when npm was run with sudo)
        [ -d "$HOME/.npm" ] && chown -R "$(whoami)" "$HOME/.npm" 2>/dev/null || true
        npm install -g github:openocto-dev/claude-api-proxy --quiet && ok "claude-api-proxy installed" || warn "Failed to install claude-api-proxy (optional)"
    else
        ok "claude-api-proxy already installed"
    fi
    # claude-max-api-proxy requires Claude Code CLI to work
    if command -v claude-max-api &>/dev/null && ! command -v claude &>/dev/null; then
        info "Installing Claude Code CLI (required by claude-max-api-proxy)..."
        npm install -g @anthropic-ai/claude-code --quiet && ok "Claude Code CLI installed" || warn "Failed to install Claude Code CLI (optional)"
    fi
else
    warn "npm not found — skipping claude-max-api-proxy (optional, needed for Claude subscription mode)"
fi

# 11. Run setup wizard
echo ""
ask WIZARD_MODE "Run setup wizard in [B]rowser or [C]LI? [B/c]: " "B"
if [[ "$WIZARD_MODE" =~ ^[Cc]$ ]]; then
    info "Starting CLI setup wizard..."
    echo ""
    openocto setup
else
    info "Starting web setup wizard..."
    # Open browser automatically
    if command -v xdg-open &>/dev/null; then
        (sleep 1 && xdg-open "http://localhost:8080/wizard" 2>/dev/null) &
    elif command -v open &>/dev/null; then
        (sleep 1 && open "http://localhost:8080/wizard" 2>/dev/null) &
    else
        echo ""
        echo -e "  ${GREEN}Open your browser at: ${BOLD}http://localhost:8080/wizard${NC}"
    fi
    echo ""
    openocto web
fi
