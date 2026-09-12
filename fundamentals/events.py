"""
fundamentals/events.py
=========================

MOTOR 2/4 -- EconomicEventsProvider (Documento 4, seção 19)

Calendário de eventos macro (FOMC, CPI, NFP, decisões de juros de
outros bancos centrais, etc.) -- o "o que está agendado" que qualquer
motor de risco/timing precisa saber ANTES do evento acontecer.

Vendor evaluation (Documento 4, seção 19 -- pesquisa feita antes de
implementar):

    Calendários econômicos ao vivo com API própria e gratuita e sem
    fortes restrições de uso comercial são raros -- os players fortes
    (Trading Economics, Investing.com/FXStreet, ForexFactory) ou cobram,
    ou têm termos que restringem uso automatizado/redistribuição. Não
    encontrei uma opção "gratuita e irrestrita" equivalente ao que a
    DefiLlama oferece para unlocks.

    Decisão para esta entrega: em vez de bloquear a Fase 4 esperando
    aprovação de orçamento, o motor abaixo (`StaticCuratedEventsProvider`)
    lê um calendário local, versionado com o projeto (JSON), com
    eventos de altíssimo impacto (FOMC, CPI, NFP) cujas DATAS são
    informação pública (calendários oficiais do Fed/BLS) -- sem
    depender de nenhum vendor pago. O que este motor NÃO cobre bem:
    `actual` / `forecast` (consenso de mercado) em tempo real, e
    eventos de menor porte (bancos centrais menores, dados regionais).

    Antes de comprar um vendor pago para isso, comparar nesta tabela
    (a preencher com cotação real quando for avaliar):

        vendor              | cobertura | latência | histórico | Point-in-Time | custo
        Trading Economics   |    ?      |    ?      |    ?      |      ?        |   ?
        FXStreet/Investing  |    ?      |    ?      |    ?      |      ?        |   ?
        ForexFactory (scrape)|   ?      |    ?      |    ?      |      ?        |   ? (ToS restritivo)

Point-in-Time: `EconomicEvent.observed_at` é quando ESTA LEITURA do
evento (agendamento, ou uma revisão de actual/forecast) ficou
conhecida -- forecasts mudam nos dias antes do evento, e `actual` só
existe a partir do instante em que o evento efetivamente ocorre.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fundamentals.base import FundamentalsDataProvider, FundamentalsUnavailableError

Importance = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class EconomicEvent:
    """Um evento do calendário econômico, com proveniência Point-in-Time."""

    event_id: str
    name: str
    country: str
    category: str
    scheduled_at: datetime
    importance: Importance
    observed_at: datetime
    source: str
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "name": self.name,
            "country": self.country,
            "category": self.category,
            "scheduled_at": self.scheduled_at.isoformat(),
            "importance": self.importance,
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
            "observed_at": self.observed_at.isoformat(),
            "source": self.source,
        }


class EconomicEventsProvider(FundamentalsDataProvider):
    """Interface para o calendário de eventos macroeconômicos."""

    @abstractmethod
    def get_events(
        self,
        start: date,
        end: date,
        as_of: datetime | None = None,
        min_importance: Importance = "low",
    ) -> list[EconomicEvent]:
        """
        Retorna os eventos agendados em [start, end].

        Args:
            as_of: quando informado, só retorna eventos cujo
                agendamento já era conhecido em `as_of`
                (`observed_at <= as_of`) -- essencial para não vazar
                para um backtest um evento que só foi anunciado depois
                da data simulada.
            min_importance: filtra eventos abaixo dessa importância
                ("low" < "medium" < "high").
        """


class NullEconomicEventsProvider(EconomicEventsProvider):
    """Fallback explícito: nenhuma fonte de calendário configurada."""

    name = "none_configured"

    def get_events(
        self,
        start: date,
        end: date,
        as_of: datetime | None = None,
        min_importance: Importance = "low",
    ) -> list[EconomicEvent]:
        raise FundamentalsUnavailableError(
            "Nenhum EconomicEventsProvider configurado. Configure "
            "StaticCuratedEventsProvider (ou outro vendor) antes de consultar eventos."
        )


_IMPORTANCE_RANK: dict[Importance, int] = {"low": 0, "medium": 1, "high": 2}


class StaticCuratedEventsProvider(EconomicEventsProvider):
    """
    Lê um calendário local versionado com o projeto -- ver docstring do
    módulo para a justificativa de não usar um vendor pago ainda.

    Formato esperado do arquivo JSON (`fundamentals/data/events_calendar.json`):

        [
          {
            "event_id": "fomc-2026-09-17",
            "name": "FOMC Rate Decision",
            "country": "US",
            "category": "interest_rate",
            "scheduled_at": "2026-09-17T18:00:00+00:00",
            "importance": "high",
            "observed_at": "2026-01-01T00:00:00+00:00",
            "actual": null, "forecast": null, "previous": 4.25
          },
          ...
        ]

    `observed_at` deve ser preenchido com a data em que o calendário
    anunciou aquele evento (para FOMC/CPI/NFP dos EUA, isso costuma
    ser meses antes -- o Fed publica o calendário anual do FOMC com
    bastante antecedência).

    O arquivo semente entregue com o projeto
    (`fundamentals/data/events_calendar.json`) já vem populado com as
    3 reuniões de FOMC restantes de 2026 (16/set, 28/out, 09/dez),
    verificadas contra o calendário oficial publicado em
    federalreserve.gov (comunicado de 09/ago/2024, que é o
    `observed_at` de cada uma). CPI/NFP/outros bancos centrais ainda
    não estão povoados -- adicionar seguindo o mesmo formato, ou
    integrar um vendor (ver avaliação acima) quando isso for prioridade.
    """

    name = "static_curated"

    def __init__(self, data_path: Path | str) -> None:
        self._data_path = Path(data_path)
        if not self._data_path.exists():
            raise FundamentalsUnavailableError(
                f"Calendário de eventos não encontrado em {self._data_path}."
            )

    def _load(self) -> list[EconomicEvent]:
        raw = json.loads(self._data_path.read_text(encoding="utf-8"))
        events: list[EconomicEvent] = []
        for row in raw:
            events.append(
                EconomicEvent(
                    event_id=row["event_id"],
                    name=row["name"],
                    country=row["country"],
                    category=row["category"],
                    scheduled_at=datetime.fromisoformat(row["scheduled_at"]),
                    importance=row["importance"],
                    observed_at=datetime.fromisoformat(row["observed_at"]),
                    source=self.name,
                    actual=row.get("actual"),
                    forecast=row.get("forecast"),
                    previous=row.get("previous"),
                )
            )
        return events

    def get_events(
        self,
        start: date,
        end: date,
        as_of: datetime | None = None,
        min_importance: Importance = "low",
    ) -> list[EconomicEvent]:
        events = self._load()

        events = [e for e in events if start <= e.scheduled_at.date() <= end]
        events = [e for e in events if _IMPORTANCE_RANK[e.importance] >= _IMPORTANCE_RANK[min_importance]]
        if as_of is not None:
            events = [e for e in events if e.observed_at <= as_of]

        return sorted(events, key=lambda e: e.scheduled_at)
