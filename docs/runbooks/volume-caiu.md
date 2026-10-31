# Runbook — volume caiu

**Incidente típico:** `fct_vendas :: volume` com queda ≥ 60%.

## 1. Confirmar o diagnóstico

```sql
-- Última verificação de volume
select executed_at, value, status, message
from meta.check_result
where dataset = 'fct_vendas' and check_name = 'volume'
order by executed_at desc
limit 5;

-- Volume por dia na origem
select date_trunc('day', criado_em)::date as dia, count(*)
from loja.pedidos
group by 1
order by 1 desc
limit 10;
```

## 2. Determinar a causa

| Sintoma | Causa provável | Ação |
|---|---|---|
| Origem também zerada | falha na ingestão / job de extração | verificar o pipeline de entrada |
| Origem normal, analytics zerado | dbt falhou ou filtro mudou | rodar `dbt run` e conferir logs |
| Queda parcial (~30–50%) | sazonalidade não prevista | conferir se houve feriado/promoção |
| Queda só em uma coluna | join quebrado | conferir `relationships` do modelo |

## 3. Resolver

- Se a origem está correta: `dbt run` e nova verificação
- Se a origem está vazia: acionar o time da fonte (`dono` no contrato)
- Se foi sazonalidade legítima: **não** relaxar o limite sem discutir — ajustar
  `semanas_base` ou criar check específico de feriado

## 4. Fechar

Quando o volume voltar ao baseline, a próxima execução resolve o incidente
automaticamente e registra o MTTR.

## Prevenção

- Contrato com `volume` cobre 4 semanas sazonais
- Alerta deve chegar antes do consumidor (scheduler de 15 min)
