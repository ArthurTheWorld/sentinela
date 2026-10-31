"""Testes do parser e validador de contratos."""

from __future__ import annotations

import pytest

from sentinela.contract import (
    ContratoInvalido,
    carregar_contrato,
    carregar_contratos,
    parse_contrato,
)

MINIMO = {"dataset": "fct_vendas", "tabela": "analytics.fct_vendas", "dono": "time-vendas"}


def test_contrato_minimo_sem_checks():
    contrato = parse_contrato(MINIMO)

    assert contrato.dataset == "fct_vendas"
    assert contrato.tabela == "analytics.fct_vendas"
    assert contrato.checks == ()
    assert contrato.critico is False


def test_contrato_completo():
    contrato = parse_contrato(
        {
            **MINIMO,
            "critico": True,
            "checks": {
                "freshness": {"coluna": "updated_at", "aviso_apos": "30m", "erro_apos": "2h"},
                "volume": {"coluna": "criado_em", "queda_aviso_pct": 30, "queda_erro_pct": 60},
                "null_rate": {"colunas": ["cliente_id"], "aviso_acima": 0.02, "erro_acima": 0.05},
                "uniqueness": {"colunas": ["pedido_id", "item_id"]},
                "schema": {"colunas_esperadas": ["pedido_id"]},
                "custom": [
                    {"nome": "valor_negativo", "sql": "select count(*) from {{ tabela }}", "erro_acima": 0}
                ],
            },
        }
    )

    assert contrato.critico is True
    assert contrato.frescor.erro_apos.total_seconds() == 7200
    assert contrato.volume.queda_erro_pct == 60
    assert contrato.nulos.colunas == ("cliente_id",)
    assert contrato.unicidade.colunas == ("pedido_id", "item_id")
    assert contrato.customs[0].nome == "valor_negativo"
    assert "freshness" in contrato.checks
    assert "custom:valor_negativo" in contrato.checks


def test_dataset_obrigatorio():
    with pytest.raises(ContratoInvalido, match="dataset"):
        parse_contrato({"tabela": "x.y", "dono": "time"})


def test_check_desconhecido_falha():
    with pytest.raises(ContratoInvalido, match="desconhecidas"):
        parse_contrato({**MINIMO, "checks": {"frescor": {"coluna": "x"}}})


def test_frescor_com_erro_menor_que_aviso_falha():
    with pytest.raises(ContratoInvalido, match="erro_apos"):
        parse_contrato(
            {
                **MINIMO,
                "checks": {
                    "freshness": {"coluna": "updated_at", "aviso_apos": "2h", "erro_apos": "30m"}
                },
            }
        )


@pytest.mark.parametrize(
    "volume",
    [
        {"coluna": "criado_em", "queda_aviso_pct": 70, "queda_erro_pct": 50},
        {"coluna": "criado_em", "queda_aviso_pct": 0, "queda_erro_pct": 50},
        {"coluna": "criado_em", "queda_aviso_pct": 10, "queda_erro_pct": 120},
    ],
)
def test_volume_com_limiares_incoerentes_falha(volume):
    with pytest.raises(ContratoInvalido, match="volume"):
        parse_contrato({**MINIMO, "checks": {"volume": volume}})


def test_duracao_invalida_no_yaml(tmp_path):
    arquivo = tmp_path / "fct_vendas.yml"
    arquivo.write_text(
        "dataset: fct_vendas\ntabela: analytics.fct_vendas\ndono: time\n"
        "checks:\n  freshness:\n    coluna: updated_at\n    aviso_apos: 'meia hora'\n    erro_apos: 2h\n",
        encoding="utf-8",
    )

    with pytest.raises(ContratoInvalido):
        carregar_contrato(arquivo)


def test_carregar_exige_dataset_igual_ao_arquivo(tmp_path):
    arquivo = tmp_path / "outro_nome.yml"
    arquivo.write_text(
        "dataset: fct_vendas\ntabela: analytics.fct_vendas\ndono: time\n",
        encoding="utf-8",
    )

    with pytest.raises(ContratoInvalido, match="nome do arquivo"):
        carregar_contrato(arquivo)


def test_contratos_do_projeto_carregam():
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]

    contratos = carregar_contratos(raiz / "contracts")

    assert len(contratos) >= 5
    assert all(contrato.checks for contrato in contratos)
