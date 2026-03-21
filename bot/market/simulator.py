import random

from bot.models import Candle


def generate_candles(
    *,
    candle_count: int,
    start_price: float,
    volatility: float,
    seed: int,
) -> list[Candle]:
    rng = random.Random(seed)
    candles: list[Candle] = []
    price = start_price
    start_timestamp_ms = 1_700_000_000_000
    interval_ms = 60_000

    for i in range(candle_count):
        open_price = price
        close_change = rng.uniform(-volatility, volatility)
        close_price = max(1.0, open_price * (1.0 + close_change))

        wick_up = rng.uniform(0.0, volatility / 2)
        wick_down = rng.uniform(0.0, volatility / 2)
        high_price = max(open_price, close_price) * (1.0 + wick_up)
        low_price = max(1.0, min(open_price, close_price) * (1.0 - wick_down))
        volume = rng.uniform(10.0, 1_000.0)

        candles.append(
            Candle(
                timestamp=start_timestamp_ms + (i * interval_ms),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
                index=i,
            )
        )
        price = close_price

    return candles
