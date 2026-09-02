"""
models/analysis_result.py
==========================

Modelo de dados que representa o resultado final da análise de um
símbolo/timeframe — a estrutura que será serializada para o JSON
padronizado consumido pelo AlphaQuant X.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class StructureResult:
    """Resultado da detecção de estrutura de mercado."""

    hh: bool
    hl: bool
    lh: bool
    ll: bool
    bos: bool
    choch: bool
    swing_high: float | None
    swing_low: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "HH": self.hh,
            "HL": self.hl,
            "LH": self.lh,
            "LL": self.ll,
            "BOS": self.bos,
            "CHOCH": self.choch,
            "swing_high": self.swing_high,
            "swing_low": self.swing_low,
        }


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """
    Resultado completo e padronizado de uma análise de mercado.

    Esta é a estrutura de mais alto nível do projeto: reúne preço,
    indicadores, estrutura de mercado e o score final, pronta para ser
    convertida em JSON por `output.json_formatter`.
    """

    symbol: str
    timeframe: str
    price: float

    trend: str

    ema20: float
    ema50: float
    ema100: float
    ema200: float

    rsi: float
    atr: float
    macd: float
    macd_signal: float
    macd_histogram: float
    volume_avg: float

    structure: StructureResult

    support: list[float] = field(default_factory=list)
    resistance: list[float] = field(default_factory=list)

    liquidity_buy_side: list[float] = field(default_factory=list)
    liquidity_sell_side: list[float] = field(default_factory=list)

    score: int = 0

    # Proveniência do dado — de qual provider veio esta análise
    # (ex.: "bybit_crypto", "binance", "bybit_tradfi"). `None` mantido
    # como default para não quebrar quem já instancia `AnalysisResult`
    # sem esse campo (ex.: testes existentes).
    data_source: str | None = None
    asset_class: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Converte o resultado para um dicionário pronto para `json.dumps`."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "price": self.price,
            "trend": self.trend,
            "ema20": self.ema20,
            "ema50": self.ema50,
            "ema100": self.ema100,
            "ema200": self.ema200,
            "rsi": self.rsi,
            "atr": self.atr,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
            "volume_avg": self.volume_avg,
            "structure": self.structure.to_dict(),
            "support": self.support,
            "resistance": self.resistance,
            "liquidity": {
                "buy_side": self.liquidity_buy_side,
                "sell_side": self.liquidity_sell_side,
            },
            "score": self.score,
            "data_source": self.data_source,
            "asset_class": self.asset_class,
        }
