# OpenOcto installer for Windows (PowerShell).
#
# Works in two modes:
#   Remote:  irm https://raw.githubusercontent.com/.../install.ps1 | iex
#   Local:   .\scripts\install.ps1   (from the project root)

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/openocto-dev/openocto.git"
$MinPython = [version]"3.10"

function Write-Info($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "✓ $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }

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

Write-Host ""
Write-Host "🐙 OpenOcto Installer" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Info "Checking Python..."
$PythonCmd = $null
foreach ($cmd in @("python3", "python", "py")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        if ($ver) {
            $parsed = [version]$ver
            if ($parsed -ge $MinPython) {
                $PythonCmd = $cmd
                Write-Ok "Found Python $ver ($cmd)"
                break
            }
        }
    } catch {}
}
if (-not $PythonCmd) {
    Write-Fail "Python $MinPython+ is required. Install it from https://python.org"
}

# 2. Determine project directory (local or remote)
$ProjectDir = Find-ProjectRoot
if ($ProjectDir) {
    Write-Info "Found project at $ProjectDir"
    Set-Location $ProjectDir
} else {
    # Remote mode: clone the repo
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Fail "git is required. Install it from https://git-scm.com"
    }
    $InstallDir = if ($env:OPENOCTO_DIR) { $env:OPENOCTO_DIR } else { "$HOME\openocto" }

    if (Test-Path "$InstallDir\.git") {
        Write-Info "Updating existing installation in $InstallDir..."
        git -C $InstallDir pull --quiet
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
& .venv\Scripts\pip install --quiet --upgrade pip
& .venv\Scripts\pip install --quiet -e .
Write-Ok "Installed"

# 5. Verify
$Version = & .venv\Scripts\openocto --version 2>&1 | Select-Object -Last 1
Write-Ok $Version

# 6. PATH hint
$OctoBin = "$(Get-Location)\.venv\Scripts"
if ($env:PATH -notlike "*$OctoBin*") {
    Write-Host ""
    Write-Warn "Add OpenOcto to your PATH:"
    Write-Host "  `$env:PATH = `"$OctoBin;`$env:PATH`"" -ForegroundColor White
    Write-Host "  # Or permanently via System Settings → Environment Variables"
}

# 7. Install claude-max-api-proxy (optional, for Claude subscription users)
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
} else {
    Write-Warn "npm not found — skipping claude-max-api-proxy (optional, needed for Claude subscription mode)"
}

# 8. Run setup wizard
Write-Host ""
Write-Info "Starting setup wizard..."
Write-Host ""
& .venv\Scripts\openocto setup
