"""
regime/detector.py
=====================

Detecção de regime de mercado (Documento 2, seção 7; Documento Master,
seção 12: "REGIME-FIRST ENGINE").

Função pura: recebe métricas já calculadas (reaproveitando
`analysis.trend`, `structure.market_structure`, `statistics_.volatility`
e Bollinger Bands já existentes) e devolve UM regime dominante, por
prioridade explícita -- nunca uma combinação ambígua.

IMPORTANTE (honestidade sobre o método): a ordem de prioridade abaixo
é uma heurística de primeira versão, não uma classificação validada
estatisticamente. Documento Master seção 26 já avisa: "Historical Edge
≠ Current Edge" -- o mesmo vale aqui, os limiares (percentis, thresholds)
são pontos de partida razoáveis, a calibrar com dados reais conforme o
Discovery Engine roda (e, futuramente, com o Learning Engine da Fase 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

TRENDING_UP: Final = "TRENDING_UP"
TRENDING_DOWN: Final = "TRENDING_DOWN"
RANGE: Final = "RANGE"
COMPRESSION: Final = "COMPRESSION"
EXPANSION: Final = "EXPANSION"
ACCUMULATION: Final = "ACCUMULATION"
DISTRIBUTION: Final = "DISTRIBUTION"
TRANSITION: Final = "TRANSITION"
HIGH_VOLATILITY: Final = "HIGH_VOLATILITY"
LOW_VOLATILITY: Final = "LOW_VOLATILITY"

ALL_REGIMES: Final[frozenset[str]] = frozenset(
    {
        TRENDING_UP, TRENDING_DOWN, RANGE, COMPRESSION, EXPANSION,
        ACCUMULATION, DISTRIBUTION, TRANSITION, HIGH_VOLATILITY, LOW_VOLATILITY,
    }
)

VOLATILITY_LOW: Final = "LOW"
VOLATILITY_NORMAL: Final = "NORMAL"
VOLATILITY_HIGH: Final = "HIGH"
VOLATILITY_EXTREME: Final = "EXTREME"


@dataclass(frozen=True, slots=True)
class RegimeResult:
    regime: str
    volatility_bucket: str
    volatility_percentile: float
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "volatility_bucket": self.volatility_bucket,
            "volatility_percentile": round(self.volatility_percentile, 1),
            "notes": self.notes,
        }


def _volatility_bucket(volatility_percentile: float) -> str:
    if volatility_percentile >= 95:
        return VOLATILITY_EXTREME
    if volatility_percentile >= 75:
        return VOLATILITY_HIGH
    if volatility_percentile <= 25:
        return VOLATILITY_LOW
    return VOLATILITY_NORMAL


def detect_regime(
    trend: str,
    bos: bool,
    choch: bool,
    volatility_percentile: float,
    bb_width_percentile: float,
    price_percentile_in_range: float,
) -> RegimeResult:
    """
    Args:
        trend: "Bullish" | "Bearish" | "Ranging" (`analysis.trend.determine_trend`).
        bos: Break of Structure detectado (`structure.market_structure`).
        choch: Change of Character detectado (possível reversão em andamento).
        volatility_percentile: percentil (0-100) do ATR atual em relação
            ao seu próprio histórico (`statistics_.volatility.calculate_percentile_rank`
            aplicado à série de ATR).
        bb_width_percentile: percentil (0-100) da largura das Bollinger
            Bands em relação ao seu próprio histórico -- baixo = squeeze
            (compressão), alto = bandas abertas (expansão).
        price_percentile_in_range: percentil (0-100) do preço atual
            dentro do range recente -- usado só para distinguir
            acumulação (perto do piso) de distribuição (perto do teto)
            quando a tendência já é "Ranging".

    Returns:
        `RegimeResult` com um único regime dominante (prioridade
        explícita, documentada abaixo) + o bucket de volatilidade
        (dimensão auxiliar, sempre reportada mesmo quando não é o
        regime dominante -- usado pelo filtro de volatilidade,
        Documento Master seção 34).
    """
    bucket = _volatility_bucket(volatility_percentile)
    notes: list[str] = []

    # 1) Volatilidade extrema domina qualquer outra leitura -- Documento
    #    Master seção 34 trata isso como filtro de primeira ordem.
    if bucket == VOLATILITY_EXTREME:
        notes.append(f"Volatilidade no percentil {volatility_percentile:.0f} (extrema) -- domina a classificação.")
        return RegimeResult(HIGH_VOLATILITY, bucket, volatility_percentile, notes)
    if volatility_percentile <= 5:
        notes.append(f"Volatilidade no percentil {volatility_percentile:.0f} (muito baixa) -- domina a classificação.")
        return RegimeResult(LOW_VOLATILITY, bucket, volatility_percentile, notes)

    # 2) Compressão / expansão -- squeeze de Bollinger é um sinal mais
    #    específico do que só "vol baixa"/"vol alta" e costuma preceder
    #    o movimento (Documento Master seção 10, "Compression Breakout").
    if bb_width_percentile <= 15:
        notes.append(f"Largura de Bollinger no percentil {bb_width_percentile:.0f} -- squeeze (compressão).")
        return RegimeResult(COMPRESSION, bucket, volatility_percentile, notes)
    if bb_width_percentile >= 90 and bos:
        notes.append(f"Bandas abertas (percentil {bb_width_percentile:.0f}) + BOS -- expansão em andamento.")
        return RegimeResult(EXPANSION, bucket, volatility_percentile, notes)

    # 3) CHOCH sem confirmação ainda (sem BOS na nova direção) -- estrutura
    #    mudando, mas ainda não validada. Documento Master seção 16.
    if choch and not bos:
        notes.append("CHOCH detectado sem BOS de confirmação -- estrutura em transição.")
        return RegimeResult(TRANSITION, bucket, volatility_percentile, notes)

    # 4) Tendência definida (EMAs + estrutura concordam -- `analysis.trend`
    #    já resolve divergência como "Ranging", então aqui é confiável).
    if trend == "Bullish":
        return RegimeResult(TRENDING_UP, bucket, volatility_percentile, notes)
    if trend == "Bearish":
        return RegimeResult(TRENDING_DOWN, bucket, volatility_percentile, notes)

    # 5) Ranging -- distingue acumulação/distribuição só quando há um
    #    CHOCH recente sugerindo reversão dentro do range (senão é só
    #    RANGE genérico -- não force uma leitura Wyckoff sem sinal).
    if choch and price_percentile_in_range <= 25:
        notes.append("Ranging + CHOCH perto do piso do range -- possível acumulação.")
        return RegimeResult(ACCUMULATION, bucket, volatility_percentile, notes)
    if choch and price_percentile_in_range >= 75:
        notes.append("Ranging + CHOCH perto do teto do range -- possível distribuição.")
        return RegimeResult(DISTRIBUTION, bucket, volatility_percentile, notes)

    return RegimeResult(RANGE, bucket, volatility_percentile, notes)
