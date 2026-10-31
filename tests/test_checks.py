"""Testes das partes puras de checks (classificação e SQL seguro)."""

from __future__ import annotations

import pytest

pytest.importorskip("psycopg2")

from sentinela.checks import IdentificadorInvalido, classificar, referenciar, validar_tabela
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


def test_validar_tabela_aceita_schema_e_tabela():
    assert validar_tabela("analytics.fct_vendas") == ("analytics", "fct_vendas")


def test_referenciar_devolve_sql_composavel():
    composto = referenciar("analytics.fct_vendas")

    # as_string exigiria uma conexão real; aqui basta garantir que é SQL válido
    assert hasattr(composto, "as_string")


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
