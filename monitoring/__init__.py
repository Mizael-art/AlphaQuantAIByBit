"""
monitoring
==========

Monitoring + Scheduler + Conditional Plans (Fase 7 do Plano de
Evolução -- Documento Master, seção 34, 43-44).

- `setup_monitor.py` -- decisão pura de transição de estado a partir
  do preço atual (testado).
- `service.py` -- I/O: busca preço + aplica transições + expira
  vencidos (rede real, smoke-tested).

Chamado por `POST /monitoring/run-cycle` (sob demanda) e por
`scripts/run_monitoring_cycle.py` (cron do Render -- ver render.yaml).
"""

from monitoring.service import MonitoringCycleResult, run_monitoring_cycle
from monitoring.setup_monitor import SetupSnapshot, SetupUpdate, evaluate_setup_update

__all__ = ["evaluate_setup_update", "SetupSnapshot", "SetupUpdate", "run_monitoring_cycle", "MonitoringCycleResult"]
