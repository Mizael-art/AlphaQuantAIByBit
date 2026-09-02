"""
structure
=========

Pacote responsável pela detecção de estrutura de mercado (Price
Action / Smart Money Concepts): swing highs/lows, HH/HL/LH/LL,
BOS (Break of Structure) e CHOCH (Change of Character).
"""

from structure.bos import detect_bos
from structure.choch import detect_choch
from structure.market_structure import MarketStructureResult, analyze_market_structure
from structure.swings import find_swing_highs, find_swing_lows, get_swing_points

__all__ = [
    "detect_bos",
    "detect_choch",
    "MarketStructureResult",
    "analyze_market_structure",
    "find_swing_highs",
    "find_swing_lows",
    "get_swing_points",
]
