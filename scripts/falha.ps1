<#
.SYNOPSIS
    Injeta uma falha no ambiente de demo.
.EXAMPLE
    .\scripts\falha.ps1 apagao
    .\scripts\falha.ps1 nulos
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("apagao", "defasagem", "nulos", "duplicados", "schema", "reparar")]
    [string]$Tipo
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

docker compose exec -T app python -m simulator.falhas $Tipo

Write-Host ""
if ($Tipo -eq "schema") {
    Write-Host "Agora rode apenas a verificação (sem dbt):" -ForegroundColor Yellow
    Write-Host "  docker compose exec -T app python -m sentinela run"
} else {
    Write-Host "Agora rode:" -ForegroundColor Yellow
    Write-Host "  docker compose exec -T app dbt run --profiles-dir dbt --project-dir dbt"
    Write-Host "  docker compose exec -T app python -m sentinela run"
}
