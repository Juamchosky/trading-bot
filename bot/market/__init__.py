"""Market adapters."""

from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.market.simulator import generate_candles

__all__ = [
    "BinanceMarketDataError",
    "fetch_historical_candles",
    "generate_candles",
]
