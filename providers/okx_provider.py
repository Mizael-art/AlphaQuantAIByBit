"""
providers/okx_provider.py
============================

Provider OKX, implementando `MarketDataProvider`. Cripto apenas
(spot/perp via instId, ex.: "BTC-USDT"). Usado hoje só pelo
`CrossExchangeReconciliationEngine` -- NÃO está no
`DEFAULT_PROVIDER_PRIORITY` do `ProviderRouter` (isso mudaria o
comportamento de fallback/execução existente sem necessidade; a OKX
entra como fonte adicional de CONSENSO, não de execução).
"""

from __future__ import annotations

from datetime import datetime, timezone

from models.candle import Candle
from providers.base import MarketDataError, MarketDataProvider, Quote
from providers.okx_client import OKX_BAR_MAP, OKXAPIError, OKXClient

_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1H": 3_600_000, "2H": 7_200_000, "4H": 14_400_000, "6H": 21_600_000, "12H": 43_200_000,
    "1D": 86_400_000, "1W": 604_800_000, "1M": 2_592_000_000,
}


def _to_okx_inst_id(canonical_symbol: str) -> str:
    """
    "BTCUSDT" -> "BTC-USDT". Assume canonical_symbol termina em USDT
    (o caso coberto hoje pelo SymbolMapper para cripto) -- se algum dia
    o mapper cobrir outros quotes (USDC, BTC), isso precisa de um
    Symbol Mapper de verdade por provider, não uma heurística de sufixo.
    """
    for quote in ("USDT", "USDC", "BTC", "ETH"):
        if canonical_symbol.endswith(quote) and len(canonical_symbol) > len(quote):
            base = canonical_symbol[: -len(quote)]
            return f"{base}-{quote}"
    raise ValueError(f"Não foi possível derivar instId da OKX a partir de '{canonical_symbol}'.")


class OKXProvider(MarketDataProvider):
    name = "okx"

    def __init__(self, client: OKXClient | None = None) -> None:
        self._client = client or OKXClient()

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class == "crypto"

    def get_candles(
        self, canonical_symbol: str, timeframe: str, limit: int, end_time: datetime | None = None
    ) -> list[Candle]:
        if timeframe not in OKX_BAR_MAP:
            raise ValueError(f"Timeframe '{timeframe}' não suportado pela OKX. Valores aceitos: {list(OKX_BAR_MAP.keys())}")

        inst_id = _to_okx_inst_id(canonical_symbol)
        after_ms = int(end_time.timestamp() * 1000) if end_time is not None else None

        try:
            raw = self._client.get_candles(inst_id=inst_id, bar=OKX_BAR_MAP[timeframe], limit=limit, after=after_ms)
        except OKXAPIError as exc:
            raise MarketDataError(f"[{self.name}] falha ao buscar candles de {inst_id} ({timeframe}): {exc}") from exc

        candles = [
            Candle(
                open_time=datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
                open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]),
                volume=float(row[5]),
                close_time=datetime.fromtimestamp(
                    (int(row[0]) + _INTERVAL_MS.get(timeframe, 0)) / 1000, tz=timezone.utc
                ),
                quote_volume=float(row[7]) if len(row) > 7 else None,
            )
            for row in raw
        ]
        # OKX retorna do mais recente pro mais antigo -- inverte para ordem cronológica.
        candles.reverse()
        return candles

    def get_quote(self, canonical_symbol: str) -> Quote:
        inst_id = _to_okx_inst_id(canonical_symbol)
        try:
            ticker = self._client.get_ticker(inst_id)
        except OKXAPIError as exc:
            raise MarketDataError(f"[{self.name}] falha ao buscar quote de {inst_id}: {exc}") from exc

        last_price = float(ticker["last"])
        bid = float(ticker["bidPx"]) if ticker.get("bidPx") not in (None, "") else None
        ask = float(ticker["askPx"]) if ticker.get("askPx") not in (None, "") else None
        spread = (ask - bid) if (bid is not None and ask is not None) else None

        return Quote(canonical_symbol=canonical_symbol, provider=self.name, last_price=last_price, bid=bid, ask=ask, spread=spread)

    def close(self) -> None:
        self._client.close()
