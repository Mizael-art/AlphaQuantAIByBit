"""
config.py
=========

Configurações centrais do AlphaQuant Engine.

Este módulo concentra todas as constantes usadas pelo restante do
sistema: URLs base da Binance, endpoints públicos, mapeamento de
timeframes, parâmetros padrão dos indicadores técnicos e limites
gerais da aplicação.

Mantendo essas configurações em um único lugar, qualquer ajuste futuro
(ex.: trocar de exchange, mudar períodos de EMA, adicionar novos
endpoints) é feito em um único ponto, sem tocar na lógica de negócio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


# ====================================================================
# BINANCE - CONFIGURAÇÕES DE REDE
# ====================================================================

# URL base da API pública da Binance (Spot Market).
# Não é necessária API Key para os endpoints usados na Fase 1.
BINANCE_BASE_URL: Final[str] = "https://api.binance.com"

# Endpoints públicos utilizados pelo projeto.
ENDPOINT_KLINES: Final[str] = "/api/v3/klines"
ENDPOINT_TICKER_PRICE: Final[str] = "/api/v3/ticker/price"
ENDPOINT_DEPTH: Final[str] = "/api/v3/depth"

# Timeout padrão (em segundos) para requisições HTTP.
REQUEST_TIMEOUT: Final[int] = 10

# Número de tentativas em caso de falha de rede/rate limit.
MAX_RETRIES: Final[int] = 3

# Tempo de espera (segundos) entre tentativas (backoff simples).
RETRY_BACKOFF_SECONDS: Final[float] = 1.5


# ====================================================================
# TIMEFRAMES
# ====================================================================

# Mapeamento de timeframes amigáveis para o formato aceito pela Binance
# no parâmetro "interval" do endpoint /klines.
TIMEFRAME_MAP: Final[dict[str, str]] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1H": "1h",
    "2H": "2h",
    "4H": "4h",
    "6H": "6h",
    "8H": "8h",
    "12H": "12h",
    "1D": "1d",
    "3D": "3d",
    "1W": "1w",
    "1M": "1M",
}

# Timeframe padrão usado quando nenhum é informado explicitamente.
DEFAULT_TIMEFRAME: Final[str] = "4H"

# Quantidade padrão de candles buscados por requisição.
# A Binance permite até 1000 candles por chamada ao /klines.
DEFAULT_KLINES_LIMIT: Final[int] = 500
MAX_KLINES_LIMIT: Final[int] = 1000


# ====================================================================
# PARÂMETROS DOS INDICADORES TÉCNICOS
# ====================================================================

@dataclass(frozen=True)
class EMAConfig:
    """Períodos das médias móveis exponenciais calculadas pelo sistema."""

    periods: tuple[int, ...] = (20, 50, 100, 200)


@dataclass(frozen=True)
class RSIConfig:
    """Parâmetros do Índice de Força Relativa (RSI)."""

    period: int = 14
    overbought: float = 70.0
    oversold: float = 30.0


@dataclass(frozen=True)
class ATRConfig:
    """Parâmetros do Average True Range (ATR)."""

    period: int = 14


@dataclass(frozen=True)
class MACDConfig:
    """Parâmetros do MACD (Moving Average Convergence Divergence)."""

    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9


@dataclass(frozen=True)
class VolumeConfig:
    """Parâmetros da análise de volume."""

    average_period: int = 20


@dataclass(frozen=True)
class IndicatorsConfig:
    """Agrupa todas as configurações de indicadores em um único objeto."""

    ema: EMAConfig = field(default_factory=EMAConfig)
    rsi: RSIConfig = field(default_factory=RSIConfig)
    atr: ATRConfig = field(default_factory=ATRConfig)
    macd: MACDConfig = field(default_factory=MACDConfig)
    volume: VolumeConfig = field(default_factory=VolumeConfig)


# Instância única (singleton simples) usada em todo o projeto.
INDICATORS_CONFIG: Final[IndicatorsConfig] = IndicatorsConfig()


# ====================================================================
# ESTRUTURA DE MERCADO
# ====================================================================

@dataclass(frozen=True)
class StructureConfig:
    """Parâmetros usados na detecção de estrutura de mercado (swings, BOS, CHOCH)."""

    # Número de candles à esquerda/direita usados para confirmar um
    # swing high/low (fractal simples).
    swing_lookback: int = 2

    # Número mínimo de swings necessários para determinar tendência.
    min_swings_for_trend: int = 3


STRUCTURE_CONFIG: Final[StructureConfig] = StructureConfig()


# ====================================================================
# ANÁLISE / SCORE
# ====================================================================

@dataclass(frozen=True)
class AnalysisConfig:
    """Parâmetros gerais do módulo de análise (suporte/resistência, score)."""

    # Número de níveis de suporte/resistência retornados no JSON final.
    max_levels_returned: int = 2

    # Tolerância percentual usada para agrupar níveis de preço próximos
    # em uma única zona de suporte/resistência.
    price_cluster_tolerance_pct: float = 0.5


ANALYSIS_CONFIG: Final[AnalysisConfig] = AnalysisConfig()


# ====================================================================
# APLICAÇÃO
# ====================================================================

# Símbolo e timeframe padrão usados quando a API é chamada sem parâmetros.
DEFAULT_SYMBOL: Final[str] = "BTCUSDT"

# Ativa/desativa logs detalhados (útil durante desenvolvimento).
DEBUG_MODE: Final[bool] = True


# ====================================================================
# SCANNER (varredura multi-símbolo / "procurar oportunidades")
# ====================================================================

# Watchlist padrão usada pelo endpoint /scan quando o usuário não
# especifica símbolos. Pares USDT (Spot) de alta liquidez na Binance.
# Ajuste livremente conforme o que você realmente acompanha.
DEFAULT_SCAN_SYMBOLS: Final[list[str]] = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
    "TRXUSDT", "DOTUSDT", "POLUSDT", "LTCUSDT", "SUIUSDT",
    "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "ATOMUSDT",
    "INJUSDT", "FILUSDT", "RENDERUSDT", "TIAUSDT", "HBARUSDT",
]

# Timeframes padrão do scan: HTF (contexto/tendência) e LTF (gatilho).
DEFAULT_SCAN_HTF: Final[str] = "4H"
DEFAULT_SCAN_LTF: Final[str] = "1H"

# Quantos símbolos o /scan processa em paralelo (threads). Mais alto
# = mais rápido, mas mais peso simultâneo na Bybit/Binance e no dyno do
# Render. Subido de 8 -> 25: a Stage 2 do universo completo (ver
# `SCAN_UNIVERSE_*` abaixo) só roda sobre um número já bem filtrado de
# candidatos, então dá pra ser mais agressivo aqui sem risco real de
# rate limit (o pool de conexões em `providers/bybit_client.py` foi
# dimensionado junto, ver `CONNECTION_POOL_SIZE`).
SCAN_CONCURRENCY: Final[int] = 25

# Quantidade de candles buscada por símbolo/timeframe DENTRO do scan
# (Stage 2). 260 é suficiente para EMA200 + margem de segurança, sem
# pagar o custo de rede/parsing de 500 candles (default usado fora do
# scan, em `/snapshot` e no CLI) para uma varredura em lote.
SCAN_KLINES_LIMIT: Final[int] = 260

# Limite de símbolos por chamada quando uma lista explícita é passada
# em `symbols=` (modo "watchlist" do /scan). Não se aplica ao modo
# `universe=all_bybit` (ver abaixo), que tem seu próprio corte via
# `SCAN_STAGE1_TOP_N` depois do pré-filtro.
SCAN_MAX_SYMBOLS: Final[int] = 60


# ====================================================================
# SCAN DE UNIVERSO COMPLETO (Bybit) -- /scan?universe=all_bybit
# ====================================================================
#
# Em vez de depender de uma watchlist fixa (DEFAULT_SCAN_SYMBOLS, ~25
# ativos mantidos manualmente), este modo varre TODOS os perpétuos
# USDT negociáveis na Bybit (ver `providers/bybit_universe.py`) em
# duas etapas:
#
#   Stage 1 (barata, ~1 requisição HTTP no total): busca o ticker de
#   todo o mercado de uma vez (`get_bulk_ticker_snapshot`) e usa só
#   isso -- sem nenhum candle -- para descartar ativos ilíquidos e
#   rankear o resto por atividade (`scanner/fast_filter.py`).
#
#   Stage 2 (cara, só nos sobreviventes): roda o pipeline completo
#   (indicadores + estrutura + score) apenas nos `SCAN_STAGE1_TOP_N`
#   candidatos que passaram na Stage 1 -- é isso que torna viável
#   escanear 300+ ativos em segundos em vez de minutos.

# Quantos candidatos passam da Stage 1 para a Stage 2 (análise completa).
SCAN_STAGE1_TOP_N: Final[int] = 60

# Piso de liquidez (turnover em USDT nas últimas 24h) para um ativo
# sequer entrar na Stage 1. Abaixo disso, o spread/slippage tende a
# inviabilizar a execução mesmo que o setup técnico pareça bom.
SCAN_STAGE1_MIN_TURNOVER_USDT: Final[float] = 3_000_000.0

# TTL do cache da lista de instrumentos negociáveis da Bybit (ver
# `providers/bybit_universe.py`). A lista de pares muda pouco por dia;
# não vale a pena repaginar `instruments-info` a cada scan.
SCAN_UNIVERSE_CACHE_TTL_SECONDS: Final[int] = 6 * 60 * 60

# Distância percentual (preço x nível) para considerar que o ativo já
# está DENTRO da zona de entrada (S/R, OB, liquidez agrupada).
#
# Era 0.6 -- apertado demais pra volatilidade normal de cripto (um
# movimento de 0.6% acontece em minutos), o que fazia um símbolo
# alternar entre "zona_de_entrada" e "observar" de um scan pro outro
# sem nenhuma mudança real de estrutura. Alargado pra 1.5 pra reduzir
# esse "pisca-pisca" e também aparecer mais candidatos (a barra de
# qualidade real agora é reforçada pelo filtro de espaço até o alvo
# abaixo, não só pela proximidade da zona de entrada).
SCAN_ENTRY_ZONE_PCT: Final[float] = 1.5

# Distância percentual para considerar que o ativo está "se
# aproximando" de uma zona e deve entrar na lista de observação.
SCAN_WATCH_ZONE_PCT: Final[float] = 2.0

# Score mínimo (média HTF+LTF) para classificar como zona de entrada.
SCAN_MIN_SCORE_ENTRY: Final[int] = 70

# Score mínimo (média HTF+LTF) para classificar como observação, ainda
# que o preço não esteja perto de uma zona (ex.: estrutura forte se
# formando).
SCAN_MIN_SCORE_WATCH: Final[int] = 60

# Espaço mínimo (% do preço) até a zona OPOSTA mais próxima (o alvo
# potencial), pra sequer contar como "zona_de_entrada". Sem isso, um
# símbolo podia ficar preso entre um suporte e uma resistência quase
# colados -- tecnicamente "na zona de entrada", mas sem espaço real
# pra correr (o "trade estranho que nem em 5x dá 5%"). Objetiva a
# pergunta "existe espaço suficiente até o alvo?" (antes só existia
# como frase solta nas instruções do GPT, sem nenhum número).
SCAN_MIN_REWARD_RUNWAY_PCT: Final[float] = 2.0

# Razão mínima entre o espaço até o alvo oposto (reward) e a distância
# até a zona de entrada (risco/gatilho) -- um proxy de R:R calculado
# no próprio scan, antes mesmo do snapshot detalhado do símbolo.
SCAN_MIN_REWARD_RISK_RATIO: Final[float] = 2.0


# ====================================================================
# SCAN CONTÍNUO DE FUNDO (background loop) -- ver scanner/background_loop.py
# ====================================================================
#
# Em vez do GPT chamar `/scan?universe=all_bybit` na hora (minutos de
# espera dentro do timeout curto de uma GPT Action), o motor roda o
# scan em loop dentro do próprio processo, grava o resultado mais
# recente no banco (`persistence.ScanSnapshot`), e o GPT só LÊ esse
# resultado via `/scan/latest` -- resposta em milissegundos, sem
# depender do timeout da Action. Um serviço externo de keep-alive
# (UptimeRobot ou similar) só precisa pingar `/health` periodicamente
# pra impedir o Render de hibernar o processo por inatividade; ele NÃO
# dispara o scan -- o loop já roda sozinho enquanto o processo existir.

# Chave usada pelo loop padrão iniciado no startup do servidor
# (formato livre: "<universe>:<htf>:<ltf>"). Mudar aqui também exige
# ajustar o valor default lido por `/scan/latest` em `server.py`.
SCAN_BACKGROUND_KEY: Final[str] = "all_bybit:4H:1H"

# Pausa mínima entre o FIM de um ciclo e o INÍCIO do próximo. Não é
# pra "esperar" no sentido de atualização periódica -- é só uma rede
# de segurança contra martelar a API da Bybit sem parar caso um ciclo
# termine anormalmente rápido (erro logo no início, por exemplo).
SCAN_BACKGROUND_MIN_INTERVAL_SECONDS: Final[float] = 5.0


# ====================================================================
# CROSS-EXCHANGE (MARKET VIEW / STRUCTURE VIEW -- Documento 4)
# ====================================================================

# Liga/desliga o consenso multi-exchange (preço + estrutura) no
# snapshot. Desligado, o `/snapshot` continua funcionando exatamente
# como antes (single-source via ProviderRouter) -- útil para não
# depender de 4 exchanges responderem em ambientes de teste/CI ou se
# o custo de rede/latência não compensar em algum contexto específico.
ENABLE_CROSS_EXCHANGE: Final[bool] = True

# Exchange de execução padrão (EXECUTION VIEW -- Documento 4, seção 9):
# onde o usuário efetivamente opera. Preço/spread/liquidez desta
# exchange NUNCA substituem o consenso de mercado -- só é usada para
# separar "o que o mercado mostra" de "o que acontece onde vou operar".
DEFAULT_EXECUTION_VENUE: Final[str] = "bitget"

# Candles buscados por exchange para o CrossExchangeReconciliationEngine
# (consenso de preço/wick -- não precisa de histórico profundo).
CROSS_EXCHANGE_PRICE_LIMIT: Final[int] = 50

# Candles buscados por exchange para o StructureConsensusEngine (precisa
# de histórico suficiente para swings/BOS/CHOCH confiáveis -- mesmo
# mínimo usado pelo `TimeframeSnapshot` de fonte única).
CROSS_EXCHANGE_STRUCTURE_LIMIT: Final[int] = 300
