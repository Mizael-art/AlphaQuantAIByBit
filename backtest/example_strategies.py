"""
backtest/example_strategies.py
=================================

Estratégias de exemplo — servem para validar o pipeline
(HistoryFetcher -> Simulator -> Performance) ponta a ponta e como
referência de implementação. NÃO são Playbooks do Documento 3 (Sniper
Liquidity Sweep etc.) — essas ainda precisam ser codificadas depois
que o formato de "estratégia" for confirmado com o usuário.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest.strategy import Signal, Strategy


@dataclass
class SmaCrossStrategy(Strategy):
    """
    Estratégia de exemplo simples: cruzamento de médias móveis simples.

    Entra long quando a SMA rápida cruza para CIMA da SMA lenta no
    candle mais recente (não tinha cruzado no candle anterior). Stop
    técnico = mínima dos últimos `stop_lookback` candles (não é um
    stop artificial fixo — segue a mesma regra do Documento 1/3 de
    usar invalidação estrutural). TP = múltiplo fixo do risco (RR).

    Não entra short nesta versão de exemplo (mantido simples de propósito).
    """

    fast_period: int = 20
    slow_period: int = 50
    stop_lookback: int = 10
    reward_risk_ratio: float = 2.0
    name: str = "sma_cross_example"

    def min_candles_required(self) -> int:
        return max(self.slow_period, self.stop_lookback) + 1

    def generate_signal(self, df: pd.DataFrame) -> Signal | None:
        if len(df) < self.min_candles_required():
            return None

        close = df["close"]
        sma_fast = close.rolling(self.fast_period).mean()
        sma_slow = close.rolling(self.slow_period).mean()

        if sma_fast.iloc[-1] is None or sma_slow.iloc[-1] is None:
            return None
        if pd.isna(sma_fast.iloc[-1]) or pd.isna(sma_slow.iloc[-1]) or pd.isna(sma_fast.iloc[-2]) or pd.isna(sma_slow.iloc[-2]):
            return None

        crossed_up_now = sma_fast.iloc[-1] > sma_slow.iloc[-1]
        crossed_up_before = sma_fast.iloc[-2] > sma_slow.iloc[-2]

        if not (crossed_up_now and not crossed_up_before):
            return None  # só entra no candle exato do cruzamento, não em todo candle acima da média.

        reference_price = float(close.iloc[-1])
        stop_price = float(df["low"].iloc[-self.stop_lookback :].min())
        risk = reference_price - stop_price
        if risk <= 0:
            return None  # estrutura inválida (mínima recente acima do preço atual) -- não força um stop artificial.

        take_profit_price = reference_price + risk * self.reward_risk_ratio

        return Signal(
            direction="long",
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            reason=f"SMA{self.fast_period} cruzou acima da SMA{self.slow_period}",
        )
