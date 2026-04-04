# OpenOcto installer for Windows (PowerShell).
#
# Works in two modes:
#   Remote:  irm https://raw.githubusercontent.com/.../install.ps1 | iex
#   Local:   .\install.ps1   (from the project root)

$ErrorActionPreference = "Stop"

$InstallerVersion = "1.0.2"
$RepoUrl = "https://github.com/openocto-dev/openocto.git"
$MinPython = [version]"3.10"

function Write-Info($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "[!!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red; throw $msg }

# Read-Host hangs when script is piped via "irm | iex" because stdin is the
# script stream itself.  Read directly from the console instead.
function Read-Prompt($prompt) {
    Write-Host "$prompt " -NoNewline
    try {
        return [Console]::ReadLine()
    } catch {
        # Non-interactive (no console attached) - return empty string so
        # callers fall through to the default branch.
        return ""
    }
}

function Find-ProjectRoot {
    $dir = Get-Location
    while ($dir) {
        $pyproject = Join-Path $dir "pyproject.toml"
        if ((Test-Path $pyproject) -and (Select-String -Path $pyproject -Pattern "openocto" -Quiet)) {
            return $dir.ToString()
        }
        $parent = Split-Path $dir -Parent
        if ($parent -eq $dir) { break }
        $dir = $parent
    }
    return $null
}

function Find-Python {
    foreach ($cmd in @("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python", "py")) {
        try {
            $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
            if ($ver) {
                $parsed = [version]$ver
                if ($parsed -ge $MinPython) {
                    return @{ cmd = $cmd; ver = $ver }
                }
            }
        } catch {}
    }
    return $null
}

Write-Host ""
Write-Host "OpenOcto Installer v$InstallerVersion" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python (offer to install via winget on Windows)
Write-Info "Checking Python..."
$py = Find-Python

if (-not $py) {
    Write-Warn "Python $MinPython+ is required but not found."
    Write-Host ""

    # Try winget
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $install = Read-Prompt "  Install Python 3.13 via winget? [Y/n]"
        if ($install -ne "n" -and $install -ne "N") {
            Write-Info "Installing Python 3.13..."
            winget install Python.Python.3.13 --accept-source-agreements --accept-package-agreements
            # Refresh PATH
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
            Write-Ok "Python installed"
        } else {
            Write-Fail "Python $MinPython+ is required. Install with: winget install Python.Python.3.13"
        }
    } else {
        Write-Fail "Python $MinPython+ is required. Install it from https://python.org"
    }

    $py = Find-Python
    if (-not $py) {
        Write-Fail "Python installation failed. Try: winget install Python.Python.3.13"
    }
}

$PythonCmd = $py.cmd
Write-Ok "Found Python $($py.ver) ($PythonCmd)"

# 2. Determine project directory (local or remote)
$ProjectDir = Find-ProjectRoot
if ($ProjectDir) {
    Write-Info "Found project at $ProjectDir"
    Set-Location $ProjectDir
} else {
    # Remote mode: clone the repo
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Warn "Git is required but not found."
        Write-Host ""
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            $installGit = Read-Prompt "  Install Git via winget? [Y/n]"
            if ($installGit -ne "n" -and $installGit -ne "N") {
                Write-Info "Installing Git..."
                winget install Git.Git --accept-source-agreements --accept-package-agreements
                # Refresh PATH
                $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
                Write-Ok "Git installed"
            } else {
                Write-Fail "Git is required. Install with: winget install Git.Git"
            }
        } else {
            Write-Fail "Git is required. Install it from https://git-scm.com"
        }
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Write-Fail "Git installation failed. Try: winget install Git.Git"
        }
    }
    $InstallDir = if ($env:OPENOCTO_DIR) { $env:OPENOCTO_DIR } else { "$HOME\openocto" }

    if (Test-Path "$InstallDir\.git") {
        Write-Info "Updating existing installation in $InstallDir..."
        git -C $InstallDir fetch --quiet origin
        git -C $InstallDir reset --hard origin/main --quiet
        # Clear stale bytecode cache to avoid running outdated code after update
        Get-ChildItem -Path $InstallDir -Directory -Recurse -Filter "__pycache__" |
            Where-Object { $_.FullName -notlike "*\.venv*" } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Write-Ok "Updated"
    } else {
        Write-Info "Cloning OpenOcto to $InstallDir..."
        git clone --quiet $RepoUrl $InstallDir
        Write-Ok "Cloned"
    }

    Set-Location $InstallDir
}

