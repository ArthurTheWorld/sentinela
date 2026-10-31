select
    pagamento_id::int           as pagamento_id,
    pedido_id::int              as pedido_id,
    metodo::text                as metodo,
    valor_pago::numeric(12, 2)  as valor_pago,
    status::text                as status,
    criado_em::timestamptz      as criado_em
from {{ source('loja', 'pagamentos') }}
