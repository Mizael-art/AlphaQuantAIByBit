"""
strategy_dsl/capabilities.py
===============================

Fonte única da verdade para o que o motor de backtest genérico
suporta hoje -- consumida pelo endpoint `GET /schema_capabilities`
(Documento 1, seção 20). O usuário/GPT deve consultar isso ANTES de
interpretar um resultado, não depois.
"""

from __future__ import annotations

from strategy_dsl.indicators_registry import SUPPORTED_INDICATORS, UNSUPPORTED_INDICATORS


def get_schema_capabilities() -> dict:
    return {
        "supported": {
            "indicators": sorted(SUPPORTED_INDICATORS),
            "functions": [
                "cross_above / crossover", "cross_below / crossunder",
                "highest(series, n)", "lowest(series, n)",
                "sma(series, n)", "ema(series, n)",
                "abs(x)", "min(x, y)", "max(x, y)",
                "and", "or", "not", "comparadores (<, <=, >, >=, ==, !=)",
                "aritmética (+, -, *, /, %)",
            ],
            "order_types": ["market"],
            "entry_timing": ["next_bar_open (execução de sinal gerado no fechamento do candle anterior)"],
            "intrabar_priority": ["stop_first", "take_first"],
            "stop_loss_types": ["percent", "atr", "price"],
            "take_profit_types": ["percent", "rr", "atr", "price"],
            "trailing_stop_types": ["percent", "atr"],
            "break_even": True,
            "position_sizing": ["fixed_quantity", "fixed_notional", "risk_percent", "risk_amount"],
            "costs": ["commission_bps", "spread_bps", "slippage_bps (combinados num custo total por perna)"],
            "assets_per_backtest": 1,
            "timeframes_per_strategy": 1,
            "rule_combination": "todas as regras de entry.long / entry.short / filters são combinadas com AND",
        },
        "not_supported": {
            "indicators": sorted(UNSUPPORTED_INDICATORS),
            "multi_asset": "não suportado nesta versão -- 1 símbolo por backtest.",
            "multi_timeframe": "não suportado nesta versão -- estratégias com HTF/LTF combinados ficam para uma fase posterior.",
            "walk_forward": "não implementado nesta versão -- ver Plano de Evolução, Fase 8.",
            "parameter_sweep": "não implementado nesta versão -- ver Plano de Evolução, Fase 8.",
            "monte_carlo": "não implementado nesta versão -- ver Plano de Evolução, Fase 8.",
            "out_of_sample_split": "não implementado nesta versão -- ver Plano de Evolução, Fase 8.",
            "multiple_take_profits": "só 1 take_profit por trade nesta versão (sem TP1/TP2/TP3 com saída parcial).",
            "pyramiding_or_multiple_positions": "não suportado -- 1 posição por vez.",
            "funding_costs": "aceito no schema (funding_bps_per_day) mas ainda não aplicado na simulação.",
            "cost_breakdown_per_trade": "custo total por trade é reportado, mas ainda não decomposto em commission/spread/slippage separados.",
            "tick_data": "motor usa candles OHLC -- ver limitação de intrabar_priority.",
        },
        "sample_quality_thresholds": {
            "insufficient": "< 30 trades",
            "in_validation": "30-99 trades",
            "moderate_confidence": "100-299 trades",
            "high_confidence": "300+ trades",
        },
    }
