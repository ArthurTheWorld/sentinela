<#
.SYNOPSIS
    Mostra o estado atual das verificações.
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

docker compose exec -T app python -m sentinela status
