from __future__ import annotations

from bot.models import Candle


class TrendPullbackReclaimStrategy:
    def __init__(self) -> None:
        self.trend_window = 50
        self.trend_slope_lookback = 10
        self.swing_lookback = 3
        self.last_stop_price = 0.0

    def signal(self, candles: list[Candle], *, in_position: bool) -> str:
        if in_position:
            return "hold"
        if len(candles) < self.trend_window + self.trend_slope_lookback:
            return "hold"

        closes = [candle.close for candle in candles]
        current_close = candles[-1].close
        previous_high = candles[-2].high

        sma50_current = _simple_moving_average(closes[-self.trend_window :])
        sma50_previous = _simple_moving_average(
            closes[
                -(self.trend_window + self.trend_slope_lookback) : -self.trend_slope_lookback
            ]
        )
        swing_low = min(
            candle.low
            for candle in candles[-(self.swing_lookback + 1) : -1]
        )

        trend_context_ok = (
            current_close > sma50_current
            and sma50_current > sma50_previous
        )
        trigger_ok = current_close > previous_high
        stop_ok = swing_low < current_close

        if trend_context_ok and trigger_ok and stop_ok:
            self.last_stop_price = swing_low
            return "buy"

        return "hold"

    def initial_stop_price(self) -> float:
        if self.last_stop_price <= 0.0:
            raise ValueError("No hay stop valido para la entrada trend pullback reclaim.")
        return self.last_stop_price


def _simple_moving_average(values: list[float]) -> float:
    return sum(values) / len(values)
