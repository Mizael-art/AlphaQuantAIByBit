"""
monitoring/setup_monitor.py
==============================

Núcleo puro do monitoramento de setups (Documento Master, seção 34,
43-44). Função pura: recebe o preço atual + o snapshot do setup
persistido, devolve a atualização de estado a aplicar (ou `None` se
nada mudou) -- nunca toca banco/rede diretamente (mesmo padrão de
`risk/engine.py`, `decision/engine.py`, `scoring/engine.py`).

Prioridade de checagem (por candle/preço mais recente): stop tem
prioridade sobre take-profit quando ambos seriam tecnicamente
atingíveis no mesmo instante -- mesma convenção conservadora do
`backtest/simulator.py` (intrabar_priority default "stop_first"),
por consistência entre os dois motores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from setups.lifecycle import (
    ACTIVE,
    COMPLETED,
    ENTRY_READY,
    FORMATION,
    INVALIDATED,
    NEAR_ENTRY,
    READY,
    TERMINAL_STATUSES,
    TP1,
    TP2,
    TP3,
    TRIGGERED,
    WATCH,
)

_PRE_ENTRY_STATUSES: Final = frozenset({FORMATION, WATCH})
_ARMED_STATUSES: Final = frozenset({NEAR_ENTRY, READY, TRIGGERED, ENTRY_READY, ACTIVE, TP1, TP2})


@dataclass(frozen=True, slots=True)
class SetupSnapshot:
    status: str
    direction: str
    entry_zone_low: float | None
    entry_zone_high: float | None
    stop: float | None
    tp1: float | None
    tp2: float | None
    tp3: float | None


@dataclass(frozen=True, slots=True)
class SetupUpdate:
    new_status: str
    reason: str

    def to_dict(self) -> dict:
        return {"new_status": self.new_status, "reason": self.reason}


def _favorable(direction: str, price: float, level: float) -> bool:
    """Preço já alcançou (ou passou) um nível a favor do trade (ex.: TP)."""
    return price >= level if direction == "long" else price <= level


def _adverse(direction: str, price: float, level: float) -> bool:
    """Preço já alcançou (ou passou) um nível contra o trade (ex.: stop)."""
    return price <= level if direction == "long" else price >= level


def evaluate_setup_update(current_price: float, setup: SetupSnapshot) -> SetupUpdate | None:
    """
    Returns:
        `SetupUpdate` se o preço atual justifica uma transição de
        estado; `None` se nada mudou (setup terminal, ou preço ainda
        não atingiu nenhum nível relevante).
    """
    if setup.status in TERMINAL_STATUSES:
        return None

    # --- Ainda não entrou na zona -- só checa se já entrou. ---
    if setup.status in _PRE_ENTRY_STATUSES:
        if setup.entry_zone_low is None or setup.entry_zone_high is None:
            return None
        if setup.entry_zone_low <= current_price <= setup.entry_zone_high:
            return SetupUpdate(NEAR_ENTRY, f"Preço ({current_price}) entrou na zona de entrada ({setup.entry_zone_low}-{setup.entry_zone_high}).")
        return None

    # --- Já armado (perto da entrada ou já ativo) -- checa stop/TP. ---
    if setup.status in _ARMED_STATUSES:
        if setup.stop is not None and _adverse(setup.direction, current_price, setup.stop):
            return SetupUpdate(INVALIDATED, f"Preço ({current_price}) atingiu o stop ({setup.stop}).")

        # TP mais distante primeiro -- se já alcançou TP3, não faz sentido
        # reportar como se só tivesse batido TP1 no meio do caminho.
        if setup.tp3 is not None and _favorable(setup.direction, current_price, setup.tp3):
            return SetupUpdate(COMPLETED, f"Preço ({current_price}) atingiu TP3 ({setup.tp3}) -- setup completo.")
        if setup.tp2 is not None and _favorable(setup.direction, current_price, setup.tp2):
            next_status = COMPLETED if setup.tp3 is None else TP2
            reason = f"Preço ({current_price}) atingiu TP2 ({setup.tp2})."
            return SetupUpdate(next_status, reason if next_status == TP2 else reason + " Sem TP3 definido -- setup completo.")
        if setup.tp1 is not None and _favorable(setup.direction, current_price, setup.tp1):
            next_status = COMPLETED if setup.tp2 is None and setup.tp3 is None else TP1
            reason = f"Preço ({current_price}) atingiu TP1 ({setup.tp1})."
            return SetupUpdate(next_status, reason if next_status == TP1 else reason + " Sem TP2/TP3 definidos -- setup completo.")

    return None
