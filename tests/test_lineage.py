"""Testes do grafo de lineage e do cálculo de alcance."""

from __future__ import annotations

from sentinela.lineage import (
    blast_radius,
    construir_grafo,
    downstream,
    severidade_por_alcance,
)
from sentinela.models import Severidade


def test_grafo_tem_uma_entrada_por_modelo(manifest):
    grafo = construir_grafo(manifest)

    assert len(grafo) == 6
    assert "model.sentinela_demo.stg_pedidos" in grafo


def test_downstream_de_stg_pedidos(manifest):
    grafo = construir_grafo(manifest)

    afetados = downstream(grafo, "model.sentinela_demo.stg_pedidos")

    assert afetados == [
        "model.sentinela_demo.fct_vendas",
        "model.sentinela_demo.mart_receita_diaria",
    ]


def test_downstream_de_modelo_folha_e_vazio(manifest):
    grafo = construir_grafo(manifest)

    assert downstream(grafo, "model.sentinela_demo.mart_receita_diaria") == []


def test_blast_radius_por_nome(manifest):
    assert blast_radius(manifest, "fct_vendas") == ["mart_receita_diaria"]


def test_blast_radius_modelo_inexistente(manifest):
    assert blast_radius(manifest, "nao_existe") == []


def test_blast_radius_sem_manifest():
    assert blast_radius(None, "fct_vendas") == []


def test_severidade_por_alcance():
    assert severidade_por_alcance([]) is Severidade.BAIXA
    assert severidade_por_alcance(["a"]) is Severidade.MEDIA
    assert severidade_por_alcance(["a", "b", "c"]) is Severidade.ALTA


def test_severidade_dataset_critico_sobe_para_alta():
    assert severidade_por_alcance([], critico=True) is Severidade.ALTA
