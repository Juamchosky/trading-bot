from __future__ import annotations

from bot.models import Candle


class TrendPullbackStrategy:
    def __init__(
        self,
        *,
        regime_sma_window: int = 50,
        regime_slope_lookback: int = 5,
        setup_ema_window: int = 20,
        ema_touch_tolerance_pct: float = 0.25,
        impulse_lookback: int = 5,
        min_impulse_return_pct: float = 1.0,
        atr_window: int = 14,
        stop_atr_multiple: float = 1.0,
    ) -> None:
        if regime_sma_window <= 0:
            raise ValueError("regime_sma_window debe ser mayor que cero")
        if regime_slope_lookback <= 0:
            raise ValueError("regime_slope_lookback debe ser mayor que cero")
        if setup_ema_window <= 0:
            raise ValueError("setup_ema_window debe ser mayor que cero")
        if ema_touch_tolerance_pct < 0:
            raise ValueError("ema_touch_tolerance_pct no puede ser negativo")
        if impulse_lookback <= 0:
            raise ValueError("impulse_lookback debe ser mayor que cero")
        if atr_window <= 0:
            raise ValueError("atr_window debe ser mayor que cero")
        if stop_atr_multiple <= 0:
            raise ValueError("stop_atr_multiple debe ser mayor que cero")

        self.regime_sma_window = regime_sma_window
        self.regime_slope_lookback = regime_slope_lookback
        self.setup_ema_window = setup_ema_window
        self.ema_touch_tolerance_pct = ema_touch_tolerance_pct
        self.impulse_lookback = impulse_lookback
        self.min_impulse_return_pct = min_impulse_return_pct
        self.atr_window = atr_window
        self.stop_atr_multiple = stop_atr_multiple
        self.last_stop_distance = 0.0

    def signal(self, candles: list[Candle], *, in_position: bool) -> str:
        if len(candles) < self._minimum_required_candles():
            return "hold"

        closes = [candle.close for candle in candles]
        current_low = candles[-1].low
        current_close = closes[-1]

        sma50 = _simple_moving_average(closes, self.regime_sma_window)
        sma50_past = _simple_moving_average(
            closes[: -self.regime_slope_lookback],
            self.regime_sma_window,
        )
        ema20_values = _exponential_moving_average_series(closes, self.setup_ema_window)
        atr14 = _average_true_range(candles, self.atr_window)

        if sma50 is None or sma50_past is None or ema20_values is None or atr14 is None:
            return "hold"

        current_ema20 = ema20_values[-1]
        self.last_stop_distance = self.stop_atr_multiple * atr14

        if in_position:
            if current_close < current_ema20:
                return "sell"
            return "hold"

        regime_ok = current_close > sma50 and sma50 > sma50_past
        ema_touch_ok = current_low <= current_ema20 and current_close >= current_ema20
        impulse_ok = _prior_return_pct(closes, self.impulse_lookback) >= self.min_impulse_return_pct

        if regime_ok and ema_touch_ok and impulse_ok:
            return "buy"
        return "hold"

    def initial_stop_price(self, entry_price: float) -> float:
        if self.last_stop_distance <= 0:
            raise ValueError("No hay ATR valido para calcular stop inicial.")
        return entry_price - self.last_stop_distance

    def _minimum_required_candles(self) -> int:
        regime_required = self.regime_sma_window + self.regime_slope_lookback
        setup_required = self.setup_ema_window
        impulse_required = self.impulse_lookback + 1
        atr_required = self.atr_window + 1
        return max(regime_required, setup_required, impulse_required, atr_required)


def _simple_moving_average(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _exponential_moving_average_series(
    closes: list[float],
    window: int,
) -> list[float] | None:
    if len(closes) < window:
        return None

    alpha = 2.0 / (window + 1.0)
    ema_values: list[float] = [sum(closes[:window]) / window]

    for close in closes[window:]:
        ema_values.append((close * alpha) + (ema_values[-1] * (1.0 - alpha)))

    padded_prefix = [ema_values[0]] * (window - 1)
    return [*padded_prefix, *ema_values]


def _average_true_range(candles: list[Candle], window: int) -> float | None:
    if len(candles) < window + 1:
        return None

    true_ranges: list[float] = []
    recent_candles = candles[-(window + 1) :]
    for previous_candle, current_candle in zip(recent_candles[:-1], recent_candles[1:]):
        true_range = max(
            current_candle.high - current_candle.low,
            abs(current_candle.high - previous_candle.close),
            abs(current_candle.low - previous_candle.close),
        )
        true_ranges.append(true_range)

    if not true_ranges:
        return None
    return sum(true_ranges) / len(true_ranges)


def _prior_return_pct(closes: list[float], lookback: int) -> float:
    start_index = -(lookback + 1)
    end_index = -2
    start_close = closes[start_index]
    end_close = closes[end_index]
    if start_close == 0:
        return 0.0
    return ((end_close / start_close) - 1.0) * 100.0
