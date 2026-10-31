"""Testes do diagnóstico assistido (motor de regras, sem LLM)."""

from __future__ import annotations

import pytest

from sentinela.diagnosis import (
    Contexto,
    Hipotese,
    diagnosticar,
    diagnosticar_por_regras,
    montar_contexto,
)

INCIDENTE = {
    "id": 7,
    "dataset": "fct_vendas",
    "check_name": "volume",
    "severity": "alta",
    "message": "0 linhas em 2026-10-30",
    "blast_radius": ["mart_receita_diaria"],
}


def _contexto(**kwargs) -> Contexto:
    padrao = dict(
        dataset="fct_vendas",
        check="volume",
        severidade="alta",
        mensagem="queda",
        valor=100.0,
    )
    padrao.update(kwargs)
    return Contexto(**padrao)


def test_volume_zerado_sugere_origem_sem_dados():
    hipoteses = diagnosticar_por_regras(_contexto(valor=100.0))

    assert hipoteses[0].causa.startswith("Origem sem dados")
    assert hipoteses[0].confianca >= 0.8
    assert hipoteses[0].runbook == "docs/runbooks/volume-caiu.md"


def test_volume_parcial_sugere_filtro_ou_sazonalidade():
    hipoteses = diagnosticar_por_regras(_contexto(valor=40.0))

    assert "Queda parcial" in hipoteses[0].causa


def test_sinais_cruzados_elevam_confianca_de_interrupcao():
    hipoteses = diagnosticar_por_regras(
        _contexto(valor=100.0, sinais={"volume": "error", "freshness": "error"})
    )

    assert hipoteses[0].causa.startswith("Interrupção total")
    assert hipoteses[0].confianca > 0.9


def test_frescor_alto_sugere_ingestao_parada():
    hipoteses = diagnosticar_por_regras(_contexto(check="freshness", valor=8 * 3600))

    assert "Ingestão parada" in hipoteses[0].causa
    assert hipoteses[0].runbook == "docs/runbooks/dados-defasados.md"


def test_schema_sugere_contrato_desatualizado():
    hipoteses = diagnosticar_por_regras(_contexto(check="schema", valor=10.0))

    assert "contrato" in hipoteses[0].causa.lower()
    assert hipoteses[0].runbook == "docs/runbooks/schema-mudou.md"


def test_uniqueness_sugere_reprocessamento():
    hipoteses = diagnosticar_por_regras(_contexto(check="uniqueness", valor=2.0))

    assert "Reprocessamento" in hipoteses[0].causa


def test_blast_radius_entra_como_hipotese_de_impacto():
    hipoteses = diagnosticar_por_regras(
        _contexto(check="null_rate", valor=10.0, blast_radius=("mart_receita_diaria",))
    )

    causas = [h.causa for h in hipoteses]
    assert any("Impacto propagado" in causa for causa in causas)


def test_hipoteses_ordenadas_e_limitadas():
    hipoteses = diagnosticar_por_regras(_contexto(sinais={"volume": "error", "freshness": "error"}))

    confiancas = [h.confianca for h in hipoteses]
    assert confiancas == sorted(confiancas, reverse=True)
    assert len(hipoteses) <= 5


def test_diagnosticar_sem_llm_cai_para_regras(monkeypatch):
    monkeypatch.delenv("SENTINELA_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    diagnostico = diagnosticar(_contexto())

    assert diagnostico.provider == "regras"
    assert diagnostico.principal is not None


def test_diagnosticar_llm_falha_e_faz_fallback(monkeypatch):
    monkeypatch.setenv("SENTINELA_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "chave-invalida")

    def explode(*args, **kwargs):
        raise RuntimeError("sem rede")

    monkeypatch.setattr("sentinela.diagnosis._chamar_openai", explode)

    diagnostico = diagnosticar(_contexto())

    assert diagnostico.provider == "regras"


def test_montar_contexto_extrai_valor_e_upstream(manifest):
    contexto = montar_contexto(
        {**INCIDENTE, "dataset": "fct_vendas"},
        historico=[{"value": 72.5, "status": "error"}],
        sinais={"volume": "error"},
        manifest=manifest,
    )

    assert contexto.valor == 72.5
    assert contexto.upstream == ("stg_pagamentos", "stg_pedidos")
    assert contexto.sinais["volume"] == "error"


def test_montar_contexto_sem_historico_nao_quebra():
    contexto = montar_contexto(INCIDENTE)

    assert contexto.valor is None
    assert contexto.upstream == ()


def test_hipotese_serializa_confianca_arredondada():
    hipotese = Hipotese(causa="x", confianca=0.876, evidencia="e", acao="a")

    assert hipotese.to_dict()["confianca"] == 0.88
