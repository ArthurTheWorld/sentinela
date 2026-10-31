"""Testes da regra de deduplicação e classificação de incidentes."""

from __future__ import annotations

import pytest

from sentinela.incidents import Acao, decidir_acao, descricao, severidade, titulo
from sentinela.models import CheckResult, Severidade, Status


@pytest.mark.parametrize(
    ("status", "tem_aberto", "esperado"),
    [
        (Status.ERROR, False, Acao.ABRIR),
        (Status.ERROR, True, Acao.ATUALIZAR),
        (Status.OK, True, Acao.RESOLVER),
        (Status.OK, False, Acao.NADA),
        (Status.WARN, False, Acao.NADA),
        (Status.WARN, True, Acao.NADA),
    ],
)
def test_decidir_acao(status, tem_aberto, esperado):
    assert decidir_acao(status, tem_aberto) is esperado


def test_resultado_fingerprint_e_estavel():
    resultado = CheckResult(dataset="fct_vendas", check="freshness", status=Status.ERROR)

    assert resultado.fingerprint == "fct_vendas:freshness"


def test_titulo_e_descricao():
    resultado = CheckResult(
        dataset="fct_vendas",
        check="volume",
        status=Status.ERROR,
        value=72.5,
        unit="%",
        message="Queda acentuada.",
    )

    assert titulo(resultado) == "fct_vendas :: volume"
    assert "Queda acentuada." in descricao(resultado)
    assert "72.5%" in descricao(resultado)


def test_severidade_sem_alcance():
    resultado = CheckResult(dataset="x", check="y", status=Status.ERROR)

    assert severidade(resultado, []) is Severidade.BAIXA
    assert severidade(resultado, ["a"]) is Severidade.MEDIA
    assert severidade(resultado, [], critico=True) is Severidade.ALTA


def test_pior_status():
    assert Status.WARN.pior(Status.OK) is Status.WARN
    assert Status.OK.pior(Status.ERROR) is Status.ERROR
