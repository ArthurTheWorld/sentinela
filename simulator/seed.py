"""Gerador de dados de e-commerce (determinístico) para o ambiente de demo.

Cria o schema `loja` (camada transacional) com ~60 dias de pedidos, respeitando
sazonalidade semanal: fim de semana vende menos. É essa sazonalidade que torna
o alerta de volume ingênuo (comparar com a média) inútil — e o baseline
sazonal necessário.
"""

from __future__ import annotations

import argparse
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

from sentinela.config import Config

log = logging.getLogger(__name__)

DDL = """
create schema if not exists loja;

create table if not exists loja.clientes (
    cliente_id integer primary key,
    nome       text,
    email      text,
    cidade     text,
    uf         text,
    criado_em  timestamptz
);

create table if not exists loja.pedidos (
    pedido_id  integer      not null,
    item_id    integer      not null,
    cliente_id integer,
    produto_id integer,
    quantidade integer,
    valor      numeric(12,2),
    status     text,
    criado_em  timestamptz,
    updated_at timestamptz
);

create index if not exists idx_pedidos_criado_em on loja.pedidos (criado_em);

create table if not exists loja.pagamentos (
    pagamento_id bigserial primary key,
    pedido_id    integer,
    metodo       text,
    valor_pago   numeric(12,2),
    status       text,
    criado_em    timestamptz
);

create index if not exists idx_pagamentos_criado_em on loja.pagamentos (criado_em);
"""

CIDADES = [
    ("São Paulo", "SP"),
    ("Campinas", "SP"),
    ("Rio de Janeiro", "RJ"),
    ("Belo Horizonte", "MG"),
    ("Curitiba", "PR"),
    ("Porto Alegre", "RS"),
    ("Florianópolis", "SC"),
    ("Brasília", "DF"),
    ("Salvador", "BA"),
    ("Recife", "PE"),
]

NOMES = [
    "Ana", "Bruno", "Carla", "Diego", "Eduarda", "Felipe", "Gabriela", "Henrique",
    "Isabela", "João", "Karina", "Lucas", "Mariana", "Nathalia", "Otávio",
    "Paula", "Rafael", "Sofia", "Thiago", "Vanessa",
]

SOBRENOMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Lima", "Pereira", "Costa",
    "Ferreira", "Almeida", "Rodrigues", "Gomes", "Martins",
]

METODOS = ["pix", "cartao_credito", "boleto", "cartao_debito"]

STATUS_PEDIDO = ["pago", "pago", "pago", "pago", "pago", "pago", "pago", "pendente", "cancelado"]


def criar_tabelas(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def limpar(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("truncate table loja.pedidos, loja.pagamentos, loja.clientes")
    conn.commit()


def gerar_clientes(conn, quantidade: int, rnd: random.Random) -> None:
    agora = datetime.now(timezone.utc)
    linhas = []
    for cliente_id in range(1, quantidade + 1):
        cidade, uf = rnd.choice(CIDADES)
        nome = f"{rnd.choice(NOMES)} {rnd.choice(SOBRENOMES)}"
        linhas.append(
            (
                cliente_id,
                nome,
                f"{nome.lower().replace(' ', '.')}{cliente_id}@exemplo.com",
                cidade,
                uf,
                agora - timedelta(days=rnd.randint(30, 900)),
            )
        )

    with conn.cursor() as cur:
        execute_values(
            cur,
            "insert into loja.clientes (cliente_id, nome, email, cidade, uf, criado_em) values %s",
            linhas,
            page_size=1000,
        )
    conn.commit()
    log.info("Clientes gerados: %d", len(linhas))


def gerar_pedidos(
    conn,
    dias: int,
    quantidade_clientes: int,
    rnd: random.Random,
) -> int:
    agora = datetime.now(timezone.utc)
    hoje = agora.date()

    linhas_pedidos: list[tuple[Any, ...]] = []
    linhas_pagamentos: list[tuple[Any, ...]] = []

    pedido_id = 0
    for delta in range(dias, -1, -1):
        dia = hoje - timedelta(days=delta)
        base = 420 if dia.weekday() < 5 else 220          # sazonalidade semanal
        quantidade = int(base * rnd.uniform(0.92, 1.08))

        if delta == 0:                                     # hoje: só até a hora atual
            fracao = max(0.05, agora.hour / 24)
            quantidade = int(quantidade * fracao)

        for _ in range(quantidade):
            pedido_id += 1
            hora = rnd.randint(0, agora.hour) if delta == 0 else rnd.randint(0, 23)
            criado = datetime(
                dia.year, dia.month, dia.day, hora, rnd.randint(0, 59), rnd.randint(0, 59),
                tzinfo=timezone.utc,
            )
            cliente_id = rnd.randint(1, quantidade_clientes)
            status = rnd.choice(STATUS_PEDIDO)
            itens = rnd.choice([1, 1, 1, 2, 2, 3])
            valor_unidade = round(rnd.uniform(25, 420), 2)

            total_pedido = 0.0
            for item_id in range(1, itens + 1):
                valor_item = round(valor_unidade * rnd.uniform(0.9, 1.1), 2)
                total_pedido += valor_item
                linhas_pedidos.append(
                    (
                        pedido_id,
                        item_id,
                        cliente_id,
                        rnd.randint(1, 500),
                        rnd.randint(1, 3),
                        valor_item,
                        status,
                        criado + timedelta(minutes=rnd.randint(0, 30)),
                        # nunca no futuro: frescor negativo confundiria a checagem
                        min(criado + timedelta(minutes=rnd.randint(30, 120)), agora),
                    )
                )

            if status != "cancelado":
                linhas_pagamentos.append(
                    (
                        pedido_id,
                        rnd.choice(METODOS),
                        round(total_pedido, 2),
                        "aprovado" if status == "pago" else "pendente",
                        min(criado + timedelta(minutes=rnd.randint(1, 20)), agora),
                    )
                )

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            insert into loja.pedidos
                (pedido_id, item_id, cliente_id, produto_id, quantidade, valor, status, criado_em, updated_at)
            values %s
            """,
            linhas_pedidos,
            page_size=2000,
        )
        execute_values(
            cur,
            "insert into loja.pagamentos (pedido_id, metodo, valor_pago, status, criado_em) values %s",
            linhas_pagamentos,
            page_size=2000,
        )
    conn.commit()

    log.info(
        "Pedidos gerados: %d linhas (%d pedidos) e %d pagamentos",
        len(linhas_pedidos),
        pedido_id,
        len(linhas_pagamentos),
    )
    return len(linhas_pedidos)


def repopular(conn, *, dias: int = 60, clientes: int = 5000, semente: int = 42) -> None:
    """Recria todo o dataset transacional (determinístico)."""
    rnd = random.Random(semente)
    criar_tabelas(conn)
    limpar(conn)
    gerar_clientes(conn, clientes, rnd)
    gerar_pedidos(conn, dias, clientes, rnd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera os dados de demo do Sentinela.")
    parser.add_argument("--dias", type=int, default=60)
    parser.add_argument("--clientes", type=int, default=5000)
    parser.add_argument("--semente", type=int, default=42)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    conn = psycopg2.connect(Config.from_env().dsn)
    try:
        repopular(conn, dias=args.dias, clientes=args.clientes, semente=args.semente)
    finally:
        conn.close()

    print("Dados gerados. Agora rode: dbt run --profiles-dir dbt --project-dir dbt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
