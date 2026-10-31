"""Leitura e escrita de durações legíveis ("30m", "2h", "1d")."""

from __future__ import annotations

import re
from datetime import timedelta

_UNIDADES = {
    "s": 1,
    "seg": 1,
    "segundo": 1,
    "segundos": 1,
    "m": 60,
    "min": 60,
    "minuto": 60,
    "minutos": 60,
    "h": 3600,
    "hora": 3600,
    "horas": 3600,
    "d": 86400,
    "dia": 86400,
    "dias": 86400,
}

_PADRAO = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([a-z]+)\s*$", re.IGNORECASE)


class DuracaoInvalida(ValueError):
    """Texto de duração que não segue o formato esperado."""


def parse_duracao(texto: str) -> timedelta:
    """Converte "30m", "2h", "1.5d" em timedelta.

    >>> parse_duracao("2h")
    datetime.timedelta(seconds=7200)
    """
    if isinstance(texto, timedelta):
        return texto

    combinacao = _PADRAO.match(str(texto))
    if not combinacao:
        raise DuracaoInvalida(
            f"Duração inválida: {texto!r}. Use algo como '30m', '2h' ou '1d'."
        )

    numero, unidade = combinacao.group(1), combinacao.group(2).lower()
    if unidade not in _UNIDADES:
        raise DuracaoInvalida(
            f"Unidade desconhecida em {texto!r}: {unidade!r}. "
            f"Use uma de: {sorted(set(_UNIDADES))}."
        )

    segundos = float(numero.replace(",", ".")) * _UNIDADES[unidade]
    return timedelta(seconds=segundos)


def humanizar(duracao: timedelta | float | None) -> str:
    """Formata segundos/timedelta de forma curta para logs e dashboard."""
    if duracao is None:
        return "-"

    segundos = duracao.total_seconds() if isinstance(duracao, timedelta) else float(duracao)
    if segundos < 60:
        return f"{segundos:.0f}s"
    if segundos < 3600:
        return f"{segundos / 60:.0f}min"
    if segundos < 86400:
        return f"{segundos / 3600:.1f}h"
    return f"{segundos / 86400:.1f}d"
