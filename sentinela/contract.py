"""Contratos de SLO: o YAML que descreve o que significa "dado saudável".

Cada contrato declara um dataset, seu dono e as verificações que precisam
passar. O contrato é a interface entre quem produz o dado e quem consome:
mudar um limiar é uma decisão registrada em código, revisável em PR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from sentinela.durations import DuracaoInvalida, parse_duracao

_yaml = YAML(typ="safe")

CHECKS_CONHECIDOS = {"freshness", "volume", "null_rate", "uniqueness", "schema", "custom"}


class ContratoInvalido(ValueError):
    """Contrato malformado — falha cedo, com mensagem acionável."""


# --------------------------------------------------------------------------
# Regras
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RegraFrescor:
    coluna: str
    aviso_apos: Any
    erro_apos: Any


@dataclass(frozen=True)
class RegraVolume:
    coluna: str
    queda_aviso_pct: float
    queda_erro_pct: float
    semanas_base: int = 4


@dataclass(frozen=True)
class RegraNulos:
    colunas: tuple[str, ...]
    aviso_acima: float
    erro_acima: float


@dataclass(frozen=True)
class RegraUnicidade:
    colunas: tuple[str, ...]
    erro_acima: float = 0.0


@dataclass(frozen=True)
class RegraSchema:
    colunas_esperadas: tuple[str, ...]
    permitir_extras: bool = True


@dataclass(frozen=True)
class RegraCustom:
    nome: str
    sql: str
    erro_acima: float = 0.0
    aviso_acima: float | None = None
    unidade: str = "linhas"


@dataclass(frozen=True)
class Contrato:
    dataset: str
    tabela: str
    dono: str
    descricao: str = ""
    critico: bool = False
    frescor: RegraFrescor | None = None
    volume: RegraVolume | None = None
    nulos: RegraNulos | None = None
    unicidade: RegraUnicidade | None = None
    schema: RegraSchema | None = None
    customs: tuple[RegraCustom, ...] = field(default_factory=tuple)

    @property
    def checks(self) -> tuple[str, ...]:
        """Nomes das verificações declaradas neste contrato."""
        nomes: list[str] = []
        if self.frescor:
            nomes.append("freshness")
        if self.volume:
            nomes.append("volume")
        if self.nulos:
            nomes.append("null_rate")
        if self.unicidade:
            nomes.append("uniqueness")
        if self.schema:
            nomes.append("schema")
        nomes.extend(f"custom:{c.nome}" for c in self.customs)
        return tuple(nomes)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def _exigir(mapa: dict, chave: str, contexto: str) -> Any:
    if chave not in mapa:
        raise ContratoInvalido(f"{contexto}: campo obrigatório ausente: {chave!r}")
    return mapa[chave]


def _duracao_obrigatoria(bruto: dict, chave: str, contexto: str) -> Any:
    """Lê uma duração e traduz o erro para o contexto do contrato."""
    try:
        return parse_duracao(_exigir(bruto, chave, contexto))
    except DuracaoInvalida as exc:
        raise ContratoInvalido(f"{contexto}.{chave}: {exc}") from exc


def _parse_frescor(bruto: dict) -> RegraFrescor:
    coluna = _exigir(bruto, "coluna", "freshness")
    aviso = _duracao_obrigatoria(bruto, "aviso_apos", "freshness")
    erro = _duracao_obrigatoria(bruto, "erro_apos", "freshness")
    if erro < aviso:
        raise ContratoInvalido("freshness: 'erro_apos' não pode ser menor que 'aviso_apos'.")
    return RegraFrescor(coluna=coluna, aviso_apos=aviso, erro_apos=erro)


def _parse_volume(bruto: dict) -> RegraVolume:
    coluna = _exigir(bruto, "coluna", "volume")
    aviso = float(_exigir(bruto, "queda_aviso_pct", "volume"))
    erro = float(_exigir(bruto, "queda_erro_pct", "volume"))
    if not (0 < aviso <= erro <= 100):
        raise ContratoInvalido(
            "volume: exige 0 < queda_aviso_pct <= queda_erro_pct <= 100."
        )
    return RegraVolume(
        coluna=coluna,
        queda_aviso_pct=aviso,
        queda_erro_pct=erro,
        semanas_base=int(bruto.get("semanas_base", 4)),
    )


def _parse_nulos(bruto: dict) -> RegraNulos:
    colunas = tuple(_exigir(bruto, "colunas", "null_rate"))
    if not colunas:
        raise ContratoInvalido("null_rate: informe ao menos uma coluna.")
    return RegraNulos(
        colunas=colunas,
        aviso_acima=float(_exigir(bruto, "aviso_acima", "null_rate")),
        erro_acima=float(_exigir(bruto, "erro_acima", "null_rate")),
    )


def _parse_unicidade(bruto: dict) -> RegraUnicidade:
    return RegraUnicidade(
        colunas=tuple(_exigir(bruto, "colunas", "uniqueness")),
        erro_acima=float(bruto.get("erro_acima", 0.0)),
    )


def _parse_schema(bruto: dict) -> RegraSchema:
    return RegraSchema(
        colunas_esperadas=tuple(_exigir(bruto, "colunas_esperadas", "schema")),
        permitir_extras=bool(bruto.get("permitir_extras", True)),
    )


def _parse_custom(bruto: dict) -> RegraCustom:
    return RegraCustom(
        nome=str(_exigir(bruto, "nome", "custom")),
        sql=str(_exigir(bruto, "sql", "custom")),
        erro_acima=float(bruto.get("erro_acima", 0.0)),
        aviso_acima=bruto.get("aviso_acima"),
        unidade=str(bruto.get("unidade", "linhas")),
    )


def parse_contrato(bruto: dict[str, Any], origem: str = "<memoria>") -> Contrato:
    """Valida e converte o dicionário do YAML em um Contrato tipado."""
    if not isinstance(bruto, dict):
        raise ContratoInvalido(f"{origem}: o contrato precisa ser um mapa YAML.")

    checks = bruto.get("checks") or {}
    desconhecidos = set(checks) - CHECKS_CONHECIDOS
    if desconhecidos:
        raise ContratoInvalido(
            f"{origem}: verificações desconhecidas: {sorted(desconhecidos)}. "
            f"Disponíveis: {sorted(CHECKS_CONHECIDOS)}."
        )

    return Contrato(
        dataset=str(_exigir(bruto, "dataset", origem)),
        tabela=str(_exigir(bruto, "tabela", origem)),
        dono=str(_exigir(bruto, "dono", origem)),
        descricao=str(bruto.get("descricao", "")),
        critico=bool(bruto.get("critico", False)),
        frescor=_parse_frescor(checks["freshness"]) if "freshness" in checks else None,
        volume=_parse_volume(checks["volume"]) if "volume" in checks else None,
        nulos=_parse_nulos(checks["null_rate"]) if "null_rate" in checks else None,
        unicidade=_parse_unicidade(checks["uniqueness"]) if "uniqueness" in checks else None,
        schema=_parse_schema(checks["schema"]) if "schema" in checks else None,
        customs=tuple(_parse_custom(c) for c in checks.get("custom", [])),
    )


def carregar_contrato(caminho: Path) -> Contrato:
    if not caminho.exists():
        raise ContratoInvalido(f"Contrato não encontrado: {caminho}")

    bruto = _yaml.load(caminho.read_text(encoding="utf-8"))
    contrato = parse_contrato(bruto, origem=str(caminho))

    if contrato.dataset != caminho.stem:
        raise ContratoInvalido(
            f"{caminho.name}: 'dataset' ({contrato.dataset}) deve ser igual ao "
            f"nome do arquivo sem extensão ({caminho.stem})."
        )
    return contrato


def carregar_contratos(diretorio: Path) -> list[Contrato]:
    """Carrega todos os .yml/.yaml de um diretório, ordenados por nome."""
    if not diretorio.is_dir():
        raise ContratoInvalido(f"Diretório de contratos inexistente: {diretorio}")

    arquivos = sorted(
        [*diretorio.glob("*.yml"), *diretorio.glob("*.yaml")],
        key=lambda p: p.name,
    )
    if not arquivos:
        raise ContratoInvalido(f"Nenhum contrato encontrado em {diretorio}")

    return [carregar_contrato(arquivo) for arquivo in arquivos]
