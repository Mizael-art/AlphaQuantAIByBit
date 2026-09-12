"""
volume_profile/profile.py
===========================

Cálculo do Volume Profile: distribuição do volume negociado por nível
de preço (não por tempo), permitindo identificar:

- **POC (Point of Control)**: o nível de preço com maior volume
  negociado — a "zona de maior aceitação de preço" do período.
- **VAH / VAL (Value Area High / Low)**: os limites da região que
  concentra ~70% do volume total ao redor do POC (a "Value Area").
- **HVN (High Volume Nodes)**: picos locais de volume — zonas onde o
  preço tende a encontrar suporte/resistência por concentração de
  negociação.
- **LVN (Low Volume Nodes)**: vales locais de volume — zonas onde o
  preço tende a se mover rapidamente por falta de negociação.

Como a Binance não fornece volume por nível de preço via REST público,
esta implementação aproxima o perfil distribuindo o volume de cada
candle uniformemente ao longo do seu range (high-low) — a mesma
aproximação usada por praticamente todas as plataformas que constroem
Volume Profile a partir de candles OHLCV (em vez de dados de tick).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class VolumeNode:
    """Um nó de volume (HVN ou LVN) em um nível de preço específico."""

    price: float
    volume: float
    kind: str  # "hvn" | "lvn"

    def to_dict(self) -> dict:
        return {"price": round(self.price, 6), "volume": round(self.volume, 4), "kind": self.kind}


@dataclass(frozen=True, slots=True)
class VolumeProfileResult:
    """Resultado completo do Volume Profile para um DataFrame OHLCV."""

    poc: float
    vah: float
    val: float
    hvns: list[VolumeNode]
    lvns: list[VolumeNode]
    price_range_low: float
    price_range_high: float

    def to_dict(self) -> dict:
        return {
            "poc": round(self.poc, 6),
            "vah": round(self.vah, 6),
            "val": round(self.val, 6),
            "hvn": [node.to_dict() for node in self.hvns],
            "lvn": [node.to_dict() for node in self.lvns],
            "range": {
                "low": round(self.price_range_low, 6),
                "high": round(self.price_range_high, 6),
            },
        }


def _distribute_volume_into_bins(
    df: pd.DataFrame, bin_edges: np.ndarray
) -> np.ndarray:
    """
    Distribui o volume de cada candle proporcionalmente aos bins de
    preço que seu range (high-low) sobrepõe.
    """
    num_bins = len(bin_edges) - 1
    bin_volumes = np.zeros(num_bins)

    bin_starts = bin_edges[:-1]
    bin_ends = bin_edges[1:]

    for low, high, volume in zip(df["low"].to_numpy(), df["high"].to_numpy(), df["volume"].to_numpy()):
        candle_range = high - low
        if candle_range <= 0:
            # Candle sem range (doji perfeito): joga todo o volume no
            # bin que contém o preço.
            bin_index = np.clip(np.searchsorted(bin_edges, low, side="right") - 1, 0, num_bins - 1)
            bin_volumes[bin_index] += volume
            continue

        # Sobreposição de cada bin com o range [low, high] do candle.
        overlap = np.minimum(bin_ends, high) - np.maximum(bin_starts, low)
        overlap = np.clip(overlap, 0, None)
        overlap_ratio = overlap / candle_range

        bin_volumes += overlap_ratio * volume

    return bin_volumes


def build_volume_profile(df: pd.DataFrame, num_bins: int = 50, value_area_pct: float = 0.70) -> VolumeProfileResult:
    """
    Constrói o Volume Profile completo para um DataFrame OHLCV.

    Args:
        df: DataFrame OHLCV (colunas high, low, volume).
        num_bins: número de níveis de preço (granularidade do perfil).
        value_area_pct: percentual do volume total considerado na
            Value Area (padrão: 70%, o valor de mercado tradicional).

    Returns:
        `VolumeProfileResult` com POC, VAH, VAL, HVNs e LVNs.
    """
    price_low = float(df["low"].min())
    price_high = float(df["high"].max())

    bin_edges = np.linspace(price_low, price_high, num_bins + 1)
    bin_midpoints = (bin_edges[:-1] + bin_edges[1:]) / 2

    bin_volumes = _distribute_volume_into_bins(df, bin_edges)

    poc_index = int(np.argmax(bin_volumes))
    poc = float(bin_midpoints[poc_index])

    vah, val = _calculate_value_area(bin_midpoints, bin_volumes, poc_index, value_area_pct)
    hvns, lvns = _find_volume_nodes(bin_midpoints, bin_volumes)

    return VolumeProfileResult(
        poc=poc,
        vah=vah,
        val=val,
        hvns=hvns,
        lvns=lvns,
        price_range_low=price_low,
        price_range_high=price_high,
    )


def _calculate_value_area(
    bin_midpoints: np.ndarray, bin_volumes: np.ndarray, poc_index: int, value_area_pct: float
) -> tuple[float, float]:
    """
    Expande a Value Area a partir do bin do POC, sempre adicionando o
    lado (superior ou inferior) com maior volume, até acumular
    `value_area_pct` do volume total.
    """
    total_volume = bin_volumes.sum()
    target_volume = total_volume * value_area_pct

    low_idx = high_idx = poc_index
    accumulated = bin_volumes[poc_index]

    while accumulated < target_volume and (low_idx > 0 or high_idx < len(bin_volumes) - 1):
        volume_below = bin_volumes[low_idx - 1] if low_idx > 0 else -1
        volume_above = bin_volumes[high_idx + 1] if high_idx < len(bin_volumes) - 1 else -1

        if volume_above >= volume_below:
            high_idx += 1
            accumulated += bin_volumes[high_idx]
        else:
            low_idx -= 1
            accumulated += bin_volumes[low_idx]

    return float(bin_midpoints[high_idx]), float(bin_midpoints[low_idx])


def _find_volume_nodes(
    bin_midpoints: np.ndarray, bin_volumes: np.ndarray, max_nodes: int = 5
) -> tuple[list[VolumeNode], list[VolumeNode]]:
    """
    Identifica picos locais (HVN) e vales locais (LVN) no histograma de
    volume, retornando os `max_nodes` mais relevantes de cada tipo.
    """
    hvns: list[VolumeNode] = []
    lvns: list[VolumeNode] = []

    for i in range(1, len(bin_volumes) - 1):
        is_local_max = bin_volumes[i] > bin_volumes[i - 1] and bin_volumes[i] > bin_volumes[i + 1]
        is_local_min = bin_volumes[i] < bin_volumes[i - 1] and bin_volumes[i] < bin_volumes[i + 1]

        if is_local_max:
            hvns.append(VolumeNode(price=float(bin_midpoints[i]), volume=float(bin_volumes[i]), kind="hvn"))
        elif is_local_min:
            lvns.append(VolumeNode(price=float(bin_midpoints[i]), volume=float(bin_volumes[i]), kind="lvn"))

    hvns.sort(key=lambda n: n.volume, reverse=True)
    lvns.sort(key=lambda n: n.volume)

    return hvns[:max_nodes], lvns[:max_nodes]
