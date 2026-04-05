from __future__ import annotations

from bot.models import Candle


class TrendBreakoutStrategy:
    def __init__(self) -> None:
        self.trend_window = 50
        self.trend_slope_lookback = 10
        self.breakout_lookback = 10
        self.last_stop_price = 0.0

    def signal(self, candles: list[Candle], *, in_position: bool) -> str:
        if in_position:
            return "hold"
        if len(candles) < self.trend_window + self.trend_slope_lookback:
            return "hold"

        current_candle = candles[-1]
        closes = [candle.close for candle in candles]

        current_sma_start_index = len(closes) - self.trend_window
        current_sma_end_index = len(closes)
        previous_sma_start_index = (
            len(closes) - self.trend_slope_lookback - self.trend_window
        )
        previous_sma_end_index = len(closes) - self.trend_slope_lookback

        sma50_current = _simple_moving_average(
            closes[current_sma_start_index:current_sma_end_index]
        )
        sma50_previous = _simple_moving_average(
            closes[previous_sma_start_index:previous_sma_end_index]
        )

        previous_breakout_candles = candles[-(self.breakout_lookback + 1) : -1]
        breakout_high = max(candle.high for candle in previous_breakout_candles)
        stop_price = min(candle.low for candle in previous_breakout_candles)

        trend_context_ok = (
            current_candle.close > sma50_current
            and sma50_current > sma50_previous
        )
        entry_trigger_ok = (
            current_candle.close > breakout_high
            and current_candle.close > current_candle.open
        )

        if trend_context_ok and entry_trigger_ok:
            self.last_stop_price = stop_price
            return "buy"

        return "hold"

    def initial_stop_price(self) -> float:
        if self.last_stop_price <= 0.0:
            raise ValueError("No hay stop valido para la entrada trend breakout.")
        return self.last_stop_price


def _simple_moving_average(values: list[float]) -> float:
    return sum(values) / len(values)
