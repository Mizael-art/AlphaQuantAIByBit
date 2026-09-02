"""
setups/lifecycle.py
======================

Máquina de estados do ciclo de vida de um setup (Documento 2, seção 13;
Documento Master, seção 13).

Estados terminais (`TERMINAL_STATUSES`) nunca transicionam de volta pra
um estado ativo -- se um setup terminou (completou, invalidou, expirou,
foi cancelado), um novo candidato pro mesmo ativo+direção+estratégia
vira um SETUP NOVO, não uma reabertura (isso é decidido em
`setups/memory.py`, não aqui).

A ordem de "maturidade" declarada em `_MATURITY_ORDER` é só um auxiliar
para `setups/memory.py` decidir se uma atualização é um avanço, um
recuo, ou uma mudança lateral -- não impõe transições proibidas: a
lista de estados é rica o suficiente (Documento Master usa
`ENTRY_READY` e `TRIGGERED` como conceitos próximos, por exemplo) que
travar transições demais criaria mais atrito do que valor nesta fase.
O que É travado (`validate_transition`) é só: nunca sair de um estado
terminal.
"""

from __future__ import annotations

from typing import Final

FORMATION: Final = "FORMATION"
WATCH: Final = "WATCH"
NEAR_ENTRY: Final = "NEAR_ENTRY"
READY: Final = "READY"
TRIGGERED: Final = "TRIGGERED"
ENTRY_READY: Final = "ENTRY_READY"
ACTIVE: Final = "ACTIVE"
TP1: Final = "TP1"
TP2: Final = "TP2"
TP3: Final = "TP3"
COMPLETED: Final = "COMPLETED"
INVALIDATED: Final = "INVALIDATED"
EXPIRED: Final = "EXPIRED"
CANCELLED: Final = "CANCELLED"

ALL_STATUSES: Final[frozenset[str]] = frozenset(
    {
        FORMATION, WATCH, NEAR_ENTRY, READY, TRIGGERED, ENTRY_READY,
        ACTIVE, TP1, TP2, TP3, COMPLETED, INVALIDATED, EXPIRED, CANCELLED,
    }
)

#: Documento 2, seção 13 -- uma vez aqui, o setup nunca volta a ser ativo
#: (um novo candidato pro mesmo ativo+direção+estratégia vira setup novo).
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({COMPLETED, INVALIDATED, EXPIRED, CANCELLED})

_MATURITY_ORDER: Final[dict[str, int]] = {
    FORMATION: 0, WATCH: 1, NEAR_ENTRY: 2, READY: 3, TRIGGERED: 4,
    ENTRY_READY: 4, ACTIVE: 5, TP1: 6, TP2: 7, TP3: 8, COMPLETED: 9,
}


class InvalidTransitionError(ValueError):
    def __init__(self, from_status: str, to_status: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Transição inválida: '{from_status}' é um estado terminal, não pode ir para '{to_status}'. "
            "Um novo candidato para o mesmo ativo/direção/estratégia deve virar um setup novo."
        )


class UnknownStatusError(ValueError):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"Status '{status}' não é um estado reconhecido do Setup Lifecycle.")


def validate_transition(from_status: str, to_status: str) -> None:
    """
    Raises:
        UnknownStatusError: status fora de `ALL_STATUSES`.
        InvalidTransitionError: `from_status` já é terminal.
    """
    if to_status not in ALL_STATUSES:
        raise UnknownStatusError(to_status)
    if from_status in TERMINAL_STATUSES and from_status != to_status:
        raise InvalidTransitionError(from_status, to_status)


def maturity_direction(from_status: str, to_status: str) -> str:
    """`"advanced" | "regressed" | "lateral"` -- usado só para o campo `reason_for_change`, informativo."""
    before, after = _MATURITY_ORDER.get(from_status), _MATURITY_ORDER.get(to_status)
    if before is None or after is None:
        return "lateral"
    if after > before:
        return "advanced"
    if after < before:
        return "regressed"
    return "lateral"
