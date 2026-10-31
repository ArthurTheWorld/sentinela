# Runbook — schema mudou

**Incidente típico:** `fct_vendas :: schema` com coluna nova ou faltando.

## 1. Ver o que mudou

```sql
select details
from meta.check_result
where dataset = 'fct_vendas' and check_name = 'schema'
order by executed_at desc
limit 1;
```

O campo `details` traz `faltando`, `extras` e `atuais`.

```sql
select column_name, data_type
from information_schema.columns
where table_schema = 'analytics' and table_name = 'fct_vendas'
order by ordinal_position;
```

## 2. Classificar

| Caso | Gravidade | Ação |
|---|---|---|
| Coluna **faltando** | crítica | rollback do modelo ou restaurar coluna |
| Coluna **extra** com `permitir_extras: false` | crítica | adicionar ao contrato e avisar consumidores, ou remover |
| Coluna extra com `permitir_extras: true` | aviso | avaliar se é intencional |

## 3. Resolver

1. Se foi mudança intencional: atualizar `contracts/<dataset>.yml` no mesmo PR
2. Se foi acidental: `dbt run` reconstrói a tabela a partir do modelo
3. Se o consumidor quebrou: usar `sentinela alcance <modelo>` para saber o que
   precisa ser revalidado

## 4. Prevenção

- Schema check no contrato de todo dataset crítico
- Mudança de schema sempre no mesmo PR do contrato
- CI rodando `sentinela` contra ambiente de staging
