"""
validation/data_quality.py
=============================

Camada de validação executada logo após um provider retornar candles,
ANTES de qualquer módulo de indicadores/estrutura/análise consumir os
dados.

Se a validação falhar, levanta `DataQualityError` — o
`ProviderRouter` trata isso exatamente como uma falha de provider
(tenta o próximo da lista / propaga `DataUnavailableError` se
esgotarem).

Este módulo NUNCA corrige dado ruim silenciosamente (ex.: não
preenche gap, não clampa OHLC inconsistente) — só detecta e rejeita.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from models.candle import Candle

# Timeframe -> duração esperada entre candles consecutivos.
_TIMEFRAME_DELTA: dict[str, timedelta] = {
    "1m": timedelta(minutes=1), "3m": timedelta(minutes=3), "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15), "30m": timedelta(minutes=30),
    "1H": timedelta(hours=1), "2H": timedelta(hours=2), "4H": timedelta(hours=4),
    "6H": timedelta(hours=6), "8H": timedelta(hours=8), "12H": timedelta(hours=12),
    "1D": timedelta(days=1), "3D": timedelta(days=3), "1W": timedelta(weeks=1),
    "1M": timedelta(days=30),
}

# Quantos períodos de timeframe um candle pode "atrasar" antes de ser
# considerado stale. Ativos TradFi fecham fora de sessão (fim de
# semana, feriado) — por isso a tolerância é generosa (mercado fechado
# não é "dado ruim").
_STALENESS_TOLERANCE_PERIODS = 6


class DataQualityError(Exception):
    """Levantada quando os dados retornados por um provider não passam na validação mínima."""


def validate_candles(
    candles: list[Candle],
    symbol: str,
    timeframe: str,
    min_candles: int = 200,
    check_freshness: bool = True,
) -> None:
    """
    Valida uma lista de candles. Levanta `DataQualityError` na primeira
    violação encontrada.

    Verifica:
        - quantidade mínima de candles
        - OHLC internamente consistente (high >= low, close/open dentro do range)
        - nenhum valor negativo ou zero onde não faz sentido (preço <= 0)
        - ordem cronológica estritamente crescente (sem duplicados/fora de ordem)
        - freshness do último candle (só se `check_freshness=True` — para
          histórico de backtest isso não se aplica: um candle de 6 meses
          atrás é esperado ser "velho", não é dado ruim. Ver
          `backtest.history_fetcher`, que usa `check_freshness=False`.)
    """
    if len(candles) < min_candles:
        raise DataQualityError(
            f"Candles insuficientes para {symbol} ({timeframe}): "
            f"{len(candles)} recebidos, mínimo {min_candles}."
        )

    previous_open_time: datetime | None = None
    for candle in candles:
        if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0:
            raise DataQualityError(
                f"Preço não positivo em {symbol} ({timeframe}) no candle {candle.open_time}."
            )
        if candle.high < candle.low:
            raise DataQualityError(
                f"OHLC inválido em {symbol} ({timeframe}): high < low no candle {candle.open_time}."
            )
        if not (candle.low <= candle.open <= candle.high):
            raise DataQualityError(
                f"OHLC inválido em {symbol} ({timeframe}): open fora do range [low, high] "
                f"no candle {candle.open_time}."
            )
        if not (candle.low <= candle.close <= candle.high):
            raise DataQualityError(
                f"OHLC inválido em {symbol} ({timeframe}): close fora do range [low, high] "
                f"no candle {candle.open_time}."
            )
        if candle.volume < 0:
            raise DataQualityError(
                f"Volume negativo em {symbol} ({timeframe}) no candle {candle.open_time}."
            )
        if previous_open_time is not None and candle.open_time <= previous_open_time:
            raise DataQualityError(
                f"Candles fora de ordem cronológica (ou duplicados) em {symbol} ({timeframe}) "
                f"perto de {candle.open_time}."
            )
        previous_open_time = candle.open_time

    if check_freshness:
        _validate_freshness(candles[-1], symbol, timeframe)


def _validate_freshness(last_candle: Candle, symbol: str, timeframe: str) -> None:
    """Rejeita dados stale — não sinaliza analisar mercado com preço desatualizado sem avisar."""
    expected_delta = _TIMEFRAME_DELTA.get(timeframe)
    if expected_delta is None:
        return  # timeframe fora do mapa conhecido: não bloqueia, mas não deveria ocorrer.

    now = datetime.now(timezone.utc)
    max_allowed_age = expected_delta * _STALENESS_TOLERANCE_PERIODS
    age = now - last_candle.close_time

    if age > max_allowed_age:
        raise DataQualityError(
            f"Dados stale para {symbol} ({timeframe}): último candle fechou em "
            f"{last_candle.close_time.isoformat()}, há {age}. "
            f"Tolerância máxima: {max_allowed_age} (pode ser mercado fechado — "
            f"forex/índices não operam 24/7 — mas o sistema não assume isso "
            f"silenciosamente; se for o caso, trate como DATA_UNAVAILABLE, não como sinal)."
        )