# 3. Create venv
if (-not (Test-Path ".venv")) {
    Write-Info "Creating virtual environment..."
    & $PythonCmd -m venv .venv
    Write-Ok "Virtual environment created"
}

# 4. Install
Write-Info "Installing dependencies..."
& .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .venv\Scripts\pip install --quiet -e ".[web]"
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Failed to install dependencies. Check the errors above."
}
Write-Ok "Installed (with web admin)"

# 4b. Try to install audio extras (pywhispercpp, piper-tts)
# On ARM64 Windows we download prebuilt wheels from GitHub Releases.
$arch = $env:PROCESSOR_ARCHITECTURE
$skipAudio = $false

$WheelsTag = "wheels-arm64-v1"
$WheelsBase = "https://github.com/openocto-dev/openocto/releases/download/$WheelsTag"

$Arm64Wheels = @(
    "piper_phonemize-1.2.0-cp313-cp313-win_arm64.whl",
    "piper_tts-1.4.2-cp313-cp313-win_arm64.whl",
    "pywhispercpp-1.4.1-cp313-cp313-win_arm64.whl"
)

function Install-Arm64AudioWheels {
    $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "openocto_wheels"
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    Write-Info "Downloading prebuilt ARM64 audio wheels..."
    foreach ($whl in $Arm64Wheels) {
        $dest = Join-Path $tmpDir $whl
        if (-not (Test-Path $dest)) {
            try {
                Write-Host "  -> $whl"
                Invoke-WebRequest -Uri "$WheelsBase/$whl" -OutFile $dest -UseBasicParsing
            } catch {
                Write-Warn "Failed to download ${whl}: $_"
                return $false
            }
        }
    }
    $wheelPaths = $Arm64Wheels | ForEach-Object { Join-Path $tmpDir $_ }
    Write-Info "Installing audio wheels..."
    & .venv\Scripts\pip install --quiet --no-deps @wheelPaths
    if ($LASTEXITCODE -ne 0) { return $false }
    # Runtime deps (pure-Python, available for ARM64 on PyPI)
    & .venv\Scripts\pip install --quiet "onnxruntime>=1,<2" "pathvalidate>=3,<4"
    if ($LASTEXITCODE -ne 0) { return $false }
    return $true
}

if ($arch -eq "ARM64") {
    Write-Info "Detected ARM64 - installing prebuilt audio wheels..."
    $ok = Install-Arm64AudioWheels
    if (-not $ok) {
        Write-Warn "Prebuilt ARM64 audio wheels failed to download or install."
        Write-Warn "OpenOcto will work without local STT/TTS."
        $skipAudio = $true
    } else {
        Write-Ok "Audio components installed (ARM64 prebuilt)"
    }
}

if (-not $skipAudio -and $arch -ne "ARM64") {
    Write-Info "Installing audio components (STT/TTS)..."
    & .venv\Scripts\pip install -e ".[audio]"
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Audio extras (pywhispercpp, piper-tts) failed to build."
        Write-Warn "You may need C++ build tools: winget install Microsoft.VisualStudio.2022.BuildTools"
        Write-Warn "OpenOcto will work but local STT/TTS will be unavailable."
    } else {
        Write-Ok "Audio components installed"
    }
}

# 5. Verify
$Version = & .venv\Scripts\openocto --version 2>&1 | Select-Object -Last 1
Write-Ok $Version

