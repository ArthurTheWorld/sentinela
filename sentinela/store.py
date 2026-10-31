"""Persistência do estado de confiabilidade no Postgres.

Duas tabelas:
    meta.check_result  -- histórico de cada verificação executada
    meta.incident      -- incidentes (abertos/resolvidos) com MTTR

O índice único parcial garante, no nível do banco, que existe no máximo um
incidente aberto por fingerprint — a deduplicação não depende só do código.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from sentinela.models import CheckResult, Severidade

log = logging.getLogger(__name__)

SCHEMA = "meta"

DDL = f"""
create schema if not exists {SCHEMA};

create table if not exists {SCHEMA}.check_result (
    id          bigserial primary key,
    executed_at timestamptz      not null default now(),
    dataset     text             not null,
    check_name  text             not null,
    status      text             not null,
    value       double precision,
    unit        text,
    message     text,
    details     jsonb            not null default '{{}}'::jsonb,
    duration_ms integer
);

create index if not exists idx_check_result_dataset
    on {SCHEMA}.check_result (dataset, executed_at desc);

create table if not exists {SCHEMA}.incident (
    id           bigserial primary key,
    fingerprint  text        not null,
    dataset      text        not null,
    check_name   text        not null,
    severity     text        not null,
    status       text        not null default 'aberto',
    title        text        not null,
    message      text,
    blast_radius jsonb       not null default '[]'::jsonb,
    opened_at    timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    resolved_at  timestamptz,
    mttr_seconds integer,
    diagnosis    jsonb
);

-- Migração para bancos criados antes do diagnóstico assistido.
alter table {SCHEMA}.incident add column if not exists diagnosis jsonb;

create unique index if not exists uq_incident_aberto
    on {SCHEMA}.incident (fingerprint) where status = 'aberto';

create index if not exists idx_incident_dataset
    on {SCHEMA}.incident (dataset, opened_at desc);
"""


def conectar(dsn: str):
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    return conn


def garantir_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def _json_seguro(obj: Any) -> Any:
    """Remove valores que o JSON do Postgres não aceita (NaN, ±Infinity)."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {chave: _json_seguro(valor) for chave, valor in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_seguro(valor) for valor in obj]
    return obj


def salvar_resultado(conn, resultado: CheckResult) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into meta.check_result
                (executed_at, dataset, check_name, status, value, unit, message, details, duration_ms)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                resultado.executed_at,
                resultado.dataset,
                resultado.check,
                resultado.status.value,
                resultado.value,
                resultado.unit,
                resultado.message,
                Json(_json_seguro(resultado.details), dumps=lambda obj: json.dumps(obj, default=str)),
                resultado.duration_ms,
            ),
        )
    conn.commit()


def buscar_incidente_aberto(conn, fingerprint: str) -> dict[str, Any] | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "select * from meta.incident where fingerprint = %s and status = 'aberto' limit 1",
            (fingerprint,),
        )
        linha = cur.fetchone()
    return dict(linha) if linha else None


def abrir_incidente(
    conn,
    resultado: CheckResult,
    gravidade: Severidade,
    alcance: list[str],
    *,
    titulo: str,
    descricao: str,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into meta.incident
                (fingerprint, dataset, check_name, severity, title, message, blast_radius)
            values (%s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                resultado.fingerprint,
                resultado.dataset,
                resultado.check,
                gravidade.value,
                titulo,
                descricao,
                Json(alcance),
            ),
        )
        incidente_id = int(cur.fetchone()[0])
    conn.commit()
    return incidente_id


def atualizar_incidente(conn, incidente_id: int, resultado: CheckResult) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update meta.incident
               set last_seen_at = now(),
                   message = %s,
                   blast_radius = coalesce(blast_radius, '[]'::jsonb)
             where id = %s
            """,
            (resultado.message, incidente_id),
        )
    conn.commit()


def resolver_incidente(conn, incidente_id: int) -> float | None:
    """Fecha o incidente e devolve o MTTR em segundos."""
    with conn.cursor() as cur:
        cur.execute(
            """
            update meta.incident
               set status = 'resolvido',
                   resolved_at = now(),
                   mttr_seconds = greatest(0, extract(epoch from (now() - opened_at))::int)
             where id = %s
            returning mttr_seconds
            """,
            (incidente_id,),
        )
        linha = cur.fetchone()
    conn.commit()
    return float(linha[0]) if linha and linha[0] is not None else None


def listar_incidentes(conn, *, apenas_abertos: bool = True, limite: int = 50) -> list[dict[str, Any]]:
    condicao = "where status = 'aberto'" if apenas_abertos else ""
    consulta = f"""
        select id, dataset, check_name, severity, status, title,
               opened_at, last_seen_at, resolved_at, mttr_seconds, blast_radius, diagnosis
        from meta.incident
        {condicao}
        order by opened_at desc
        limit %s
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(consulta, (limite,))
        return [dict(linha) for linha in cur.fetchall()]


def ultimo_status_por_check(conn) -> list[dict[str, Any]]:
    """Última execução de cada verificação (estado atual da plataforma)."""
    consulta = """
        select distinct on (dataset, check_name)
               dataset, check_name, status, value, unit, message, executed_at
          from meta.check_result
         order by dataset, check_name, executed_at desc
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(consulta)
        return [dict(linha) for linha in cur.fetchall()]


def resumo(conn) -> dict[str, Any]:
    consulta = """
        select
          (select count(*) from meta.incident where status = 'aberto')            as abertos,
          (select count(*) from meta.incident where status = 'resolvido')         as resolvidos,
          (select round(avg(mttr_seconds)) from meta.incident
            where mttr_seconds is not null)                                       as mttr_medio_segundos,
          (select count(*) from meta.check_result)                                as execucoes,
          (select max(executed_at) from meta.check_result)                        as ultima_execucao
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(consulta)
        return dict(cur.fetchone())


def historico(conn, dataset: str, check: str, *, limite: int = 50) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            select executed_at, status, value, unit, message
              from meta.check_result
             where dataset = %s and check_name = %s
             order by executed_at desc
             limit %s
            """,
            (dataset, check, limite),
        )
        return [dict(linha) for linha in cur.fetchall()]


def buscar_incidente(conn, incidente_id: int | None = None) -> dict[str, Any] | None:
    """Busca um incidente por id ou, sem id, o aberto mais recente."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if incidente_id is None:
            cur.execute(
                "select * from meta.incident where status = 'aberto' order by opened_at desc limit 1"
            )
        else:
            cur.execute("select * from meta.incident where id = %s", (incidente_id,))
        linha = cur.fetchone()
    return dict(linha) if linha else None


def ultimos_status_do_dataset(conn, dataset: str) -> dict[str, str]:
    """Último status de cada verificação do dataset (sinais vizinhos)."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            select distinct on (check_name) check_name, status
              from meta.check_result
             where dataset = %s
             order by check_name, executed_at desc
            """,
            (dataset,),
        )
        return {linha["check_name"]: linha["status"] for linha in cur.fetchall()}


def salvar_diagnostico(conn, incidente_id: int, diagnostico: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update meta.incident set diagnosis = %s where id = %s",
            (
                Json(diagnostico, dumps=lambda obj: json.dumps(obj, default=str, ensure_ascii=False)),
                incidente_id,
            ),
        )
    conn.commit()
