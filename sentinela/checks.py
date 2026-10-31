"""Verificações de qualidade executadas contra o warehouse.

Cada função recebe a conexão e o contrato, executa uma consulta e devolve um
`CheckResult` com status, valor medido e contexto. Nenhuma regra de negócio
mora aqui: os limiares vêm sempre do contrato.
"""

from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from psycopg2 import sql

from sentinela.anomalies import baseline_sazonal, mediana, robust_z
from sentinela.contract import Contrato, RegraCustom
from sentinela.models import CheckResult, Status

log = logging.getLogger(__name__)

_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class IdentificadorInvalido(ValueError):
    """Nome de tabela/coluna fora do padrão — evita injeção de SQL."""


def referenciar(tabela: str) -> sql.Composed:
    """Converte 'schema.tabela' em SQL seguro (identificadores citados)."""
    partes = tabela.split(".")
    if not partes or len(partes) > 2:
        raise IdentificadorInvalido(f"Tabela inválida: {tabela!r} (use schema.tabela).")
    for parte in partes:
        if not _IDENTIFICADOR.match(parte):
            raise IdentificadorInvalido(f"Identificador inválido: {parte!r}")
    return sql.SQL(".").join(sql.Identifier(parte) for parte in partes)


def classificar(
    valor: float,
    *,
    aviso: float | None,
    erro: float | None,
    maior_e_pior: bool = True,
) -> Status:
    """Compara o valor medido com os limiares do contrato.

    Os limiares são "acima de" (ou "abaixo de") — estritamente. Um valor
    exatamente igual ao limiar ainda é aceitável; é o que permite usar
    `erro_acima: 0` para dizer "nenhuma linha" sem que 0 vire erro.
    """
    if erro is not None:
        if (maior_e_pior and valor > erro) or (not maior_e_pior and valor < erro):
            return Status.ERROR
    if aviso is not None:
        if (maior_e_pior and valor > aviso) or (not maior_e_pior and valor < aviso):
            return Status.WARN
    return Status.OK


def _escalar(conn, consulta: sql.Composable, params: tuple = ()) -> Any:
    with conn.cursor() as cur:
        cur.execute(consulta, params)
        linha = cur.fetchone()
        return linha[0] if linha else None


def _resultado(
    contrato: Contrato,
    check: str,
    status: Status,
    *,
    value: float | None = None,
    unit: str | None = None,
    message: str = "",
    details: dict[str, Any] | None = None,
    inicio: float,
) -> CheckResult:
    return CheckResult(
        dataset=contrato.dataset,
        check=check,
        status=status,
        value=value,
        unit=unit,
        message=message,
        details=details or {},
        duration_ms=int((time.perf_counter() - inicio) * 1000),
    )


# --------------------------------------------------------------------------
# freshness
# --------------------------------------------------------------------------
def verificar_frescor(conn, contrato: Contrato) -> CheckResult:
    inicio = time.perf_counter()
    regra = contrato.frescor
    assert regra is not None

    consulta = sql.SQL("select max({coluna}) from {tabela}").format(
        coluna=sql.Identifier(regra.coluna),
        tabela=referenciar(contrato.tabela),
    )
    ultimo = _escalar(conn, consulta)

    if ultimo is None:
        return _resultado(
            contrato,
            "freshness",
            Status.ERROR,
            message="Tabela vazia: não há registro para medir frescor.",
            details={"coluna": regra.coluna},
            inicio=inicio,
        )

    if ultimo.tzinfo is None:
        ultimo = ultimo.replace(tzinfo=timezone.utc)

    # Idade negativa = registro no futuro (relógio divergente ou backfill).
    # Tratamos como 0 ("fresco"), mas registramos a ocorrência no detalhe.
    bruto = (datetime.now(timezone.utc) - ultimo).total_seconds()
    idade_segundos = max(0.0, bruto)

    if idade_segundos >= regra.erro_apos.total_seconds():
        status = Status.ERROR
    elif idade_segundos >= regra.aviso_apos.total_seconds():
        status = Status.WARN
    else:
        status = Status.OK

    return _resultado(
        contrato,
        "freshness",
        status,
        value=round(idade_segundos, 1),
        unit="s",
        message=f"Último registro há {idade_segundos / 60:.1f} min.",
        details={
            "coluna": regra.coluna,
            "ultimo_registro": ultimo.isoformat(),
            "aviso_apos_s": regra.aviso_apos.total_seconds(),
            "erro_apos_s": regra.erro_apos.total_seconds(),
            "registro_no_futuro": bruto < 0,
        },
        inicio=inicio,
    )


