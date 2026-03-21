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

    for i in range(candle_count):
        change = rng.uniform(-volatility, volatility)
        price = max(1.0, price * (1.0 + change))
        candles.append(Candle(index=i, close=price))

    return candles

