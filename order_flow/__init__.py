"""
order_flow
==========

Aproxima Delta (pressão compradora vs. vendedora) e CVD (Cumulative
Volume Delta) a partir do `taker_buy_volume` que a Binance já retorna
em todo candle de /api/v3/klines — sem precisar de /aggTrades (tick
data), o que evitaria estourar limites de requisição em timeframes com
muitos candles.

Isso NÃO é o Delta "real" de nível de tick (não separa cada trade
individualmente), mas é a mesma aproximação que a maioria das
ferramentas de order flow de varejo usa quando não têm acesso a feed
tick-a-tick: toda vez que uma vela fecha, a Binance já sabe quanto
desse volume foi iniciado por compradores agressivos (taker buy) e o
resto foi iniciado por vendedores agressivos (taker sell).
"""

from order_flow.delta import build_order_flow

__all__ = ["build_order_flow"]
