"""
strategy_dsl/portfolio.py
============================

Converte a lista de `Trade` (saída do `BacktestSimulator`, em termos
de preço/R) em position sizing real, trade log enriquecido e equity
curve (Documento 1, seções 8, 9, 11, 12).

Princípio (Documento 1, seção 8): "Nunca assumir capital inicial se
ele não foi informado" -- já garantido antes deste módulo, pelo
validador do schema (`GenericStrategySchema._starting_capital_required_for_risk_sizing`).

Limitação conhecida (documentada em `capabilities.py`): `CostModel`
aplica spread+slippage+comissão como um único bps combinado por perna
-- o custo total por trade é reportado (`costs_total`), mas ainda não
é decomposto em `commission` / `spread` / `slippage` separados.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtest.simulator import Trade
from strategy_dsl.schema import GenericStrategySchema


@dataclass(frozen=True, slots=True)
class TradeReportEntry:
    trade: Trade
    quantity: float
    notional: float
    gross_pnl: float
    costs_total: float
    net_pnl: float

    def to_dict(self) -> dict:
        d = self.trade.to_dict()
        d.update(
            {
                "quantity": round(self.quantity, 8),
                "notional": round(self.notional, 2),
                "gross_pnl": round(self.gross_pnl, 4),
                "costs_total": round(self.costs_total, 4),
                "net_pnl": round(self.net_pnl, 4),
            }
        )
        return d


def _quantity_for_trade(trade: Trade, schema: GenericStrategySchema) -> float:
    sizing = schema.position_sizing
    stop_distance = abs(trade.entry_price_effective - trade.stop_price)

    if sizing.type == "fixed_quantity":
        return sizing.value
    if sizing.type == "fixed_notional":
        return sizing.value / trade.entry_price_effective
    if sizing.type == "risk_percent":
        capital_at_risk = schema.starting_capital * (sizing.value / 100)
        return capital_at_risk / stop_distance if stop_distance > 0 else 0.0
    if sizing.type == "risk_amount":
        return sizing.value / stop_distance if stop_distance > 0 else 0.0
    raise ValueError(f"position_sizing.type '{sizing.type}' desconhecido.")  # inalcançável -- já validado pelo schema.


def build_trade_report(trades: list[Trade], schema: GenericStrategySchema) -> list[TradeReportEntry]:
    entries: list[TradeReportEntry] = []
    for trade in trades:
        quantity = _quantity_for_trade(trade, schema)
        sign = 1 if trade.direction == "long" else -1

        gross_pnl = quantity * sign * (trade.exit_price_raw - trade.entry_price_raw)
        net_pnl = quantity * sign * (trade.exit_price_effective - trade.entry_price_effective)
        notional = quantity * trade.entry_price_effective

        entries.append(
            TradeReportEntry(
                trade=trade,
                quantity=quantity,
                notional=notional,
                gross_pnl=gross_pnl,
                costs_total=gross_pnl - net_pnl,
                net_pnl=net_pnl,
            )
        )
    return entries


def build_equity_curve(entries: list[TradeReportEntry], starting_capital: float) -> dict:
    """
    Curva de capital acumulada (Documento 1, seção 11), em ordem
    cronológica de SAÍDA dos trades (é quando o PnL é realizado).
    """
    ordered = sorted(entries, key=lambda e: e.trade.exit_time)

    equity = starting_capital
    peak = starting_capital
    points: list[dict] = [{"timestamp": None, "equity": round(equity, 2), "drawdown": 0.0}]
    max_drawdown = 0.0
    max_drawdown_pct = 0.0

    for entry in ordered:
        equity += entry.net_pnl
        peak = max(peak, equity)
        drawdown = peak - equity
        drawdown_pct = (drawdown / peak) if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        points.append(
            {
                "timestamp": entry.trade.exit_time.isoformat(),
                "equity": round(equity, 2),
                "drawdown": round(drawdown, 2),
            }
        )

    return {
        "starting_capital": round(starting_capital, 2),
        "final_capital": round(equity, 2),
        "peak_equity": round(peak, 2),
        "max_drawdown": round(max_drawdown, 2),
        "max_drawdown_pct": round(max_drawdown_pct * 100, 2),
        "points": points,
    }
