"""Dashboard de confiabilidade (Streamlit).

Quatro visões:
    Visão geral  -- estado atual de cada verificação
    Incidentes   -- abertos e histórico, com MTTR e alcance
    Histórico    -- série temporal de uma métrica
    Lineage      -- grafo de dependências do dbt
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
import streamlit as st

from sentinela import store
from sentinela.config import Config
from sentinela.durations import humanizar
from sentinela.lineage import carregar_manifest, construir_grafo, _indice_modelos

st.set_page_config(page_title="Sentinela", page_icon="🛡️", layout="wide")

MANIFEST = Path("dbt/target/manifest.json")

STATUS_EMOJI = {"ok": "🟢", "warn": "🟡", "error": "🔴"}
SEVERIDADE_EMOJI = {"baixa": "🔵", "media": "🟠", "alta": "🔴"}


def _conexao():
    return psycopg2.connect(Config.from_env().dsn)


@st.cache_data(ttl=10)
def carregar_estado() -> tuple[pd.DataFrame, dict, pd.DataFrame, pd.DataFrame]:
    conn = _conexao()
    try:
        status = pd.DataFrame(store.ultimo_status_por_check(conn))
        resumo = store.resumo(conn)
        abertos = pd.DataFrame(store.listar_incidentes(conn, apenas_abertos=True, limite=200))
        todos = pd.DataFrame(store.listar_incidentes(conn, apenas_abertos=False, limite=200))
    finally:
        conn.close()

    if not status.empty:
        status["status"] = status["status"].map(lambda s: f"{STATUS_EMOJI.get(s, '')} {s}")

    return status, resumo, abertos, todos


@st.cache_data(ttl=10)
def carregar_historico(dataset: str, check: str) -> pd.DataFrame:
    conn = _conexao()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select executed_at, value, status
                  from meta.check_result
                 where dataset = %s and check_name = %s
                 order by executed_at
                """,
                (dataset, check),
            )
            linhas = cur.fetchall()
    finally:
        conn.close()

    return pd.DataFrame(linhas, columns=["executed_at", "value", "status"])


def grafo_dot(manifest: dict) -> str:
    grafo = construir_grafo(manifest)
    nomes = {uid: nome for nome, uid in _indice_modelos(manifest).items()}

    linhas = ["digraph G {", "  rankdir=LR;", '  node [shape=box, style="rounded,filled", fillcolor="#e8f0fe", fontname="Helvetica"];']
    for uid, nome in nomes.items():
        linhas.append(f'  "{nome}";')
    for origem, destinos in grafo.items():
        for destino in destinos:
            if origem in nomes and destino in nomes:
                linhas.append(f'  "{nomes[origem]}" -> "{nomes[destino]}";')
    linhas.append("}")
    return "\n".join(linhas)


# --------------------------------------------------------------------------
st.sidebar.title("🛡️ Sentinela")
st.sidebar.caption("Confiabilidade de dados: SLOs, lineage e incidentes")

pagina = st.sidebar.radio(
    "Visão",
    ["Visão geral", "Incidentes", "Histórico", "Lineage"],
    label_visibility="collapsed",
)

if st.sidebar.button("Atualizar agora"):
    st.cache_data.clear()

status, resumo, abertos, todos = carregar_estado()

