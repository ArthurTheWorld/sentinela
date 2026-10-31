"""Tipos de domínio: status de verificação, severidade e resultado."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Status(str, Enum):
    """Resultado de uma verificação."""

    OK = "ok"
    WARN = "warn"
    ERROR = "error"

    @property
    def peso(self) -> int:
        """Permite comparar status: error > warn > ok."""
        return {"ok": 0, "warn": 1, "error": 2}[self.value]

    def pior(self, outro: "Status") -> "Status":
        return self if self.peso >= outro.peso else outro


class Severidade(str, Enum):
    """Gravidade de um incidente, derivada do alcance (blast radius)."""

    BAIXA = "baixa"
    MEDIA = "media"
    ALTA = "alta"


@dataclass(frozen=True)
class CheckResult:
    """Uma verificação executada sobre um dataset."""

    dataset: str
    check: str
    status: Status
    value: float | None = None
    unit: str | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int = 0

    @property
    def fingerprint(self) -> str:
        """Identidade estável do problema: dataset + verificação.

        Serve para deduplicar incidentes: a mesma verificação falhando dez
        vezes seguidas é um incidente só, não dez.
        """
        return f"{self.dataset}:{self.check}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "check": self.check,
            "status": self.status.value,
            "value": self.value,
            "unit": self.unit,
            "message": self.message,
            "details": self.details,
            "executed_at": self.executed_at.isoformat(),
            "duration_ms": self.duration_ms,
        }
