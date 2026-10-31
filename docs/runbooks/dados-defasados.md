# Runbook — dado defasado (freshness)

**Incidente típico:** `stg_pedidos :: freshness` acima de 6h.

## 1. Confirmar

```sql
select dataset, check_name, value as idade_segundos, message
from meta.check_result
where check_name = 'freshness'
  and executed_at = (select max(executed_at) from meta.check_result);
```

## 2. Identificar onde parou

```sql
-- Último registro na origem
select max(criado_em) from loja.pedidos;

-- Último registro na camada modelada
select max(criado_em) from analytics.stg_pedidos;

-- Último build do dbt (mart tem atualizado_em)
select max(atualizado_em) from analytics.mart_receita_diaria;
```

| Origem | Modelado | Causa |
|---|---|---|
| atualizado | velho | dbt parou / falhou |
| velho | velho | ingestão parou |
| atualizado | atualizado | relógio/timezone divergente |

## 3. Ações

- **dbt parou:** `dbt run --profiles-dir dbt --project-dir dbt` e verificar o scheduler
- **ingestão parou:** acionar o dono da fonte (campo `dono` do contrato)
- **timezone:** conferir se o container e o banco usam UTC; freshness calcula em UTC

## 4. Prevenção

- Threshold de `aviso_apos` deve ser menor que a frequência de atualização × 2
- Monitorar o próprio scheduler (o Sentinela detecta, mas não reinicia o job)
