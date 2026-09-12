"""
fundamentals/macro.py
========================

MOTOR 1/4 -- MacroDataProvider (Documento 4, seção 19)

Séries macroeconômicas (Fed Funds Rate, CPI, DXY, US 10Y Yield etc.)
que afetam o apetite a risco do mercado como um todo -- contexto que
nenhum candle de exchange consegue expressar sozinho.

Implementações incluídas:

    FredMacroProvider  -- referência real, gratuita: FRED (Federal
        Reserve Economic Data, St. Louis Fed). Cobre a imensa maioria
        das séries macro relevantes (juros, inflação, DXY via índice
        trade-weighted, payrolls) sem custo, mas exige uma API key
        gratuita (cadastro em https://fred.stlouisfed.org/docs/api/api_key.html).
    NullMacroProvider  -- fallback explícito quando nenhum vendor está
        configurado: nunca inventa valor, sempre reporta indisponível.

NOTA DE AMBIENTE: este sandbox de desenvolvimento não tem acesso de
rede a `api.stlouisfed.org` (fora da allowlist), então `FredMacroProvider`
foi implementado e coberto por testes unitários com HTTP mockado, mas
NÃO foi validado contra a API real. Validar com uma chamada real antes
de habilitar em produção.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import requests

from fundamentals.base import FundamentalsDataProvider, FundamentalsUnavailableError

FRED_BASE_URL = "https://api.stlouisfed.org/fred"
REQUEST_TIMEOUT = 10


@dataclass(frozen=True, slots=True)
class MacroDataPoint:
    """Um ponto de uma série macroeconômica, com proveniência Point-in-Time."""

    series_id: str
    period: date
    value: float
    unit: str
    observed_at: datetime
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "period": self.period.isoformat(),
            "value": self.value,
            "unit": self.unit,
            "observed_at": self.observed_at.isoformat(),
            "source": self.source,
        }


class MacroDataProvider(FundamentalsDataProvider):
    """Interface para séries macroeconômicas."""

    @abstractmethod
    def get_series(self, series_id: str, start: date, end: date) -> list[MacroDataPoint]:
        """Retorna todos os pontos PUBLICADOS da série no intervalo [start, end] (por `period`)."""

    @abstractmethod
    def get_latest(self, series_id: str, as_of: datetime | None = None) -> MacroDataPoint | None:
        """
        Retorna o ponto mais recente da série.

        Args:
            as_of: quando informado, só considera pontos com
                `observed_at <= as_of` -- é isso que torna a consulta
                Point-in-Time-safe para backtesting (Documento 4,
                seção 18). `None` (padrão) = "agora" (uso em produção).

        Returns:
            `None` quando não há nenhum ponto conhecido até `as_of`
            (nunca um valor estimado/extrapolado).
        """


class NullMacroProvider(MacroDataProvider):
    """
    Fallback explícito: nenhum vendor macro configurado ainda.

    Usado como padrão até uma decisão consciente de vendor ser tomada
    (Documento 4, seção 19 -- comparação de custo/cobertura/latência
    antes de comprar). Motores superiores devem tratar
    `FundamentalsUnavailableError` exatamente como tratam qualquer
    outra ausência de evidência: registrar `available: False`, nunca
    quebrar a análise.
    """

    name = "none_configured"

    def get_series(self, series_id: str, start: date, end: date) -> list[MacroDataPoint]:
        raise FundamentalsUnavailableError(
            "Nenhum MacroDataProvider configurado. Configure FredMacroProvider "
            "(ou outro vendor) antes de consultar séries macro."
        )

    def get_latest(self, series_id: str, as_of: datetime | None = None) -> MacroDataPoint | None:
        return None


class FredMacroProvider(MacroDataProvider):
    """
    Séries macro via FRED (St. Louis Fed) -- gratuito, requer API key.

    `observed_at`: o FRED expõe `realtime_start` em cada observação --
    a data em que aquele valor específico ficou disponível na série
    "as revised on that date". Usamos isso (à meia-noite UTC do dia)
    como `observed_at`, o que já resolve nativamente o problema de
    revisões (ex.: um GDP preliminar revisado dois meses depois vira
    um NOVO ponto com `observed_at` mais recente, não uma reescrita
    silenciosa do ponto antigo).
    """

    name = "fred"

    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        if not api_key:
            raise FundamentalsUnavailableError(
                "FredMacroProvider requer uma API key (gratuita) do FRED. "
                "Cadastro em https://fred.stlouisfed.org/docs/api/api_key.html"
            )
        self._api_key = api_key
        self._session = session or requests.Session()

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {"api_key": self._api_key, "file_type": "json", **params}
        try:
            response = self._session.get(f"{FRED_BASE_URL}/{endpoint}", params=query, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise FundamentalsUnavailableError(f"[fred] falha de rede em {endpoint}: {exc}") from exc
        return response.json()

    def get_series(self, series_id: str, start: date, end: date) -> list[MacroDataPoint]:
        data = self._get(
            "series/observations",
            {
                "series_id": series_id,
                "observation_start": start.isoformat(),
                "observation_end": end.isoformat(),
            },
        )
        points: list[MacroDataPoint] = []
        for row in data.get("observations", []):
            if row.get("value") in (None, ".", ""):
                continue  # FRED usa "." para "sem dado no período" -- não é zero.
            observed_at = datetime.fromisoformat(row["realtime_start"]).replace(
                hour=0, minute=0, second=0, tzinfo=timezone.utc
            )
            points.append(
                MacroDataPoint(
                    series_id=series_id,
                    period=date.fromisoformat(row["date"]),
                    value=float(row["value"]),
                    unit="",
                    observed_at=observed_at,
                    source=self.name,
                )
            )
        return points

    def get_latest(self, series_id: str, as_of: datetime | None = None) -> MacroDataPoint | None:
        # Busca uma janela ampla e filtra localmente por `observed_at`
        # -- o endpoint de observações do FRED não tem um parâmetro
        # nativo de "como visto em <timestamp>" tão granular quanto
        # precisamos para Point-in-Time por publicação.
        today = (as_of or datetime.now(timezone.utc)).date()
        window_start = date(today.year - 5, today.month, 1)
        points = self.get_series(series_id, window_start, today)
        if as_of is not None:
            points = [p for p in points if p.observed_at <= as_of]
        if not points:
            return None
        return max(points, key=lambda p: p.period)
