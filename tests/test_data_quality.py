"""
tests/test_data_quality.py
=============================

Testes do Data Quality Layer (`validation.data_quality`). Sem rede —
só valida listas de `Candle` construídas em memória.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from models.candle import Candle
from validation.data_quality import DataQualityError, validate_candles


def _make_candles(n: int, timeframe_minutes: int = 60, start_price: float = 100.0) -> list[Candle]:
    """Gera `n` candles válidos e cronologicamente ordenados, terminando agora (fresh)."""
    now = datetime.now(timezone.utc)
    delta = timedelta(minutes=timeframe_minutes)
    candles = []
    price = start_price
    for i in range(n):
        open_time = now - delta * (n - i)
        close_time = open_time + delta
        candles.append(
            Candle(
                open_time=open_time,
                open=price,
                high=price + 1,
                low=price - 1,
                close=price + 0.5,
                volume=10.0,
                close_time=close_time,
            )
        )
        price += 0.1
    return candles


def test_valid_candles_pass() -> None:
    candles = _make_candles(200, timeframe_minutes=60)
    validate_candles(candles, symbol="BTCUSDT", timeframe="1H", min_candles=200)


def test_insufficient_candles_raises() -> None:
    candles = _make_candles(50, timeframe_minutes=60)
    with pytest.raises(DataQualityError, match="insuficientes"):
        validate_candles(candles, symbol="BTCUSDT", timeframe="1H", min_candles=200)


def test_high_less_than_low_raises() -> None:
    candles = _make_candles(200, timeframe_minutes=60)
    bad = candles[-1]
    candles[-1] = Candle(
        open_time=bad.open_time, open=bad.open, high=5.0, low=10.0,
        close=bad.close, volume=bad.volume, close_time=bad.close_time,
    )
    with pytest.raises(DataQualityError, match="high < low"):
        validate_candles(candles, symbol="XAUUSD", timeframe="1H", min_candles=200)


def test_close_outside_range_raises() -> None:
    candles = _make_candles(200, timeframe_minutes=60)
    bad = candles[-1]
    candles[-1] = Candle(
        open_time=bad.open_time, open=bad.open, high=bad.high, low=bad.low,
        close=bad.high + 100, volume=bad.volume, close_time=bad.close_time,
    )
    with pytest.raises(DataQualityError, match="close fora do range"):
        validate_candles(candles, symbol="XAUUSD", timeframe="1H", min_candles=200)


def test_non_positive_price_raises() -> None:
    candles = _make_candles(200, timeframe_minutes=60)
    bad = candles[-1]
    candles[-1] = Candle(
        open_time=bad.open_time, open=0.0, high=bad.high, low=bad.low,
        close=bad.close, volume=bad.volume, close_time=bad.close_time,
    )
    with pytest.raises(DataQualityError, match="não positivo"):
        validate_candles(candles, symbol="XAUUSD", timeframe="1H", min_candles=200)


def test_out_of_order_candles_raise() -> None:
    candles = _make_candles(200, timeframe_minutes=60)
    candles[100], candles[101] = candles[101], candles[100]
    with pytest.raises(DataQualityError, match="fora de ordem"):
        validate_candles(candles, symbol="BTCUSDT", timeframe="1H", min_candles=200)


def test_stale_data_raises() -> None:
    candles = _make_candles(200, timeframe_minutes=60)
    stale_time_shift = timedelta(hours=100)
    shifted = []
    for c in candles:
        shifted.append(
            Candle(
                open_time=c.open_time - stale_time_shift,
                open=c.open, high=c.high, low=c.low, close=c.close,
                volume=c.volume, close_time=c.close_time - stale_time_shift,
            )
        )
    with pytest.raises(DataQualityError, match="stale"):
        validate_candles(shifted, symbol="BTCUSDT", timeframe="1H", min_candles=200)
