from __future__ import annotations

from bot.models import Candle


class TimeSeriesMomentumMultiStrategy:
    def __init__(self) -> None:
        self.lookback_periods = (50, 100, 200)

    def signal(self, candles: list[Candle], *, in_position: bool) -> str:
        max_lookback = max(self.lookback_periods)
        if len(candles) <= max_lookback:
            return "hold"

        current_close = candles[-1].close
        positive_returns = 0

        for lookback_period in self.lookback_periods:
            past_close = candles[-1 - lookback_period].close
            if past_close <= 0.0:
                return "hold"

            past_return = (current_close / past_close) - 1.0
            if past_return > 0.0:
                positive_returns += 1

        if not in_position and positive_returns >= 2:
            return "buy"
        if in_position and positive_returns < 2:
            return "sell"
        return "hold"
