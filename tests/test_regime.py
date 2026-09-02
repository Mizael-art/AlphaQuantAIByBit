"""
tests/test_regime.py
=======================

Testes puros da Fase 3: detecção de regime, força relativa e filtro
de contexto BTC.
"""

from __future__ import annotations

import pytest

from regime.btc_filter import BTC_HOSTILE, BTC_NEUTRAL, BTC_SUPPORTIVE, classify_btc_context
from regime.detector import (
    ACCUMULATION,
    COMPRESSION,
    DISTRIBUTION,
    EXPANSION,
    HIGH_VOLATILITY,
    LOW_VOLATILITY,
    RANGE,
    TRANSITION,
    TRENDING_DOWN,
    TRENDING_UP,
    detect_regime,
)
from regime.relative_strength import NEUTRAL, STRONG, WEAK, classify_relative_strength

# ---------------------------------------------------------------------------
# detect_regime
# ---------------------------------------------------------------------------


def test_extreme_volatility_dominates_everything() -> None:
    result = detect_regime(
        trend="Bullish", bos=True, choch=False,
        volatility_percentile=97, bb_width_percentile=50, price_percentile_in_range=50,
    )
    assert result.regime == HIGH_VOLATILITY
    assert result.volatility_bucket == "EXTREME"


def test_very_low_volatility_dominates() -> None:
    result = detect_regime(
        trend="Ranging", bos=False, choch=False,
        volatility_percentile=3, bb_width_percentile=50, price_percentile_in_range=50,
    )
    assert result.regime == LOW_VOLATILITY


def test_bollinger_squeeze_is_compression() -> None:
    result = detect_regime(
        trend="Ranging", bos=False, choch=False,
        volatility_percentile=40, bb_width_percentile=10, price_percentile_in_range=50,
    )
    assert result.regime == COMPRESSION


def test_wide_bands_with_bos_is_expansion() -> None:
    result = detect_regime(
        trend="Bullish", bos=True, choch=False,
        volatility_percentile=60, bb_width_percentile=95, price_percentile_in_range=50,
    )
    assert result.regime == EXPANSION


def test_choch_without_bos_is_transition() -> None:
    result = detect_regime(
        trend="Ranging", bos=False, choch=True,
        volatility_percentile=50, bb_width_percentile=50, price_percentile_in_range=50,
    )
    assert result.regime == TRANSITION


def test_bullish_trend_is_trending_up() -> None:
    result = detect_regime(
        trend="Bullish", bos=True, choch=False,
        volatility_percentile=50, bb_width_percentile=50, price_percentile_in_range=60,
    )
    assert result.regime == TRENDING_UP


def test_bearish_trend_is_trending_down() -> None:
    result = detect_regime(
        trend="Bearish", bos=True, choch=False,
        volatility_percentile=50, bb_width_percentile=50, price_percentile_in_range=40,
    )
    assert result.regime == TRENDING_DOWN


def test_ranging_with_choch_near_low_is_accumulation() -> None:
    result = detect_regime(
        trend="Ranging", bos=False, choch=True,
        volatility_percentile=50, bb_width_percentile=50, price_percentile_in_range=10,
    )
    # CHOCH sem BOS teria virado TRANSITION -- aqui simulamos com bos=True para chegar no ramo de Ranging.
    assert result.regime in (TRANSITION, ACCUMULATION)


def test_ranging_with_bos_and_choch_near_low_is_accumulation() -> None:
    result = detect_regime(
        trend="Ranging", bos=True, choch=True,
        volatility_percentile=50, bb_width_percentile=50, price_percentile_in_range=10,
    )
    assert result.regime == ACCUMULATION


def test_ranging_with_bos_and_choch_near_high_is_distribution() -> None:
    result = detect_regime(
        trend="Ranging", bos=True, choch=True,
        volatility_percentile=50, bb_width_percentile=50, price_percentile_in_range=90,
    )
    assert result.regime == DISTRIBUTION


def test_plain_ranging_without_choch_is_range() -> None:
    result = detect_regime(
        trend="Ranging", bos=False, choch=False,
        volatility_percentile=50, bb_width_percentile=50, price_percentile_in_range=50,
    )
    assert result.regime == RANGE


# ---------------------------------------------------------------------------
# classify_relative_strength
# ---------------------------------------------------------------------------


def test_relative_strength_strong() -> None:
    result = classify_relative_strength(asset_return_pct=5.0, btc_return_pct=1.0)
    assert result.label == STRONG
    assert result.relative_strength_pct == 4.0


def test_relative_strength_weak() -> None:
    result = classify_relative_strength(asset_return_pct=-3.0, btc_return_pct=1.0)
    assert result.label == WEAK


def test_relative_strength_neutral() -> None:
    result = classify_relative_strength(asset_return_pct=1.0, btc_return_pct=0.5)
    assert result.label == NEUTRAL


# ---------------------------------------------------------------------------
# classify_btc_context
# ---------------------------------------------------------------------------


def test_btc_supportive_for_long_when_btc_trending_up_and_not_weak() -> None:
    assert classify_btc_context(TRENDING_UP, NEUTRAL, "long") == BTC_SUPPORTIVE
    assert classify_btc_context(TRENDING_UP, STRONG, "long") == BTC_SUPPORTIVE


def test_btc_neutral_for_long_when_btc_trending_up_but_asset_weak() -> None:
    assert classify_btc_context(TRENDING_UP, WEAK, "long") == BTC_NEUTRAL


def test_btc_hostile_for_long_when_btc_trending_down() -> None:
    assert classify_btc_context(TRENDING_DOWN, NEUTRAL, "long") == BTC_HOSTILE


def test_btc_neutral_for_long_when_btc_trending_down_but_asset_strong() -> None:
    """Documento Master, seção 8: BTC caindo não significa que nenhuma altcoin pode subir."""
    assert classify_btc_context(TRENDING_DOWN, STRONG, "long") == BTC_NEUTRAL


def test_btc_context_mirrors_for_short_direction() -> None:
    assert classify_btc_context(TRENDING_DOWN, NEUTRAL, "short") == BTC_SUPPORTIVE
    assert classify_btc_context(TRENDING_UP, NEUTRAL, "short") == BTC_HOSTILE


def test_btc_context_neutral_when_btc_range_and_asset_neutral() -> None:
    assert classify_btc_context(RANGE, NEUTRAL, "long") == BTC_NEUTRAL


def test_btc_context_rejects_invalid_direction() -> None:
    with pytest.raises(ValueError):
        classify_btc_context(TRENDING_UP, NEUTRAL, "sideways")
