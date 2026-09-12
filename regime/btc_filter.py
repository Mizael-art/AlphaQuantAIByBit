"""
regime/btc_filter.py
=======================

BTC como filtro de contexto para altcoins (Documento 2, seção 8;
Documento Master, seção 13). Explicitamente NÃO é "BTC caiu = nenhuma
altcoin pode subir" -- combina regime do BTC com a força relativa do
ativo (uma altcoin com força relativa STRONG pode ser BTC_NEUTRAL
mesmo com BTC em TRENDING_DOWN).
"""

from __future__ import annotations

from typing import Final

from regime.detector import TRENDING_DOWN, TRENDING_UP
from regime.relative_strength import NEUTRAL, STRONG, WEAK

BTC_SUPPORTIVE: Final = "BTC_SUPPORTIVE"
BTC_NEUTRAL: Final = "BTC_NEUTRAL"
BTC_HOSTILE: Final = "BTC_HOSTILE"


def classify_btc_context(btc_regime: str, relative_strength_label: str, direction: str) -> str:
    """
    Args:
        btc_regime: regime atual do BTC (`regime.detector`).
        relative_strength_label: STRONG | WEAK | NEUTRAL do ativo vs. BTC.
        direction: "long" | "short" -- a direção pretendida do trade no
            ativo (o contexto BTC muda de sinal dependendo da direção:
            BTC em alta é suportivo para longs, hostil para shorts).
    """
    if direction not in ("long", "short"):
        raise ValueError("direction deve ser 'long' ou 'short'.")

    # Direção "favorável" ao BTC do ponto de vista do trade pretendido.
    btc_aligned = (btc_regime == TRENDING_UP and direction == "long") or (
        btc_regime == TRENDING_DOWN and direction == "short"
    )
    btc_against = (btc_regime == TRENDING_UP and direction == "short") or (
        btc_regime == TRENDING_DOWN and direction == "long"
    )

    if btc_aligned:
        return BTC_NEUTRAL if relative_strength_label == WEAK else BTC_SUPPORTIVE

    if btc_against:
        # Ativo com força relativa STRONG desafiando um BTC contrário --
        # não é hostil, mas também não é suportivo -- fica neutro.
        return BTC_NEUTRAL if relative_strength_label == STRONG else BTC_HOSTILE

    # BTC sem tendência definida (RANGE/COMPRESSION/etc.) -- só a força
    # relativa do próprio ativo importa.
    if relative_strength_label == STRONG and direction == "long":
        return BTC_SUPPORTIVE
    if relative_strength_label == WEAK and direction == "short":
        return BTC_SUPPORTIVE
    return BTC_NEUTRAL
