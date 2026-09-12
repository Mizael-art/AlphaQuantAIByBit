"""
fundamentals/base.py
=======================

Base comum dos 4 motores pedidos no Documento 4, seção 19:

    MacroDataProvider          -- fundamentals/macro.py
    EconomicEventsProvider     -- fundamentals/events.py
    TokenUnlockProvider        -- fundamentals/unlocks.py
    CryptoFundamentalsProvider -- fundamentals/crypto_fundamentals.py

Por que interfaces abstratas antes de qualquer vendor: o documento é
explícito (seção 19) -- "não comprar nenhum vendor pago sem antes
apresentar custo/cobertura/latência/histórico/Point-in-Time/limites/
qualidade/licença/benefícios". Definindo o contrato primeiro, os
motores superiores (Evidence & Scoring, Decision Intelligence) podem
ser desenvolvidos e testados contra QUALQUER implementação -- gratuita
hoje, paga amanhã -- sem re-trabalho.

Ponto-chave de TODOS os 4 (Documento 4, seção 18 -- anti-look-ahead):
cada registro carrega `observed_at`, o instante em que o dado ficou
PUBLICAMENTE conhecido -- que é diferente da data a que o dado se
refere (`period` / `scheduled_at` / `unlock_date`). Um backtest rodando
num timestamp T só pode enxergar registros com `observed_at <= T`.
Nenhum dos providers deste pacote busca dado de rede sem essa marcação.
"""

from __future__ import annotations

from abc import ABC


class FundamentalsUnavailableError(Exception):
    """
    Levantada por qualquer um dos 4 providers quando a fonte configurada
    não conseguiu responder (rede, vendor não configurado, símbolo/série
    não coberta, etc.).

    Segue a mesma filosofia do resto do projeto (`NoExchangeAvailableError`,
    `DataUnavailableError`): nunca inventar/estimar um valor para não
    quebrar o chamador -- propagar a ausência de evidência com um motivo
    claro, para a camada de decisão registrar "sem dado" em vez de um
    número fabricado.
    """


class FundamentalsDataProvider(ABC):
    """
    Raiz comum dos 4 motores -- só o nome do provider e o encerramento
    de recursos são realmente compartilhados; cada motor define seu
    próprio contrato de dados (séries são muito diferentes de eventos,
    que são muito diferentes de unlocks).
    """

    #: Nome curto e estável do provider (ex.: "fred", "defillama",
    #: "coingecko", "static_curated"). Usado em logs, testes e no
    #: campo `source` de cada registro retornado.
    name: str

    def close(self) -> None:  # pragma: no cover - default no-op
        """Encerra recursos de rede do provider (sessão HTTP etc.), quando houver."""
