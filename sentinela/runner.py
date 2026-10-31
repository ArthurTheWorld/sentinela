"""Orquestração de uma run completa de verificação.

Fluxo:
    1. carrega contratos
    2. executa cada verificação e grava o resultado
    3. decide o que fazer com o incidente (abrir/atualizar/resolver)
    4. agrega um relatório para o CLI e para o scheduler
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sentinela import store
from sentinela.checks import executar_checks
from sentinela.contract import Contrato
from sentinela.durations import humanizar
from sentinela.incidents import Acao, decidir_acao, descricao, severidade, titulo
from sentinela.lineage import blast_radius
from sentinela.models import CheckResult, Status

log = logging.getLogger(__name__)


@dataclass
class Relatorio:
    total: int = 0
    ok: int = 0
    warn: int = 0
    error: int = 0
    incidentes_abertos: list[str] = field(default_factory=list)
    incidentes_resolvidos: list[str] = field(default_factory=list)
    resultados: list[CheckResult] = field(default_factory=list)
    duracao_ms: int = 0

    @property
    def saudavel(self) -> bool:
        return self.error == 0


def executar_contratos(
    conn,
    contratos: list[Contrato],
    manifest: dict[str, Any] | None = None,
) -> Relatorio:
    store.garantir_schema(conn)
    relatorio = Relatorio()
    inicio = time.perf_counter()

    for contrato in contratos:
        resultados = executar_checks(conn, contrato)
        alcance = blast_radius(manifest, contrato.dataset)

        for resultado in resultados:
            relatorio.resultados.append(resultado)
            relatorio.total += 1

            if resultado.status is Status.OK:
                relatorio.ok += 1
            elif resultado.status is Status.WARN:
                relatorio.warn += 1
            else:
                relatorio.error += 1

            store.salvar_resultado(conn, resultado)

            aberto = store.buscar_incidente_aberto(conn, resultado.fingerprint)
            acao = decidir_acao(resultado.status, aberto is not None)

            if acao is Acao.ABRIR:
                gravidade = severidade(resultado, alcance, contrato.critico)
                store.abrir_incidente(
                    conn,
                    resultado,
                    gravidade,
                    alcance,
                    titulo=titulo(resultado),
                    descricao=descricao(resultado),
                )
                relatorio.incidentes_abertos.append(resultado.fingerprint)
                log.warning(
                    "Incidente aberto [%s] %s (%s) — alcance: %s",
                    gravidade.value,
                    resultado.fingerprint,
                    resultado.message,
                    alcance or "nenhum modelo downstream",
                )

            elif acao is Acao.ATUALIZAR and aberto is not None:
                store.atualizar_incidente(conn, int(aberto["id"]), resultado)

            elif acao is Acao.RESOLVER and aberto is not None:
                mttr = store.resolver_incidente(conn, int(aberto["id"]))
                relatorio.incidentes_resolvidos.append(resultado.fingerprint)
                log.info(
                    "Incidente resolvido %s — MTTR %s",
                    resultado.fingerprint,
                    humanizar(mttr),
                )

    relatorio.duracao_ms = int((time.perf_counter() - inicio) * 1000)
    return relatorio
