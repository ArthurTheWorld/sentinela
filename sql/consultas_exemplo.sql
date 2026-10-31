-- Consultas para explorar a plataforma de confiabilidade.
-- Conexão: localhost:5434 | db sentinela | user sentinela | senha sentinela

-- 1) Estado atual de todas as verificações
--    (última execução de CADA check, não do banco inteiro)
select distinct on (dataset, check_name)
       dataset, check_name, status, value, unit, executed_at
from meta.check_result
order by dataset, check_name, executed_at desc;

-- 2) Incidentes abertos com severidade e alcance
select severity, dataset, check_name, title, opened_at, blast_radius
from meta.incident
where status = 'aberto'
order by opened_at desc;

-- 3) MTTR por dataset (tempo médio de resolução)
select dataset,
       count(*) as incidentes_resolvidos,
       round(avg(mttr_seconds)) as mttr_medio_s,
       round(max(mttr_seconds)) as mttr_max_s
from meta.incident
where status = 'resolvido'
group by dataset
order by mttr_medio_s desc;

-- 4) Histórico de uma métrica (ex.: volume do fct_vendas)
select executed_at, status, value, unit
from meta.check_result
where dataset = 'fct_vendas' and check_name = 'volume'
order by executed_at desc
limit 24;

-- 5) Quantas verificações falharam por dia
select date_trunc('day', executed_at)::date as dia,
       count(*) filter (where status = 'error') as erros,
       count(*) filter (where status = 'warn')  as avisos,
       count(*)                                  as total
from meta.check_result
group by 1
order by 1 desc;
