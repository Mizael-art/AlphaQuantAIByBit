"""
tests/test_monitoring.py
===========================

Testes puros da Fase 7: `monitoring.setup_monitor.evaluate_setup_update`.
"""

from __future__ import annotations

from monitoring.setup_monitor import SetupSnapshot, evaluate_setup_update
from setups.lifecycle import COMPLETED, INVALIDATED, NEAR_ENTRY, TP1, TP2, TRIGGERED, WATCH


def _setup(**overrides) -> SetupSnapshot:
    base = dict(
        status=WATCH, direction="long", entry_zone_low=140.0, entry_zone_high=142.0,
        stop=138.0, tp1=146.0, tp2=150.0, tp3=155.0,
    )
    base.update(overrides)
    return SetupSnapshot(**base)


def test_terminal_status_never_updates() -> None:
    assert evaluate_setup_update(999.0, _setup(status=COMPLETED)) is None
    assert evaluate_setup_update(1.0, _setup(status=INVALIDATED)) is None


def test_price_outside_entry_zone_does_nothing() -> None:
    assert evaluate_setup_update(160.0, _setup(status=WATCH)) is None


def test_price_entering_zone_moves_to_near_entry() -> None:
    update = evaluate_setup_update(141.0, _setup(status=WATCH))
    assert update.new_status == NEAR_ENTRY


def test_armed_setup_without_entry_zone_fields_still_checks_stop_and_tp() -> None:
    """Depois de armado (TRIGGERED etc.) não depende mais de entry_zone -- só stop/TP."""
    update = evaluate_setup_update(137.0, _setup(status=TRIGGERED))
    assert update.new_status == INVALIDATED


def test_price_hitting_stop_invalidates_long() -> None:
    update = evaluate_setup_update(137.5, _setup(status=NEAR_ENTRY, direction="long", stop=138.0))
    assert update.new_status == INVALIDATED


def test_price_hitting_stop_invalidates_short() -> None:
    update = evaluate_setup_update(142.5, _setup(status=NEAR_ENTRY, direction="short", stop=142.0))
    assert update.new_status == INVALIDATED


def test_price_hitting_tp1_with_more_tps_ahead_moves_to_tp1() -> None:
    update = evaluate_setup_update(146.5, _setup(status=TRIGGERED, tp1=146.0, tp2=150.0, tp3=155.0))
    assert update.new_status == TP1


def test_price_hitting_final_tp_with_no_more_tps_completes() -> None:
    update = evaluate_setup_update(146.5, _setup(status=TRIGGERED, tp1=146.0, tp2=None, tp3=None))
    assert update.new_status == COMPLETED


def test_price_hitting_tp3_always_completes_even_from_tp1_status() -> None:
    update = evaluate_setup_update(156.0, _setup(status=TP1, tp1=146.0, tp2=150.0, tp3=155.0))
    assert update.new_status == COMPLETED


def test_price_hitting_tp2_moves_to_tp2_when_tp3_exists() -> None:
    update = evaluate_setup_update(151.0, _setup(status=TP1, tp1=146.0, tp2=150.0, tp3=155.0))
    assert update.new_status == TP2


def test_short_direction_favorable_price_completes() -> None:
    update = evaluate_setup_update(94.0, _setup(status=TRIGGERED, direction="short", stop=102.0, tp1=95.0, tp2=None, tp3=None))
    assert update.new_status == COMPLETED


def test_stop_takes_priority_when_both_reachable_same_price() -> None:
    """Mesma convenção conservadora do backtest/simulator.py: stop primeiro."""
    # Preço simultaneamente <= stop (long) não deveria também favorecer o TP nesse mesmo valor
    # em cenários reais, mas o teste garante que, se ambos fossem tecnicamente verdade, o código
    # checa o stop antes -- a ordem de checagem no código já garante isso; aqui validamos que
    # com stop no caminho, INVALIDATED é retornado mesmo que o preço também exceda um TP inválido
    # (ex.: dados inconsistentes onde tp1 < stop por engano de configuração).
    update = evaluate_setup_update(137.0, _setup(status=TRIGGERED, stop=138.0, tp1=130.0, tp2=None, tp3=None))
    assert update.new_status == INVALIDATED


def test_no_relevant_level_hit_returns_none() -> None:
    assert evaluate_setup_update(144.0, _setup(status=TRIGGERED, stop=138.0, tp1=146.0)) is None
