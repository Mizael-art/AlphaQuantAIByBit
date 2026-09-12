"""
strategy_dsl/generic_strategy.py
===================================

`GenericStrategy` -- ponte entre o `GenericStrategySchema` (Documento 1)
e a interface `Strategy` já existente em `backtest/strategy.py`, para
reaproveitar 100% do `BacktestSimulator` sem duplicar a lógica de
execução bar-a-bar / não-lookahead.

Estratégia de implementação:

1. Todo o histórico de candles é conhecido ANTES do backtest rodar
   (não é streaming ao vivo) -- então os indicadores e as regras de
   entrada/filtro são calculados UMA VEZ, de forma vetorizada, sobre o
   DataFrame completo (`indicators_registry` + `expression_engine`).
2. `BacktestSimulator.run()` reconstrói seu próprio DataFrame a partir
   da MESMA lista de `Candle` (mesma ordem, mesmo tamanho) e chama
   `generate_signal(df.iloc[:j+1])` a cada candle `j`. Como a posição
   `j` é idêntica entre os dois DataFrames, `GenericStrategy` só
   precisa indexar as séries pré-calculadas por POSIÇÃO
   (`.iloc[j]`), nunca recalcular nada dentro do loop.
3. Isso preserva a garantia de não-lookahead: cada indicador/regra usa
   só `.rolling()`/EMA causais, e o valor usado no candle `j` só
   depende de candles `<= j` -- exatamente o que já valia para as
   estratégias manuais.

`entry.long` / `entry.short`: todas as regras da lista são combinadas
com AND (é uma checklist, não uma lista de alternativas) -- e da mesma
forma `filters`. Essa é uma decisão de design explícita (o Documento 1
não define isso), documentada aqui e em `capabilities.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backtest.strategy import Signal, Strategy
from indicators.atr import calculate_atr
from strategy_dsl.errors import InvalidRuleError
from strategy_dsl.expression_engine import evaluate_rule
from strategy_dsl.indicators_registry import compute_indicator
from strategy_dsl.schema import GenericStrategySchema

_INTERNAL_ATR_PERIOD = 14  # usado para stop_loss/take_profit do tipo "atr" quando o schema não declara um indicador ATR explícito.


def build_indicator_context(df: pd.DataFrame, schema: GenericStrategySchema) -> dict[str, pd.Series]:
    """
    Calcula todos os indicadores declarados + as séries base OHLCV +
    um ATR(14) interno de referência (para stop/TP tipo "atr" quando
    o schema não declarar um indicador ATR próprio).

    Raises:
        UnsupportedIndicatorError: propagada de `compute_indicator`.
    """
    context: dict[str, pd.Series] = {
        "open": df["open"], "high": df["high"], "low": df["low"],
        "close": df["close"], "volume": df["volume"],
        "__atr__": calculate_atr(df, _INTERNAL_ATR_PERIOD),
    }
    for spec in schema.indicators:
        context.update(compute_indicator(df, spec))
    return context


def _combine_and(df: pd.DataFrame, rules: list[str], context: dict[str, pd.Series]) -> pd.Series:
    if not rules:
        return pd.Series(True, index=df.index)
    result = evaluate_rule(rules[0], context)
    for rule in rules[1:]:
        result = result & evaluate_rule(rule, context)
    return result.fillna(False)


@dataclass
class GenericStrategy(Strategy):
    schema: GenericStrategySchema
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.name = self.schema.name
        self._context: dict[str, pd.Series] | None = None
        self._long_signal: pd.Series | None = None
        self._short_signal: pd.Series | None = None
        self._filters_ok: pd.Series | None = None
        self._min_candles = 200  # ajustado em `prepare()` com base nos períodos reais dos indicadores.

    def prepare(self, df: pd.DataFrame) -> None:
        """
        Pré-computa indicadores e regras sobre o histórico completo.
        Deve ser chamado UMA VEZ, com o DataFrame completo, antes de
        passar esta strategy para o `BacktestSimulator` (que depois só
        recebe fatias progressivas dele -- ver docstring do módulo).
        """
        self._context = build_indicator_context(df, self.schema)

        long_rules = list(self.schema.entry.long)
        short_rules = list(self.schema.entry.short)
        self._long_signal = _combine_and(df, long_rules, self._context) if long_rules else None
        self._short_signal = _combine_and(df, short_rules, self._context) if short_rules else None
        self._filters_ok = _combine_and(df, self.schema.filters, self._context)

        declared_periods = [spec.period for spec in self.schema.indicators if spec.period]
        needs_atr = self.schema.exit.stop_loss.type == "atr" or self.schema.exit.take_profit.type == "atr"
        if self.schema.exit.trailing_stop is not None and self.schema.exit.trailing_stop.type == "atr":
            needs_atr = True
        periods = [*declared_periods, _INTERNAL_ATR_PERIOD] if needs_atr else (declared_periods or [1])
        self._min_candles = max(periods) + 2

    def min_candles_required(self) -> int:
        return self._min_candles

    def generate_signal(self, df: pd.DataFrame) -> Signal | None:
        if self._context is None:
            raise RuntimeError("GenericStrategy.prepare(df_completo) precisa ser chamado antes do backtest rodar.")

        i = len(df) - 1
        if i < self.min_candles_required():
            return None
        if not bool(self._filters_ok.iloc[i]):
            return None

        direction = self.schema.direction
        if direction in ("long", "long_short") and self._long_signal is not None and bool(self._long_signal.iloc[i]):
            return self._build_signal("long", df, i)
        if direction in ("short", "long_short") and self._short_signal is not None and bool(self._short_signal.iloc[i]):
            return self._build_signal("short", df, i)
        return None

    def _build_signal(self, direction: str, df: pd.DataFrame, i: int) -> Signal | None:
        reference_price = float(df["close"].iloc[i])
        atr_value = float(self._context["__atr__"].iloc[i]) if not pd.isna(self._context["__atr__"].iloc[i]) else None

        stop_price = self._resolve_stop(direction, reference_price, atr_value)
        if stop_price is None:
            return None  # ATR indisponível (início da série) -- nunca inventa um stop.

        risk = abs(reference_price - stop_price)
        if risk <= 0:
            return None

        take_profit_price = self._resolve_take_profit(direction, reference_price, stop_price, risk, atr_value)
        if take_profit_price is None:
            return None

        trailing = None
        if self.schema.exit.trailing_stop is not None:
            trailing = {
                "type": self.schema.exit.trailing_stop.type,
                "value": self.schema.exit.trailing_stop.value,
                "activation_r": self.schema.exit.trailing_stop.activation_r,
            }
        break_even = None
        if self.schema.exit.break_even is not None:
            break_even = {
                "trigger_r": self.schema.exit.break_even.trigger_r,
                "offset": self.schema.exit.break_even.offset,
            }

        return Signal(
            direction=direction,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            reason=f"{self.schema.name}: " + " AND ".join(
                self.schema.entry.long if direction == "long" else self.schema.entry.short
            ),
            trailing_stop=trailing,
            break_even=break_even,
        )

    def _resolve_stop(self, direction: str, reference_price: float, atr_value: float | None) -> float | None:
        spec = self.schema.exit.stop_loss
        sign = 1 if direction == "long" else -1
        if spec.type == "percent":
            return reference_price - sign * reference_price * (spec.value / 100)
        if spec.type == "atr":
            if atr_value is None:
                return None
            return reference_price - sign * atr_value * spec.value
        if spec.type == "price":
            return spec.value
        raise InvalidRuleError(spec.type, "tipo de stop_loss não suportado.")

    def _resolve_take_profit(
        self, direction: str, reference_price: float, stop_price: float, risk: float, atr_value: float | None
    ) -> float | None:
        spec = self.schema.exit.take_profit
        sign = 1 if direction == "long" else -1
        if spec.type == "percent":
            return reference_price + sign * reference_price * (spec.value / 100)
        if spec.type == "rr":
            return reference_price + sign * risk * spec.value
        if spec.type == "atr":
            if atr_value is None:
                return None
            return reference_price + sign * atr_value * spec.value
        if spec.type == "price":
            return spec.value
        raise InvalidRuleError(spec.type, "tipo de take_profit não suportado.")
