select
    pedido_id::int              as pedido_id,
    item_id::int                as item_id,
    cliente_id::int             as cliente_id,
    produto_id::int             as produto_id,
    quantidade::int             as quantidade,
    valor::numeric(12, 2)       as valor,
    status::text                as status,
    criado_em::timestamptz      as criado_em,
    updated_at::timestamptz     as updated_at
from {{ source('loja', 'pedidos') }}
where pedido_id is not null