# --------------------------------------------------------------------------
if pagina == "Visão geral":
    st.title("Visão geral")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Incidentes abertos", int(resumo.get("abertos") or 0))
    c2.metric("Resolvidos", int(resumo.get("resolvidos") or 0))
    c3.metric("MTTR médio", humanizar(resumo.get("mttr_medio_segundos")))
    ultima = resumo.get("ultima_execucao")
    c4.metric("Última execução", ultima.strftime("%d/%m %H:%M") if ultima else "-")

    if status.empty:
        st.info("Nenhuma verificação executada ainda. Rode `python -m sentinela run`.")
    else:
        st.subheader("Estado atual por verificação")
        filtro = st.multiselect(
            "Filtrar por status",
            options=sorted(status["status"].unique().tolist()),
            default=sorted(status["status"].unique().tolist()),
        )
        tabela = status[status["status"].isin(filtro)] if filtro else status
        st.dataframe(
            tabela[["status", "dataset", "check_name", "value", "unit", "message", "executed_at"]],
            use_container_width=True,
            hide_index=True,
        )

        total = len(status)
        erros = int(status["status"].str.contains("error").sum())
        warns = int(status["status"].str.contains("warn").sum())
        st.progress(
            (total - erros - warns) / total if total else 1.0,
            text=f"{total - erros - warns} de {total} verificações saudáveis",
        )

    if not abertos.empty:
        st.subheader("Incidentes abertos")
        st.dataframe(
            abertos[["severity", "dataset", "check_name", "title", "opened_at", "blast_radius"]],
            use_container_width=True,
            hide_index=True,
        )

# --------------------------------------------------------------------------
elif pagina == "Incidentes":
    st.title("Incidentes")

    if abertos.empty:
        st.success("Nenhum incidente aberto. Plataforma saudável.")
    else:
        for _, linha in abertos.iterrows():
            alcance = linha.get("blast_radius") or []
            titulo = f"{SEVERIDADE_EMOJI.get(linha['severity'], '')} {linha['title']}"
            with st.expander(titulo, expanded=False):
                st.write(f"**Severidade:** {linha['severity']}")
                st.write(f"**Descrição:** {linha['message']}")
                st.write(f"**Aberto em:** {linha['opened_at']}")
                if alcance:
                    st.write(f"**Alcance ({len(alcance)} modelo(s)):** {', '.join(alcance)}")
                else:
                    st.write("**Alcance:** nenhum modelo downstream")

    st.divider()
    st.subheader("Histórico")
    if todos.empty:
        st.caption("Sem histórico ainda.")
    else:
        historico = todos.copy()
        historico["mttr"] = historico["mttr_seconds"].map(humanizar)
        st.dataframe(
            historico[["severity", "dataset", "check_name", "status", "opened_at", "resolved_at", "mttr"]],
            use_container_width=True,
            hide_index=True,
        )

        resolvidos = todos[todos["mttr_seconds"].notna()]
        if not resolvidos.empty:
            st.caption(
                f"MTTR médio: {humanizar(resolvidos['mttr_seconds'].mean())} · "
                f"maior: {humanizar(resolvidos['mttr_seconds'].max())} · "
                f"menor: {humanizar(resolvidos['mttr_seconds'].min())}"
            )

# --------------------------------------------------------------------------
elif pagina == "Histórico":
    st.title("Histórico de uma métrica")

    if status.empty:
        st.info("Nenhuma verificação executada ainda.")
    else:
        col1, col2 = st.columns(2)
        dataset = col1.selectbox("Dataset", sorted(status["dataset"].unique()))
        opcoes_check = sorted(status[status["dataset"] == dataset]["check_name"].unique())
        check = col2.selectbox("Verificação", opcoes_check)

        historico = carregar_historico(dataset, check)

        if historico.empty or historico["value"].isna().all():
            st.info("Esta verificação não registra valor numérico.")
        else:
            serie = historico.dropna(subset=["value"]).set_index("executed_at")["value"]
            st.line_chart(serie)
            st.dataframe(historico.sort_values("executed_at", ascending=False), use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------
elif pagina == "Lineage":
    st.title("Lineage (dbt)")

    manifest = carregar_manifest(MANIFEST)
    if manifest is None:
        st.warning("Manifest não encontrado. Rode `dbt run` para gerar dbt/target/manifest.json.")
    else:
        st.graphviz_chart(grafo_dot(manifest))
        st.caption("Setas apontam de quem depende para quem é dependente. Um incidente em `stg_pedidos` afeta tudo que está à direita.")