# --------------------------------------------------------------------------
# volume
# --------------------------------------------------------------------------
def verificar_volume(conn, contrato: Contrato) -> CheckResult:
    inicio = time.perf_counter()
    regra = contrato.volume
    assert regra is not None

    consulta = sql.SQL(
        """
        select date_trunc('day', {coluna})::date as dia, count(*) as total
        from {tabela}
        where {coluna} >= current_date - (%s * interval '7 days')
        group by 1
        order by 1
        """
    ).format(coluna=sql.Identifier(regra.coluna), tabela=referenciar(contrato.tabela))

    with conn.cursor() as cur:
        cur.execute(consulta, (regra.semanas_base + 1,))
        serie = [(dia, int(total)) for dia, total in cur.fetchall()]

    if not serie:
        return _resultado(
            contrato, "volume", Status.ERROR,
            message="Sem dados no período de análise.",
            details={"coluna": regra.coluna},
            inicio=inicio,
        )

    # O dia analisado é SEMPRE ontem (último dia fechado). Se ontem não tem
    # nenhuma linha, o volume é zero — e isso é queda de 100%, não "sem dado".
    hoje = datetime.now(timezone.utc).date()
    referencia = hoje - timedelta(days=1)
    por_dia = dict(serie)
    valor_atual = por_dia.get(referencia, 0)

    base = baseline_sazonal(serie, referencia=referencia, semanas=regra.semanas_base)

    if not base:
        return _resultado(
            contrato, "volume", Status.OK,
            value=float(valor_atual),
            unit="linhas",
            message="Sem base histórica suficiente para comparar (primeiro dia).",
            details={"serie": [(d.isoformat(), t) for d, t in serie[-7:]]},
            inicio=inicio,
        )

    mediana_base = mediana([float(v) for v in base])
    if mediana_base <= 0:
        queda_pct = 0.0
    else:
        queda_pct = max(0.0, min(100.0, (1 - valor_atual / mediana_base) * 100))

    z = robust_z(float(valor_atual), [float(v) for v in base])

    if queda_pct >= regra.queda_erro_pct:
        status = Status.ERROR
    elif queda_pct >= regra.queda_aviso_pct:
        status = Status.WARN
    else:
        status = Status.OK

    return _resultado(
        contrato,
        "volume",
        status,
        value=round(queda_pct, 2),
        unit="%",
        message=(
            f"{valor_atual} linhas em {referencia.isoformat()}; baseline "
            f"{mediana_base:.0f} (queda de {queda_pct:.1f}%)."
        ),
        details={
            "coluna": regra.coluna,
            "dia_analisado": referencia.isoformat(),
            "valor_atual": valor_atual,
            "baseline_mediana": round(mediana_base, 2),
            "baseline_valores": base,
            # inf não é JSON válido; quando o MAD é zero, registramos None
            "robust_z": round(z, 2) if z is not None and math.isfinite(z) else None,
        },
        inicio=inicio,
    )


# --------------------------------------------------------------------------
# null_rate
# --------------------------------------------------------------------------
def verificar_nulos(conn, contrato: Contrato) -> CheckResult:
    inicio = time.perf_counter()
    regra = contrato.nulos
    assert regra is not None

    por_coluna: dict[str, float] = {}

    for coluna in regra.colunas:
        consulta = sql.SQL(
            """
            select coalesce(
                count(*) filter (where {coluna} is null)::numeric
                / nullif(count(*), 0), 0)
            from {tabela}
            """
        ).format(coluna=sql.Identifier(coluna), tabela=referenciar(contrato.tabela))
        por_coluna[coluna] = float(_escalar(conn, consulta) or 0)

    pior_coluna = max(por_coluna, key=por_coluna.get)
    pior_taxa = por_coluna[pior_coluna]

    if pior_taxa >= regra.erro_acima:
        status = Status.ERROR
    elif pior_taxa >= regra.aviso_acima:
        status = Status.WARN
    else:
        status = Status.OK

    return _resultado(
        contrato,
        "null_rate",
        status,
        value=round(pior_taxa * 100, 2),
        unit="%",
        message=f"Coluna {pior_coluna}: {pior_taxa * 100:.2f}% nulos.",
        details={
            "por_coluna": {c: round(t * 100, 4) for c, t in por_coluna.items()},
            "aviso_acima": regra.aviso_acima,
            "erro_acima": regra.erro_acima,
        },
        inicio=inicio,
    )


