# Mingge Cross-border Plate - Settlement Statement Skill - Windows installer
# Usage (PowerShell):
#   powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -InstallSkill
param([switch]$InstallSkill)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Here ".venv"
$Vpy  = Join-Path $Venv "Scripts\python.exe"

Write-Host "==> 1/4 Checking Python"
$PyExe = $null
$PyArgs = @()

$cmd = Get-Command py -ErrorAction SilentlyContinue
if ($cmd) {
    $PyExe = "py"
    $PyArgs = @("-3")
} else {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        $PyExe = "python"
        $PyArgs = @()
    } else {
        $cmd = Get-Command python3 -ErrorAction SilentlyContinue
        if ($cmd) {
            $PyExe = "python3"
            $PyArgs = @()
        }
    }
}

if (-not $PyExe) {
    Write-Host "Python 3 not found." -ForegroundColor Red
    Write-Host "Install it from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "(During install, tick 'Add Python to PATH', then run install.bat again.)" -ForegroundColor Yellow
    exit 127
}
Write-Host ("    Using: " + $PyExe + " " + ($PyArgs -join " "))

Write-Host "==> 2/4 Creating virtual environment"
if (-not (Test-Path $Vpy)) {
    & $PyExe @PyArgs -m venv $Venv
}
if (-not (Test-Path $Vpy)) {
    Write-Host "Failed to create .venv" -ForegroundColor Red
    exit 1
}

Write-Host "==> 3/4 Installing dependencies (reportlab, pypdfium2)"
& $Vpy -m pip install --upgrade pip --quiet
& $Vpy -m pip install -r (Join-Path $Here "requirements.txt") --quiet

Write-Host "==> 4/4 Self check"
& $Vpy (Join-Path $Here "scripts\check_env.py")

if ($InstallSkill) {
    $Dest = Join-Path $HOME ".workbuddy\skills\settlement-statement"
    Write-Host "==> Installing skill to $Dest"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dest) | Out-Null
    if (Test-Path $Dest) {
        Write-Host "    Already exists, left untouched: $Dest" -ForegroundColor Yellow
    } else {
        Copy-Item -Path $Here -Destination $Dest -Recurse -Force
        Write-Host "    Installed. Restart your AI client to pick it up."
    }
}

Write-Host ""
Write-Host "Done."
Write-Host "  Make a statement : scripts\settle.bat --input - --png --clipboard --brief"
Write-Host "  Open entry board : scripts\board.bat"
