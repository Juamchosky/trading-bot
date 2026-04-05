from __future__ import annotations

from bot.models import Candle


class TimeSeriesMomentumStrategy:
    def __init__(self, *, lookback_period: int = 200) -> None:
        self.lookback_period = lookback_period

    def signal(self, candles: list[Candle], *, in_position: bool) -> str:
        if len(candles) <= self.lookback_period:
            return "hold"

        current_close = candles[-1].close
        past_close = candles[-1 - self.lookback_period].close
        if past_close <= 0.0:
            return "hold"

        past_return = (current_close / past_close) - 1.0

        if not in_position and past_return > 0.0:
            return "buy"
        if in_position and past_return <= 0.0:
            return "sell"
        return "hold"