# --------------------------------------------------------------------------
# uniqueness
# --------------------------------------------------------------------------
def verificar_unicidade(conn, contrato: Contrato) -> CheckResult:
    inicio = time.perf_counter()
    regra = contrato.unicidade
    assert regra is not None

    chave = sql.SQL(", ").join(sql.Identifier(coluna) for coluna in regra.colunas)
    consulta = sql.SQL(
        """
        select coalesce(
            (count(*) - count(distinct ({chave})))::numeric / nullif(count(*), 0),
        0)
        from {tabela}
        """
    ).format(chave=chave, tabela=referenciar(contrato.tabela))

    taxa = float(_escalar(conn, consulta) or 0)
    status = Status.ERROR if taxa > regra.erro_acima else Status.OK

    return _resultado(
        contrato,
        "uniqueness",
        status,
        value=round(taxa * 100, 4),
        unit="%",
        message=f"{taxa * 100:.4f}% de linhas duplicadas em {', '.join(regra.colunas)}.",
        details={"colunas": list(regra.colunas), "erro_acima": regra.erro_acima},
        inicio=inicio,
    )


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------
def verificar_schema(conn, contrato: Contrato) -> CheckResult:
    inicio = time.perf_counter()
    regra = contrato.schema
    assert regra is not None

    schema_nome, tabela_nome = contrato.tabela.split(".")
    consulta = sql.SQL(
        """
        select column_name
        from information_schema.columns
        where table_schema = %s and table_name = %s
        order by ordinal_position
        """
    )
    with conn.cursor() as cur:
        cur.execute(consulta, (schema_nome, tabela_nome))
        atuais = [linha[0] for linha in cur.fetchall()]

    esperadas = list(regra.colunas_esperadas)
    faltando = [c for c in esperadas if c not in atuais]
    extras = [c for c in atuais if c not in esperadas]

    if faltando:
        status = Status.ERROR
    elif extras and not regra.permitir_extras:
        status = Status.ERROR
    elif extras:
        status = Status.WARN
    else:
        status = Status.OK

    return _resultado(
        contrato,
        "schema",
        status,
        value=float(len(atuais)),
        unit="colunas",
        message=(
            f"{len(atuais)} colunas"
            + (f"; faltando: {faltando}" if faltando else "")
            + (f"; novas: {extras}" if extras else "")
        ),
        details={"faltando": faltando, "extras": extras, "atuais": atuais},
        inicio=inicio,
    )


# --------------------------------------------------------------------------
# custom
# --------------------------------------------------------------------------
def verificar_custom(conn, contrato: Contrato, regra: RegraCustom) -> CheckResult:
    inicio = time.perf_counter()

    sql_renderizado = regra.sql.replace("{{ tabela }}", contrato.tabela)

    with conn.cursor() as cur:
        cur.execute(sql_renderizado)
        linha = cur.fetchone()
        valor = float(linha[0]) if linha and linha[0] is not None else 0.0

    status = classificar(valor, aviso=regra.aviso_acima, erro=regra.erro_acima)

    return _resultado(
        contrato,
        f"custom:{regra.nome}",
        status,
        value=valor,
        unit=regra.unidade,
        message=f"{regra.nome}: {valor:g} {regra.unidade}.",
        details={"sql": sql_renderizado, "erro_acima": regra.erro_acima},
        inicio=inicio,
    )


# --------------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------------
def executar_checks(conn, contrato: Contrato) -> list[CheckResult]:
    """Roda todas as verificações declaradas no contrato, na ordem do contrato."""
    executores: list[Callable] = [
        (lambda: verificar_frescor(conn, contrato)) if contrato.frescor else None,
        (lambda: verificar_volume(conn, contrato)) if contrato.volume else None,
        (lambda: verificar_nulos(conn, contrato)) if contrato.nulos else None,
        (lambda: verificar_unicidade(conn, contrato)) if contrato.unicidade else None,
        (lambda: verificar_schema(conn, contrato)) if contrato.schema else None,
    ]

    resultados: list[CheckResult] = []
    for executar in filter(None, executores):
        try:
            resultados.append(executar())
        except Exception as exc:  # noqa: BLE001 - falha de um check não derruba a run
            log.exception("Falha ao executar check de %s", contrato.dataset)
            resultados.append(
                CheckResult(
                    dataset=contrato.dataset,
                    check="execucao",
                    status=Status.ERROR,
                    message=f"Erro ao executar verificação: {exc}",
                    details={"erro": repr(exc)},
                )
            )

    for regra in contrato.customs:
        try:
            resultados.append(verificar_custom(conn, contrato, regra))
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha no check custom %s", regra.nome)
            resultados.append(
                CheckResult(
                    dataset=contrato.dataset,
                    check=f"custom:{regra.nome}",
                    status=Status.ERROR,
                    message=f"Erro ao executar SQL customizado: {exc}",
                    details={"erro": repr(exc)},
                )
            )

    return resultados
