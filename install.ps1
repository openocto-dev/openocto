# OpenOcto installer for Windows (PowerShell).
#
# Works in two modes:
#   Remote:  irm https://raw.githubusercontent.com/.../install.ps1 | iex
#   Local:   .\install.ps1   (from the project root)

$ErrorActionPreference = "Stop"

$InstallerVersion = "1.0.1"
$RepoUrl = "https://github.com/openocto-dev/openocto.git"
$MinPython = [version]"3.10"

function Write-Info($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "✓ $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "✗ $msg" -ForegroundColor Red; throw $msg }

function Read-Prompt($msg) {
    # Read-Host hangs when stdin is a pipe (irm | iex).
    # Read directly from the console instead.
    Write-Host $msg -NoNewline -ForegroundColor Cyan
    try {
        return [Console]::ReadLine()
    } catch {
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
Write-Host "🐙 OpenOcto Installer" -ForegroundColor Cyan -NoNewline; Write-Host "  v$InstallerVersion" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python (offer to install via winget on Windows)
Write-Info "Checking Python..."
$py = Find-Python

if (-not $py) {
    Write-Warn "Python $MinPython+ is required but not found."
    Write-Host ""

    # Try winget
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $install = Read-Prompt "  Install Python 3.13 via winget? [Y/n]: "
        if ($install -ne "n" -and $install -ne "N") {
            Write-Info "Installing Python 3.13..."
            winget install Python.Python.3.13 --accept-source-agreements --accept-package-agreements
            # Refresh PATH
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
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
            $installGit = Read-Prompt "  Install Git via winget? [Y/n]: "
            if ($installGit -ne "n" -and $installGit -ne "N") {
                Write-Info "Installing Git..."
                winget install Git.Git --accept-source-agreements --accept-package-agreements
                # Refresh PATH
                $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
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
& .venv\Scripts\pip install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Failed to install dependencies. Check the errors above."
}
Write-Ok "Installed"

# 5. Verify
$Version = & .venv\Scripts\openocto --version 2>&1 | Select-Object -Last 1
if ($LASTEXITCODE -ne 0) {
    Write-Fail "openocto command not found. Installation may have failed."
}
Write-Ok $Version

# 6. Add to PATH
$OctoBin = "$(Get-Location)\.venv\Scripts"
if ($env:PATH -notlike "*$OctoBin*") {
    # Add to user PATH permanently
    $userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    if ($userPath -notlike "*$OctoBin*") {
        [System.Environment]::SetEnvironmentVariable("PATH", "$OctoBin;$userPath", "User")
        Write-Ok "Added openocto to user PATH"
    }
    # Also update current session
    $env:PATH = "$OctoBin;$env:PATH"
}

# 7. Install openwakeword (optional)
Write-Host ""
$installWW = Read-Prompt "Install wake word detection ('Hey Octo!')? [y/N]: "
if ($installWW -eq "y" -or $installWW -eq "Y") {
    Write-Info "Installing openwakeword..."
    try {
        & .venv\Scripts\pip install --quiet "openwakeword>=0.6.0"
        Write-Ok "openwakeword installed"
    } catch {
        Write-Warn "Failed to install openwakeword (optional - wake word won't work)"
    }
} else {
    Write-Info "Skipping wake word detection (enable later with: pip install openwakeword)"
}

# 8. Ensure Node.js/npm is available (needed for Claude proxy)
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host ""
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $installNode = Read-Prompt "Node.js is required for Claude proxy. Install via winget? [Y/n]: "
        if ($installNode -ne "n" -and $installNode -ne "N") {
            Write-Info "Installing Node.js..."
            winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
            # Refresh PATH so npm is available in this session
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
            Write-Ok "Node.js installed"
        }
    } else {
        Write-Warn "npm not found. Install Node.js from https://nodejs.org for Claude proxy support."
    }
}

# 9. Install claude-max-api-proxy (optional, for Claude subscription users)
if (Get-Command npm -ErrorAction SilentlyContinue) {
    if (-not (Get-Command claude-max-api -ErrorAction SilentlyContinue)) {
        Write-Info "Installing claude-max-api-proxy (for Claude subscription users)..."
        try {
            npm install -g claude-max-api-proxy --quiet
            Write-Ok "claude-max-api-proxy installed"
        } catch {
            Write-Warn "Failed to install claude-max-api-proxy (optional)"
        }
    } else {
        Write-Ok "claude-max-api-proxy already installed"
    }
    # claude-max-api-proxy requires Claude Code CLI to work
    if ((Get-Command claude-max-api -ErrorAction SilentlyContinue) -and -not (Get-Command claude -ErrorAction SilentlyContinue)) {
        Write-Info "Installing Claude Code CLI (required by claude-max-api-proxy)..."
        try {
            npm install -g @anthropic-ai/claude-code --quiet
            Write-Ok "Claude Code CLI installed"
        } catch {
            Write-Warn "Failed to install Claude Code CLI (optional)"
        }
    }
} else {
    Write-Warn "npm not found - skipping claude-max-api-proxy (optional, needed for Claude subscription mode)"
}

# 10. Run setup wizard
Write-Host ""
Write-Info "Starting setup wizard..."
Write-Host ""
& openocto setup
