"""
analysis/score.py
====================

Score técnico (0-100): "quanto o setup parece bom", combinando
tendência, momentum (RSI/MACD), confirmação estrutural (BOS/CHOCH) e
volume.

IMPORTANTE (Documento 4, seção 13): este é o SCORE TÉCNICO, não a
CONFIANÇA. Este número não sabe nada sobre quantas exchanges
confirmam o dado -- essa é outra dimensão (`cross_exchange` /
`data_confidence`), calculada em outro lugar e combinada com este
score fora deste módulo. Um score alto aqui NUNCA deve ser lido, por
si só, como "pode entrar".
"""

from __future__ import annotations

# Pesos somam 100 -- cada componente contribui proporcionalmente à sua
# importância relativa para a decisão técnica.
_WEIGHT_TREND = 35
_WEIGHT_MOMENTUM = 25
_WEIGHT_STRUCTURE = 30
_WEIGHT_VOLUME = 10


def calculate_score(
    trend: str,
    rsi: float,
    macd_histogram: float,
    bos: bool,
    choch: bool,
    volume_above_average: bool,
) -> int:
    """
    Calcula o score técnico combinado.

    Args:
        trend: tendência final ("Bullish" | "Bearish" | "Ranging"),
            já reconciliada entre EMAs e estrutura (`analysis.trend`).
        rsi: RSI(14) atual.
        macd_histogram: histograma MACD atual (positivo = momentum de
            alta, negativo = momentum de baixa).
        bos: houve Break of Structure na direção da tendência.
        choch: houve Change of Character (sinal de possível reversão
            -- penaliza o score, não soma).
        volume_above_average: volume do último candle acima da média.

    Returns:
        Inteiro de 0 a 100.
    """
    score = 0.0

    # --- Tendência: só pontua quando há direção definida. ---
    if trend in ("Bullish", "Bearish"):
        score += _WEIGHT_TREND

    # --- Momentum: RSI fora da zona neutra e alinhado à tendência,
    #     MACD com histograma na mesma direção. ---
    momentum_score = 0.0
    if trend == "Bullish":
        if rsi > 50:
            momentum_score += _WEIGHT_MOMENTUM * 0.5
        if macd_histogram > 0:
            momentum_score += _WEIGHT_MOMENTUM * 0.5
    elif trend == "Bearish":
        if rsi < 50:
            momentum_score += _WEIGHT_MOMENTUM * 0.5
        if macd_histogram < 0:
            momentum_score += _WEIGHT_MOMENTUM * 0.5
    score += momentum_score

    # --- Estrutura: BOS na direção da tendência confirma continuação;
    #     CHOCH é um alerta de reversão e reduz a pontuação estrutural. ---
    structure_score = 0.0
    if bos and trend in ("Bullish", "Bearish"):
        structure_score += _WEIGHT_STRUCTURE
    if choch:
        structure_score = max(0.0, structure_score - _WEIGHT_STRUCTURE * 0.5)
    score += structure_score

    # --- Volume: confirma convicção por trás do movimento. ---
    if volume_above_average and trend in ("Bullish", "Bearish"):
        score += _WEIGHT_VOLUME

    return max(0, min(100, round(score)))
