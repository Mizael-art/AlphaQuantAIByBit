"""
scanner/background_loop.py
=============================

Loop de fundo: roda `scanner.screener.scan_universe` continuamente
dentro do próprio processo -- assim que um ciclo termina, o próximo já
começa (`config.SCAN_BACKGROUND_MIN_INTERVAL_SECONDS` só existe como
rede de segurança, não como "intervalo de atualização" no sentido de
esperar de propósito). O resultado de cada ciclo é gravado em
`persistence.ScanSnapshot` via `persistence.scan_snapshot`.

Por que isso existe: uma GPT Action tem timeout curto (tipicamente
~45s); escanear 700+ ativos ao vivo dentro desse timeout é frágil.
Rodando em background, o GPT só lê o último resultado pronto
(`GET /scan/latest`, resposta em milissegundos) em vez de esperar um
scan novo ser calculado na hora.

Este módulo NÃO decide quando o processo acorda/dorme -- isso é
responsabilidade de infraestrutura (Render + serviço de keep-alive tipo
UptimeRobot pingando `/health`). Enquanto o processo estiver vivo, este
loop roda sozinho; se o processo hibernar e for acordado de novo, o
`start_background_loop` chamado no startup do servidor recomeça o loop
do zero.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from datetime import datetime, timezone

from config import SCAN_BACKGROUND_KEY, SCAN_BACKGROUND_MIN_INTERVAL_SECONDS
from persistence.scan_snapshot import save_scan_snapshot
from scanner.screener import scan_universe

logger = logging.getLogger("alphaquant.scanner.background_loop")

# Guarda contra iniciar o loop duas vezes no mesmo processo (ex.: se o
# startup event do FastAPI disparar mais de uma vez sob certos
# servidores/reloaders). Um único loop por processo é a premissa de
# design -- ver aviso sobre múltiplos workers na docstring de
# `start_background_loop`.
_loop_started = threading.Event()


def _run_one_cycle(htf: str, ltf: str, scan_key: str) -> float:
    """Roda um ciclo completo de `scan_universe` e persiste o resultado. Retorna a duração em segundos (para log/backoff)."""
    started_at = datetime.now(timezone.utc)
    result_json = None
    error = None
    try:
        result = scan_universe(htf=htf, ltf=ltf)
        result_json = result.to_dict()
    except Exception as exc:  # noqa: BLE001 - o loop não pode morrer por causa de um ciclo ruim.
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("Ciclo de scan de fundo falhou: %s\n%s", error, traceback.format_exc())
    finished_at = datetime.now(timezone.utc)

    try:
        save_scan_snapshot(scan_key, result_json, started_at, finished_at, error=error)
    except Exception:
        # Se nem gravar no banco der certo, loga mas não derruba o loop --
        # o próximo ciclo tenta de novo. Perder 1 ciclo de histórico é
        # muito menos grave do que o loop de fundo inteiro morrer.
        logger.exception("Falha ao gravar ScanSnapshot no banco (ciclo continua).")

    return (finished_at - started_at).total_seconds()


def _loop_forever(htf: str, ltf: str, scan_key: str) -> None:
    while True:
        duration = _run_one_cycle(htf, ltf, scan_key)
        # Rede de segurança: nunca menos que SCAN_BACKGROUND_MIN_INTERVAL_SECONDS
        # entre o fim de um ciclo e o início do próximo, mesmo se o ciclo
        # falhar instantaneamente (ex.: erro de configuração) -- sem isso,
        # um erro logo no início criaria um loop apertado martelando a
        # Bybit sem parar.
        remaining = SCAN_BACKGROUND_MIN_INTERVAL_SECONDS - duration
        if remaining > 0:
            time.sleep(remaining)


def start_background_loop(
    htf: str = "4H", ltf: str = "1H", scan_key: str = SCAN_BACKGROUND_KEY
) -> None:
    """
    Inicia o loop de fundo em uma thread daemon. Idempotente -- chamar
    mais de uma vez no mesmo processo é seguro (só a primeira chamada
    efetivamente inicia a thread).

    AVISO IMPORTANTE SOBRE MÚLTIPLOS WORKERS: se o servidor for rodado
    com mais de um worker (`uvicorn server:app --workers N` com N > 1,
    ou um `Procfile`/config do Render pedindo múltiplas instâncias),
    CADA worker é um processo separado e vai iniciar seu PRÓPRIO loop
    de fundo -- ou seja, N scans do mercado inteiro rodando em
    paralelo, martelando a Bybit N vezes mais que o necessário, todos
    escrevendo na mesma linha de `ScanSnapshot` (last-write-wins, sem
    corrupção de dado, mas com trabalho duplicado). Rodar este loop
    pressupõe explicitamente 1 único worker. Se precisar escalar para
    múltiplos workers no futuro por causa de tráfego HTTP, mover este
    loop para um processo/worker dedicado (ex.: um Background Worker
    separado no Render, não o mesmo processo que serve HTTP).
    """
    if _loop_started.is_set():
        return
    _loop_started.set()

    thread = threading.Thread(
        target=_loop_forever, args=(htf, ltf, scan_key), name="scan-background-loop", daemon=True
    )
    thread.start()
    logger.info("Loop de scan de fundo iniciado (scan_key=%s, htf=%s, ltf=%s).", scan_key, htf, ltf)
