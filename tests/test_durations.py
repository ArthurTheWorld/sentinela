"""Testes de parsing de duração."""

from __future__ import annotations

from datetime import timedelta

import pytest

from sentinela.durations import DuracaoInvalida, humanizar, parse_duracao


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("30m", timedelta(minutes=30)),
        ("2h", timedelta(hours=2)),
        ("1d", timedelta(days=1)),
        ("45s", timedelta(seconds=45)),
        ("1.5h", timedelta(hours=1, minutes=30)),
        (" 90 min ", timedelta(minutes=90)),
    ],
)
def test_parse_duracao_valida(texto, esperado):
    assert parse_duracao(texto) == esperado


@pytest.mark.parametrize("texto", ["", "abc", "30", "30x", "-5m"])
def test_parse_duracao_invalida(texto):
    with pytest.raises(DuracaoInvalida):
        parse_duracao(texto)


def test_parse_duracao_aceita_timedelta():
    valor = timedelta(minutes=15)
    assert parse_duracao(valor) is valor


@pytest.mark.parametrize(
    ("segundos", "esperado"),
    [
        (None, "-"),
        (45, "45s"),
        (1800, "30min"),
        (7200, "2.0h"),
        (172800, "2.0d"),
    ],
)
def test_humanizar(segundos, esperado):
    assert humanizar(segundos) == esperado
