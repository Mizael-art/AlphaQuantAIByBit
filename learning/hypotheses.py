"""
learning/hypotheses.py
=========================

Agregação estatística de padrões a partir dos sinais registrados
(Documento 2, seção 29; Documento Master, seção 26, 29).

Função pura: recebe uma lista de dicts já extraídos do banco (não
importa SQLAlchemy aqui -- mesma separação decisão/I/O de
`risk/engine.py` e `scoring/engine.py`).

Classificação (mesmos limiares de amostra já usados no resto do
projeto -- Documento 1, seção 14: <30 insuficiente, 30-99 em teste,
100-299 confiança moderada, 300+ alta confiança -- aqui simplificado
para 2 limiares porque hipóteses de Playbook tendem a ter amostras
menores que backtests quantitativos):

    sample_size < 10                       -> OBSERVATION
    10 <= sample_size < 30                 -> IN_TEST
    sample_size >= 30 e win_rate > 50
        e avg_r_multiple > 0               -> VALIDATED
    sample_size >= 30 e (win_rate <= 40
        ou avg_r_multiple <= 0)            -> REJECTED
    sample_size >= 30 caso contrário       -> IN_TEST (misto -- nem validável nem claramente ruim)

Nunca declara VALIDATED com amostra pequena (Documento Master, seção
29: "Esse trader acertou 8 calls, então sua estratégia funciona" é
exatamente o erro que este limiar evita).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

OBSERVATION: Final = "OBSERVATION"
IN_TEST: Final = "IN_TEST"
VALIDATED: Final = "VALIDATED"
REJECTED: Final = "REJECTED"


@dataclass(frozen=True, slots=True)
class Hypothesis:
    group_key: str
    sample_size: int
    win_rate_pct: float
    avg_r_multiple: float
    status: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "group": self.group_key,
            "sample_size": self.sample_size,
            "win_rate_pct": round(self.win_rate_pct, 1),
            "avg_r_multiple": round(self.avg_r_multiple, 2),
            "status": self.status,
            "notes": self.notes,
        }


def _classify_status(sample_size: int, win_rate_pct: float, avg_r_multiple: float) -> str:
    if sample_size < 10:
        return OBSERVATION
    if sample_size < 30:
        return IN_TEST
    if win_rate_pct > 50 and avg_r_multiple > 0:
        return VALIDATED
    if win_rate_pct <= 40 or avg_r_multiple <= 0:
        return REJECTED
    return IN_TEST


def build_hypotheses(signals: list[dict], group_by: str = "strategy_guess") -> list[Hypothesis]:
    """
    Args:
        signals: cada dict precisa ter `group_by`, `result`
            ("win"/"loss"/"breakeven"/None) e `r_multiple` (float|None).
            Sinais com `result is None` (Documento Master, seção 76 --
            nunca inventa resultado) são ignorados na agregação, mas
            não travam o cálculo dos demais.
        group_by: chave de agrupamento -- "strategy_guess" (default),
            mas pode ser "asset" para agregar por ativo em vez de estratégia.

    Returns:
        Uma `Hypothesis` por valor distinto de `group_by`, ordenadas
        por `sample_size` decrescente (grupos com mais evidência primeiro).
    """
    groups: dict[str, list[dict]] = {}
    for signal in signals:
        key = signal.get(group_by)
        if key is None or signal.get("result") is None:
            continue
        groups.setdefault(key, []).append(signal)

    hypotheses: list[Hypothesis] = []
    for key, group_signals in groups.items():
        sample_size = len(group_signals)
        wins = sum(1 for s in group_signals if s["result"] == "win")
        win_rate_pct = (wins / sample_size) * 100

        r_multiples = [s["r_multiple"] for s in group_signals if s.get("r_multiple") is not None]
        avg_r_multiple = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0

        status = _classify_status(sample_size, win_rate_pct, avg_r_multiple)
        notes = []
        if not r_multiples:
            notes.append("Nenhum r_multiple registrado -- avg_r_multiple é 0.0 por ausência de dado, não por resultado neutro real.")
        if sample_size < 30:
            notes.append(f"Amostra ({sample_size}) abaixo do limiar de validação (30) -- ver Documento 1, seção 14.")

        hypotheses.append(Hypothesis(key, sample_size, win_rate_pct, avg_r_multiple, status, notes))

    hypotheses.sort(key=lambda h: h.sample_size, reverse=True)
    return hypotheses
