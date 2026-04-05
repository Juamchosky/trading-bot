from __future__ import annotations

from bot.models import Candle


class CompressionBreakoutStrategy:
    def __init__(self) -> None:
        self.compression_window = 20
        self.max_box_range_pct = 3.0
        self.last_box_low = 0.0

    def signal(self, candles: list[Candle], *, in_position: bool) -> str:
        if in_position:
            return "hold"
        if len(candles) < self.compression_window + 1:
            return "hold"

        current_candle = candles[-1]
        previous_box_candles = candles[-(self.compression_window + 1) : -1]
        box_high = max(candle.high for candle in previous_box_candles)
        box_low = min(candle.low for candle in previous_box_candles)

        if box_low <= 0.0:
            return "hold"

        box_range_pct = ((box_high - box_low) / box_low) * 100.0
        if box_range_pct > self.max_box_range_pct:
            return "hold"

        if current_candle.close > box_high and current_candle.close > current_candle.open:
            self.last_box_low = box_low
            return "buy"

        return "hold"

    def initial_stop_price(self) -> float:
        if self.last_box_low <= 0.0:
            raise ValueError("No hay box_low valido para calcular stop inicial.")
        return self.last_box_low
