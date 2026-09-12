"""
analysis/trend.py
====================

Tendência final = combinação de duas leituras independentes:

1. Empilhamento de EMAs (20/50/100/200) -- leitura de médias móveis
   clássica, sensível a médio prazo.
2. Tendência estrutural (`structure.market_structure`, baseada em
   HH/HL vs. LH/LL) -- leitura de price action pura.

Quando as duas concordam, a tendência final é essa direção. Quando
divergem, o resultado é "Ranging" -- o sistema prefere admitir
indefinição a forçar uma direção que só uma das duas leituras suporta
(mesma filosofia de "preferir NÃO OPERAR" do restante do projeto).
"""

from __future__ import annotations


def _ema_stack_trend(ema20: float, ema50: float, ema100: float, ema200: float) -> str:
    """
    Classifica o empilhamento das EMAs.

    Bullish: EMAs em ordem decrescente de período (20 > 50 > 100 > 200).
    Bearish: ordem inversa (20 < 50 < 100 < 200).
    Ranging: qualquer outra combinação (EMAs entrelaçadas).
    """
    if ema20 > ema50 > ema100 > ema200:
        return "Bullish"
    if ema20 < ema50 < ema100 < ema200:
        return "Bearish"
    return "Ranging"


def determine_trend(
    ema20: float,
    ema50: float,
    ema100: float,
    ema200: float,
    structural_trend: str,
) -> str:
    """
    Determina a tendência final do timeframe.

    Args:
        ema20, ema50, ema100, ema200: valores atuais das EMAs.
        structural_trend: tendência estrutural já calculada por
            `structure.market_structure.analyze_market_structure`
            ("Bullish" | "Bearish" | "Ranging").

    Returns:
        "Bullish", "Bearish" ou "Ranging". Só retorna uma direção
        quando o empilhamento de EMAs E a estrutura concordam --
        divergência entre as duas leituras é reportada como "Ranging"
        em vez de escolher uma arbitrariamente.
    """
    ema_trend = _ema_stack_trend(ema20, ema50, ema100, ema200)

    if ema_trend == structural_trend and ema_trend in ("Bullish", "Bearish"):
        return ema_trend

    return "Ranging"
