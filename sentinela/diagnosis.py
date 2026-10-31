"""Diagnóstico assistido de incidentes.

Duas camadas, de propósito:

1. **Regras** (padrão, offline) — heurísticas determinísticas a partir do tipo
   de verificação, do valor medido e dos sinais vizinhos do mesmo dataset.
   Funciona sem chave de API, então qualquer pessoa que clonar o repositório
   consegue rodar.
2. **LLM** (opcional) — quando configurado, recebe o mesmo contexto e devolve
   hipóteses ranqueadas. Se falhar, cai de volta para as regras: diagnóstico
   nunca pode ser um ponto único de falha.

O diagnóstico é gravado no incidente (auditável), não apenas impresso.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

import requests

log = logging.getLogger(__name__)

MAX_HIPOTESES = 5
RUNBOOKS = {
    "freshness": "docs/runbooks/dados-defasados.md",
    "volume": "docs/runbooks/volume-caiu.md",
    "schema": "docs/runbooks/schema-mudou.md",
}


@dataclass(frozen=True)
class Hipotese:
    causa: str
    confianca: float
    evidencia: str
    acao: str
    runbook: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "causa": self.causa,
            "confianca": round(self.confianca, 2),
            "evidencia": self.evidencia,
            "acao": self.acao,
            "runbook": self.runbook,
        }


@dataclass(frozen=True)
class Contexto:
    """Tudo que o motor de diagnóstico precisa saber sobre o incidente."""

    dataset: str
    check: str
    severidade: str
    mensagem: str
    valor: float | None = None
    blast_radius: tuple[str, ...] = ()
    upstream: tuple[str, ...] = ()
    sinais: dict[str, str] = field(default_factory=dict)
    historico: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "check": self.check,
            "severidade": self.severidade,
            "mensagem": self.mensagem,
            "valor": self.valor,
            "blast_radius": list(self.blast_radius),
            "upstream": list(self.upstream),
            "sinais_do_mesmo_dataset": self.sinais,
            "historico": list(self.historico[:10]),
        }


@dataclass(frozen=True)
class Diagnostico:
    provider: str
    hipoteses: tuple[Hipotese, ...]
    gerado_em: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    incidente_id: int | None = None

    @property
    def principal(self) -> Hipotese | None:
        return self.hipoteses[0] if self.hipoteses else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "gerado_em": self.gerado_em.isoformat(),
            "incidente_id": self.incidente_id,
            "hipoteses": [h.to_dict() for h in self.hipoteses],
        }


# --------------------------------------------------------------------------
# Motor de regras (offline)
# --------------------------------------------------------------------------
def _runbook_para(check: str) -> str | None:
    base = check.split(":")[0]
    return RUNBOOKS.get(base)


def diagnosticar_por_regras(contexto: Contexto) -> list[Hipotese]:
    """Heurísticas determinísticas, ordenadas por confiança."""
    check = contexto.check
    sinais = {k.split(":")[0]: v for k, v in contexto.sinais.items()}
    hipoteses: list[Hipotese] = []

    def add(causa: str, confianca: float, evidencia: str, acao: str) -> None:
        hipoteses.append(
            Hipotese(
                causa=causa,
                confianca=max(0.0, min(1.0, confianca)),
                evidencia=evidencia,
                acao=acao,
                runbook=_runbook_para(check),
            )
        )

    # Sinal cruzado: volume e frescor juntos = interrupção total da ingestão.
    if sinais.get("volume") == "error" and sinais.get("freshness") == "error":
        add(
            "Interrupção total da ingestão (origem ou scheduler)",
            confianca=0.92,
            evidencia="volume e frescor falharam no mesmo dataset, na mesma execução",
            acao="Verificar o job de ingestão e o scheduler antes de mexer no dbt",
        )

    if check == "freshness":
        valor = contexto.valor or 0
        if valor >= 6 * 3600:
            add(
                "Ingestão parada na origem",
                confianca=0.75,
                evidencia=f"último registro há {valor / 3600:.1f}h",
                acao="Conferir o pipeline de origem e acionar o dono do contrato",
            )
        add(
            "DAG do dbt não executou (ou falhou silenciosamente)",
            confianca=0.45,
            evidencia="a camada analítica reflete o último build",
            acao="Rodar `dbt run` e conferir o histórico do scheduler",
        )
        add(
            "Registro com timestamp futuro (relógio/timezone divergente)",
            confianca=0.20,
            evidencia="idade pode ficar negativa se a origem usar outro fuso",
            acao="Comparar `now()` do banco com o relógio da aplicação",
        )

    elif check == "volume":
        valor = contexto.valor or 0
        if valor >= 90:
            add(
                "Origem sem dados no período (ingestão interrompida)",
                confianca=0.85,
                evidencia=f"queda de {valor:.0f}% contra o baseline sazonal",
                acao="Verificar contagem na tabela de origem antes de qualquer reprocessamento",
            )
            add(
                "Filtro ou join removeu as linhas",
                confianca=0.40,
                evidencia="o volume caiu mas a origem pode estar intacta",
                acao="Conferir WHERE e joins do modelo em relação à última release",
            )
        else:
            add(
                "Queda parcial: filtro/join alterado ou sazonalidade não prevista",
                confianca=0.55,
                evidencia=f"queda de {valor:.0f}% contra a mediana do mesmo dia da semana",
                acao="Comparar com feriados/promoções e revisar o diff do modelo",
            )

    elif check == "null_rate":
        add(
            "Coluna passou a vir nula na origem",
            confianca=0.70,
            evidencia="taxa de nulos acima do limite do contrato",
            acao="Conferir a extração e o mapeamento de colunas na camada de origem",
        )
        add(
            "Join não encontrou correspondência",
            confianca=0.45,
            evidencia="nulos concentrados em coluna de dimensão",
            acao="Validar a chave de join e a integridade referencial",
        )

    elif check == "uniqueness":
        add(
            "Reprocessamento sem idempotência",
            confianca=0.75,
            evidencia="chave duplicada no snapshot",
            acao="Verificar se a carga usa UPSERT/MERGE por chave",
        )
        add(
            "Duplicação na origem",
            confianca=0.55,
            evidencia="o modelo apenas reflete o que veio",
            acao="Consultar a origem pela chave duplicada",
        )

    elif check == "schema":
        add(
            "Mudança de schema sem atualizar o contrato",
            confianca=0.80,
            evidencia="colunas diferentes das declaradas no contrato",
            acao="Atualizar o contrato no mesmo PR ou reverter o modelo",
        )

    elif check.startswith("custom:"):
        add(
            "Regra de negócio violada",
            confianca=0.60,
            evidencia="SQL customizado retornou linhas acima do limite",
            acao="Inspecionar as linhas retornadas pelo SQL do contrato",
        )

    else:
        add(
            "Verificação desconhecida",
            confianca=0.30,
            evidencia=f"check {check!r} sem heurística específica",
            acao="Ampliar o motor de regras para este tipo de verificação",
        )

    # Impacto nunca é causa, mas ajuda a priorizar.
    if contexto.blast_radius:
        add(
            f"Impacto propagado para {len(contexto.blast_radius)} modelo(s)",
            confianca=0.50,
            evidencia=", ".join(contexto.blast_radius),
            acao="Revalidar os modelos downstream depois da correção",
        )

    return _normalizar(hipoteses)


def _normalizar(hipoteses: Sequence[Hipotese]) -> list[Hipotese]:
    """Remove duplicatas, ordena por confiança e limita a quantidade."""
    vistos: set[str] = set()
    unicas: list[Hipotese] = []
    for hipotese in hipoteses:
        if hipotese.causa in vistos:
            continue
        vistos.add(hipotese.causa)
        unicas.append(hipotese)
    unicas.sort(key=lambda h: h.confianca, reverse=True)
    return unicas[:MAX_HIPOTESES]


# --------------------------------------------------------------------------
# Motor LLM (opcional)
# --------------------------------------------------------------------------
PROMPT = """Você é um engenheiro de dados sênior diagnosticando um incidente de qualidade de dados.

