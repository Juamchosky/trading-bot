from __future__ import annotations

from bot.models import Candle


class TrendInsideCompressionStrategy:
    def __init__(self) -> None:
        self.trend_window = 50
        self.trend_slope_lookback = 10
        self.last_stop_price = 0.0

    def signal(self, candles: list[Candle], *, in_position: bool) -> str:
        if in_position:
            return "hold"
        if len(candles) < self.trend_window + self.trend_slope_lookback:
            return "hold"

        closes = [candle.close for candle in candles]
        current_close = candles[-1].close
        previous_close = candles[-2].close
        mother_candle = candles[-4]

        sma50_current = _simple_moving_average(closes[-self.trend_window :])
        sma50_previous = _simple_moving_average(
            closes[
                -(self.trend_window + self.trend_slope_lookback) : -self.trend_slope_lookback
            ]
        )

        first_inside_bar = (
            candles[-3].high < mother_candle.high
            and candles[-3].low > mother_candle.low
        )
        second_inside_bar = (
            candles[-2].high < mother_candle.high
            and candles[-2].low > mother_candle.low
        )

        trend_context_ok = (
            current_close > sma50_current
            and sma50_current > sma50_previous
        )
        trigger_ok = (
            current_close > previous_close
            and current_close < mother_candle.high
        )
        stop_ok = mother_candle.low < current_close

        if (
            trend_context_ok
            and first_inside_bar
            and second_inside_bar
            and trigger_ok
            and stop_ok
        ):
            self.last_stop_price = mother_candle.low
            return "buy"

        return "hold"

    def initial_stop_price(self) -> float:
        if self.last_stop_price <= 0.0:
            raise ValueError("No hay stop valido para la entrada trend inside compression.")
        return self.last_stop_price


def _simple_moving_average(values: list[float]) -> float:
    return sum(values) / len(values)
