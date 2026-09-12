"""
smc/premium_discount.py
=========================

Cálculo das zonas de Premium, Discount, Equilibrium e OTE (Optimal
Trade Entry), baseadas no range do swing mais recente (swing high ao
swing low mais relevante, ou o range completo da janela analisada).

- **Discount** (0%-50% do range, a partir do swing low): zona
  "barata", onde compradores institucionais tendem a buscar entradas
  em tendência de alta.
- **Premium** (50%-100% do range): zona "cara", onde vendedores
  institucionais tendem a buscar entradas em tendência de baixa.
- **Equilibrium**: o ponto médio exato (50%) do range.
- **OTE (Optimal Trade Entry)**: zona de retração entre 61.8% e 79%
  (níveis de Fibonacci), considerada a região ideal de entrada a favor
  da tendência após um impulso.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PremiumDiscountZones:
    """Zonas de Premium/Discount/Equilibrium/OTE para o range vigente."""

    range_high: float
    range_low: float
    equilibrium: float
    premium_zone: tuple[float, float]     # (equilibrium, range_high)
    discount_zone: tuple[float, float]    # (range_low, equilibrium)
    ote_zone: tuple[float, float]         # zona de 61.8%-79% de retração
    current_zone: str                     # "premium" | "discount" | "equilibrium"

    def to_dict(self) -> dict:
        return {
            "range_high": round(self.range_high, 6),
            "range_low": round(self.range_low, 6),
            "equilibrium": round(self.equilibrium, 6),
            "premium_zone": [round(v, 6) for v in self.premium_zone],
            "discount_zone": [round(v, 6) for v in self.discount_zone],
            "ote_zone": [round(v, 6) for v in self.ote_zone],
            "current_zone": self.current_zone,
        }


def calculate_premium_discount(
    range_high: float,
    range_low: float,
    current_price: float,
) -> PremiumDiscountZones:
    """
    Calcula as zonas de Premium/Discount/OTE para um range de preço.

    Args:
        range_high: topo do range de referência (ex.: swing high mais
            recente relevante para a tendência vigente).
        range_low: fundo do range de referência (ex.: swing low mais
            recente relevante).
        current_price: preço atual, usado para classificar em qual
            zona o mercado está agora.

    Returns:
        `PremiumDiscountZones` com todas as zonas calculadas.
    """
    if range_high <= range_low:
        raise ValueError("range_high deve ser maior que range_low")

    span = range_high - range_low
    equilibrium = range_low + span * 0.5

    # Zona OTE: entre 61.8% e 79% de retração medidos a partir do
    # range_low (para um impulso de alta) — aqui expressa de forma
    # simétrica, aplicável a ambos os lados do range.
    ote_bottom = range_low + span * 0.618
    ote_top = range_low + span * 0.79

    if current_price > equilibrium:
        current_zone = "premium"
    elif current_price < equilibrium:
        current_zone = "discount"
    else:
        current_zone = "equilibrium"

    return PremiumDiscountZones(
        range_high=range_high,
        range_low=range_low,
        equilibrium=equilibrium,
        premium_zone=(equilibrium, range_high),
        discount_zone=(range_low, equilibrium),
        ote_zone=(ote_bottom, ote_top),
        current_zone=current_zone,
    )


def premium_discount_from_swings(
    swing_high: float | None,
    swing_low: float | None,
    current_price: float,
) -> PremiumDiscountZones | None:
    """
    Wrapper conveniente: calcula Premium/Discount usando o último
    swing high/low já detectado por `structure.market_structure`.

    Retorna None se algum dos swings não estiver disponível (ex.:
    histórico insuficiente).
    """
    if swing_high is None or swing_low is None:
        return None
    return calculate_premium_discount(range_high=swing_high, range_low=swing_low, current_price=current_price)
