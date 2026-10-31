<#
.SYNOPSIS
    Demonstração completa do ciclo de incidente: falha -> detecção -> reparo -> MTTR.
.EXAMPLE
    .\scripts\demo-incidente.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Rodar($mensagem, $comando) {
    Write-Host "`n=== $mensagem ===" -ForegroundColor Cyan
    docker compose exec -T app bash -c $comando
}

Rodar "1. Estado saudável" "python -m sentinela run --ignorar-erros"

Rodar "2. Injetando apagao (some com ontem e hoje)" "python -m simulator.falhas apagao"

Rodar "3. Reconstruindo dbt e verificando" "dbt run --profiles-dir dbt --project-dir dbt && python -m sentinela run --ignorar-erros"

Rodar "3b. Diagnóstico assistido do incidente" "python -m sentinela diagnosticar"

Write-Host "`n>>> Abra http://localhost:8501 e veja o incidente aberto e o diagnóstico." -ForegroundColor Yellow
Read-Host "Pressione ENTER para reparar e medir o MTTR"

Rodar "4. Reparando" "python -m simulator.falhas reparar"

Rodar "5. Reconstruindo dbt e verificando" "dbt run --profiles-dir dbt --project-dir dbt && python -m sentinela run --ignorar-erros"

Rodar "6. Incidentes (inclui resolvidos + MTTR)" "python -m sentinela incidentes --todos"
