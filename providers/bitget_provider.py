"""
providers/bitget_provider.py
===============================

Provider Bitget, implementando `MarketDataProvider`. Cripto Spot
apenas. Assim como a OKX, usado só pelo
`CrossExchangeReconciliationEngine` -- não entra no fallback de
execução do `ProviderRouter` por padrão.
"""

from __future__ import annotations

from datetime import datetime, timezone

from models.candle import Candle
from providers.base import MarketDataError, MarketDataProvider, Quote
from providers.bitget_client import BITGET_GRANULARITY_MAP, BitgetAPIError, BitgetClient

_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1H": 3_600_000, "4H": 14_400_000, "6H": 21_600_000, "12H": 43_200_000,
    "1D": 86_400_000, "1W": 604_800_000,
}


class BitgetProvider(MarketDataProvider):
    name = "bitget"

    def __init__(self, client: BitgetClient | None = None) -> None:
        self._client = client or BitgetClient()

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class == "crypto"

    def get_candles(
        self, canonical_symbol: str, timeframe: str, limit: int, end_time: datetime | None = None
    ) -> list[Candle]:
        if timeframe not in BITGET_GRANULARITY_MAP:
            raise ValueError(f"Timeframe '{timeframe}' não suportado pela Bitget. Valores aceitos: {list(BITGET_GRANULARITY_MAP.keys())}")

        end_ms = int(end_time.timestamp() * 1000) if end_time is not None else None
        try:
            raw = self._client.get_candles(
                symbol=canonical_symbol, granularity=BITGET_GRANULARITY_MAP[timeframe],
                limit=limit, end_time=end_ms,
            )
        except BitgetAPIError as exc:
            raise MarketDataError(f"[{self.name}] falha ao buscar candles de {canonical_symbol} ({timeframe}): {exc}") from exc

        candles = [
            Candle(
                open_time=datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
                open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]),
                volume=float(row[5]),
                close_time=datetime.fromtimestamp(
                    (int(row[0]) + _INTERVAL_MS.get(timeframe, 0)) / 1000, tz=timezone.utc
                ),
                quote_volume=float(row[6]) if len(row) > 6 else None,
            )
            for row in raw
        ]
        # Ordena defensivamente -- a doc pública não garante ordem cronológica explícita.
        candles.sort(key=lambda c: c.open_time)
        return candles

    def get_quote(self, canonical_symbol: str) -> Quote:
        try:
            ticker = self._client.get_ticker(canonical_symbol)
        except BitgetAPIError as exc:
            raise MarketDataError(f"[{self.name}] falha ao buscar quote de {canonical_symbol}: {exc}") from exc

        last_price = float(ticker["lastPr"])
        bid = float(ticker["bidPr"]) if ticker.get("bidPr") not in (None, "") else None
        ask = float(ticker["askPr"]) if ticker.get("askPr") not in (None, "") else None
        spread = (ask - bid) if (bid is not None and ask is not None) else None

        return Quote(canonical_symbol=canonical_symbol, provider=self.name, last_price=last_price, bid=bid, ask=ask, spread=spread)

    def close(self) -> None:
        self._client.close()
