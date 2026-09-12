"""
backtest/costs.py
====================

Modelo de custo de execução, em basis points (bps = 0,01%) sobre o
preço — não em unidades de preço fixas, porque XAUUSD (~2400),
BTCUSDT (~65000) e EURUSD (~1.08) têm escalas completamente
diferentes; bps é a única unidade que generaliza entre eles sem
inventar um número "por ponto" arbitrário por ativo.

Default de TODOS os custos é ZERO — o motor nunca assume um spread ou
slippage "realista" por conta própria (isso seria inventar dado). Se
o chamador não informar custos, o backtest roda "sem fricção" e o
resultado deve ser apresentado como tal (ver Documento 3, Parte 20 —
"custo de execução... se não informado, deixar explícito que o
resultado é bruto, sem custos").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CostModel:
    """
    Custos de execução aplicados a cada trade simulado.

    Attributes:
        spread_bps: metade do spread bid/ask, aplicado tanto na
            entrada quanto na saída (cada perna paga metade do
            spread). Em bps do preço.
        slippage_bps: deslizamento estimado entre o preço de sinal e o
            preço de execução real, aplicado na entrada e na saída.
        commission_bps: comissão da corretora/exchange, aplicada na
            entrada e na saída (round-turn = 2x este valor).
    """

    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0

    @property
    def is_zero_cost(self) -> bool:
        return self.spread_bps == 0.0 and self.slippage_bps == 0.0 and self.commission_bps == 0.0

    def _total_bps_per_leg(self) -> float:
        # spread_bps já representa "metade do spread" (custo de uma perna).
        return self.spread_bps + self.slippage_bps + self.commission_bps

    def apply_to_entry(self, direction: str, raw_price: float) -> float:
        """Preço de entrada efetivo, incluindo custo (pior para o trader: paga mais ao comprar)."""
        cost_fraction = self._total_bps_per_leg() / 10_000
        return raw_price * (1 + cost_fraction) if direction == "long" else raw_price * (1 - cost_fraction)

    def apply_to_exit(self, direction: str, raw_price: float) -> float:
        """Preço de saída efetivo, incluindo custo (pior para o trader: recebe menos ao vender)."""
        cost_fraction = self._total_bps_per_leg() / 10_000
        return raw_price * (1 - cost_fraction) if direction == "long" else raw_price * (1 + cost_fraction)


ZERO_COST = CostModel()
