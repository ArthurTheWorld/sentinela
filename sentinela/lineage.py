"""Lineage a partir do manifest do dbt.

O manifest é gerado por `dbt parse`/`dbt run` e diz, para cada modelo, de
quais outros modelos ele depende. Invertendo as arestas, sabemos o que está
*abaixo* de um modelo — é assim que calculamos o alcance de um incidente:
se `stg_pedidos` quebra, quais marts ficam comprometidos?
"""

from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path
from typing import Any

from sentinela.models import Severidade

log = logging.getLogger(__name__)


def carregar_manifest(caminho: str | Path | None) -> dict[str, Any] | None:
    """Lê o manifest.json; devolve None se o arquivo não existir."""
    if not caminho:
        return None

    arquivo = Path(caminho)
    if not arquivo.exists():
        log.warning("Manifest do dbt não encontrado em %s; seguindo sem lineage.", arquivo)
        return None

    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.warning("Manifest inválido (%s); seguindo sem lineage.", exc)
        return None


def _indice_modelos(manifest: dict[str, Any]) -> dict[str, str]:
    """nome do modelo -> unique_id."""
    indices: dict[str, str] = {}
    for unique_id, no in (manifest.get("nodes") or {}).items():
        if no.get("resource_type") == "model":
            indices[no.get("name", unique_id)] = unique_id
    return indices


def construir_grafo(manifest: dict[str, Any]) -> dict[str, set[str]]:
    """Adjacência de *downstream*: nó -> nós que dependem dele."""
    modelos = _indice_modelos(manifest)
    grafo: dict[str, set[str]] = {uid: set() for uid in modelos.values()}

    for unique_id, no in (manifest.get("nodes") or {}).items():
        if unique_id not in grafo:
            continue
        for dependencia in (no.get("depends_on") or {}).get("nodes") or []:
            if dependencia in grafo:  # só modelos; sources ficam de fora
                grafo[dependencia].add(unique_id)

    return grafo


def downstream(grafo: dict[str, set[str]], inicio: str) -> list[str]:
    """Todos os nós alcançáveis a partir de `inicio` (BFS, sem ciclos)."""
    vistos: set[str] = set()
    fila: deque[str] = deque([inicio])

    while fila:
        atual = fila.popleft()
        for filho in grafo.get(atual, set()):
            if filho not in vistos and filho != inicio:
                vistos.add(filho)
                fila.append(filho)

    return sorted(vistos)


def blast_radius(manifest: dict[str, Any] | None, modelo: str) -> list[str]:
    """Nomes dos modelos afetados se `modelo` falhar (vazio sem manifest)."""
    if not manifest:
        return []

    indices = _indice_modelos(manifest)
    if modelo not in indices:
        return []

    grafo = construir_grafo(manifest)
    afetados = downstream(grafo, indices[modelo])

    por_id = {uid: nome for nome, uid in indices.items()}
    return sorted(por_id[uid] for uid in afetados if uid in por_id)


def severidade_por_alcance(alcance: list[str], critico: bool = False) -> Severidade:
    """Quanto maior o alcance, mais grave — e ativo crítico sempre é alta."""
    if critico or len(alcance) >= 3:
        return Severidade.ALTA
    if alcance:
        return Severidade.MEDIA
    return Severidade.BAIXA
