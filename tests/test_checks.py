"""Testes das partes puras de checks (classificação e SQL seguro)."""

from __future__ import annotations

import pytest

pytest.importorskip("psycopg2")

from sentinela.checks import IdentificadorInvalido, classificar, referenciar
from sentinela.models import Status


@pytest.mark.parametrize(
    ("valor", "aviso", "erro", "esperado"),
    [
        (0, 2, 5, Status.OK),
        (2, 2, 5, Status.OK),      # igual ao limiar de aviso ainda é aceitável
        (2.1, 2, 5, Status.WARN),
        (4.9, 2, 5, Status.WARN),
        (5, 2, 5, Status.WARN),    # igual ao limiar de erro ainda é aceitável
        (5.1, 2, 5, Status.ERROR),
        (10, 2, 5, Status.ERROR),
        (1, None, 5, Status.OK),
        (1, 2, None, Status.OK),
    ],
)
def test_classificar_maior_e_pior(valor, aviso, erro, esperado):
    assert classificar(valor, aviso=aviso, erro=erro) is esperado


@pytest.mark.parametrize(
    ("valor", "aviso", "erro", "esperado"),
    [
        (100, 50, 20, Status.OK),
        (50, 50, 20, Status.OK),
        (49, 50, 20, Status.WARN),
        (20, 50, 20, Status.WARN),
        (19, 50, 20, Status.ERROR),
    ],
)
def test_classificar_menor_e_pior(valor, aviso, erro, esperado):
    assert classificar(valor, aviso=aviso, erro=erro, maior_e_pior=False) is esperado


def test_referenciar_schema_tabela():
    composto = referenciar("analytics.fct_vendas")

    assert "analytics" in composto.as_string(None)
    assert "fct_vendas" in composto.as_string(None)


@pytest.mark.parametrize(
    "tabela",
    [
        "analytics.fct_vendas; drop table x",
        "fct_vendas",
        "a.b.c",
        "schema.tabela--",
        "",
    ],
)
def test_referenciar_rejeita_identificador_invalido(tabela):
    with pytest.raises(IdentificadorInvalido):
        referenciar(tabela)
