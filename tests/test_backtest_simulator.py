"""
tests/test_backtest_simulator.py
===================================

Testes do `BacktestSimulator` com estratégias determinísticas
(escritas só para teste, sem indicador real) — cobre: execução no
próximo candle (não lookahead), regra conservadora "stop antes do TP"
quando ambos cabem no mesmo candle, fechamento por fim de dados,
aplicação de custo, e rejeição de sinal estruturalmente inválido.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from backtest.costs import CostModel
from backtest.simulator import BacktestSimulator
from backtest.strategy import Signal, Strategy
from models.candle import Candle


def _candle(t: datetime, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(open_time=t, open=o, high=h, low=l, close=c, volume=10.0, close_time=t + timedelta(hours=1))


def _flat_candles(n: int, start: datetime, price: float = 100.0) -> list[Candle]:
    """Candles planos (sem movimento) -- útil como "padding" antes do gatilho do teste."""
    return [_candle(start + timedelta(hours=i), price, price + 0.1, price - 0.1, price) for i in range(n)]


class _FireOnceStrategy(Strategy):
    """Dispara exatamente UM sinal, no índice de candle `fire_at_index` (contando a partir de 0)."""

    name = "fire_once_test"

    def __init__(self, fire_at_index: int, signal: Signal, min_required: int = 5) -> None:
        self._fire_at_index = fire_at_index
        self._signal = signal
        self._min_required = min_required
        self._fired = False

    def min_candles_required(self) -> int:
        return self._min_required

    def generate_signal(self, df: pd.DataFrame) -> Signal | None:
        current_index = len(df) - 1
        if current_index == self._fire_at_index and not self._fired:
            self._fired = True
            return self._signal
        return None


def test_entry_executes_on_next_candle_open_not_signal_candle_close() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_candles(10, start, price=100.0)
    # candle de sinal (índice 5) fecha em 100 -- mas a entrada deve ser
    # o OPEN do candle 6, não o close do candle 5.
    candles[6] = _candle(start + timedelta(hours=6), o=105.0, h=106.0, l=104.0, c=105.0)
    # candles seguintes nunca tocam stop/tp -- termina em end_of_data.

    signal = Signal(direction="long", stop_price=90.0, take_profit_price=200.0)
    strategy = _FireOnceStrategy(fire_at_index=5, signal=signal, min_required=5)
    sim = BacktestSimulator(strategy=strategy)

    trades = sim.run(candles)

    assert len(trades) == 1
    assert trades[0].entry_price_raw == 105.0  # open do candle 6, não close do candle 5 (100.0)
    assert trades[0].entry_time == candles[6].open_time


def test_stop_checked_before_take_profit_when_both_fit_same_candle() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_candles(10, start, price=100.0)
    entry_open = 100.0
    candles[6] = _candle(start + timedelta(hours=6), o=entry_open, h=100.5, l=99.5, c=100.0)
    # candle seguinte (entrada) toca tanto o stop (95) quanto o TP (110) --
    # convenção conservadora: stop deve ganhar.
    candles[7] = _candle(start + timedelta(hours=7), o=100.0, h=115.0, l=90.0, c=105.0)

    signal = Signal(direction="long", stop_price=95.0, take_profit_price=110.0)
    strategy = _FireOnceStrategy(fire_at_index=5, signal=signal, min_required=5)
    sim = BacktestSimulator(strategy=strategy)

    trades = sim.run(candles)

    assert len(trades) == 1
    assert trades[0].exit_reason == "stop_loss"
    assert trades[0].exit_price_raw == 95.0
    assert trades[0].r_multiple == pytest.approx(-1.0, abs=1e-6)


def test_take_profit_hit_cleanly_gives_positive_r() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_candles(10, start, price=100.0)
    candles[6] = _candle(start + timedelta(hours=6), o=100.0, h=100.5, l=99.5, c=100.0)
    # TP a 110 (risco de 10 a partir de stop=90, entrada=100 -> RR=2 exato ao tocar 120)
    candles[7] = _candle(start + timedelta(hours=7), o=100.0, h=121.0, l=99.0, c=115.0)

    signal = Signal(direction="long", stop_price=90.0, take_profit_price=120.0)
    strategy = _FireOnceStrategy(fire_at_index=5, signal=signal, min_required=5)
    sim = BacktestSimulator(strategy=strategy)

    trades = sim.run(candles)

    assert trades[0].exit_reason == "take_profit"
    assert trades[0].r_multiple == pytest.approx(2.0, abs=1e-6)  # risco=10, ganho=20 -> R=2


def test_open_trade_closed_as_end_of_data_at_last_candle() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_candles(9, start, price=100.0)  # índices 0..8, último é o 8
    candles[7] = _candle(start + timedelta(hours=7), o=100.0, h=101.0, l=99.0, c=100.0)
    candles[8] = _candle(start + timedelta(hours=8), o=100.0, h=101.0, l=99.0, c=102.0)  # última vela

    signal = Signal(direction="long", stop_price=50.0, take_profit_price=500.0)  # nunca vai bater nenhum dos dois
    strategy = _FireOnceStrategy(fire_at_index=6, signal=signal, min_required=5)
    sim = BacktestSimulator(strategy=strategy)

    trades = sim.run(candles)

    assert len(trades) == 1
    assert trades[0].exit_reason == "end_of_data"
    assert trades[0].exit_price_raw == 102.0  # close da última vela


def test_cost_model_reduces_effective_pnl() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_candles(10, start, price=100.0)
    candles[6] = _candle(start + timedelta(hours=6), o=100.0, h=100.5, l=99.5, c=100.0)
    candles[7] = _candle(start + timedelta(hours=7), o=100.0, h=121.0, l=99.0, c=115.0)

    signal = Signal(direction="long", stop_price=90.0, take_profit_price=120.0)

    strategy_free = _FireOnceStrategy(fire_at_index=5, signal=signal, min_required=5)
    r_no_cost = BacktestSimulator(strategy=strategy_free).run(candles)[0].r_multiple

    strategy_costly = _FireOnceStrategy(fire_at_index=5, signal=signal, min_required=5)
    costs = CostModel(spread_bps=50.0, slippage_bps=20.0, commission_bps=10.0)  # custo alto de propósito
    r_with_cost = BacktestSimulator(strategy=strategy_costly, cost_model=costs).run(candles)[0].r_multiple

    assert r_with_cost < r_no_cost  # custo sempre piora o resultado, nunca melhora


def test_invalid_signal_is_rejected_not_silently_dropped() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_candles(10, start, price=100.0)
    # sinal 'long' com stop ACIMA do preço de entrada -- estruturalmente inválido.
    signal = Signal(direction="long", stop_price=999.0, take_profit_price=1000.0)
    strategy = _FireOnceStrategy(fire_at_index=5, signal=signal, min_required=5)
    sim = BacktestSimulator(strategy=strategy)

    trades = sim.run(candles)

    assert trades == []
    assert len(sim.rejected_signals) == 1


def test_insufficient_candles_raises() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_candles(3, start)
    strategy = _FireOnceStrategy(fire_at_index=1, signal=Signal("long", 90, 110), min_required=200)
    sim = BacktestSimulator(strategy=strategy)

    with pytest.raises(ValueError, match="insuficientes"):
        sim.run(candles)


def test_mae_mfe_are_tracked_and_signed_correctly() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_candles(10, start, price=100.0)
    candles[6] = _candle(start + timedelta(hours=6), o=100.0, h=100.5, l=99.5, c=100.0)
    # dá um mergulho adverso (até 95) antes de fechar no TP no candle seguinte.
    candles[7] = _candle(start + timedelta(hours=7), o=100.0, h=101.0, l=95.0, c=98.0)
    candles[8] = _candle(start + timedelta(hours=8), o=98.0, h=121.0, l=97.0, c=115.0)

    signal = Signal(direction="long", stop_price=90.0, take_profit_price=120.0)
    strategy = _FireOnceStrategy(fire_at_index=5, signal=signal, min_required=5)
    trades = BacktestSimulator(strategy=strategy).run(candles)

    assert trades[0].mae_r < 0  # excursão adversa sempre <= 0
    assert trades[0].mfe_r > 0  # excursão favorável sempre >= 0
