"""
scoring/engine.py
====================

Multi-Score Engine (Documento 2, seção 12; Documento Master, seção 25).

Nota de honestidade metodológica: o Documento Master (seção 25) propõe
pesos para um OVERALL SCORE a partir de 10 fatores (Contexto, Regime,
Estrutura, Liquidez, Volume/Order Flow, SMC/Wyckoff, Playbook,
Timing/Entry, RR/Risk, Statistical Edge) que não mapeiam 1:1 com os 9
scores nomeados do Documento 2 seção 12 (Quality/Tradeability/Timing/
Risk/Asymmetry/Confirmation/Setup Maturity/Statistical Edge/Overall).
Este módulo adapta os dois: calcula os 9 scores nomeados a partir dos
inputs disponíveis hoje (technical score já existente, estrutura,
distância até a zona, RR, contexto BTC, volatilidade, correlação,
estatística do Playbook quando existir) e deriva o OVERALL como uma
média ponderada EXPLÍCITA dos 8 (pesos declarados abaixo, ajustáveis --
Documento Master seção 25 já autoriza isso: "você pode modificar os
pesos se os dados/backtests demonstrarem que outra distribuição é
superior"). Nenhum score aqui é probabilidade de lucro (Documento
Master, seção 75) -- é só a pontuação dos critérios atuais.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Pesos do OVERALL_SCORE -- somam 1.0. Ver nota de honestidade acima:
# esta é uma adaptação explícita da tabela do Documento Master seção 25,
# não uma cópia literal (os 9 scores nomeados do Documento 2 seção 12
# não são os mesmos 10 fatores da seção 25 do Documento Master).
_OVERALL_WEIGHTS: dict[str, float] = {
    "quality": 0.20,
    "confirmation": 0.15,
    "tradeability": 0.10,
    "timing": 0.10,
    "risk": 0.15,
    "asymmetry": 0.15,
    "setup_maturity": 0.10,
    "statistical_edge": 0.05,
}


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


@dataclass(frozen=True, slots=True)
class OpportunityScore:
    quality: float
    tradeability: float
    timing: float
    risk: float
    asymmetry: float
    confirmation: float
    setup_maturity: float
    statistical_edge: float
    overall: float
    statistical_edge_available: bool
    factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "quality_score": round(self.quality, 1),
            "tradeability_score": round(self.tradeability, 1),
            "timing_score": round(self.timing, 1),
            "risk_score": round(self.risk, 1),
            "asymmetry_score": round(self.asymmetry, 1),
            "confirmation_score": round(self.confirmation, 1),
            "setup_maturity_score": round(self.setup_maturity, 1),
            "statistical_edge_score": round(self.statistical_edge, 1),
            "statistical_edge_available": self.statistical_edge_available,
            "overall_opportunity_score": round(self.overall, 1),
            "factors": self.factors,
        }


def _asymmetry_from_rr(rr: float | None) -> float:
    if rr is None:
        return 0.0
    if rr < 1:
        return 10.0
    if rr < 2:
        return 35.0
    if rr < 3:
        return 60.0
    if rr < 4:
        return 80.0
    return 95.0


def _distance_curve(distance_to_zone_pct: float | None, near_value: float, far_value: float) -> float:
    """Curva genérica usada por TIMING e SETUP_MATURITY -- quanto mais perto da zona, maior o score; distância desconhecida = valor neutro baixo (nunca inventa proximidade)."""
    if distance_to_zone_pct is None:
        return (near_value + far_value) / 4  # neutro-baixo, explicitamente conservador
    if distance_to_zone_pct <= 0.5:
        return near_value
    if distance_to_zone_pct <= 1.5:
        return near_value * 0.75
    if distance_to_zone_pct <= 3.0:
        return near_value * 0.5
    return far_value


def compute_opportunity_score(
    *,
    trend: str,
    bos: bool,
    choch: bool,
    regime_compatible: bool,
    rr: float | None,
    distance_to_zone_pct: float | None,
    volatility_bucket: str,
    btc_context: str | None,
    correlation_penalty: bool,
    playbook_stats: dict | None = None,
) -> OpportunityScore:
    """
    Args:
        trend: "Bullish" | "Bearish" | "Ranging".
        bos, choch: confirmação/alerta estrutural (`structure.market_structure`).
        regime_compatible: se a estratégia do Playbook escolhida é
            compatível com o regime atual (`playbook.compatible_playbooks`).
        rr: risco:retorno estimado do trade (None se não estimável).
        distance_to_zone_pct: distância % até a zona de entrada (None
            se não há zona identificada).
        volatility_bucket: "LOW" | "NORMAL" | "HIGH" | "EXTREME" (`regime.detector`).
        btc_context: "BTC_SUPPORTIVE" | "BTC_NEUTRAL" | "BTC_HOSTILE" |
            None (None para o próprio BTC, que não tem contexto de si mesmo).
        correlation_penalty: True se o Correlated Exposure Engine já
            identificou este ativo como redundante com outro de score maior.
        playbook_stats: {"win_rate": float, "sample_size": int,
            "expectancy_r": float} vindo de backtests reais já rodados
            (Fase 5/6) -- None ou sample_size < 30 => estatística
            insuficiente, `statistical_edge` fica neutro e
            `statistical_edge_available=False`.
    """
    factors: list[str] = []

    # --- QUALITY ---
    quality = 50.0
    if trend in ("Bullish", "Bearish"):
        quality += 20
        factors.append(f"Tendência definida ({trend}).")
    if bos:
        quality += 15
        factors.append("BOS confirmado.")
    if choch:
        quality -= 15
        factors.append("CHOCH ativo -- estrutura em possível reversão.")
    if btc_context == "BTC_SUPPORTIVE":
        quality += 15
        factors.append("Contexto BTC suportivo.")
    elif btc_context == "BTC_HOSTILE":
        quality -= 15
        factors.append("Contexto BTC hostil.")
    quality = _clamp(quality)

    # --- CONFIRMATION ---
    confirmation = 50.0
    if bos:
        confirmation += 30
    if choch:
        confirmation -= 30
    if regime_compatible:
        confirmation += 20
    else:
        factors.append("Estratégia escolhida não é compatível com o regime atual.")
    confirmation = _clamp(confirmation)

    # --- TRADEABILITY / TIMING / SETUP_MATURITY (curvas de distância) ---
    tradeability = _clamp(_distance_curve(distance_to_zone_pct, near_value=90.0, far_value=30.0) + (10 if regime_compatible else 0))
    timing = _clamp(_distance_curve(distance_to_zone_pct, near_value=90.0, far_value=25.0))
    setup_maturity = _clamp(_distance_curve(distance_to_zone_pct, near_value=95.0, far_value=20.0))

    # --- RISK (mais alto = mais seguro) ---
    risk = 100.0
    if volatility_bucket == "EXTREME":
        risk -= 25
        factors.append("Volatilidade extrema.")
    elif volatility_bucket == "HIGH":
        risk -= 10
    if correlation_penalty:
        risk -= 20
        factors.append("Exposição correlacionada com outra oportunidade já rankeada.")
    if choch:
        risk -= 15
    risk = _clamp(risk)

    # --- ASYMMETRY ---
    asymmetry = _clamp(_asymmetry_from_rr(rr))
    if rr is None:
        factors.append("RR não estimável -- asymmetry_score conservador.")

    # --- STATISTICAL EDGE ---
    stats_available = bool(playbook_stats and playbook_stats.get("sample_size", 0) >= 30)
    if stats_available:
        win_rate = playbook_stats.get("win_rate", 50.0)
        expectancy_r = playbook_stats.get("expectancy_r", 0.0)
        statistical_edge = _clamp(50.0 + (win_rate - 50.0) * 0.6 + expectancy_r * 10)
    else:
        statistical_edge = 50.0
        factors.append("Sem histórico de backtest suficiente para este Playbook (amostra < 30) -- statistical_edge neutro.")

    overall = _clamp(
        quality * _OVERALL_WEIGHTS["quality"]
        + confirmation * _OVERALL_WEIGHTS["confirmation"]
        + tradeability * _OVERALL_WEIGHTS["tradeability"]
        + timing * _OVERALL_WEIGHTS["timing"]
        + risk * _OVERALL_WEIGHTS["risk"]
        + asymmetry * _OVERALL_WEIGHTS["asymmetry"]
        + setup_maturity * _OVERALL_WEIGHTS["setup_maturity"]
        + statistical_edge * _OVERALL_WEIGHTS["statistical_edge"]
    )

    return OpportunityScore(
        quality=quality,
        tradeability=tradeability,
        timing=timing,
        risk=risk,
        asymmetry=asymmetry,
        confirmation=confirmation,
        setup_maturity=setup_maturity,
        statistical_edge=statistical_edge,
        overall=overall,
        statistical_edge_available=stats_available,
        factors=factors,
    )
