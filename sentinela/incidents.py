"""Ciclo de vida do incidente, como funções puras.

Separar essa decisão do banco é o que permite testá-la sem infraestrutura —
e é a parte que mais importa: abrir incidente duplicado toda hora é o
caminho mais curto para o time ignorar os alertas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from sentinela.models import CheckResult, Severidade, Status


class Acao(str, Enum):
    ABRIR = "abrir"
    ATUALIZAR = "atualizar"
    RESOLVER = "resolver"
    NADA = "nada"


def decidir_acao(status: Status, existe_incidente_aberto: bool) -> Acao:
    """Regra de deduplicação do incidente.

    - ERROR sem incidente aberto  -> abre
    - ERROR com incidente aberto  -> atualiza (mesmo incidente)
    - OK com incidente aberto     -> resolve
    - OK sem incidente            -> nada
    - WARN                        -> nada (aparece no painel, não vira incidente)
    """
    if status is Status.OK:
        return Acao.RESOLVER if existe_incidente_aberto else Acao.NADA

    if status is Status.ERROR:
        return Acao.ATUALIZAR if existe_incidente_aberto else Acao.ABRIR

    return Acao.NADA


def severidade(resultado: CheckResult, alcance: list[str], critico: bool = False) -> Severidade:
    """Gravidade derivada do impacto no lineage, não só do status."""
    if critico or len(alcance) >= 3:
        return Severidade.ALTA
    if alcance:
        return Severidade.MEDIA
    return Severidade.BAIXA


def titulo(resultado: CheckResult) -> str:
    return f"{resultado.dataset} :: {resultado.check}"


def descricao(resultado: CheckResult) -> str:
    partes = [resultado.message or "Verificação falhou."]
    if resultado.value is not None:
        unidade = resultado.unit or ""
        partes.append(f"Valor medido: {resultado.value:g}{unidade}.")
    return " ".join(partes)


@dataclass(frozen=True)
class Incidente:
    id: int
    fingerprint: str
    dataset: str
    check: str
    severidade: Severidade
    titulo: str
    descricao: str
    alcance: list[str]
    aberto_em: datetime
    ultima_vez: datetime
    resolvido_em: datetime | None = None
    mttr_segundos: float | None = None

    @property
    def aberto(self) -> bool:
        return self.resolvido_em is None

    @property
    def duracao_segundos(self) -> float:
        fim = self.resolvido_em or datetime.now(timezone.utc)
        return (fim - self.aberto_em).total_seconds()
