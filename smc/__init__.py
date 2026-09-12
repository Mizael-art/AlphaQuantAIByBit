"""
smc
===

Pacote de Smart Money Concepts (SMC): Order Blocks, Breaker Blocks,
Fair Value Gaps (FVG/iFVG), Equal Highs/Lows, Liquidity Sweeps e
zonas de Premium/Discount/OTE.

Complementa o pacote `structure` (que cobre HH/HL/LH/LL, BOS e CHOCH
em um nível mais "clássico" de price action).
"""

from smc.equal_highs_lows import EqualLevel, find_equal_highs_lows
from smc.fair_value_gaps import FVGZone, find_fair_value_gaps
from smc.liquidity_sweeps import LiquiditySweep, find_liquidity_sweeps
from smc.order_blocks import OrderBlock, find_order_blocks
from smc.premium_discount import (
    PremiumDiscountZones,
    calculate_premium_discount,
    premium_discount_from_swings,
)

__all__ = [
    "EqualLevel",
    "find_equal_highs_lows",
    "FVGZone",
    "find_fair_value_gaps",
    "LiquiditySweep",
    "find_liquidity_sweeps",
    "OrderBlock",
    "find_order_blocks",
    "PremiumDiscountZones",
    "calculate_premium_discount",
    "premium_discount_from_swings",
]
