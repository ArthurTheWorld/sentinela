with vendas as (

    select * from {{ ref('fct_vendas') }}

)

select
    date_trunc('day', criado_em)::date                            as dia,
    sum(valor)::numeric(14, 2)                                    as receita,
    count(distinct pedido_id)                                     as pedidos,
    round(sum(valor) / nullif(count(distinct pedido_id), 0), 2)   as ticket_medio,
    now()                                                         as atualizado_em
from vendas
where status = 'pago'
group by 1
order by 1
