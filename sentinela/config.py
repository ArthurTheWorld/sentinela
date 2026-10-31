"""Configuração via variáveis de ambiente (nada de segredo no código)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    dsn: str

    @classmethod
    def from_env(cls) -> "Config":
        dsn = os.getenv("DATABASE_URL", "").strip()
        if dsn:
            return cls(dsn=dsn)

        host = os.getenv("PGHOST", "localhost")
        porta = os.getenv("PGPORT", "5432")
        banco = os.getenv("PGDATABASE", "sentinela")
        usuario = os.getenv("PGUSER", "sentinela")
        senha = os.getenv("PGPASSWORD", "sentinela")

        return cls(
            dsn=f"host={host} port={porta} dbname={banco} user={usuario} password={senha}"
        )
