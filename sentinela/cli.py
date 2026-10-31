"""Interface de linha de comando do Sentinela.

    sentinela run            # executa as verificações de todos os contratos
    sentinela status         # estado atual da plataforma
    sentinela incidentes     # incidentes abertos (ou --todos)
    sentinela alcance MODELO # impacto de um modelo no lineage do dbt
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from sentinela import __version__, store
from sentinela.config import Config
from sentinela.contract import carregar_contratos
from sentinela.durations import humanizar
from sentinela.lineage import blast_radius, carregar_manifest
from sentinela.models import Status
from sentinela.runner import executar_contratos

DIRETORIO_PADRAO = "contracts"
MANIFEST_PADRAO = "dbt/target/manifest.json"

ROTULO = {
    Status.OK: "OK  ",
    Status.WARN: "WARN",
    Status.ERROR: "ERRO",
}


def _colar(texto: str, largura: int) -> str:
    texto = str(texto)
    return texto[: largura - 1].ljust(largura) if len(texto) >= largura else texto.ljust(largura)


def _imprimir_tabela(cabecalho: list[str], linhas: list[list[str]], larguras: list[int]) -> None:
    print("  ".join(_colar(titulo, largura) for titulo, largura in zip(cabecalho, larguras)))
    print("  ".join("-" * largura for largura in larguras))
    for linha in linhas:
        print("  ".join(_colar(valor, largura) for valor, largura in zip(linha, larguras)))


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------
def cmd_run(args: argparse.Namespace) -> int:
    contratos = carregar_contratos(Path(args.contratos))
    manifest = carregar_manifest(args.manifest)

    config = Config.from_env()
    conn = store.conectar(config.dsn)

    try:
        relatorio = executar_contratos(conn, contratos, manifest)
    finally:
        conn.close()

    linhas = []
    for resultado in relatorio.resultados:
        linhas.append(
            [
                ROTULO[resultado.status],
                resultado.dataset,
                resultado.check,
                f"{resultado.duration_ms}ms",
                resultado.message,
            ]
        )

    print()
    _imprimir_tabela(
        ["STATUS", "DATASET", "CHECK", "TEMPO", "DETALHE"],
        linhas,
        [6, 18, 18, 7, 70],
    )
    print()
    print(
        f"{relatorio.total} verificações: "
        f"{relatorio.ok} ok, {relatorio.warn} warn, {relatorio.error} erro "
        f"em {relatorio.duracao_ms}ms"
    )

    if relatorio.incidentes_abertos:
        print(f"Incidentes abertos ({len(relatorio.incidentes_abertos)}):")
        for fingerprint in relatorio.incidentes_abertos:
            print(f"  + {fingerprint}")

    if relatorio.incidentes_resolvidos:
        print(f"Incidentes resolvidos ({len(relatorio.incidentes_resolvidos)}):")
        for fingerprint in relatorio.incidentes_resolvidos:
            print(f"  - {fingerprint}")

    if not relatorio.saudavel and not args.ignorar_erros:
        print("\nFalha: existem verificações em ERRO.", file=sys.stderr)
        return 1

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = Config.from_env()
    conn = store.conectar(config.dsn)
    try:
        resultados = store.ultimo_status_por_check(conn)
        resumo = store.resumo(conn)
    finally:
        conn.close()

    if not resultados:
        print("Nenhuma verificação executada ainda. Rode: sentinela run")
        return 0

    linhas = [
        [
            ROTULO[Status(r["status"])],
            r["dataset"],
            r["check_name"],
            "" if r["value"] is None else f"{r['value']:g}{r['unit'] or ''}",
            r["executed_at"].strftime("%d/%m %H:%M"),
            (r["message"] or "")[:50],
        ]
        for r in resultados
    ]

    _imprimir_tabela(
        ["STATUS", "DATASET", "CHECK", "VALOR", "QUANDO", "DETALHE"],
        linhas,
        [6, 18, 18, 12, 12, 50],
    )

    print()
    print(
        f"Incidentes abertos: {resumo['abertos']} | "
        f"resolvidos: {resumo['resolvidos']} | "
        f"MTTR médio: {humanizar(resumo['mttr_medio_segundos'])} | "
        f"verificações registradas: {resumo['execucoes']}"
    )
    return 0


def cmd_incidentes(args: argparse.Namespace) -> int:
    config = Config.from_env()
    conn = store.conectar(config.dsn)
    try:
        incidentes = store.listar_incidentes(conn, apenas_abertos=not args.todos)
    finally:
        conn.close()

    if not incidentes:
        print("Nenhum incidente aberto. Plataforma saudável." if not args.todos else "Nenhum incidente registrado.")
        return 0

    linhas = []
    for incidente in incidentes:
        aberto_em = incidente["opened_at"]
        if incidente["resolved_at"]:
            quando = f"resolvido em {humanizar(incidente['mttr_seconds'])}"
        else:
            referencia = incidente["opened_at"].tzinfo or timezone.utc
            aberto_ha = (datetime.now(referencia) - incidente["opened_at"]).total_seconds()
            quando = f"aberto há {humanizar(aberto_ha)}"
        linhas.append(
            [
                incidente["severity"].upper(),
                incidente["dataset"],
                incidente["check_name"],
                incidente["status"],
                quando,
                ", ".join(incidente["blast_radius"] or []) or "-",
            ]
        )

    _imprimir_tabela(
        ["SEV", "DATASET", "CHECK", "STATUS", "DURACAO", "ALCANCE"],
        linhas,
        [6, 18, 18, 10, 18, 45],
    )
    return 0


def cmd_alcance(args: argparse.Namespace) -> int:
    manifest = carregar_manifest(args.manifest)
    if manifest is None:
        print(f"Manifest não encontrado: {args.manifest}")
        print("Gere com: dbt parse (ou dbt run).")
        return 1

    afetados = blast_radius(manifest, args.modelo)
    if not afetados:
        print(f"Nenhum modelo downstream de {args.modelo} (ou modelo inexistente).")
        return 0

    print(f"Se {args.modelo} falhar, ficam comprometidos {len(afetados)} modelo(s):")
    for modelo in afetados:
        print(f"  - {modelo}")
    return 0


# --------------------------------------------------------------------------
def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentinela",
        description="Sentinela — confiabilidade de dados com SLOs, lineage e incidentes.",
    )
    parser.add_argument("--versao", action="version", version=f"sentinela {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)

    run = sub.add_parser("run", help="executa as verificações dos contratos")
    run.add_argument("--contratos", default=DIRETORIO_PADRAO, help="diretório de contratos YAML")
    run.add_argument("--manifest", default=MANIFEST_PADRAO, help="caminho do manifest.json do dbt")
    run.add_argument("--ignorar-erros", action="store_true", help="sai com código 0 mesmo com erro")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="estado atual de todas as verificações")
    status.set_defaults(func=cmd_status)

    incidentes = sub.add_parser("incidentes", help="lista incidentes")
    incidentes.add_argument("--todos", action="store_true", help="inclui resolvidos")
    incidentes.set_defaults(func=cmd_incidentes)

    alcance = sub.add_parser("alcance", help="modelos downstream de um modelo no dbt")
    alcance.add_argument("modelo", help="nome do modelo (ex.: stg_pedidos)")
    alcance.add_argument("--manifest", default=MANIFEST_PADRAO)
    alcance.set_defaults(func=cmd_alcance)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
