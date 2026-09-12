"""
order_flow/delta.py
====================

Calcula Delta por candle e CVD (Cumulative Volume Delta) acumulado ao
longo da janela de candles disponível, a partir de `taker_buy_volume`
(já presente em todo candle vindo de /api/v3/klines).

Fórmulas:
    delta_candle   = taker_buy_volume - taker_sell_volume
                    = taker_buy_volume - (volume - taker_buy_volume)
                    = (2 * taker_buy_volume) - volume

    cvd[i] = cvd[i-1] + delta_candle[i]   (cvd[0] = delta_candle[0])

O CVD é relativo à janela de candles retornada (não é o CVD "desde o
início dos tempos" do ativo) — o que importa para leitura de order
flow é a INCLINAÇÃO/DIREÇÃO do CVD e sua relação com o preço no mesmo
período, não o valor absoluto.

Divergência CVD x Preço (o principal sinal acionável deste módulo):
    - Bearish: preço faz máxima mais alta (HH) no lookback, mas o CVD
      NÃO acompanha (máxima do CVD não é mais alta) -> alta foi
      sustentada por menos agressão compradora líquida do que a
      anterior -> possível exaustão / distribuição.
    - Bullish: preço faz mínima mais baixa (LL) no lookback, mas o CVD
      NÃO acompanha (mínima do CVD não é mais baixa) -> queda foi
      sustentada por menos agressão vendedora líquida -> possível
      exaustão / acumulação (reforça leitura de Spring no Wyckoff
      Engine quando combinado com liquidity_sweeps + BOS).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class OrderFlowSnapshot:
    """Resultado do cálculo de Delta/CVD para um (symbol, timeframe)."""

    delta_last: float
    buy_volume_pct_last: float
    dominant_side_last: str  # "buyers" | "sellers" | "balanced"
    cvd_last: float
    cvd_trend: str  # "rising" | "falling" | "flat"
    cvd_slope_pct: float | None
    divergence: str | None  # "bullish" | "bearish" | None
    lookback_used: int

    def to_dict(self) -> dict:
        return {
            "delta_last_candle": round(self.delta_last, 4),
            "buy_volume_pct_last_candle": round(self.buy_volume_pct_last, 2),
            "dominant_side_last_candle": self.dominant_side_last,
            "cvd_last": round(self.cvd_last, 4),
            "cvd_trend": self.cvd_trend,
            "cvd_slope_pct": (
                round(self.cvd_slope_pct, 2) if self.cvd_slope_pct is not None else None
            ),
            "cvd_price_divergence": self.divergence,
            "lookback_used": self.lookback_used,
            "method": "taker_buy_volume_proxy",
            "note": (
                "Delta/CVD aproximados a partir do taker_buy_volume por candle "
                "(fornecido pela Binance em /klines). Não é tick-data de "
                "/aggTrades — trate como proxy de pressão agressora, não como "
                "leitura exata de fluxo por ordem individual."
            ),
        }


def _dominant_side(delta: float, volume: float) -> str:
    if volume <= 0:
        return "balanced"
    ratio = delta / volume
    if ratio > 0.05:
        return "buyers"
    if ratio < -0.05:
        return "sellers"
    return "balanced"


def build_order_flow(df: pd.DataFrame, lookback: int = 20) -> OrderFlowSnapshot:
    """
    Constrói o snapshot de order flow (Delta + CVD + divergência) para
    o DataFrame OHLCV informado.

    Args:
        df: DataFrame OHLCV com a coluna `taker_buy_volume` (ver
            `api.market_data.MarketData.get_ohlcv_dataframe`).
        lookback: quantidade de candles mais recentes usada para
            calcular a inclinação do CVD e checar divergência com o
            preço. Default 20 (equivalente ao lookback de swings
            usado em `structure.swings`).

    Returns:
        `OrderFlowSnapshot`.
    """
    volume = df["volume"]
    taker_buy = df["taker_buy_volume"]
    delta = (2 * taker_buy) - volume
    cvd = delta.cumsum()

    effective_lookback = min(lookback, len(df))
    window = df.iloc[-effective_lookback:]
    delta_window = delta.iloc[-effective_lookback:]
    cvd_window = cvd.iloc[-effective_lookback:]

    delta_last = float(delta.iloc[-1])
    volume_last = float(volume.iloc[-1])
    buy_pct_last = float(taker_buy.iloc[-1] / volume_last * 100) if volume_last > 0 else 50.0

    cvd_first = float(cvd_window.iloc[0])
    cvd_last = float(cvd_window.iloc[-1])
    cvd_change = cvd_last - cvd_first

    # Inclinação do CVD normalizada pelo volume total do período, para
    # não depender da magnitude absoluta do ativo/timeframe.
    total_volume_window = float(window["volume"].sum())
    cvd_slope_pct = (cvd_change / total_volume_window * 100) if total_volume_window > 0 else None

    if cvd_slope_pct is None:
        cvd_trend = "flat"
    elif cvd_slope_pct > 3:
        cvd_trend = "rising"
    elif cvd_slope_pct < -3:
        cvd_trend = "falling"
    else:
        cvd_trend = "flat"

    # ------------------------------------------------------------------
    # Divergência CVD x Preço dentro do lookback.
    # ------------------------------------------------------------------
    price_high_idx = window["high"].idxmax()
    price_low_idx = window["low"].idxmin()
    is_new_high_at_end = price_high_idx == window.index[-1] or window["high"].iloc[-3:].max() == window["high"].max()
    is_new_low_at_end = price_low_idx == window.index[-1] or window["low"].iloc[-3:].min() == window["low"].min()

    cvd_high_idx = cvd_window.idxmax()
    cvd_low_idx = cvd_window.idxmin()

    divergence: str | None = None
    if is_new_high_at_end and cvd_high_idx != price_high_idx and cvd_window.iloc[-1] < cvd_window.max():
        divergence = "bearish"
    elif is_new_low_at_end and cvd_low_idx != price_low_idx and cvd_window.iloc[-1] > cvd_window.min():
        divergence = "bullish"

    return OrderFlowSnapshot(
        delta_last=delta_last,
        buy_volume_pct_last=buy_pct_last,
        dominant_side_last=_dominant_side(delta_last, volume_last),
        cvd_last=cvd_last,
        cvd_trend=cvd_trend,
        cvd_slope_pct=cvd_slope_pct,
        divergence=divergence,
        lookback_used=effective_lookback,
    )