# 6. Add to PATH
$OctoBin = "$(Get-Location)\.venv\Scripts"
if ($env:PATH -notlike "*$OctoBin*") {
    # Add to user PATH permanently
    $userPath = [System.Environment]::GetEnvironmentVariable("PATH","User")
    if ($userPath -notlike "*$OctoBin*") {
        [System.Environment]::SetEnvironmentVariable("PATH","$OctoBin;$userPath","User")
        Write-Ok "Added openocto to user PATH"
    }
    # Also update current session
    $env:PATH = "$OctoBin;$env:PATH"
}

# 7. Install openwakeword (optional)
Write-Host ""
$installWW = Read-Prompt "Install wake word detection ('Hey Octo!')? [y/N]"
if ($installWW -eq "y" -or $installWW -eq "Y") {
    Write-Info "Installing openwakeword..."
    try {
        & .venv\Scripts\pip install --quiet "openwakeword>=0.6.0"
        Write-Ok "openwakeword installed"
    } catch {
        Write-Warn "Failed to install openwakeword (optional - wake word will not work)"
    }
} else {
    Write-Info "Skipping wake word detection (enable later with: pip install openwakeword)"
}

# 8. Ensure Node.js/npm is available (needed for Claude proxy)
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host ""
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $installNode = Read-Prompt "Node.js is required for Claude proxy. Install via winget? [Y/n]"
        if ($installNode -ne "n" -and $installNode -ne "N") {
            Write-Info "Installing Node.js..."
            winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
            # Refresh PATH so npm is available in this session
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
            Write-Ok "Node.js installed"
        }
    } else {
        Write-Warn "npm not found. Install Node.js from https://nodejs.org for Claude proxy support."
    }
}

# 9. Install claude-max-api-proxy + Claude Code CLI (for Claude subscription users)
if (Get-Command npm -ErrorAction SilentlyContinue) {
    # Refresh PATH so freshly installed npm packages are visible
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")

    if (-not (Get-Command claude-max-api -ErrorAction SilentlyContinue)) {
        Write-Info "Installing claude-max-api-proxy (for Claude subscription users)..."
        try {
            npm install -g claude-max-api-proxy --quiet
            # Refresh PATH again after install
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
            Write-Ok "claude-max-api-proxy installed"
        } catch {
            Write-Warn "Failed to install claude-max-api-proxy (optional)"
        }
    } else {
        Write-Ok "claude-max-api-proxy already installed"
    }

    # Claude Code CLI is required by claude-max-api-proxy
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
        Write-Info "Installing Claude Code CLI (required by claude-max-api-proxy)..."
        try {
            npm install -g @anthropic-ai/claude-code --quiet
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
            Write-Ok "Claude Code CLI installed"
        } catch {
            Write-Warn "Failed to install Claude Code CLI (optional)"
        }
    } else {
        Write-Ok "Claude Code CLI already installed"
    }

    # Prompt to log in to Claude if not already authenticated
    if (Get-Command claude -ErrorAction SilentlyContinue) {
        $claudeAuth = claude auth status 2>&1
        if ($claudeAuth -notmatch "Logged in") {
            Write-Host ""
            Write-Info "Claude Code CLI requires login to work with the proxy."
            Write-Info "Running: claude login"
            Write-Host ""
            claude login
        }
    }
} else {
    Write-Warn "npm not found - skipping claude-max-api-proxy (optional, needed for Claude subscription mode)"
}

# 10. Run setup wizard
Write-Host ""
$wizardMode = Read-Host "Run setup wizard in [B]rowser or [C]LI? [B/c]"
if ($wizardMode -match '^[Cc]$') {
    Write-Info "Starting CLI setup wizard..."
    Write-Host ""
    & openocto setup
} else {
    Write-Info "Starting web setup wizard..."
    Write-Host ""
    Start-Process "http://localhost:8080/wizard"
    & openocto web
}
