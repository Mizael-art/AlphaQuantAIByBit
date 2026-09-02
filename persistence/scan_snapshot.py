"""
persistence/scan_snapshot.py
==============================

Save/load do resultado mais recente do scan de fundo (`ScanSnapshot`).
Camada fina sobre `persistence/db.py` -- mesmo padrão de
`setups/memory.py`: nenhum código fora daqui/`persistence/db.py` toca
SQLAlchemy diretamente.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from persistence.db import session_scope
from persistence.models import ScanSnapshot

DEFAULT_SCAN_KEY = "all_bybit:4H:1H"


def save_scan_snapshot(
    scan_key: str,
    result_json: dict[str, Any] | None,
    started_at: datetime,
    finished_at: datetime,
    error: str | None = None,
) -> None:
    """
    Upsert do snapshot mais recente para `scan_key`.

    Quando `error` não é `None` e `result_json` é `None` (o ciclo
    falhou por inteiro), o snapshot anterior de `result` NÃO é
    sobrescrito por um `None` -- assim o `/scan/latest` continua
    devolvendo o último resultado bom, só com `error` preenchido
    avisando que o ciclo mais recente falhou. Isso evita que uma
    instabilidade pontual da Bybit apague o único dado que o GPT tinha
    pra usar.
    """
    with session_scope() as session:
        existing = session.get(ScanSnapshot, scan_key)
        if existing is None:
            session.add(
                ScanSnapshot(
                    scan_key=scan_key,
                    result_json=result_json,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=(finished_at - started_at).total_seconds(),
                    error=error,
                    cycle_count=1,
                )
            )
            return

        if result_json is not None:
            existing.result_json = result_json
        existing.started_at = started_at
        existing.finished_at = finished_at
        existing.duration_seconds = (finished_at - started_at).total_seconds()
        existing.error = error
        existing.cycle_count = (existing.cycle_count or 0) + 1


def load_scan_snapshot(scan_key: str = DEFAULT_SCAN_KEY) -> dict[str, Any] | None:
    """Lê o snapshot mais recente (sem disparar nenhum scan novo). `None` se o loop de fundo ainda não completou nenhum ciclo."""
    with session_scope() as session:
        row = session.get(ScanSnapshot, scan_key)
        if row is None:
            return None
        payload = row.to_dict()

    finished_at = datetime.fromisoformat(payload["finished_at"])
    payload["age_seconds"] = round((datetime.now(timezone.utc) - finished_at).total_seconds(), 1)
    return payload
