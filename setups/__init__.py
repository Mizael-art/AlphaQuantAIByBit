"""
setups
======

Setup Lifecycle + Setup Memory (Fase 2 do Plano de Evolução --
Documento 2, seções 13-15, 41; Documento Master, seções 13-15).

Fluxo: `schema.SetupCandidate` (validação de entrada) ->
`memory.upsert_setup` (decide criar vs. atualizar, classifica a
mudança) -> `repository` (CRUD sobre `persistence.models.SetupRecord`)
-> `lifecycle` (máquina de estados, nunca sai de um estado terminal).
`expiration.sweep_expired` fica pronto para o scheduler da Fase 7.
"""

from setups.lifecycle import ALL_STATUSES, TERMINAL_STATUSES, InvalidTransitionError, UnknownStatusError
from setups.memory import UpsertResult, upsert_setup
from setups.schema import EntryZone, SetupCandidate

__all__ = [
    "ALL_STATUSES",
    "TERMINAL_STATUSES",
    "InvalidTransitionError",
    "UnknownStatusError",
    "SetupCandidate",
    "EntryZone",
    "upsert_setup",
    "UpsertResult",
]
