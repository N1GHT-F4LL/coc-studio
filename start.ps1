<#
.SYNOPSIS
  One-shot launcher for coc-studio (frontend + backend).

.DESCRIPTION
  Default (production): build the frontend then start the backend, which serves
  the built SPA at http://127.0.0.1:8000 and opens the browser. One process.

  -Dev: start the backend (:8000) AND the Vite dev server (:5173) together with
  hot reload. Use http://127.0.0.1:5173. Vite proxies /api and /ws to :8000.
  Ctrl+C stops the dev server; the backend is stopped automatically.

.EXAMPLE
  .\start.ps1          # build + serve at :8000
  .\start.ps1 -Dev     # hot-reload dev at :5173 (+ backend :8000)
#>
param([switch]$Dev)

# NOTE: do NOT set $ErrorActionPreference = "Stop" here. uvicorn logs to stderr,
# and PowerShell would otherwise treat the first native-stderr line as a
# terminating error and kill the server. Build failures are caught via
# $LASTEXITCODE below instead.
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$frontend = Join-Path $root "frontend"
$backend = Join-Path $root "backend"

if (-not (Test-Path $python)) {
    Write-Error "venv python not found at $python - create it and install backend\requirements.txt"
    exit 1
}

# Install frontend deps on first run.
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "==> Installing frontend dependencies (first run)..." -ForegroundColor Cyan
    Push-Location $frontend; npm install; Pop-Location
}

if ($Dev) {
    Write-Host "==> Dev mode: backend :8000 + Vite :5173 (hot reload)" -ForegroundColor Cyan
    $env:COC_OPEN_BROWSER = "0"
    $be = Start-Process -FilePath $python -ArgumentList "main.py" `
        -WorkingDirectory $backend -PassThru
    try {
        Start-Sleep -Seconds 2
        Write-Host "==> Open http://127.0.0.1:5173  (Ctrl+C to stop)" -ForegroundColor Green
        Push-Location $frontend
        npm run dev
        Pop-Location
    }
    finally {
        Write-Host "==> Stopping backend (pid $($be.Id))..." -ForegroundColor Cyan
        if (-not $be.HasExited) { Stop-Process -Id $be.Id -Force -ErrorAction SilentlyContinue }
    }
}
else {
    Write-Host "==> Building frontend..." -ForegroundColor Cyan
    Push-Location $frontend
    npm run build
    Pop-Location
    if ($LASTEXITCODE -ne 0) { Write-Error "frontend build failed"; exit 1 }

    Write-Host "==> Starting backend at http://127.0.0.1:8000 (Ctrl+C to stop)" -ForegroundColor Green
    Push-Location $backend
    & $python main.py
    Pop-Location
}
