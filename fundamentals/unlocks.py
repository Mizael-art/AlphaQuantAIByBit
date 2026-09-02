"""
fundamentals/unlocks.py
==========================

MOTOR 3/4 -- TokenUnlockProvider (Documento 4, seção 19)

Cronograma de liberação de tokens travados (vesting de time/investidores,
recompensas de ecossistema, etc.) -- um unlock grande é pressão de
venda conhecida ANTECIPADAMENTE, ao contrário da maior parte do resto
deste projeto.

Vendor evaluation (pesquisa feita antes de implementar):

    vendor      | cobertura        | custo              | API              | observação
    DefiLlama   | ~300+ projetos   | gratuito           | api.llama.fi,    | dados vêm de
                |                  |                    | sem API key      | adapters open-source
                |                  |                    |                  | (auditáveis)
    Tokenomist  | maior, mais      | freemium/pago para | sim (paga)       | "fonte de verdade"
                | granular         | uso automatizado   |                  | citada por vários
    CryptoRank  | amplo, dashboard | freemium/pago      | sim (paga)       | forte para UX/alertas,
                | forte            |                    |                  | não para automação

    Decisão para esta entrega: `DefiLlamaUnlockProvider` como
    implementação de referência -- é a única opção gratuita, sem chave
    e com adapters auditáveis publicamente encontrada. Se a cobertura
    (~300 projetos) ou a granularidade não forem suficientes para os
    ativos que o AlphaQuant realmente opera, Tokenomist/CryptoRank são
    os candidatos pagos a cotar (custo/limites reais, não estimados
    aqui) -- comparação a preencher antes de qualquer contratação,
    conforme a seção 19 do documento pede explicitamente.

NOTA DE AMBIENTE: este sandbox não tem acesso de rede a `api.llama.fi`
(fora da allowlist). A implementação abaixo segue a estrutura pública
documentada da API de emissions da DefiLlama e está coberta por testes
unitários com HTTP mockado, mas NÃO foi validada contra a API real —
validar isso é o primeiro passo antes de habilitar em produção.

Point-in-Time: `TokenUnlockEvent.observed_at` é quando o CRONOGRAMA
daquele unlock ficou conhecido (normalmente na tokenomics do projeto,
publicada bem antes do TGE) -- distinto de `unlock_date` (quando o
unlock efetivamente ocorre). Cronogramas de vesting raramente mudam,
mas quando mudam (renegociação com investidores, por exemplo), isso
gera um novo `observed_at` para o registro revisado.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal

import requests

from fundamentals.base import FundamentalsDataProvider, FundamentalsUnavailableError

DEFILLAMA_BASE_URL = "https://api.llama.fi"
REQUEST_TIMEOUT = 10

UnlockType = Literal["cliff", "linear", "unknown"]


@dataclass(frozen=True, slots=True)
class TokenUnlockEvent:
    """Um evento de unlock (liberação de tokens travados), com proveniência Point-in-Time."""

    symbol: str
    unlock_date: date
    amount_tokens: float
    pct_of_circulating_supply: float | None
    unlock_type: UnlockType
    category: str | None  # ex.: "team", "investors", "community", "ecosystem"
    observed_at: datetime
    source: str
    amount_usd_estimate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "unlock_date": self.unlock_date.isoformat(),
            "amount_tokens": self.amount_tokens,
            "amount_usd_estimate": self.amount_usd_estimate,
            "pct_of_circulating_supply": self.pct_of_circulating_supply,
            "unlock_type": self.unlock_type,
            "category": self.category,
            "observed_at": self.observed_at.isoformat(),
            "source": self.source,
        }


class TokenUnlockProvider(FundamentalsDataProvider):
    """Interface para o cronograma de unlocks/vesting de um token."""

    @abstractmethod
    def get_upcoming_unlocks(self, symbol: str, start: date, end: date) -> list[TokenUnlockEvent]:
        """Unlocks agendados no intervalo [start, end] (`unlock_date` futuro)."""

    @abstractmethod
    def get_unlock_history(self, symbol: str, start: date, end: date) -> list[TokenUnlockEvent]:
        """Unlocks já ocorridos no intervalo [start, end] -- útil para backtesting/journal."""


class NullTokenUnlockProvider(TokenUnlockProvider):
    """Fallback explícito: nenhuma fonte de unlocks configurada."""

    name = "none_configured"

    def get_upcoming_unlocks(self, symbol: str, start: date, end: date) -> list[TokenUnlockEvent]:
        raise FundamentalsUnavailableError(
            "Nenhum TokenUnlockProvider configurado. Configure DefiLlamaUnlockProvider "
            "(ou outro vendor) antes de consultar unlocks."
        )

    def get_unlock_history(self, symbol: str, start: date, end: date) -> list[TokenUnlockEvent]:
        raise FundamentalsUnavailableError(
            "Nenhum TokenUnlockProvider configurado. Configure DefiLlamaUnlockProvider "
            "(ou outro vendor) antes de consultar unlocks."
        )


class DefiLlamaUnlockProvider(TokenUnlockProvider):
    """
    Cronograma de unlocks via DefiLlama (`GET /emissions/{protocol_slug}`)
    -- gratuito, sem API key. Ver avaliação de vendor no topo do módulo.
    """

    name = "defillama"

    def __init__(
        self,
        symbol_to_slug: dict[str, str],
        session: requests.Session | None = None,
    ) -> None:
        """
        Args:
            symbol_to_slug: mapa símbolo canônico -> slug do projeto na
                DefiLlama (ex.: {"ARBUSDT": "arbitrum"}). A DefiLlama
                identifica projetos por slug, não por par de trading --
                esse mapeamento é responsabilidade de quem instancia o
                provider (mesma ideia do `symbols.mapper`, mas para um
                vocabulário de identificadores diferente).
        """
        self._symbol_to_slug = symbol_to_slug
        self._session = session or requests.Session()

    def _resolve_slug(self, symbol: str) -> str:
        slug = self._symbol_to_slug.get(symbol.upper())
        if slug is None:
            raise FundamentalsUnavailableError(
                f"[{self.name}] símbolo {symbol} não mapeado para um slug de projeto DefiLlama."
            )
        return slug

    def _fetch_events(self, symbol: str) -> list[TokenUnlockEvent]:
        slug = self._resolve_slug(symbol)
        try:
            response = self._session.get(f"{DEFILLAMA_BASE_URL}/emissions/{slug}", timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise FundamentalsUnavailableError(f"[{self.name}] falha de rede para {symbol} ({slug}): {exc}") from exc

        payload = response.json()
        observed_at = datetime.now(timezone.utc)  # DefiLlama não versiona "quando o schedule foi publicado".
        events: list[TokenUnlockEvent] = []

        for row in payload.get("events", []):
            timestamp = row.get("timestamp")
            if timestamp is None:
                continue
            unlock_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
            for allocation in row.get("noOfTokens", []) or [row.get("total")]:
                if allocation is None:
                    continue
                events.append(
                    TokenUnlockEvent(
                        symbol=symbol.upper(),
                        unlock_date=unlock_date,
                        amount_tokens=float(allocation),
                        amount_usd_estimate=None,  # exigiria cruzar com preço no momento -- não fabricado aqui.
                        pct_of_circulating_supply=None,  # exigiria supply circulante no momento do unlock.
                        unlock_type="cliff" if row.get("category") == "cliff" else "linear",
                        category=row.get("category"),
                        observed_at=observed_at,
                        source=self.name,
                    )
                )
        return events

    def get_upcoming_unlocks(self, symbol: str, start: date, end: date) -> list[TokenUnlockEvent]:
        today = datetime.now(timezone.utc).date()
        effective_start = max(start, today)
        events = self._fetch_events(symbol)
        return sorted(
            (e for e in events if effective_start <= e.unlock_date <= end),
            key=lambda e: e.unlock_date,
        )

    def get_unlock_history(self, symbol: str, start: date, end: date) -> list[TokenUnlockEvent]:
        today = datetime.now(timezone.utc).date()
        effective_end = min(end, today)
        events = self._fetch_events(symbol)
        return sorted(
            (e for e in events if start <= e.unlock_date <= effective_end),
            key=lambda e: e.unlock_date,
        )

    def close(self) -> None:
        self._session.close()
