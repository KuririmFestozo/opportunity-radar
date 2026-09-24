param(
    [switch]$Offline,
    [string]$Channel = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "=============================================================="
Write-Host " Opportunity Radar - Server Bootstrap"
Write-Host "=============================================================="

if (-not $Offline) {
    Write-Host "[1/3] Atualizando código..."
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        throw "git pull --ff-only falhou. Corrija o Git ou use -Offline conscientemente."
    }

    Write-Host "[2/3] Sincronizando banco + dashboard..."
    if ($Channel) {
        python -m tools.sync_server_state --channel $Channel
    }
    else {
        python -m tools.sync_server_state
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Sincronização do estado falhou. O servidor não será iniciado."
    }
}
else {
    Write-Host "[1/3] Modo offline: git pull ignorado."
    Write-Host "[2/3] Modo offline: sync remoto ignorado."
    if (-not (Test-Path "data\opportunity_radar.db")) {
        throw "Modo offline solicitado, mas data\opportunity_radar.db não existe."
    }
    if (-not (Test-Path "output\index.html")) {
        throw "Modo offline solicitado, mas output\index.html não existe."
    }
}

Write-Host "[3/3] Iniciando servidor..."
Write-Host "Abra: http://127.0.0.1:8000"
Write-Host ""
python server.py
