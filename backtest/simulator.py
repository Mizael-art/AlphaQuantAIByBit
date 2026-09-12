"""
backtest/simulator.py
========================

Motor de simulação bar-a-bar (candle a candle), sem lookahead.

Regras de execução (documentadas porque mudam o resultado do
backtest — não são triviais):

1. `Strategy.generate_signal()` recebe candles só até e incluindo o
   candle `i` (fechado). Se gerar um `Signal`, a ORDEM É EXECUTADA NA
   ABERTURA do candle `i+1` — nunca no fechamento do candle `i` (isso
   seria assumir que dava pra entrar num preço que só existiu depois
   do sinal ter sido confirmado).

2. Dentro de um candle onde o trade está aberto, se tanto o stop
   quanto o TP estariam tecnicamente dentro do range [low, high]
   daquele candle, o simulador assume que o STOP FOI ATINGIDO PRIMEIRO
   (convenção conservadora-padrão em backtest sem dado de tick/book —
   ver Documento 2, "evitar lookahead bias"). Isso SUBESTIMA
   resultados otimistas de propósito — é a escolha mais defensável sem
   acesso a dado intrabar real.

3. Se o fim dos dados históricos chegar com um trade ainda aberto, ele
   é fechado ao preço de fechamento do último candle disponível, com
   `exit_reason="end_of_data"` — nunca é descartado silenciosamente
   (isso inflaria o Profit Factor ao remover perdas "em aberto").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

from backtest.costs import ZERO_COST, CostModel
from backtest.strategy import Signal, Strategy
from indicators.atr import calculate_atr
from models.candle import Candle

ExitReason = Literal["take_profit", "stop_loss", "end_of_data"]
IntrabarPriority = Literal["stop_first", "take_first"]
#: período fixo usado para o ATR de trailing_stop quando `type="atr"` --
#: o Documento 1 não define um período separado para isso no schema,
#: então usamos o mesmo default conservador do resto do motor (14).
_TRAILING_ATR_PERIOD = 14


@dataclass(frozen=True, slots=True)
class Trade:
    """Um trade simulado, do sinal ao fechamento."""

    strategy_name: str
    direction: str
    signal_time: datetime
    entry_time: datetime
    entry_price_raw: float
    entry_price_effective: float
    stop_price: float
    take_profit_price: float
    exit_time: datetime
    exit_price_raw: float
    exit_price_effective: float
    exit_reason: ExitReason
    bars_held: int
    r_multiple: float
    mae_r: float
    mfe_r: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy_name,
            "direction": self.direction,
            "signal_time": self.signal_time.isoformat(),
            "entry_time": self.entry_time.isoformat(),
            "entry_price": self.entry_price_effective,
            "stop_price": self.stop_price,
            "take_profit_price": self.take_profit_price,
            "exit_time": self.exit_time.isoformat(),
            "exit_price": self.exit_price_effective,
            "exit_reason": self.exit_reason,
            "bars_held": self.bars_held,
            "r_multiple": round(self.r_multiple, 3),
            "mae_r": round(self.mae_r, 3),
            "mfe_r": round(self.mfe_r, 3),
            "reason": self.reason,
        }


@dataclass
class _OpenTrade:
    direction: str
    signal_time: datetime
    entry_time: datetime
    entry_price_raw: float
    entry_price_effective: float
    stop_price: float
    take_profit_price: float
    risk_distance: float
    reason: str
    bars_held: int = 0
    worst_price: float = 0.0  # menor preço (long) / maior preço (short) já visto
    best_price: float = 0.0   # maior preço (long) / menor preço (short) já visto
    trailing_stop_config: dict | None = None
    break_even_config: dict | None = None
    break_even_applied: bool = False


class BacktestSimulator:
    """
    Roda uma `Strategy` sobre uma série de candles, produzindo uma
    lista de `Trade` simulados. Uma posição por vez (sem pirâmide,
    sem hedge) — mantém o modelo simples e auditável.
    """

    def __init__(
        self,
        strategy: Strategy,
        cost_model: CostModel | None = None,
        intrabar_priority: IntrabarPriority = "stop_first",
    ) -> None:
        self.strategy = strategy
        self.cost_model = cost_model or ZERO_COST
        #: Documento 1, seção 6 -- convenção explícita de qual lado é
        #: checado primeiro quando stop e TP cabem no mesmo candle.
        #: "stop_first" é o default conservador (comportamento anterior
        #: a este parâmetro, preservado). Sempre reportado no resultado
        #: final (nunca fica implícito -- ver `strategy_dsl/report.py`).
        self.intrabar_priority: IntrabarPriority = intrabar_priority
        #: sinais que a Strategy gerou mas que falharam na validação
        #: estrutural (`Signal.validate`) -- não viram trade, mas ficam
        #: registrados para diagnóstico (nunca descartados em silêncio).
        self.rejected_signals: list[tuple[datetime, str]] = []

    def run(self, candles: list[Candle]) -> list[Trade]:
        if len(candles) < self.strategy.min_candles_required() + 2:
            raise ValueError(
                f"Candles insuficientes para rodar '{self.strategy.name}': "
                f"{len(candles)} disponíveis, mínimo "
                f"{self.strategy.min_candles_required() + 2} "
                f"(min_candles_required + 1 para executar + 1 para checar saída)."
            )

        df = pd.DataFrame([c.to_dict() for c in candles])
        df["open_time"] = pd.to_datetime(df["open_time"])
        df = df.set_index("open_time", drop=False).sort_index()

        # Pré-calculado sempre (custo desprezível) para estar disponível
        # caso algum trade aberto use trailing_stop do tipo "atr".
        atr_series = calculate_atr(df, _TRAILING_ATR_PERIOD)

        trades: list[Trade] = []
        open_trade: _OpenTrade | None = None
        min_required = self.strategy.min_candles_required()

        j = min_required
        n = len(df)
        while j < n:
            candle = df.iloc[j]

            if open_trade is None:
                if j + 1 >= n:
                    break  # não há candle seguinte pra executar a entrada -- fim dos dados.

                signal = self.strategy.generate_signal(df.iloc[: j + 1])
                if signal is None:
                    j += 1
                    continue

                entry_candle = df.iloc[j + 1]
                entry_raw = float(entry_candle["open"])

                try:
                    signal.validate(entry_raw)
                except ValueError as exc:
                    self.rejected_signals.append((entry_candle["open_time"], str(exc)))
                    j += 1
                    continue

                entry_effective = self.cost_model.apply_to_entry(signal.direction, entry_raw)
                risk_distance = abs(entry_effective - signal.stop_price)
                if risk_distance <= 0:
                    self.rejected_signals.append(
                        (entry_candle["open_time"], "risk_distance <= 0 (stop igual à entrada)")
                    )
                    j += 1
                    continue

                open_trade = _OpenTrade(
                    direction=signal.direction,
                    signal_time=candle["open_time"],
                    entry_time=entry_candle["open_time"],
                    entry_price_raw=entry_raw,
                    entry_price_effective=entry_effective,
                    stop_price=signal.stop_price,
                    take_profit_price=signal.take_profit_price,
                    risk_distance=risk_distance,
                    reason=signal.reason,
                    worst_price=entry_effective,
                    best_price=entry_effective,
                    trailing_stop_config=signal.trailing_stop,
                    break_even_config=signal.break_even,
                )
                j += 1  # avança pro candle de entrada -- ele já é checado como candle de exit abaixo.
                continue

            # há um trade aberto: atualiza MAE/MFE, aplica break-even/trailing
            # (na ordem: primeiro atualiza best/worst do candle, depois ajusta
            # o stop com base neles, só então checa se o candle atingiu o
            # stop/TP -- isso evita usar um "melhor preço" que só existiria
            # depois do próprio candle ter sido avaliado).
            open_trade.bars_held += 1

            if open_trade.direction == "long":
                open_trade.worst_price = min(open_trade.worst_price, float(candle["low"]))
                open_trade.best_price = max(open_trade.best_price, float(candle["high"]))
            else:
                open_trade.worst_price = max(open_trade.worst_price, float(candle["high"]))
                open_trade.best_price = min(open_trade.best_price, float(candle["low"]))

            self._apply_break_even(open_trade)
            self._apply_trailing_stop(open_trade, atr_series, j)

            exit_info = self._check_exit(open_trade, candle)

            is_last_candle = j == n - 1
            if exit_info is not None or is_last_candle:
                exit_price_raw, exit_reason = exit_info or (float(candle["close"]), "end_of_data")
                trades.append(self._close_trade(open_trade, candle["open_time"], exit_price_raw, exit_reason))
                open_trade = None

            j += 1

        return trades

    def _current_r(self, trade: _OpenTrade) -> float:
        """R multiple não-realizado com base no `best_price` já visto (usado por break-even/trailing)."""
        if trade.direction == "long":
            return (trade.best_price - trade.entry_price_effective) / trade.risk_distance
        return (trade.entry_price_effective - trade.best_price) / trade.risk_distance

    def _apply_break_even(self, trade: _OpenTrade) -> None:
        """Documento 1, seção 7 -- move o stop para o preço de entrada (+ offset) ao atingir `trigger_r`."""
        config = trade.break_even_config
        if config is None or trade.break_even_applied:
            return
        if self._current_r(trade) < config["trigger_r"]:
            return

        offset = config.get("offset", 0.0)
        if trade.direction == "long":
            new_stop = trade.entry_price_effective + offset
            if new_stop > trade.stop_price:
                trade.stop_price = new_stop
        else:
            new_stop = trade.entry_price_effective - offset
            if new_stop < trade.stop_price:
                trade.stop_price = new_stop
        trade.break_even_applied = True

    def _apply_trailing_stop(self, trade: _OpenTrade, atr_series: pd.Series, bar_index: int) -> None:
        """Documento 1, seção 7 -- nunca afrouxa o stop, só aperta a favor do trade."""
        config = trade.trailing_stop_config
        if config is None:
            return
        if self._current_r(trade) < config.get("activation_r", 0.0):
            return

        trailing_type = config["type"]
        value = config["value"]

        if trailing_type == "percent":
            distance = trade.best_price * (value / 100)
        elif trailing_type == "atr":
            atr_value = atr_series.iloc[bar_index]
            if pd.isna(atr_value):
                return  # ATR ainda não disponível (início da série) -- não afrouxa nem trava o stop.
            distance = value * float(atr_value)
        else:
            return

        if trade.direction == "long":
            new_stop = trade.best_price - distance
            if new_stop > trade.stop_price:
                trade.stop_price = new_stop
        else:
            new_stop = trade.best_price + distance
            if new_stop < trade.stop_price:
                trade.stop_price = new_stop

    def _check_exit(self, trade: _OpenTrade, candle: pd.Series) -> tuple[float, ExitReason] | None:
        """
        Ordem de checagem controlada por `self.intrabar_priority` quando
        tanto o stop quanto o TP caberiam no range do mesmo candle --
        nunca assumido implicitamente (Documento 1, seção 6). Default
        "stop_first" preserva o comportamento anterior a este parâmetro.
        """
        high, low = float(candle["high"]), float(candle["low"])

        if trade.direction == "long":
            hit_stop = low <= trade.stop_price
            hit_take = high >= trade.take_profit_price
        else:
            hit_stop = high >= trade.stop_price
            hit_take = low <= trade.take_profit_price

        if hit_stop and hit_take:
            if self.intrabar_priority == "take_first":
                return trade.take_profit_price, "take_profit"
            return trade.stop_price, "stop_loss"
        if hit_stop:
            return trade.stop_price, "stop_loss"
        if hit_take:
            return trade.take_profit_price, "take_profit"
        return None

    def _close_trade(
        self, trade: _OpenTrade, exit_time: datetime, exit_price_raw: float, exit_reason: ExitReason
    ) -> Trade:
        exit_effective = self.cost_model.apply_to_exit(trade.direction, exit_price_raw)

        if trade.direction == "long":
            r_multiple = (exit_effective - trade.entry_price_effective) / trade.risk_distance
            mae_r = (trade.worst_price - trade.entry_price_effective) / trade.risk_distance
            mfe_r = (trade.best_price - trade.entry_price_effective) / trade.risk_distance
        else:
            r_multiple = (trade.entry_price_effective - exit_effective) / trade.risk_distance
            mae_r = (trade.entry_price_effective - trade.worst_price) / trade.risk_distance
            mfe_r = (trade.entry_price_effective - trade.best_price) / trade.risk_distance

        return Trade(
            strategy_name=self.strategy.name,
            direction=trade.direction,
            signal_time=trade.signal_time,
            entry_time=trade.entry_time,
            entry_price_raw=trade.entry_price_raw,
            entry_price_effective=trade.entry_price_effective,
            stop_price=trade.stop_price,
            take_profit_price=trade.take_profit_price,
            exit_time=exit_time,
            exit_price_raw=exit_price_raw,
            exit_price_effective=exit_effective,
            exit_reason=exit_reason,
            bars_held=trade.bars_held,
            r_multiple=r_multiple,
            mae_r=min(mae_r, 0.0),  # MAE é sempre <= 0 por definição (excursão adversa)
            mfe_r=max(mfe_r, 0.0),  # MFE é sempre >= 0 por definição (excursão favorável)
            reason=trade.reason,
        )
