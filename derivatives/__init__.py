"""
derivatives
===========

Pacote responsável pelos dados de derivativos (Open Interest, Funding
Rate, Long/Short Ratio), obtidos via endpoints públicos da Binance
Futures — sem depender de provedores pagos como CoinGlass.
"""

from derivatives.binance_futures_client import BinanceFuturesClient
from derivatives.snapshot import DerivativesSnapshot, build_derivatives_snapshot

__all__ = ["BinanceFuturesClient", "DerivativesSnapshot", "build_derivatives_snapshot"]
