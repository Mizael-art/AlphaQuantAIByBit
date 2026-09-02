"""
setups/schema.py
===================

Schema do "candidato a setup" recebido por `POST /setups` -- o mesmo
formato serve tanto para um scanner/Discovery Engine (fases futuras)
quanto para o GPT registrar manualmente um setup identificado numa
conversa, hoje.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from setups.lifecycle import ALL_STATUSES


class EntryZone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    low: float
    high: float


class SetupCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    direction: str  # "long" | "short"
    strategy: str
    status: str

    entry_zone: EntryZone | None = None
    trigger: str | None = None
    stop: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    tp3: float | None = None
    rr: float | None = None

    score: float | None = None
    invalidation: str | None = None
    expiration: datetime | None = None

    #: nota de por que este candidato está sendo enviado agora --
    #: vira `reason_for_change` no registro (Documento 2, seção 14).
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_direction_and_status(self) -> "SetupCandidate":
        if self.direction not in ("long", "short"):
            raise ValueError("direction deve ser 'long' ou 'short'.")
        if self.status not in ALL_STATUSES:
            raise ValueError(f"status '{self.status}' não é um estado reconhecido do Setup Lifecycle.")
        return self
