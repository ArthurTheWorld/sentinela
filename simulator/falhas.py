"""Simulador de falhas — "caos engineering" para dados.

Cada comando injeta um problema realista e explica o que rodar em seguida.
O objetivo é provar, com número, que o Sentinela detecta e que o MTTR é medido.
"""

from __future__ import annotations

import argparse
import logging

import psycopg2

from sentinela.config import Config
from simulator.seed import repopular

log = logging.getLogger(__name__)

COMANDOS = ("apagao", "defasagem", "nulos", "duplicados", "schema", "reparar")

EXPLICACAO = {
    "apagao": "Remove ontem e hoje do banco operacional: volume cai a zero e o dado fica velho.",
    "defasagem": "Remove apenas as últimas 12h: freshness estoura, volume de ontem continua ok.",
    "nulos": "Anula 8% dos clientes dos pedidos de ontem (acima do limite de 5%).",
    "duplicados": "Duplica os pedidos de ontem: quebra a unicidade da chave.",
    "schema": "Adiciona uma coluna não prevista em analytics.fct_vendas (quebra o contrato).",
    "reparar": "Recria o dataset transacional e remove a coluna intrusa.",
}


def _exec(conn, sql: str, params: tuple = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def apagao(conn) -> None:
    linhas = _exec(conn, "delete from loja.pedidos where criado_em >= current_date - interval '1 day'")
    _exec(conn, "delete from loja.pagamentos where criado_em >= current_date - interval '1 day'")
    conn.commit()
    print(f"Apagão: {linhas} linhas de pedidos removidas (ontem + hoje).")
    print("Rode: dbt run --profiles-dir dbt --project-dir dbt && sentinela run")


def defasagem(conn) -> None:
    linhas = _exec(conn, "delete from loja.pedidos where criado_em >= now() - interval '12 hours'")
    _exec(conn, "delete from loja.pagamentos where criado_em >= now() - interval '12 hours'")
    conn.commit()
    print(f"Defasagem: {linhas} linhas recentes removidas (últimas 12h).")
    print("Rode: dbt run --profiles-dir dbt --project-dir dbt && sentinela run")


def nulos(conn) -> None:
    linhas = _exec(
        conn,
        """
        update loja.pedidos
           set cliente_id = null
         where criado_em::date = current_date - 1
           and random() < 0.08
        """,
    )
    conn.commit()
    print(f"Nulos: {linhas} pedidos de ontem ficaram sem cliente (~8%).")
    print("Rode: dbt run --profiles-dir dbt --project-dir dbt && sentinela run")


def duplicados(conn) -> None:
    linhas = _exec(
        conn,
        """
        insert into loja.pedidos
            (pedido_id, item_id, cliente_id, produto_id, quantidade, valor, status, criado_em, updated_at)
        select pedido_id, item_id, cliente_id, produto_id, quantidade, valor, status, criado_em, updated_at
          from loja.pedidos
         where criado_em::date = current_date - 1
        """,
    )
    conn.commit()
    print(f"Duplicados: {linhas} linhas copiadas (mesma chave pedido_id + item_id).")
    print("Rode: dbt run --profiles-dir dbt --project-dir dbt && sentinela run")


def schema(conn) -> None:
    _exec(conn, "alter table analytics.fct_vendas add column if not exists campo_intruso text")
    conn.commit()
    print("Schema: coluna 'campo_intruso' adicionada em analytics.fct_vendas.")
    print("Rode APENAS: sentinela run   (se rodar dbt, a tabela é reconstruída e o desvio some)")


def reparar(conn) -> None:
    _exec(conn, "alter table analytics.fct_vendas drop column if exists campo_intruso")
    conn.commit()
    repopular(conn)
    print("Ambiente reparado: dataset recriado e coluna intrusa removida.")
    print("Rode: dbt run --profiles-dir dbt --project-dir dbt && sentinela run")


ACOES = {
    "apagao": apagao,
    "defasagem": defasagem,
    "nulos": nulos,
    "duplicados": duplicados,
    "schema": schema,
    "reparar": reparar,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Injeta falhas no ambiente de demo.")
    parser.add_argument("falha", choices=COMANDOS, help="tipo de falha a injetar")
    args = parser.parse_args()

    print(f"> {args.falha}: {EXPLICACAO[args.falha]}\n")

    conn = psycopg2.connect(Config.from_env().dsn)
    try:
        ACOES[args.falha](conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