Contexto do incidente (JSON):
{contexto}

Responda APENAS com JSON válido, sem markdown, no formato:
{{"hipoteses": [{{"causa": "...", "confianca": 0.0, "evidencia": "...", "acao": "...", "runbook": null}}]}}

Regras: no máximo 5 hipóteses, confiança entre 0 e 1, causas específicas
(evite "erro humano"), e cada hipótese deve citar uma evidência do contexto."""


def _provider_configurado() -> tuple[str, str, str]:
    provider = os.getenv("SENTINELA_LLM_PROVIDER", "").strip().lower()
    modelo = os.getenv("SENTINELA_LLM_MODEL", "").strip()

    if provider == "openai":
        return provider, os.getenv("OPENAI_API_KEY", "").strip(), modelo or "gpt-4o-mini"
    if provider == "gemini":
        return provider, os.getenv("GEMINI_API_KEY", "").strip(), modelo or "gemini-2.0-flash"
    return "", "", ""


def _chamar_openai(chave: str, modelo: str, contexto: Contexto) -> str:
    resposta = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
        json={
            "model": modelo,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT.format(
                        contexto=json.dumps(contexto.to_dict(), ensure_ascii=False, default=str)
                    ),
                }
            ],
        },
        timeout=60,
    )
    resposta.raise_for_status()
    return resposta.json()["choices"][0]["message"]["content"]


def _chamar_gemini(chave: str, modelo: str, contexto: Contexto) -> str:
    resposta = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
        params={"key": chave},
        json={
            "contents": [
                {
                    "parts": [
                        {
                            "text": PROMPT.format(
                                contexto=json.dumps(contexto.to_dict(), ensure_ascii=False, default=str)
                            )
                        }
                    ]
                }
            ]
        },
        timeout=60,
    )
    resposta.raise_for_status()
    return resposta.json()["candidates"][0]["content"]["parts"][0]["text"]


def diagnosticar_com_llm(contexto: Contexto) -> list[Hipotese]:
    """Consulta o LLM configurado. Levanta exceção se não estiver pronto."""
    provider, chave, modelo = _provider_configurado()
    if not provider or not chave:
        raise RuntimeError("Nenhum provedor de LLM configurado.")

    texto = (
        _chamar_openai(chave, modelo, contexto)
        if provider == "openai"
        else _chamar_gemini(chave, modelo, contexto)
    )

    dados = json.loads(texto)
    hipoteses = [
        Hipotese(
            causa=str(item.get("causa", "Causa não identificada")),
            confianca=float(item.get("confianca", 0.5)),
            evidencia=str(item.get("evidencia", "")),
            acao=str(item.get("acao", "")),
            runbook=item.get("runbook"),
        )
        for item in dados.get("hipoteses", [])
        if isinstance(item, dict)
    ]
    if not hipoteses:
        raise ValueError("LLM não devolveu hipóteses.")
    return _normalizar(hipoteses)


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------
def montar_contexto(
    incidente: dict[str, Any],
    *,
    historico: Sequence[dict[str, Any]] = (),
    sinais: dict[str, str] | None = None,
    manifest: dict[str, Any] | None = None,
) -> Contexto:
    """Monta o contexto do diagnóstico a partir do incidente e do histórico."""
    from sentinela.lineage import upstream as modelos_upstream

    dataset = str(incidente.get("dataset", ""))
    valor = None
    for linha in historico:
        if linha.get("value") is not None:
            valor = float(linha["value"])
            break

    return Contexto(
        dataset=dataset,
        check=str(incidente.get("check_name", "")),
        severidade=str(incidente.get("severity", "")),
        mensagem=str(incidente.get("message") or ""),
        valor=valor,
        blast_radius=tuple(incidente.get("blast_radius") or ()),
        upstream=tuple(modelos_upstream(manifest, dataset)),
        sinais=dict(sinais or {}),
        historico=tuple(historico),
    )


def diagnosticar(contexto: Contexto, provider: str = "auto") -> Diagnostico:
    """Escolhe o motor, com fallback para regras em qualquer falha do LLM."""
    if provider in {"auto", "", "llm"}:
        provider, chave, _ = _provider_configurado()
        if provider and chave:
            try:
                return Diagnostico(provider=f"llm:{provider}", hipoteses=tuple(diagnosticar_com_llm(contexto)))
            except Exception as exc:  # noqa: BLE001 - diagnóstico não pode derrubar a run
                log.warning("LLM falhou (%s); caindo para regras.", exc)

    return Diagnostico(provider="regras", hipoteses=tuple(diagnosticar_por_regras(contexto)))
