"""
tests/test_order_flow.py
==========================

Testes unitários do módulo order_flow (Delta/CVD aproximados via
taker_buy_volume, sem depender de /aggTrades).

Executar com:
    pytest tests/test_order_flow.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from order_flow.delta import build_order_flow


def _make_df(volume: list[float], taker_buy_volume: list[float]) -> pd.DataFrame:
    periods = len(volume)
    index = pd.date_range("2024-01-01", periods=periods, freq="4h")
    close = 100 + np.cumsum(np.zeros(periods))  # preço neutro por padrão nos testes de delta puro
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": volume,
            "taker_buy_volume": taker_buy_volume,
        },
        index=index,
    )


@pytest.fixture
def balanced_df() -> pd.DataFrame:
    # 30 candles, metade do volume sempre do lado comprador -> delta ~0.
    volume = [1000.0] * 30
    taker_buy = [500.0] * 30
    return _make_df(volume, taker_buy)


@pytest.fixture
def buyer_dominant_df() -> pd.DataFrame:
    # Todo candle com 80% do volume iniciado por compradores -> CVD sobe.
    volume = [1000.0] * 30
    taker_buy = [800.0] * 30
    return _make_df(volume, taker_buy)


@pytest.fixture
def seller_dominant_df() -> pd.DataFrame:
    volume = [1000.0] * 30
    taker_buy = [200.0] * 30
    return _make_df(volume, taker_buy)


def test_balanced_flow_has_near_zero_delta(balanced_df: pd.DataFrame) -> None:
    result = build_order_flow(balanced_df)
    assert result.delta_last == pytest.approx(0.0)
    assert result.dominant_side_last == "balanced"


def test_buyer_dominant_flow_produces_rising_cvd(buyer_dominant_df: pd.DataFrame) -> None:
    result = build_order_flow(buyer_dominant_df)
    assert result.delta_last > 0
    assert result.dominant_side_last == "buyers"
    assert result.cvd_last > 0
    assert result.cvd_trend == "rising"


def test_seller_dominant_flow_produces_falling_cvd(seller_dominant_df: pd.DataFrame) -> None:
    result = build_order_flow(seller_dominant_df)
    assert result.delta_last < 0
    assert result.dominant_side_last == "sellers"
    assert result.cvd_last < 0
    assert result.cvd_trend == "falling"


def test_bullish_divergence_detected_when_price_makes_lower_low_but_cvd_does_not() -> None:
    # Primeira perna de queda: volume vendedor forte, CVD despenca junto com o preço.
    # Segunda perna de queda: preço faz LL, mas o volume agora é majoritariamente
    # comprador (menos pressão vendedora líquida) -> CVD NÃO acompanha a nova mínima.
    periods = 20
    index = pd.date_range("2024-01-01", periods=periods, freq="4h")

    close = np.concatenate(
        [
            np.linspace(100, 90, 10),  # perna 1: queda forte
            np.linspace(90, 85, 10),   # perna 2: nova mínima (LL), mas mais rasa
        ]
    )
    volume = np.array([1000.0] * periods)
    # perna 1: 80% vendedor (taker_buy baixo) | perna 2: 60% comprador (taker_buy alto)
    taker_buy = np.concatenate([np.full(10, 200.0), np.full(10, 600.0)])

    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": volume,
            "taker_buy_volume": taker_buy,
        },
        index=index,
    )

    result = build_order_flow(df, lookback=20)
    assert result.divergence == "bullish"


def test_order_flow_to_dict_has_expected_keys(balanced_df: pd.DataFrame) -> None:
    result = build_order_flow(balanced_df).to_dict()
    expected_keys = {
        "delta_last_candle",
        "buy_volume_pct_last_candle",
        "dominant_side_last_candle",
        "cvd_last",
        "cvd_trend",
        "cvd_slope_pct",
        "cvd_price_divergence",
        "lookback_used",
        "method",
        "note",
    }
    assert expected_keys.issubset(result.keys())
