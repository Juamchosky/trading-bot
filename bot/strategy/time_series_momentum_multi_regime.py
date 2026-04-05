from __future__ import annotations

from bot.models import Candle


class TimeSeriesMomentumMultiRegimeStrategy:
    def __init__(self, *, min_abs_regime_return: float = 0.03) -> None:
        self.lookback_periods = (50, 100, 200)
        self.regime_lookback_period = 200
        self.min_abs_regime_return = min_abs_regime_return

    def signal(self, candles: list[Candle], *, in_position: bool) -> str:
        max_lookback = max(self.lookback_periods)
        if len(candles) <= max_lookback:
            return "hold"

        current_close = candles[-1].close
        regime_past_close = candles[-1 - self.regime_lookback_period].close
        if regime_past_close <= 0.0:
            return "hold"

        r200 = (current_close / regime_past_close) - 1.0
        if abs(r200) < self.min_abs_regime_return:
            return "hold"

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
