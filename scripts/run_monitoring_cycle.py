#!/usr/bin/env python3
"""
scripts/run_monitoring_cycle.py
==================================

Entrypoint do Render Cron Job (Fase 7 -- ver `render.yaml`). Roda
`monitoring.service.run_monitoring_cycle` diretamente contra o banco
(mesma `DATABASE_URL` do serviço web) -- sem passar por HTTP, então
não depende do serviço web estar de pé nem de autenticação entre
serviços.

Uso local: `python scripts/run_monitoring_cycle.py`
(precisa de `DATABASE_URL` no ambiente, senão cai no SQLite local).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Garante que o diretório raiz do repo está no sys.path, independente
# de como o script é invocado (`python scripts/run_monitoring_cycle.py`
# a partir de qualquer diretório, ou via cron do Render).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from persistence.db import session_scope  # noqa: E402
from monitoring.service import run_monitoring_cycle  # noqa: E402


def main() -> int:
    with session_scope() as session:
        result = run_monitoring_cycle(session)

    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    # Exit code != 0 só se o ciclo inteiro falhou de forma inesperada --
    # erros por símbolo individual (`result.errors`) não devem marcar o
    # cron job como falho (um provider fora do ar não deve gerar alerta
    # de infraestrutura toda vez).
    return 0


if __name__ == "__main__":
    sys.exit(main())
