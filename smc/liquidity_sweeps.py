"""
smc/liquidity_sweeps.py
=========================

Detecção de Liquidity Sweeps ("stop hunts").

Um liquidity sweep ocorre quando o preço rompe brevemente um swing
high/low (ou uma zona de Equal High/Low) — varrendo os stops
posicionados ali — e em seguida **fecha de volta** para o lado
oposto do nível, sem sustentar o rompimento. É um dos sinais mais
usados em Smart Money Concepts para antecipar reversões de curto prazo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from structure.swings import get_swing_points


@dataclass(frozen=True, slots=True)
class LiquiditySweep:
    """Representa um evento de varredura de liquidez em um único candle."""

    direction: str          # "sweep_high" | "sweep_low"
    swept_level: float
    wick_extreme: float      # ponta do pavio que varreu o nível
    close_price: float
    candle_time: datetime

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "swept_level": round(self.swept_level, 6),
            "wick_extreme": round(self.wick_extreme, 6),
            "close_price": round(self.close_price, 6),
            "candle_time": self.candle_time.isoformat(),
        }


def find_liquidity_sweeps(
    df: pd.DataFrame,
    swing_lookback: int = 2,
    max_events: int = 10,
) -> list[LiquiditySweep]:
    """
    Detecta candles que romperam um swing high/low e fecharam de volta
    para o lado oposto (rejeição / stop hunt).

    Args:
        df: DataFrame OHLCV.
        swing_lookback: lookback usado na detecção de swings.
        max_events: número máximo de eventos retornados (mais recentes).

    Returns:
        Lista de `LiquiditySweep`, mais recentes primeiro.
    """
    swings = get_swing_points(df, lookback=swing_lookback)
    swing_highs = swings.loc[swings["type"] == "high", "price"]
    swing_lows = swings.loc[swings["type"] == "low", "price"]

    events: list[LiquiditySweep] = []

    for i in range(len(df)):
        candle_time = df.index[i]
        candle_high = df["high"].iloc[i]
        candle_low = df["low"].iloc[i]
        candle_close = df["close"].iloc[i]

        # Considera apenas swings já confirmados ANTES deste candle.
        prior_highs = swing_highs.loc[swing_highs.index < candle_time]
        prior_lows = swing_lows.loc[swing_lows.index < candle_time]

        if not prior_highs.empty:
            last_high = prior_highs.iloc[-1]
            # Rompeu o high com o pavio, mas fechou abaixo dele: sweep de alta.
            if candle_high > last_high and candle_close < last_high:
                events.append(
                    LiquiditySweep(
                        direction="sweep_high",
                        swept_level=float(last_high),
                        wick_extreme=float(candle_high),
                        close_price=float(candle_close),
                        candle_time=candle_time,
                    )
                )

        if not prior_lows.empty:
            last_low = prior_lows.iloc[-1]
            # Rompeu o low com o pavio, mas fechou acima dele: sweep de baixa.
            if candle_low < last_low and candle_close > last_low:
                events.append(
                    LiquiditySweep(
                        direction="sweep_low",
                        swept_level=float(last_low),
                        wick_extreme=float(candle_low),
                        close_price=float(candle_close),
                        candle_time=candle_time,
                    )
                )

    events.sort(key=lambda e: e.candle_time, reverse=True)
    return events[:max_events]
