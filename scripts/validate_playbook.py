#!/usr/bin/env python3
"""
scripts/validate_playbook.py
===============================

Validação do Playbook (Documento 2, seção 11: BACKTEST -> OUT-OF-
SAMPLE -> FORWARD TEST -> LIVE ELIGIBILITY) -- este script cobre só a
primeira etapa (BACKTEST), rodando cada estratégia do Playbook que for
formalizável no `strategy_dsl` (Fase 1) contra histórico real via
`POST /backtest/generic` (chamado aqui diretamente, sem HTTP).

==========================================================================
AVALIAÇÃO DE COBERTURA DO PLAYBOOK (7 estratégias, playbook/library.py)
==========================================================================

EXPRESSÁVEIS no DSL atual (ver strategy_dsl/capabilities.py -- funções
disponíveis: cross_above/below, highest, lowest, sma, ema, comparadores,
aritmética):

  1. Trend Continuation   -- aproximação: alinhamento de EMAs (20>50>200)
                              + pullback cruzando de volta a favor.
                              APROXIMAÇÃO: "BOS na direção da tendência"
                              (definição original) não tem primitivo no
                              DSL -- usamos alinhamento de EMA como proxy.
  2. EMA Pullback          -- recuo até EMA50 + reação cruzando de volta.
  3. Compression Breakout  -- rompimento das Bollinger Bands.
                              APROXIMAÇÃO: a precondição de "squeeze"
                              (percentil de largura de banda) não é um
                              input do rule engine -- só existe no
                              regime detector (camada separada). Esta
                              versão captura só o rompimento, sem exigir
                              squeeze prévio.
  4. Range High Rejection  -- toque próximo da máxima do range + fecha
                              de volta abaixo dela (rejeição).
                              APROXIMAÇÃO: usa limiares percentuais de
                              proximidade, não a lógica de wick/liquidez
                              real de SMC.
  5. Range Low Rejection   -- espelho da anterior, para o piso do range.

PARCIALMENTE expressável:

  6. Breakout + Retest     -- só o "Breakout" é expressável como regra
                              de 1 candle (close cruza acima da máxima
                              recente). O "+ Retest" (aguardar o preço
                              voltar à zona rompida antes de confirmar)
                              exige estado entre candles que o rule
                              engine atual não expõe (não há primitivo
                              tipo "N candles atrás"). Esta validação
                              roda só a variante "Breakout" -- e isso é
                              reportado explicitamente no resultado, não
                              escondido.

NÃO expressável -- não roda, por decisão explícita (Documento 1, seção
24: "quando uma estratégia não puder ser representada, não inventar uma
aproximação"):

  7. Liquidity Sweep Reversal -- depende de detecção de varredura de
                                 liquidez (sweep) + Order Block / FVG,
                                 que não existem como primitivos no rule
                                 engine (`strategy_dsl/expression_engine.py`)
                                 nem na tabela de indicadores
                                 (`strategy_dsl/indicators_registry.py`).
                                 Formalizar isso exigiria estender o DSL
                                 com uma função de detecção de sweep --
                                 não feito nesta rodada.

==========================================================================

Uso:
    python scripts/validate_playbook.py --symbol BTCUSDT --days 180
    python scripts/validate_playbook.py --synthetic   # sem rede -- só valida a mecânica, não a performance

Precisa de rede real para exchanges (Bybit/Binance) para o modo padrão.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.history_fetcher import HistoryFetcher, HistoryFetchError
from providers import DataUnavailableError, build_default_router
from strategy_dsl.errors import StrategyDslError
from strategy_dsl.executor import run_generic_backtest

NOT_SUPPORTED = {
    "Liquidity Sweep Reversal": (
        "Depende de detecção de sweep de liquidez + Order Block/FVG -- sem primitivo "
        "correspondente no rule engine ou na tabela de indicadores do DSL atual."
    ),
}

PARTIAL_SUPPORT = {
    "Breakout + Retest": "Só a variante 'Breakout' roda (sem confirmação de retest -- não expressável como regra de 1 candle).",
}


def _base(name: str, direction: str) -> dict:
    return {
        "name": name,
        "market": {"symbols": ["__SYMBOL__"], "timeframe": "1H", "exchange": "BINANCE"},
        "direction": direction,
        "execution": {"intrabar_priority": "stop_first"},
        "position_sizing": {"type": "risk_percent", "value": 1.0},
        "costs": {"commission_bps": 5, "spread_bps": 1, "slippage_bps": 2},
        "starting_capital": 10_000.0,
        "filters": [],
    }


def build_schemas() -> dict[str, dict]:
    schemas: dict[str, dict] = {}

    # 1. Trend Continuation (aproximação via alinhamento de EMA)
    s = _base("Trend Continuation", "long_short")
    s["indicators"] = [
        {"id": "EMA20", "type": "EMA", "period": 20},
        {"id": "EMA50", "type": "EMA", "period": 50},
        {"id": "EMA200", "type": "EMA", "period": 200},
    ]
    s["entry"] = {
        "long": ["EMA20 > EMA50", "EMA50 > EMA200", "close crosses above EMA20"],
        "short": ["EMA20 < EMA50", "EMA50 < EMA200", "close crosses below EMA20"],
    }
    s["exit"] = {"stop_loss": {"type": "atr", "value": 2.0}, "take_profit": {"type": "rr", "value": 2.0}}
    schemas["Trend Continuation"] = s

    # 2. EMA Pullback
    s = _base("EMA Pullback", "long_short")
    s["indicators"] = [{"id": "EMA50", "type": "EMA", "period": 50}, {"id": "EMA200", "type": "EMA", "period": 200}]
    s["entry"] = {
        "long": ["close > EMA200", "low <= EMA50", "close crosses above EMA50"],
        "short": ["close < EMA200", "high >= EMA50", "close crosses below EMA50"],
    }
    s["exit"] = {"stop_loss": {"type": "atr", "value": 1.5}, "take_profit": {"type": "rr", "value": 1.8}}
    schemas["EMA Pullback"] = s

    # 3. Compression Breakout (via Bollinger)
    s = _base("Compression Breakout", "long_short")
    s["indicators"] = [{"id": "BB", "type": "BOLLINGER", "period": 20, "params": {"std_dev": 2.0}}]
    s["entry"] = {"long": ["close crosses above BB_UPPER"], "short": ["close crosses below BB_LOWER"]}
    s["exit"] = {"stop_loss": {"type": "atr", "value": 1.5}, "take_profit": {"type": "rr", "value": 2.2}}
    schemas["Compression Breakout"] = s

    # 4. Range High Rejection (short only)
    s = _base("Range High Rejection", "short")
    s["indicators"] = []
    s["entry"] = {"long": [], "short": ["high >= highest(high, 20) * 0.998", "close < highest(high, 20) * 0.99"]}
    s["exit"] = {"stop_loss": {"type": "percent", "value": 1.2}, "take_profit": {"type": "rr", "value": 1.8}}
    schemas["Range High Rejection"] = s

    # 5. Range Low Rejection (long only)
    s = _base("Range Low Rejection", "long")
    s["indicators"] = []
    s["entry"] = {"long": ["low <= lowest(low, 20) * 1.002", "close > lowest(low, 20) * 1.01"], "short": []}
    s["exit"] = {"stop_loss": {"type": "percent", "value": 1.2}, "take_profit": {"type": "rr", "value": 1.8}}
    schemas["Range Low Rejection"] = s

    # 6. Breakout (parcial -- sem retest)
    s = _base("Breakout + Retest (só Breakout)", "long_short")
    s["indicators"] = []
    s["entry"] = {
        "long": ["close crosses above highest(high, 20)"],
        "short": ["close crosses below lowest(low, 20)"],
    }
    s["exit"] = {"stop_loss": {"type": "atr", "value": 2.0}, "take_profit": {"type": "rr", "value": 2.0}}
    schemas["Breakout + Retest"] = s

    return schemas


def _synthetic_candles(n: int = 4500, end: datetime | None = None):
    """Sem rede -- só pra confirmar que o schema roda mecanicamente (não valida performance real)."""
    import random

    from models.candle import Candle

    random.seed(42)
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(hours=n)
    price = 100.0
    candles = []
    for i in range(n):
        drift = random.uniform(-1.2, 1.3)
        o = price
        c = max(1.0, price + drift)
        h = max(o, c) + abs(random.uniform(0, 0.8))
        l = max(0.5, min(o, c) - abs(random.uniform(0, 0.8)))
        candles.append(Candle(open_time=start + timedelta(hours=i), open=o, high=h, low=l, close=c, volume=1000.0, close_time=start + timedelta(hours=i + 1)))
        price = c
    return candles


class _SyntheticFetcher:
    def __init__(self, candles):
        self._candles = candles

    def fetch(self, symbol, timeframe, start, end, min_candles):
        from backtest.history_fetcher import HistoryResult

        filtered = [c for c in self._candles if start <= c.open_time <= end]
        actual_start = filtered[0].open_time if filtered else start
        actual_end = filtered[-1].open_time if filtered else end
        return HistoryResult(
            canonical_symbol=symbol, asset_class="crypto", provider="synthetic", timeframe=timeframe,
            candles=filtered, requested_start=start, requested_end=end, actual_start=actual_start, actual_end=actual_end,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida o Playbook rodando backtest real (ou sintético) por estratégia.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--synthetic", action="store_true", help="Roda sem rede, com candles sintéticos -- só valida a mecânica, não a performance real.")
    args = parser.parse_args()

    print("=" * 70)
    print("COBERTURA DO PLAYBOOK")
    print("=" * 70)
    for name, reason in NOT_SUPPORTED.items():
        print(f"  NÃO SUPORTADO -- {name}: {reason}")
    for name, reason in PARTIAL_SUPPORT.items():
        print(f"  PARCIAL       -- {name}: {reason}")
    print()

    schemas = build_schemas()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)

    if args.synthetic:
        fetcher = _SyntheticFetcher(_synthetic_candles(end=end))
        print(f"MODO SINTÉTICO (sem rede) -- resultados abaixo NÃO validam performance real, só a mecânica do schema.\n")
    else:
        fetcher = HistoryFetcher(router=build_default_router())

    results = {}
    for name, schema in schemas.items():
        schema = dict(schema)
        schema["market"] = dict(schema["market"], symbols=[args.symbol])
        print(f"--- {name} ---")
        try:
            report = run_generic_backtest(schema, fetcher, start, end, min_candles=30)
            perf = report.get("performance")
            print(f"  trades: {report['trades_count']}  sample_quality: {report['sample_quality']}")
            if perf:
                print(f"  win_rate: {perf['win_rate']*100:.1f}%  expectancy_r: {perf['expectancy_r']:.3f}  profit_factor: {perf.get('profit_factor')}")
            results[name] = report
        except StrategyDslError as exc:
            print(f"  ERRO (schema/regra): {exc.to_dict()}")
            results[name] = {"error": exc.to_dict()}
        except (HistoryFetchError, DataUnavailableError) as exc:
            print(f"  ERRO (dados de mercado -- provavelmente sem acesso de rede às exchanges): {exc}")
            results[name] = {"error": str(exc)}
        print()

    output_path = Path(__file__).resolve().parent / f"playbook_validation_{'synthetic' if args.synthetic else args.symbol}.json"
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"Resultado completo salvo em: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
