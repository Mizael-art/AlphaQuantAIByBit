"""
setups/memory.py
===================

Ponto de entrada único para registrar um candidato a setup
(Documento 2, seções 15 e 41 -- "Setup Memory" / "não repetir tudo").

`upsert_setup` decide, sozinho, se o candidato é um setup novo ou uma
atualização de um já existente (mesmo ativo+direção+estratégia, ainda
em aberto) -- quem chama nunca precisa saber disso de antemão.

O `change_type` retornado é o que alimenta a categorização pedida no
Documento Master, seção 14 / Documento 2, seção 41:
NOVOS / MELHORARAM / PIORARAM / ATIVADOS / INVALIDADOS / EXPIRADOS /
SEM MUDANÇA.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from persistence.models import SetupRecord
from setups.lifecycle import ACTIVE, ENTRY_READY, EXPIRED, INVALIDATED, TRIGGERED, maturity_direction
from setups.repository import apply_update, create_setup, get_open_setup
from setups.schema import SetupCandidate

ChangeType = str  # "new" | "activated" | "invalidated" | "expired" | "improved" | "worsened" | "unchanged"

_ACTIVATION_STATUSES = frozenset({TRIGGERED, ENTRY_READY, ACTIVE})


@dataclass(frozen=True, slots=True)
class UpsertResult:
    record: SetupRecord
    created: bool
    change_type: ChangeType


def _classify_change(previous_status: str, previous_score: float | None, candidate: SetupCandidate) -> ChangeType:
    if candidate.status == INVALIDATED:
        return "invalidated"
    if candidate.status == EXPIRED:
        return "expired"
    if candidate.status in _ACTIVATION_STATUSES and previous_status not in _ACTIVATION_STATUSES:
        return "activated"

    direction = maturity_direction(previous_status, candidate.status)
    if direction == "advanced":
        return "improved"
    if direction == "regressed":
        return "worsened"

    if candidate.score is not None and previous_score is not None:
        if candidate.score > previous_score:
            return "improved"
        if candidate.score < previous_score:
            return "worsened"
    return "unchanged"


def upsert_setup(session: Session, candidate: SetupCandidate) -> UpsertResult:
    existing = get_open_setup(session, candidate.asset, candidate.direction, candidate.strategy)

    if existing is None:
        record = create_setup(session, candidate)
        return UpsertResult(record=record, created=True, change_type="new")

    previous_status = existing.status
    previous_score = existing.score
    change_type = _classify_change(previous_status, previous_score, candidate)
    reason_note = candidate.reason or f"{previous_status} -> {candidate.status}"
    record = apply_update(session, existing, candidate, reason_note)
    return UpsertResult(record=record, created=False, change_type=change_type)
