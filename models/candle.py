"""
models/candle.py
=================

Modelo de dados NORMALIZADO que representa um candle OHLCV.

Este modelo é agnóstico de provider: `indicators/`, `structure/`,
`smc/`, `volume_profile/`, `analysis/` etc. só conhecem `Candle` — não
sabem (nem devem saber) se o dado veio da Binance, da Bybit ou de
qualquer outro provider.

Alguns campos (`trades`, `taker_buy_volume`) só existem em provedores
de cripto que expõem klines "enriquecidos" (ex.: Binance). Quando o
provider não fornece esse dado (ex.: Bybit, qualquer provider TradFi),
o campo fica `None` — NUNCA é preenchido com um valor estimado ou
zero disfarçado de dado real. Módulos que dependem desses campos
(ex.: `order_flow.delta`, aproximação de Delta/CVD) devem checar a
disponibilidade antes de calcular (ver `Candle.has_order_flow_data`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class Candle:
    """
    Representa um único candle OHLCV normalizado.

    Attributes:
        open_time: timestamp de abertura do candle (UTC).
        open: preço de abertura.
        high: preço máximo.
        low: preço mínimo.
        close: preço de fechamento.
        volume: volume negociado no ativo base.
        close_time: timestamp de fechamento do candle (UTC).
        quote_volume: volume negociado no ativo de cotação (ex.: USDT).
            `None` quando o provider não expõe esse dado.
        trades: número de trades executados no período. `None` quando
            o provider não expõe esse dado (ex.: Bybit kline público).
        taker_buy_volume: volume (ativo base) originado por ordens de
            mercado do lado comprador (taker buy). Disponível na
            Binance via /api/v3/klines; `None` em providers que não
            expõem esse dado (ex.: Bybit, TradFi) — módulos consumidores
            devem tratar `None` como "order flow indisponível", nunca
            assumir 0 ou metade do volume.
    """

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: datetime
    quote_volume: float | None = None
    trades: int | None = None
    taker_buy_volume: float | None = None

    @property
    def has_order_flow_data(self) -> bool:
        """True se este candle tem dado real de taker_buy_volume (não estimado)."""
        return self.taker_buy_volume is not None

    @classmethod
    def from_binance_raw(cls, raw: list[Any]) -> "Candle":
        """
        Constrói um `Candle` a partir de uma linha bruta retornada pelo
        endpoint /api/v3/klines da Binance.

        Formato bruto esperado (índices):
            0: open_time (ms)
            1: open
            2: high
            3: low
            4: close
            5: volume
            6: close_time (ms)
            7: quote_asset_volume
            8: number_of_trades
            9: taker_buy_base_volume
            10: taker_buy_quote_volume
            11: ignore
        """
        return cls(
            open_time=datetime.fromtimestamp(raw[0] / 1000, tz=timezone.utc),
            open=float(raw[1]),
            high=float(raw[2]),
            low=float(raw[3]),
            close=float(raw[4]),
            volume=float(raw[5]),
            close_time=datetime.fromtimestamp(raw[6] / 1000, tz=timezone.utc),
            quote_volume=float(raw[7]),
            trades=int(raw[8]),
            taker_buy_volume=float(raw[9]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa o candle para um dicionário simples (útil em JSON/debug)."""
        return {
            "open_time": self.open_time.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "close_time": self.close_time.isoformat(),
            "quote_volume": self.quote_volume,
            "trades": self.trades,
            "taker_buy_volume": self.taker_buy_volume,
        }

    @classmethod
    def from_bybit_raw(cls, raw: list[str], interval_timedelta_ms: int) -> "Candle":
        """
        Constrói um `Candle` a partir de uma linha bruta retornada pelo
        endpoint /v5/market/kline da Bybit.

        Formato bruto esperado (lista de strings):
            [start_ms, open, high, low, close, volume, turnover]

        A Bybit não retorna `close_time` explícito nem `trades`/
        `taker_buy_volume` — `close_time` é derivado a partir do
        intervalo do timeframe; os demais ficam `None` (ver docstring
        da classe — nunca estimados).
        """
        open_time_ms = int(raw[0])
        return cls(
            open_time=datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc),
            open=float(raw[1]),
            high=float(raw[2]),
            low=float(raw[3]),
            close=float(raw[4]),
            volume=float(raw[5]),
            close_time=datetime.fromtimestamp(
                (open_time_ms + interval_timedelta_ms) / 1000, tz=timezone.utc
            ),
            quote_volume=float(raw[6]) if len(raw) > 6 and raw[6] not in (None, "") else None,
            trades=None,
            taker_buy_volume=None,
        )
