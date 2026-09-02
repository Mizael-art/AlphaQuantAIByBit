"""
playbook
========

Playbook Library (Fase 3 -- ver `playbook/library.py` para a limitação
importante: são metadados de filtro regime-first, ainda não
estratégias validadas por backtest).
"""

from playbook.library import DAY_TRADE, INTRADAY, PLAYBOOK, SWING, PlaybookEntry, compatible_playbooks

__all__ = ["PLAYBOOK", "PlaybookEntry", "compatible_playbooks", "DAY_TRADE", "INTRADAY", "SWING"]
