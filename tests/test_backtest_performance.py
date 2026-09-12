"""
tests/test_backtest_performance.py
=====================================

Testes de `calculate_performance` com trades sintéticos (números
redondos, fáceis de verificar à mão).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backtest.performance import calculate_performance
from backtest.simulator import Trade


def _trade(r_multiple: float, exit_reason: str = "take_profit", mae_r: float = 0.0, mfe_r: float | None = None) -> Trade:
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return Trade(
        strategy_name="test", direction="long", signal_time=t, entry_time=t,
        entry_price_raw=100.0, entry_price_effective=100.0, stop_price=90.0, take_profit_price=120.0,
        exit_time=t, exit_price_raw=100.0 + r_multiple * 10, exit_price_effective=100.0 + r_multiple * 10,
        exit_reason=exit_reason, bars_held=5, r_multiple=r_multiple,
        mae_r=mae_r, mfe_r=mfe_r if mfe_r is not None else max(r_multiple, 0.0),
        reason="",
    )


def test_empty_trades_raises() -> None:
    with pytest.raises(ValueError, match="Nenhum trade"):
        calculate_performance([])


def test_all_wins_has_no_profit_factor_denominator_issue() -> None:
    trades = [_trade(2.0), _trade(1.5), _trade(3.0)]
    report = calculate_performance(trades)

    assert report.win_rate == 1.0
    assert report.losses == 0
    assert report.profit_factor is None  # sem perdas -- não divide por zero, não fabrica infinito
    assert report.payoff_ratio is None


def test_win_rate_and_expectancy_simple_case() -> None:
    # 2 wins de +2R, 2 losses de -1R -> win rate 50%, expectancy = 0.5*2 - 0.5*1 = 0.5
    trades = [_trade(2.0), _trade(2.0), _trade(-1.0), _trade(-1.0)]
    report = calculate_performance(trades)

    assert report.total_trades == 4
    assert report.wins == 2
    assert report.losses == 2
    assert report.win_rate == pytest.approx(0.5)
    assert report.expectancy_r == pytest.approx(0.5, abs=1e-6)
    assert report.avg_r == pytest.approx(0.5, abs=1e-6)


def test_profit_factor_calculation() -> None:
    # gross profit = 2+2=4, gross loss = |-1-1| = 2 -> PF = 2.0
    trades = [_trade(2.0), _trade(2.0), _trade(-1.0), _trade(-1.0)]
    report = calculate_performance(trades)

    assert report.profit_factor == pytest.approx(2.0, abs=1e-6)


def test_payoff_ratio_calculation() -> None:
    # avg win = 2.0, avg loss = 1.0 -> payoff = 2.0
    trades = [_trade(2.0), _trade(2.0), _trade(-1.0), _trade(-1.0)]
    report = calculate_performance(trades)

    assert report.payoff_ratio == pytest.approx(2.0, abs=1e-6)


def test_max_drawdown_from_r_curve() -> None:
    # curva acumulada: +2, +4 (pico), +1 (dd=3), -1 (dd=5), +2 (dd=2)
    trades = [_trade(2.0), _trade(2.0), _trade(-3.0), _trade(-2.0), _trade(3.0)]
    report = calculate_performance(trades)

    assert report.max_drawdown_r == pytest.approx(5.0, abs=1e-6)


def test_exit_reason_counts() -> None:
    trades = [
        _trade(2.0, exit_reason="take_profit"),
        _trade(-1.0, exit_reason="stop_loss"),
        _trade(0.3, exit_reason="end_of_data"),
    ]
    report = calculate_performance(trades)

    assert report.exit_reason_counts == {"take_profit": 1, "stop_loss": 1, "end_of_data": 1}


def test_avg_mae_mfe_aggregation() -> None:
    trades = [_trade(2.0, mae_r=-0.5, mfe_r=2.5), _trade(-1.0, mae_r=-1.2, mfe_r=0.1)]
    report = calculate_performance(trades)

    assert report.avg_mae_r == pytest.approx(-0.85, abs=1e-6)
    assert report.avg_mfe_r == pytest.approx(1.3, abs=1e-6)
