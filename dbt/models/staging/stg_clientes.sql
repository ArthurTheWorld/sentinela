select
    cliente_id::int         as cliente_id,
    nome::text              as nome,
    email::text             as email,
    cidade::text            as cidade,
    uf::text                as uf,
    criado_em::timestamptz  as criado_em
from {{ source('loja', 'clientes') }}
