"""
app.py
======

Ponto de entrada do AlphaQuant Engine.

Orquestra o pipeline completo:

    Binance (api) -> Indicadores -> Estrutura -> Análise -> JSON

Uso via linha de comando:
    python app.py --symbol ETHUSDT --timeframe 4H

Uso programático:
    from app import run_analysis
    result = run_analysis("ETHUSDT", "4H")
    print(result.to_dict())
"""

from __future__ import annotations

import argparse
import json
import sys

from analysis.liquidity import find_liquidity_zones
from analysis.score import calculate_score
from analysis.support_resistance import find_support_resistance
from analysis.trend import determine_trend
from api.market_data import MarketData
from config import DEFAULT_KLINES_LIMIT, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME
from indicators.atr import calculate_atr
from indicators.ema import calculate_all_emas
from indicators.macd import calculate_macd
from indicators.rsi import calculate_rsi
from indicators.volume import calculate_volume_average, is_volume_above_average
from models.analysis_result import AnalysisResult, StructureResult
from output.json_formatter import to_json_string
from structure.market_structure import analyze_market_structure
from structure.swings import get_swing_points


class InsufficientDataError(Exception):
    """Levantada quando não há candles suficientes para uma análise confiável."""


def run_analysis(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    limit: int = DEFAULT_KLINES_LIMIT,
    market_data: MarketData | None = None,
    current_price: float | None = None,
) -> AnalysisResult:
    """
    Executa o pipeline completo de análise para um símbolo/timeframe.

    Args:
        symbol: par de negociação, ex. "ETHUSDT".
        timeframe: timeframe amigável, ex. "4H" (ver config.TIMEFRAME_MAP).
        limit: quantidade de candles buscados (máx. 1000).
        market_data: instância opcional de `MarketData` (injeção de
            dependência, útil em testes).
        current_price: se informado, pula a chamada de rede para buscar
            o preço atual (`md.get_current_price`) e usa este valor
            diretamente. Usado pelo scanner de universo completo
            (`scanner/screener.py`), que já tem o preço de um snapshot
            de tickers em lote buscado uma única vez para o mercado
            inteiro -- sem isso, cada chamada a `run_analysis` pagaria
            mais uma requisição HTTP só de ticker, por símbolo E por
            timeframe, à toa.

    Returns:
        `AnalysisResult` com todos os campos calculados.

    Raises:
        InsufficientDataError: se a Binance não retornar candles
            suficientes para calcular os indicadores com segurança
            (ex.: símbolo novo, pouco histórico disponível).
    """
    md = market_data or MarketData()

    df = md.get_ohlcv_dataframe(symbol=symbol, timeframe=timeframe, limit=limit)

    # EMA200 precisa de pelo menos 200 candles para um valor confiável;
    # usamos essa referência como piso mínimo de segurança.
    if len(df) < 200:
        raise InsufficientDataError(
            f"Candles insuficientes para {symbol} ({timeframe}): "
            f"{len(df)} recebidos, mínimo recomendado é 200."
        )

    current_price = current_price if current_price is not None else md.get_current_price(symbol)

    # ------------------------------------------------------------------
    # INDICADORES
    # ------------------------------------------------------------------
    emas = calculate_all_emas(df)
    rsi_series = calculate_rsi(df["close"])
    atr_series = calculate_atr(df)
    macd_result = calculate_macd(df["close"])
    volume_avg_series = calculate_volume_average(df)
    volume_above_avg_series = is_volume_above_average(df)

    ema20 = float(emas["ema20"].iloc[-1])
    ema50 = float(emas["ema50"].iloc[-1])
    ema100 = float(emas["ema100"].iloc[-1])
    ema200 = float(emas["ema200"].iloc[-1])

    rsi = float(rsi_series.iloc[-1])
    atr = float(atr_series.iloc[-1])

    macd_value = float(macd_result.macd_line.iloc[-1])
    macd_signal = float(macd_result.signal_line.iloc[-1])
    macd_histogram = float(macd_result.histogram.iloc[-1])

    volume_avg = float(volume_avg_series.iloc[-1])
    volume_above_average = bool(volume_above_avg_series.iloc[-1])

    # ------------------------------------------------------------------
    # ESTRUTURA DE MERCADO
    # ------------------------------------------------------------------
    structure_result = analyze_market_structure(df)
    swings = get_swing_points(df)

    # ------------------------------------------------------------------
    # ANÁLISE
    # ------------------------------------------------------------------
    trend = determine_trend(ema20, ema50, ema100, ema200, structure_result.trend)

    support, resistance = find_support_resistance(df, swings, current_price)
    liquidity = find_liquidity_zones(swings)

    score = calculate_score(
        trend=trend,
        rsi=rsi,
        macd_histogram=macd_histogram,
        bos=structure_result.bos,
        choch=structure_result.choch,
        volume_above_average=volume_above_average,
    )

    structure_payload = StructureResult(
        hh=structure_result.hh,
        hl=structure_result.hl,
        lh=structure_result.lh,
        ll=structure_result.ll,
        bos=structure_result.bos,
        choch=structure_result.choch,
        swing_high=structure_result.swing_high,
        swing_low=structure_result.swing_low,
    )

    return AnalysisResult(
        symbol=symbol.upper(),
        timeframe=timeframe,
        price=current_price,
        trend=trend,
        ema20=round(ema20, 6),
        ema50=round(ema50, 6),
        ema100=round(ema100, 6),
        ema200=round(ema200, 6),
        rsi=round(rsi, 2),
        atr=round(atr, 6),
        macd=round(macd_value, 6),
        macd_signal=round(macd_signal, 6),
        macd_histogram=round(macd_histogram, 6),
        volume_avg=round(volume_avg, 6),
        structure=structure_payload,
        support=support,
        resistance=resistance,
        liquidity_buy_side=liquidity.buy_side,
        liquidity_sell_side=liquidity.sell_side,
        score=score,
        data_source=md.last_result.provider if md.last_result else None,
        asset_class=md.last_result.asset_class if md.last_result else None,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Configura e interpreta os argumentos de linha de comando."""
    parser = argparse.ArgumentParser(
        description="AlphaQuant Engine — gera análise estruturada de mercado em JSON."
    )
    parser.add_argument(
        "--symbol", default=DEFAULT_SYMBOL, help=f"Par de negociação (padrão: {DEFAULT_SYMBOL})"
    )
    parser.add_argument(
        "--timeframe",
        default=DEFAULT_TIMEFRAME,
        help=f"Timeframe (padrão: {DEFAULT_TIMEFRAME}). Ex.: 15m, 1H, 4H, 1D.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_KLINES_LIMIT,
        help=f"Quantidade de candles buscados (padrão: {DEFAULT_KLINES_LIMIT}, máx. 1000).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada de linha de comando: executa a análise e imprime o JSON no stdout."""
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    try:
        result = run_analysis(symbol=args.symbol, timeframe=args.timeframe, limit=args.limit)
    except InsufficientDataError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - erro de topo, reportado como JSON.
        print(json.dumps({"error": f"Falha ao gerar análise: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(to_json_string(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
