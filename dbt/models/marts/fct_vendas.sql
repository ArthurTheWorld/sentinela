with pedidos as (

    select * from {{ ref('stg_pedidos') }}

),

pagamento_por_pedido as (

    select distinct on (pedido_id)
        pedido_id,
        metodo  as metodo_pagamento,
        valor_pago
    from {{ ref('stg_pagamentos') }}
    order by pedido_id, criado_em desc

)

select
    p.pedido_id,
    p.item_id,
    p.cliente_id,
    p.valor,
    p.quantidade,
    p.status,
    p.criado_em,
    pg.metodo_pagamento,
    pg.valor_pago
from pedidos p
left join pagamento_por_pedido pg
    on pg.pedido_id = p.pedido_id
