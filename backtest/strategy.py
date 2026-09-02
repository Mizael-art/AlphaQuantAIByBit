"""
backtest/strategy.py
=======================

Interface `Strategy` para o motor de backtest.

DECISÃO DE DESIGN (assumida, sinalizada ao usuário — pode mudar):
como o GPT só envia parâmetros estruturados para uma action (não
código arbitrário), uma "estratégia" aqui é uma classe Python
pré-cadastrada no motor, identificada por um nome curto (ex.:
`"ema_cross"`), com parâmetros numéricos ajustáveis. Isso espelha o
conceito de Playbook do arquivo 02 das instruções do GPT — a ideia é
que, no futuro, cada Playbook (Liquidity Sweep Reversal, Session
High/Low Sweep, etc.) vire uma `Strategy` concreta aqui.

Uma `Strategy` NUNCA vê candles futuros: `generate_signal` recebe só
o histórico até e incluindo o candle atual (`df.iloc[:i+1]`). Isso é
a garantia estrutural contra lookahead bias — o simulador é quem
impõe esse corte, a Strategy não tem acesso a mais do que isso.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

import pandas as pd

Direction = Literal["long", "short"]


@dataclass(frozen=True, slots=True)
class Signal:
    """
    Sinal de entrada gerado por uma `Strategy` no fechamento de um candle.

    A execução real (pelo simulador) acontece na ABERTURA do PRÓXIMO
    candle — nunca no mesmo candle em que o sinal foi gerado (isso
    seria lookahead: a Strategy não poderia ter sabido o preço de
    fechamento antes dele acontecer, então também não pode "entrar"
    nesse exato preço).

    O stop DEVE ser a invalidação técnica da tese, nunca comprimido
    artificialmente para melhorar o RR (mesma regra do Documento 1/3)
    — isso é responsabilidade de quem implementa a `Strategy`, o
    simulador não valida se o stop é "tecnicamente correto", só que é
    coerente (do lado certo do preço de entrada).
    """

    direction: Direction
    stop_price: float
    take_profit_price: float
    reason: str = ""
    #: gestão de saída opcional (Documento 1, seção 7) -- `None` preserva
    #: 100% o comportamento anterior (stop/TP fixos). Formato:
    #: {"type": "percent"|"atr", "value": float, "activation_r": float}
    trailing_stop: dict | None = None
    #: {"trigger_r": float, "offset": float}
    break_even: dict | None = None

    def validate(self, reference_price: float) -> None:
        """Sanity check estrutural (stop/TP do lado certo do preço de referência)."""
        if self.direction == "long":
            if not (self.stop_price < reference_price < self.take_profit_price):
                raise ValueError(
                    f"Signal 'long' inconsistente: stop={self.stop_price}, "
                    f"ref={reference_price}, tp={self.take_profit_price} "
                    f"(esperado stop < ref < tp)."
                )
        else:
            if not (self.take_profit_price < reference_price < self.stop_price):
                raise ValueError(
                    f"Signal 'short' inconsistente: tp={self.take_profit_price}, "
                    f"ref={reference_price}, stop={self.stop_price} "
                    f"(esperado tp < ref < stop)."
                )


class Strategy(ABC):
    """
    Interface que toda estratégia de backtest deve implementar.

    Exemplo mínimo:
        class MyStrategy(Strategy):
            name = "my_strategy"
            def generate_signal(self, df):
                if df["close"].iloc[-1] > df["close"].iloc[-2]:
                    price = df["close"].iloc[-1]
                    return Signal(direction="long", stop_price=price*0.99, take_profit_price=price*1.02)
                return None
    """

    #: Nome curto e estável, usado para registrar/selecionar a estratégia
    #: (ex.: no parâmetro `strategy` da action de backtest).
    name: str

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> Signal | None:
        """
        Avalia o histórico disponível ATÉ o candle mais recente
        (`df.iloc[-1]`) e decide se um novo sinal de entrada deve ser
        considerado.

        Chamado pelo simulador candle a candle, sempre que não há
        posição aberta. `df` nunca contém candles futuros em relação
        ao candle atual — essa é a garantia de não-lookahead.

        Returns:
            `Signal` se uma entrada deve ser considerada (executada na
            abertura do PRÓXIMO candle pelo simulador), ou `None`.
        """

    def min_candles_required(self) -> int:
        """
        Quantos candles de histórico esta estratégia precisa antes de
        começar a gerar sinais (ex.: uma EMA de 200 períodos precisa
        de pelo menos 200 candles). Default conservador — sobrescreva
        se a estratégia precisar de mais.
        """
        return 200
