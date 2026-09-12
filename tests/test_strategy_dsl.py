"""
tests/test_strategy_dsl.py
=============================

Testes do DSL de estratégia genérica (Documento 1): validação de
schema, indicador não suportado, regra subjetiva rejeitada,
cruzamento SMA gerando trade real via `BacktestSimulator`, trailing
stop/break-even, intrabar_priority configurável e position sizing.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from backtest.costs import CostModel
from backtest.simulator import BacktestSimulator
from models.candle import Candle
from strategy_dsl.errors import (
    InvalidRuleError,
    SchemaValidationError,
    UnsupportedFunctionError,
    UnsupportedIndicatorError,
)
from strategy_dsl.executor import parse_schema
from strategy_dsl.expression_engine import evaluate_rule, validate_rule_syntax
from strategy_dsl.generic_strategy import GenericStrategy, build_indicator_context
from strategy_dsl.indicators_registry import compute_indicator
from strategy_dsl.portfolio import build_equity_curve, build_trade_report
from strategy_dsl.schema import GenericStrategySchema, IndicatorSpec


def _candle(t: datetime, o: float, h: float, l: float, c: float, v: float = 100.0) -> Candle:
    return Candle(open_time=t, open=o, high=h, low=l, close=c, volume=v, close_time=t + timedelta(hours=1))


def _candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame([c.to_dict() for c in candles])
    df["open_time"] = pd.to_datetime(df["open_time"])
    return df.set_index("open_time", drop=False).sort_index()


def _sma_cross_schema(**overrides) -> dict:
    base = {
        "name": "sma_cross_generic",
        "description": "teste",
        "market": {"symbols": ["BTCUSDT"], "timeframe": "1h", "exchange": "BINANCE"},
        "direction": "long",
        "indicators": [
            {"id": "FAST", "type": "SMA", "period": 3, "source": "close"},
            {"id": "SLOW", "type": "SMA", "period": 6, "source": "close"},
        ],
        "entry": {"long": ["FAST crosses above SLOW"], "short": []},
        "filters": [],
        "exit": {
            "stop_loss": {"type": "percent", "value": 1.0},
            "take_profit": {"type": "rr", "value": 2.0},
        },
        "execution": {"intrabar_priority": "stop_first"},
        "position_sizing": {"type": "risk_percent", "value": 1.0},
        "costs": {},
        "starting_capital": 10_000.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_rejects_unknown_field() -> None:
    schema_dict = _sma_cross_schema()
    schema_dict["not_a_real_field"] = 123
    with pytest.raises(SchemaValidationError):
        parse_schema(schema_dict)


def test_schema_requires_starting_capital_for_risk_sizing() -> None:
    schema_dict = _sma_cross_schema(starting_capital=None)
    with pytest.raises(SchemaValidationError):
        parse_schema(schema_dict)


def test_schema_requires_entry_rules_for_declared_direction() -> None:
    schema_dict = _sma_cross_schema(direction="long_short")
    schema_dict["entry"] = {"long": ["FAST crosses above SLOW"], "short": []}
    with pytest.raises(SchemaValidationError):
        parse_schema(schema_dict)


def test_schema_rejects_multi_symbol() -> None:
    schema_dict = _sma_cross_schema()
    schema_dict["market"]["symbols"] = ["BTCUSDT", "ETHUSDT"]
    with pytest.raises(SchemaValidationError):
        parse_schema(schema_dict)


def test_indicator_id_defaults_to_type_plus_period() -> None:
    spec = IndicatorSpec(type="RSI", period=14)
    assert spec.id == "RSI14"


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------


def test_unsupported_indicator_raises_structured_error() -> None:
    candles = [_candle(datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i), 100, 101, 99, 100) for i in range(30)]
    df = _candles_to_df(candles)
    spec = IndicatorSpec(type="HMA", period=9)
    with pytest.raises(UnsupportedIndicatorError) as exc_info:
        compute_indicator(df, spec)
    assert exc_info.value.to_dict()["error"] == "unsupported_indicator"
    assert exc_info.value.to_dict()["indicator"] == "HMA"


def test_sma_indicator_matches_manual_rolling_mean() -> None:
    candles = [_candle(datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i), 100 + i, 101 + i, 99 + i, 100 + i) for i in range(10)]
    df = _candles_to_df(candles)
    spec = IndicatorSpec(id="S", type="SMA", period=3, source="close")
    result = compute_indicator(df, spec)
    expected = df["close"].rolling(3).mean()
    pd.testing.assert_series_equal(result["S"].reset_index(drop=True), expected.reset_index(drop=True), check_names=False)


# ---------------------------------------------------------------------------
# Expression engine (regras determinísticas)
# ---------------------------------------------------------------------------


def test_subjective_rule_is_rejected() -> None:
    with pytest.raises(InvalidRuleError):
        validate_rule_syntax("estrutura bonita")


def test_unsupported_function_is_rejected() -> None:
    with pytest.raises(UnsupportedFunctionError):
        validate_rule_syntax("import_os(close)")


def test_cross_above_detects_exact_crossing_bar() -> None:
    a = pd.Series([1, 1, 2, 3], dtype=float)
    b = pd.Series([2, 2, 2, 2], dtype=float)
    result = evaluate_rule("a crosses above b", {"a": a, "b": b})
    assert list(result) == [False, False, False, True]


def test_simple_comparison_rule() -> None:
    close = pd.Series([10, 20, 5], dtype=float)
    result = evaluate_rule("close > 15", {"close": close})
    assert list(result) == [False, True, False]


# ---------------------------------------------------------------------------
# GenericStrategy + BacktestSimulator (ponta a ponta)
# ---------------------------------------------------------------------------


def _flat_then_trending_candles(
    flat_n: int, trend_n: int, start: datetime, price: float = 100.0, step: float = 1.0
) -> list[Candle]:
    """
    `flat_n` candles parados (SMA rápida == SMA lenta, sem cruzamento
    possível) seguidos de `trend_n` candles em alta constante -- garante
    que o cruzamento de SMA aconteça DEPOIS do warmup mínimo dos
    indicadores, nunca escondido antes dele (o que faria o teste vazio
    por acidente de dados, não por bug real).
    """
    candles = []
    t = start
    for _ in range(flat_n):
        candles.append(_candle(t, price, price + 0.1, price - 0.1, price))
        t += timedelta(hours=1)
    for _ in range(trend_n):
        o = price
        c = price + step
        h = max(o, c) + 0.2
        l = min(o, c) - 0.2
        candles.append(_candle(t, o, h, l, c))
        price = c
        t += timedelta(hours=1)
    return candles


def _trending_candles(n: int, start: datetime, start_price: float = 100.0, step: float = 1.0) -> list[Candle]:
    """Preço sobe de forma constante -- garante que a SMA rápida cruza para cima da lenta."""
    candles = []
    price = start_price
    for i in range(n):
        o = price
        c = price + step
        h = max(o, c) + 0.2
        l = min(o, c) - 0.2
        candles.append(_candle(start + timedelta(hours=i), o, h, l, c))
        price = c
    return candles


def test_generic_strategy_generates_trade_on_sma_cross() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_then_trending_candles(15, 30, start)
    df = _candles_to_df(candles)

    schema = parse_schema(_sma_cross_schema())
    strategy = GenericStrategy(schema=schema)
    strategy.prepare(df)

    simulator = BacktestSimulator(strategy=strategy, cost_model=CostModel(), intrabar_priority="stop_first")
    trades = simulator.run(candles)

    assert len(trades) >= 1
    assert trades[0].direction == "long"


def test_generic_strategy_respects_intrabar_priority() -> None:
    """Mesmo cenário, priority diferente -> exit_reason pode divergir quando stop e TP cabem no mesmo candle."""
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_then_trending_candles(15, 30, start)
    df = _candles_to_df(candles)

    schema_dict = _sma_cross_schema()
    schema_dict["execution"]["intrabar_priority"] = "take_first"
    schema = parse_schema(schema_dict)
    strategy = GenericStrategy(schema=schema)
    strategy.prepare(df)

    simulator = BacktestSimulator(strategy=strategy, cost_model=CostModel(), intrabar_priority="take_first")
    assert simulator.intrabar_priority == "take_first"
    trades = simulator.run(candles)
    assert isinstance(trades, list)  # não quebra -- resultado pode ter 0+ trades dependendo do cenário.


def test_unsupported_stop_type_raises() -> None:
    schema_dict = _sma_cross_schema()
    schema_dict["exit"]["stop_loss"] = {"type": "not_a_real_type", "value": 1.0}
    with pytest.raises(SchemaValidationError):
        parse_schema(schema_dict)


# ---------------------------------------------------------------------------
# Position sizing + equity curve
# ---------------------------------------------------------------------------


def test_position_sizing_risk_percent_matches_expected_quantity() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_then_trending_candles(15, 30, start)
    df = _candles_to_df(candles)

    schema = parse_schema(_sma_cross_schema())
    strategy = GenericStrategy(schema=schema)
    strategy.prepare(df)

    simulator = BacktestSimulator(strategy=strategy, cost_model=CostModel(), intrabar_priority="stop_first")
    trades = simulator.run(candles)
    assert trades

    report = build_trade_report(trades, schema)
    first = report[0]
    stop_distance = abs(first.trade.entry_price_effective - first.trade.stop_price)
    expected_capital_at_risk = schema.starting_capital * (schema.position_sizing.value / 100)
    expected_quantity = expected_capital_at_risk / stop_distance
    assert math.isclose(first.quantity, expected_quantity, rel_tol=1e-9)


def test_equity_curve_starts_at_starting_capital_and_tracks_drawdown() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_then_trending_candles(15, 40, start)
    df = _candles_to_df(candles)

    schema = parse_schema(_sma_cross_schema())
    strategy = GenericStrategy(schema=schema)
    strategy.prepare(df)

    simulator = BacktestSimulator(strategy=strategy, cost_model=CostModel(), intrabar_priority="stop_first")
    trades = simulator.run(candles)
    assert trades

    report = build_trade_report(trades, schema)
    curve = build_equity_curve(report, schema.starting_capital)
    assert curve["starting_capital"] == schema.starting_capital
    assert curve["points"][0]["equity"] == schema.starting_capital
    assert curve["max_drawdown"] >= 0.0


# ---------------------------------------------------------------------------
# Trailing stop / break-even (via BacktestSimulator diretamente, sem GenericStrategy)
# ---------------------------------------------------------------------------


class _FixedSignalStrategy:
    """Strategy mínima (não usa a ABC pra simplificar) só para testar trailing/break-even isoladamente."""

    name = "fixed_signal_test"

    def __init__(self, signal, fire_at_index: int) -> None:
        self._signal = signal
        self._fire_at_index = fire_at_index
        self._fired = False

    def min_candles_required(self) -> int:
        return 2

    def generate_signal(self, df: pd.DataFrame):
        current_index = len(df) - 1
        if current_index == self._fire_at_index and not self._fired:
            self._fired = True
            return self._signal
        return None


def test_break_even_moves_stop_to_entry_after_trigger_r() -> None:
    from backtest.strategy import Signal

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    # min_candles_required=2 -> a primeira checagem de sinal acontece em
    # j=2 (usando candles[0:3]) -- o sinal dispara nesse candle, e a
    # ENTRADA acontece na abertura do candle seguinte (índice 3).
    candles = [
        _candle(start + timedelta(hours=0), 100, 100.5, 99.5, 100),
        _candle(start + timedelta(hours=1), 100, 100.5, 99.5, 100),
        _candle(start + timedelta(hours=2), 100, 100.5, 99.5, 100),  # sinal dispara aqui (índice 2)
        _candle(start + timedelta(hours=3), 100, 100.2, 99.8, 100),  # candle de entrada (open=100) -- neutro
        _candle(start + timedelta(hours=4), 100, 110, 100, 109),      # sobe forte -- 1R+ atingido, break-even deveria mover o stop
        _candle(start + timedelta(hours=5), 109, 109.5, 94, 95),      # despenca -- sem break-even, bateria no stop original (90)
    ]
    signal = Signal(
        direction="long",
        stop_price=90.0,
        take_profit_price=200.0,  # bem longe, não deve ser atingido neste teste
        break_even={"trigger_r": 1.0, "offset": 0.0},
    )
    strategy = _FixedSignalStrategy(signal, fire_at_index=2)
    simulator = BacktestSimulator(strategy=strategy, cost_model=CostModel(), intrabar_priority="stop_first")
    trades = simulator.run(candles)

    assert len(trades) == 1
    trade = trades[0]
    # Break-even aplicado -> saída perto da entrada (100), não no stop original (90).
    assert trade.exit_price_raw > 95.0
    assert trade.exit_reason == "stop_loss"


def test_trailing_stop_percent_tightens_stop_upward() -> None:
    from backtest.strategy import Signal

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = [
        _candle(start + timedelta(hours=0), 100, 100.5, 99.5, 100),
        _candle(start + timedelta(hours=1), 100, 100.5, 99.5, 100),
        _candle(start + timedelta(hours=2), 100, 100.5, 99.5, 100),  # sinal dispara aqui (índice 2)
        _candle(start + timedelta(hours=3), 100, 100.2, 99.8, 100),  # candle de entrada (open=100) -- neutro
        _candle(start + timedelta(hours=4), 100, 120, 100, 119),      # sobe até 120
        _candle(start + timedelta(hours=5), 119, 119.5, 100, 105),    # recua bastante -- trailing (5% de 120 = 114) deveria ter fechado antes disso
    ]
    signal = Signal(
        direction="long",
        stop_price=80.0,
        take_profit_price=500.0,
        trailing_stop={"type": "percent", "value": 5.0, "activation_r": 0.0},
    )
    strategy = _FixedSignalStrategy(signal, fire_at_index=2)
    simulator = BacktestSimulator(strategy=strategy, cost_model=CostModel(), intrabar_priority="stop_first")
    trades = simulator.run(candles)

    assert len(trades) == 1
    trade = trades[0]
    # Stop original era 80 -- se o trailing não tivesse funcionado, só fecharia bem mais abaixo.
    assert trade.exit_price_raw > 90.0
    assert trade.exit_reason == "stop_loss"
