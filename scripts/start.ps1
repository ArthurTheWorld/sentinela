<#
.SYNOPSIS
    Sobe o ambiente, popula os dados, roda o dbt e a primeira verificação.
.EXAMPLE
    .\scripts\start.ps1
#>
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker não encontrado. Abra o Docker Desktop e tente de novo." -ForegroundColor Red
    exit 1
}

Write-Host "Subindo containers (primeira vez compila a imagem)..." -ForegroundColor Cyan
docker compose up -d --build

Write-Host "Aguardando o Postgres..." -ForegroundColor Cyan
for ($i = 1; $i -le 30; $i++) {
    docker compose exec -T postgres pg_isready -U sentinela -d sentinela *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 3
}

Write-Host "Gerando dados de demo (60 dias de pedidos)..." -ForegroundColor Cyan
docker compose exec -T app python -m simulator.seed

Write-Host "Construindo os modelos dbt..." -ForegroundColor Cyan
docker compose exec -T app dbt run --profiles-dir dbt --project-dir dbt

Write-Host "Executando verificações..." -ForegroundColor Cyan
docker compose exec -T app python -m sentinela run

Write-Host ""
Write-Host "Dashboard .... http://localhost:8501" -ForegroundColor Green
Write-Host "Postgres ..... localhost:5434 (sentinela/sentinela/sentinela)" -ForegroundColor Green
Write-Host ""
Write-Host "Para simular um incidente: .\scripts\falha.ps1 apagao" -ForegroundColor Yellow
