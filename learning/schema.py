"""
learning/schema.py
=====================

Schema de entrada de um sinal externo (Documento 2, seção 30) --
o que o usuário fornece ao registrar uma call de terceiros.
`reconstructed_context` NÃO é preenchido aqui -- é calculado por
`learning/reconstruction.py` a partir de `asset` + `signal_time`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

_VALID_RESULTS = {"win", "loss", "breakeven"}


class ExternalSignalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    direction: str  # "long" | "short"
    timeframe: str
    signal_time: datetime  # quando o sinal foi emitido (não quando foi registrado no sistema)

    entry: float | None = None
    stop: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    tp3: float | None = None
    rr: float | None = None

    source: str
    strategy_guess: str | None = None

    result: str | None = None  # "win" | "loss" | "breakeven" | None (ainda não se sabe)
    r_multiple: float | None = None
    execution_quality: str | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "ExternalSignalInput":
        if self.direction not in ("long", "short"):
            raise ValueError("direction deve ser 'long' ou 'short'.")
        if self.result is not None and self.result not in _VALID_RESULTS:
            raise ValueError(f"result deve ser um de {sorted(_VALID_RESULTS)} ou omitido.")
        return self


class SignalResultUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: str
    r_multiple: float | None = None
    execution_quality: str | None = None

    @model_validator(mode="after")
    def _validate_result(self) -> "SignalResultUpdate":
        if self.result not in _VALID_RESULTS:
            raise ValueError(f"result deve ser um de {sorted(_VALID_RESULTS)}.")
        return self
