"""
setups/expiration.py
=======================

Varredura de expiração (Documento 2, seção 14; Documento Master,
seção 34). Nesta fase é uma função chamável sob demanda (endpoint
`POST /setups/sweep-expired`) -- o *scheduler* automático (Render Cron
chamando esse endpoint periodicamente) é trabalho da Fase 7, não
desta. A lógica em si já fica pronta e testada agora, pra Fase 7 só
precisar "apertar o play" nela.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from setups.lifecycle import EXPIRED
from setups.repository import list_setups


def _as_utc(value: datetime) -> datetime:
    """SQLite descarta tzinfo ao ler DateTime(timezone=True) de volta -- trata naive como UTC (Postgres já preserva tzinfo nativamente, isso vira no-op lá)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def sweep_expired(session: Session, now: datetime | None = None) -> list[int]:
    """
    Marca como `EXPIRED` todo setup não-terminal cujo `expiration` já
    passou. Retorna os ids alterados.
    """
    now = now or datetime.now(timezone.utc)
    changed_ids: list[int] = []

    for record in list_setups(session, exclude_terminal=True):
        if record.expiration is not None and _as_utc(record.expiration) <= now:
            record.status = EXPIRED
            record.status_changed_at = now
            record.reason_for_change = f"Expirado automaticamente (expiration={record.expiration.isoformat()})."
            changed_ids.append(record.id)

    if changed_ids:
        session.flush()
    return changed_ids
