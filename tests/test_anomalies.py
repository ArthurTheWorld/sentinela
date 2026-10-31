"""Testes da estatística robusta e do baseline sazonal."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from sentinela.anomalies import baseline_sazonal, mad, mediana, robust_z


def test_mediana_impar_e_par():
    assert mediana([1, 2, 3]) == 2
    assert mediana([1, 2, 3, 4]) == 2.5


def test_mediana_vazia_falha():
    with pytest.raises(ValueError):
        mediana([])


def test_mad_resiste_a_outlier():
    base = [100, 102, 98, 101, 99]
    assert mad(base) == pytest.approx(1.0)


def test_robust_z_detecta_queda():
    base = [100, 102, 98, 101, 99]
    z = robust_z(40, base)

    assert z is not None
    assert z < -3


def test_robust_z_valor_normal():
    base = [100, 102, 98, 101, 99]
    assert abs(robust_z(101, base)) < 1


def test_robust_z_base_vazia():
    assert robust_z(10, []) is None


def test_robust_z_mad_zero():
    base = [100, 100, 100]
    assert robust_z(100, base) == 0.0
    assert robust_z(90, base) == float("-inf")


def test_baseline_sazonal_pega_mesmo_dia_da_semana():
    # 2026-10-05 é uma segunda-feira.
    segunda = date(2026, 10, 5)
    serie = [(segunda + timedelta(days=7 * i), 100 + i) for i in range(5)]
    serie.append((segunda + timedelta(days=1), 999))  # terça-feira não entra

    base = baseline_sazonal(serie, referencia=segunda + timedelta(days=28), semanas=4)

    assert len(base) == 4
    assert 999 not in base


def test_baseline_sazonal_serie_vazia():
    assert baseline_sazonal([]) == []
