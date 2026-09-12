"""
snapshot
========

Pacote orquestrador: consolida indicadores, estrutura, SMC, volume
profile, estatística e derivativos em um único Market Snapshot
multi-timeframe.
"""

from snapshot.confluence import ConfluenceResult, calculate_confluence
from snapshot.market_snapshot import DEFAULT_TIMEFRAMES, MarketSnapshot, build_market_snapshot
from snapshot.timeframe_snapshot import InsufficientDataError, TimeframeSnapshot, build_timeframe_snapshot

__all__ = [
    "ConfluenceResult",
    "calculate_confluence",
    "MarketSnapshot",
    "build_market_snapshot",
    "DEFAULT_TIMEFRAMES",
    "TimeframeSnapshot",
    "build_timeframe_snapshot",
    "InsufficientDataError",
]
