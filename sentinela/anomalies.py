"""Estatística robusta: mediana, MAD e baseline sazonal.

Por que não usar média e desvio-padrão?
---------------------------------------
Um único dia com pico (Black Friday) infla a média e o desvio, mascarando
quedas reais nos dias seguintes. Mediana + MAD (desvio absoluto mediano)
resistem a outliers — é a mesma ideia usada em detecção de anomalia com
séries sazonais.
"""

from __future__ import annotations

from datetime import date
from statistics import median
from typing import Sequence

# Constante que torna o MAD comparável ao desvio-padrão de uma normal.
_FATOR_MAD = 0.6745


def mediana(valores: Sequence[float]) -> float:
    if not valores:
        raise ValueError("Não é possível calcular mediana de uma série vazia.")
    return float(median(valores))


def mad(valores: Sequence[float]) -> float:
    """Desvio absoluto mediano."""
    if not valores:
        raise ValueError("Não é possível calcular MAD de uma série vazia.")
    centro = mediana(valores)
    return float(median([abs(valor - centro) for valor in valores]))


def robust_z(valor: float, base: Sequence[float]) -> float | None:
    """Z-score robusto: (valor - mediana) / (1.4826 * MAD).

    Devolve None quando a base é vazia. Quando o MAD é zero (base perfeitamente
    estável), qualquer desvio é tratado como infinito — exceto se o valor for
    exatamente a mediana.
    """
    if not base:
        return None

    centro = mediana(base)
    dispersao = mad(base)

    if dispersao == 0:
        return 0.0 if valor == centro else float("inf") * (1 if valor > centro else -1)

    return _FATOR_MAD * (valor - centro) / dispersao


def baseline_sazonal(
    serie: Sequence[tuple[date, int]],
    *,
    referencia: date | None = None,
    semanas: int = 4,
) -> list[int]:
    """Valores de dias com o mesmo dia da semana, nas N semanas anteriores.

    Segunda-feira é comparada com segundas-feiras. É isso que evita o alerta
    falso de domingo: o volume cai todo domingo, então a queda não é incidente.
    """
    if not serie:
        return []

    ordenada = sorted(serie, key=lambda item: item[0])
    ultima_data = referencia or ordenada[-1][0]
    dia_semana = ultima_data.weekday()

    candidatos = [
        total
        for dia, total in ordenada
        if dia < ultima_data and dia.weekday() == dia_semana
    ]
    return candidatos[-semanas:]
