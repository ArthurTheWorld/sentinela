select distinct on (cliente_id)
    cliente_id,
    nome,
    cidade,
    uf,
    criado_em
from {{ ref('stg_clientes') }}
order by cliente_id, criado_em desc
