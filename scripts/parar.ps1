<#
.SYNOPSIS
    Para os containers (preserva os dados).
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

docker compose down
Write-Host "Containers parados. Volumes preservados." -ForegroundColor Yellow
