"""
tests/test_scoring.py
========================

Testes puros do Multi-Score Engine.
"""

from __future__ import annotations

from scoring.engine import compute_opportunity_score


def _base_kwargs(**overrides) -> dict:
    base = dict(
        trend="Bullish",
        bos=True,
        choch=False,
        regime_compatible=True,
        rr=3.0,
        distance_to_zone_pct=0.3,
        volatility_bucket="NORMAL",
        btc_context="BTC_SUPPORTIVE",
        correlation_penalty=False,
        playbook_stats=None,
    )
    base.update(overrides)
    return base


def test_strong_setup_scores_high_overall() -> None:
    score = compute_opportunity_score(**_base_kwargs())
    assert score.overall > 70
    assert score.statistical_edge_available is False  # sem playbook_stats


def test_choch_penalizes_quality_confirmation_and_risk() -> None:
    strong = compute_opportunity_score(**_base_kwargs())
    with_choch = compute_opportunity_score(**_base_kwargs(choch=True))
    assert with_choch.quality < strong.quality
    assert with_choch.confirmation < strong.confirmation
    assert with_choch.risk < strong.risk


def test_btc_hostile_lowers_quality_vs_supportive() -> None:
    supportive = compute_opportunity_score(**_base_kwargs(btc_context="BTC_SUPPORTIVE"))
    hostile = compute_opportunity_score(**_base_kwargs(btc_context="BTC_HOSTILE"))
    assert hostile.quality < supportive.quality


def test_rr_none_gives_lowest_asymmetry() -> None:
    score = compute_opportunity_score(**_base_kwargs(rr=None))
    assert score.asymmetry == 0.0


def test_higher_rr_gives_higher_asymmetry() -> None:
    low_rr = compute_opportunity_score(**_base_kwargs(rr=1.2))
    high_rr = compute_opportunity_score(**_base_kwargs(rr=4.5))
    assert high_rr.asymmetry > low_rr.asymmetry


def test_extreme_volatility_lowers_risk_score() -> None:
    normal = compute_opportunity_score(**_base_kwargs(volatility_bucket="NORMAL"))
    extreme = compute_opportunity_score(**_base_kwargs(volatility_bucket="EXTREME"))
    assert extreme.risk < normal.risk


def test_correlation_penalty_lowers_risk_score() -> None:
    no_penalty = compute_opportunity_score(**_base_kwargs(correlation_penalty=False))
    penalized = compute_opportunity_score(**_base_kwargs(correlation_penalty=True))
    assert penalized.risk < no_penalty.risk


def test_distance_to_zone_none_is_conservative_not_optimistic() -> None:
    close = compute_opportunity_score(**_base_kwargs(distance_to_zone_pct=0.2))
    unknown = compute_opportunity_score(**_base_kwargs(distance_to_zone_pct=None))
    far = compute_opportunity_score(**_base_kwargs(distance_to_zone_pct=10.0))
    assert unknown.timing < close.timing
    assert unknown.timing > far.timing * 0.5  # neutro-baixo, não igual ao pior caso


def test_sufficient_playbook_stats_enable_statistical_edge() -> None:
    score = compute_opportunity_score(
        **_base_kwargs(playbook_stats={"win_rate": 65.0, "sample_size": 120, "expectancy_r": 0.8})
    )
    assert score.statistical_edge_available is True
    assert score.statistical_edge > 50.0


def test_insufficient_sample_size_keeps_statistical_edge_neutral() -> None:
    score = compute_opportunity_score(
        **_base_kwargs(playbook_stats={"win_rate": 90.0, "sample_size": 5, "expectancy_r": 2.0})
    )
    assert score.statistical_edge_available is False
    assert score.statistical_edge == 50.0


def test_scores_are_always_within_0_100() -> None:
    score = compute_opportunity_score(
        trend="Bearish", bos=False, choch=True, regime_compatible=False, rr=None,
        distance_to_zone_pct=None, volatility_bucket="EXTREME", btc_context="BTC_HOSTILE",
        correlation_penalty=True, playbook_stats=None,
    )
    for value in (
        score.quality, score.tradeability, score.timing, score.risk, score.asymmetry,
        score.confirmation, score.setup_maturity, score.statistical_edge, score.overall,
    ):
        assert 0.0 <= value <= 100.0
