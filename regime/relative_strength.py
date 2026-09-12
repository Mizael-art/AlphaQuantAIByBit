"""
regime/relative_strength.py
==============================

Força relativa vs. BTC (Documento 2, seção 9; Documento Master, seção 14).

Limiares (+2% / -2%) são um ponto de partida documentado, não um valor
validado estatisticamente -- mesma ressalva de `regime/detector.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

STRONG: Final = "STRONG"
WEAK: Final = "WEAK"
NEUTRAL: Final = "NEUTRAL"

_STRONG_THRESHOLD_PCT = 2.0
_WEAK_THRESHOLD_PCT = -2.0


@dataclass(frozen=True, slots=True)
class RelativeStrengthResult:
    asset_return_pct: float
    btc_return_pct: float
    relative_strength_pct: float
    label: str

    def to_dict(self) -> dict:
        return {
            "asset_return_pct": round(self.asset_return_pct, 2),
            "btc_return_pct": round(self.btc_return_pct, 2),
            "relative_strength_pct": round(self.relative_strength_pct, 2),
            "label": self.label,
        }


def classify_relative_strength(asset_return_pct: float, btc_return_pct: float) -> RelativeStrengthResult:
    """
    Args:
        asset_return_pct: retorno % do ativo no período de lookback
            (ex.: variação do preço nas últimas N horas).
        btc_return_pct: retorno % do BTC no mesmo período.

    Returns:
        Força relativa = diferença simples entre os dois retornos (em
        pontos percentuais) -- positiva = ativo performando melhor que
        BTC no período. Documento Master, seção 9: "combinar sempre com
        estrutura e setup", nunca usar isso isoladamente -- essa
        combinação acontece em `scoring/engine.py`, não aqui.
    """
    relative_strength_pct = asset_return_pct - btc_return_pct

    if relative_strength_pct >= _STRONG_THRESHOLD_PCT:
        label = STRONG
    elif relative_strength_pct <= _WEAK_THRESHOLD_PCT:
        label = WEAK
    else:
        label = NEUTRAL

    return RelativeStrengthResult(asset_return_pct, btc_return_pct, relative_strength_pct, label)
