"""
snapshot/confluence.py
========================

Calcula a confluência entre os timeframes analisados: o quanto a
tendência e o score concordam entre 15m, 1H, 4H, 1D (ou qualquer outro
conjunto de timeframes usado).

A ideia central: um sinal só é realmente forte quando MÚLTIPLOS
timeframes apontam na mesma direção — exatamente o tipo de contexto
que um trader institucional monta mentalmente ao alternar entre
gráficos, e que este módulo entrega pronto.
"""

from __future__ import annotations

from dataclasses import dataclass

# Pesos por timeframe: timeframes mais altos têm mais peso na
# confluência final, refletindo maior relevância estrutural.
_TIMEFRAME_WEIGHTS: dict[str, float] = {
    "15m": 1.0,
    "30m": 1.2,
    "1H": 1.5,
    "2H": 1.8,
    "4H": 2.0,
    "6H": 2.2,
    "8H": 2.4,
    "12H": 2.6,
    "1D": 3.0,
    "3D": 3.5,
    "1W": 4.0,
}


@dataclass(frozen=True, slots=True)
class ConfluenceResult:
    """Resultado da análise de confluência entre múltiplos timeframes."""

    overall_trend: str
    alignment: str            # "full" | "partial" | "mixed"
    alignment_pct: float       # % do peso total alinhado com overall_trend
    weighted_score: float      # score (0-100) ponderado pelos timeframes alinhados
    trend_by_timeframe: dict[str, str]
    score_by_timeframe: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "overall_trend": self.overall_trend,
            "alignment": self.alignment,
            "alignment_pct": round(self.alignment_pct, 1),
            "weighted_score": round(self.weighted_score, 1),
            "trend_by_timeframe": self.trend_by_timeframe,
            "score_by_timeframe": self.score_by_timeframe,
        }


def calculate_confluence(
    trend_by_timeframe: dict[str, str], score_by_timeframe: dict[str, int]
) -> ConfluenceResult:
    """
    Calcula a confluência multi-timeframe a partir das tendências e
    scores individuais de cada timeframe.

    Args:
        trend_by_timeframe: ex.: {"15m": "Bullish", "1H": "Bullish", "4H": "Ranging", "1D": "Bullish"}
        score_by_timeframe: ex.: {"15m": 60, "1H": 72, "4H": 50, "1D": 81}

    Returns:
        `ConfluenceResult` com a tendência geral, o grau de alinhamento
        e o score ponderado.
    """
    weights = {tf: _TIMEFRAME_WEIGHTS.get(tf, 1.0) for tf in trend_by_timeframe}
    total_weight = sum(weights.values()) or 1.0

    bullish_weight = sum(w for tf, w in weights.items() if trend_by_timeframe[tf] == "Bullish")
    bearish_weight = sum(w for tf, w in weights.items() if trend_by_timeframe[tf] == "Bearish")

    if bullish_weight > bearish_weight:
        overall_trend = "Bullish"
        aligned_weight = bullish_weight
    elif bearish_weight > bullish_weight:
        overall_trend = "Bearish"
        aligned_weight = bearish_weight
    else:
        overall_trend = "Ranging"
        aligned_weight = total_weight - bullish_weight - bearish_weight

    alignment_pct = (aligned_weight / total_weight) * 100

    if alignment_pct >= 99.9:
        alignment = "full"
    elif alignment_pct >= 60:
        alignment = "partial"
    else:
        alignment = "mixed"

    aligned_timeframes = [tf for tf in trend_by_timeframe if trend_by_timeframe[tf] == overall_trend]
    if aligned_timeframes:
        weighted_score = sum(score_by_timeframe[tf] * weights[tf] for tf in aligned_timeframes) / sum(
            weights[tf] for tf in aligned_timeframes
        )
    else:
        weighted_score = sum(score_by_timeframe.values()) / len(score_by_timeframe)

    return ConfluenceResult(
        overall_trend=overall_trend,
        alignment=alignment,
        alignment_pct=alignment_pct,
        weighted_score=weighted_score,
        trend_by_timeframe=trend_by_timeframe,
        score_by_timeframe=score_by_timeframe,
    )
