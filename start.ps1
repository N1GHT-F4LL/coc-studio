<#
.SYNOPSIS
  One-shot launcher for coc-studio (frontend + backend). Self-bootstrapping:
  on first run it creates the venv, installs backend + frontend deps, builds.

.DESCRIPTION
  Default (production): build the frontend then start the backend, which serves
  the built SPA at http://127.0.0.1:8000 and opens the browser. One process.

  -Dev: start the backend (:8000) AND the Vite dev server (:5173) together with
  hot reload. Use http://127.0.0.1:5173. Vite proxies /api and /ws to :8000.
  Ctrl+C stops the dev server; the backend is stopped automatically.

  First run (or after deleting .venv / node_modules, or editing
  backend\requirements.txt): everything is installed automatically. The easyocr
  dependency pulls in torch, so the first pip install downloads several GB.

.NOTES
  Prerequisites: Python 3 and Node.js LTS on PATH. If either is missing the
  script stops with a download link instead of half-starting.

  Fresh Windows blocks .ps1 files (execution policy). Run once via:
    powershell -ExecutionPolicy Bypass -File .\start.ps1

.EXAMPLE
  .\start.ps1          # build + serve at :8000
  .\start.ps1 -Dev     # hot-reload dev at :5173 (+ backend :8000)
#>
param([switch]$Dev)

# NOTE: do NOT set $ErrorActionPreference = "Stop" here. uvicorn logs to stderr,
# and PowerShell would otherwise treat the first native-stderr line as a
# terminating error and kill the server. Failures are caught via $LASTEXITCODE.
$root = $PSScriptRoot
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$frontend = Join-Path $root "frontend"
$backend = Join-Path $root "backend"
$requirements = Join-Path $backend "requirements.txt"

# --- Toolchain checks (fail fast, before any slow work) --------------------
# Windows ships a fake python.exe/python3.exe in WindowsApps that only prints
# an install hint and exits 9009, so Get-Command alone is not proof of a real
# install - probe --version and require a sane answer.
function Find-PythonCommand {
    foreach ($name in "py", "python", "python3") {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $out = & $cmd.Source --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$out" -match "Python \d") { return $cmd.Source }
    }
    return $null
}

# npm is needed on every run (build or dev). A missing command does NOT set
# $LASTEXITCODE in PowerShell, so without this guard a missing npm would be
# mistaken for success further down.
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "npm not found - install Node.js LTS from https://nodejs.org (includes npm), reopen the terminal, then re-run .\start.ps1"
    exit 1
}

# --- Bootstrap: create the venv on first run -------------------------------
if (-not (Test-Path $python)) {
    $sysPython = Find-PythonCommand
    if (-not $sysPython) {
        Write-Error "Python not found - install Python 3 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), reopen the terminal, then re-run .\start.ps1"
        exit 1
    }
    Write-Host "==> Creating Python venv (first run, using $sysPython)..." -ForegroundColor Cyan
    & $sysPython -m venv $venv
    if (-not (Test-Path $python)) {
        Write-Error "venv creation failed - no python.exe at $python"
        exit 1
    }
}

# --- Bootstrap: install backend deps on first run or when requirements.txt
# changed. The stamp lives inside .venv, so deleting the venv resets it. ----
$stamp = Join-Path $venv ".requirements.stamp"
$reqHash = (Get-FileHash $requirements -Algorithm SHA256).Hash
$installed = (Test-Path $stamp) -and ((Get-Content $stamp -Raw).Trim() -eq $reqHash)
if (-not $installed) {
    # Rare, but a venv can end up without pip - bootstrap it instead of dying.
    & $python -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "==> pip missing in venv - bootstrapping with ensurepip..." -ForegroundColor Cyan
        & $python -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) {
            Write-Error "could not bootstrap pip - delete .venv and re-run .\start.ps1"
            exit 1
        }
    }
    Write-Host "==> Installing backend dependencies (first run downloads several GB for torch/easyocr)..." -ForegroundColor Cyan
    & $python -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install failed - fix the error above and re-run .\start.ps1"
        exit 1
    }
    Set-Content -Path $stamp -Value $reqHash -Encoding ascii
}

# --- Bootstrap: install frontend deps on first run -------------------------
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "==> Installing frontend dependencies (first run)..." -ForegroundColor Cyan
    Push-Location $frontend
    npm install
    $npmOk = ($LASTEXITCODE -eq 0)
    Pop-Location
    if (-not $npmOk) {
        Write-Error "npm install failed - fix the error above and re-run .\start.ps1"
        exit 1
    }
}

if ($Dev) {
    Write-Host "==> Dev mode: backend :8000 + Vite :5173 (hot reload)" -ForegroundColor Cyan
    $env:COC_OPEN_BROWSER = "0"
    $be = Start-Process -FilePath $python -ArgumentList "main.py" `
        -WorkingDirectory $backend -PassThru
    Push-Location $frontend
    try {
        Start-Sleep -Seconds 2
        Write-Host "==> Open http://127.0.0.1:5173  (Ctrl+C to stop)" -ForegroundColor Green
        npm run dev
    }
    finally {
        # Runs even on Ctrl+C, so the shell returns to where it started and the
        # backend doesn't linger.
        Pop-Location
        Write-Host "==> Stopping backend (pid $($be.Id))..." -ForegroundColor Cyan
        if (-not $be.HasExited) { Stop-Process -Id $be.Id -Force -ErrorAction SilentlyContinue }
    }
}
else {
    Write-Host "==> Building frontend..." -ForegroundColor Cyan
    Push-Location $frontend
    npm run build
    $buildOk = ($LASTEXITCODE -eq 0)
    Pop-Location
    if (-not $buildOk) { Write-Error "frontend build failed"; exit 1 }

    Write-Host "==> Starting backend at http://127.0.0.1:8000 (Ctrl+C to stop)" -ForegroundColor Green
    Push-Location $backend
    try {
        & $python main.py
    }
    finally {
        # Ctrl+C aborts the script mid-run; without this the shell would stay
        # stranded in backend\. finally runs on Ctrl+C, so we always return.
        Pop-Location
    }
}
