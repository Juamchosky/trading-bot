from __future__ import annotations

from bot.models import Candle


class TrendCompressionExpansionStrategy:
    def __init__(self) -> None:
        self.trend_window = 50
        self.trend_slope_lookback = 10
        self.compression_window = 5
        self.max_compression_range_pct = 1.2
        self.min_body_pct = 0.5
        self.last_stop_price = 0.0

    def signal(self, candles: list[Candle], *, in_position: bool) -> str:
        if in_position:
            return "hold"
        if len(candles) < self.trend_window + self.trend_slope_lookback:
            return "hold"

        current_candle = candles[-1]
        if current_candle.open <= 0.0:
            return "hold"

        closes = [candle.close for candle in candles]
        sma50_current = _simple_moving_average(closes[-self.trend_window :])
        sma50_previous = _simple_moving_average(
            closes[
                -(self.trend_window + self.trend_slope_lookback) : -self.trend_slope_lookback
            ]
        )

        compression_candles = candles[-(self.compression_window + 1) : -1]
        compression_high = max(candle.high for candle in compression_candles)
        compression_low = min(candle.low for candle in compression_candles)
        if compression_low <= 0.0:
            return "hold"

        compression_range_pct = (
            (compression_high - compression_low) / compression_low
        ) * 100.0
        body_pct = (
            (current_candle.close - current_candle.open) / current_candle.open
        ) * 100.0

        trend_context_ok = (
            current_candle.close > sma50_current
            and sma50_current > sma50_previous
        )
        compression_ok = compression_range_pct <= self.max_compression_range_pct
        trigger_ok = (
            current_candle.close > compression_high
            and current_candle.close > current_candle.open
            and body_pct >= self.min_body_pct
        )
        stop_ok = compression_low < current_candle.close

        if trend_context_ok and compression_ok and trigger_ok and stop_ok:
            self.last_stop_price = compression_low
            return "buy"

        return "hold"

    def initial_stop_price(self) -> float:
        if self.last_stop_price <= 0.0:
            raise ValueError(
                "No hay stop valido para la entrada trend compression expansion."
            )
        return self.last_stop_price


def _simple_moving_average(values: list[float]) -> float:
    return sum(values) / len(values)
