from __future__ import annotations

from math import sqrt

from bot.models import Candle


class MeanReversionZScoreStrategy:
    def __init__(
        self,
        *,
        window: int = 20,
        entry_zscore: float = -2.0,
        exit_zscore: float = 0.0,
    ) -> None:
        if window <= 1:
            raise ValueError("window debe ser mayor a 1 para calcular STD.")
        self.window = window
        self.entry_zscore = entry_zscore
        self.exit_zscore = exit_zscore
        self.last_sma = 0.0
        self.last_std = 0.0
        self.last_zscore = 0.0

    def signal(self, candles: list[Candle], *, in_position: bool) -> str:
        regime_window = 50
        regime_slope_lookback = 10
        bull_persistence_bars = 5
        if len(candles) < regime_window + regime_slope_lookback:
            return "hold"

        regime_closes = [candle.close for candle in candles]
        sma50 = sum(regime_closes[-regime_window:]) / regime_window
        sma50_prev = (
            sum(
                regime_closes[
                    -(regime_window + regime_slope_lookback) : -regime_slope_lookback
                ]
            )
            / regime_window
        )
        bull_regime = sma50 > sma50_prev

        bull_regime_count = 0
        for end_index in range(len(regime_closes), regime_window + regime_slope_lookback - 1, -1):
            current_sma = sum(regime_closes[end_index - regime_window : end_index]) / regime_window
            previous_sma = (
                sum(
                    regime_closes[
                        end_index - (regime_window + regime_slope_lookback) : end_index - regime_slope_lookback
                    ]
                )
                / regime_window
            )
            if current_sma > previous_sma:
                bull_regime_count += 1
                continue
            break

        effective_bull_regime = bull_regime and bull_regime_count >= bull_persistence_bars
        active_entry_zscore = self.entry_zscore if effective_bull_regime else -3.5
        active_exit_zscore = self.exit_zscore if effective_bull_regime else -1.0

        if len(candles) < self.window + 1:
            self.last_sma = 0.0
            self.last_std = 0.0
            self.last_zscore = 0.0
            return "hold"

        closes = [candle.close for candle in candles[-self.window :]]
        self.last_sma = sum(closes) / self.window
        variance = sum((close - self.last_sma) ** 2 for close in closes) / self.window
        self.last_std = sqrt(variance)

        if self.last_std <= 0.0:
            self.last_zscore = 0.0
            return "hold"

        self.last_zscore = (candles[-1].close - self.last_sma) / self.last_std
        previous_window_closes = [candle.close for candle in candles[-(self.window + 1) : -1]]
        previous_sma = sum(previous_window_closes) / self.window
        previous_variance = (
            sum((close - previous_sma) ** 2 for close in previous_window_closes) / self.window
        )
        previous_std = sqrt(previous_variance)
        previous_zscore = (
            0.0
            if previous_std <= 0.0
            else (candles[-2].close - previous_sma) / previous_std
        )

        if (
            not in_position
            and self.last_zscore < active_entry_zscore
            and previous_zscore >= active_entry_zscore
        ):
            return "buy"
        if in_position and self.last_zscore >= active_exit_zscore:
            return "sell"
        return "hold"
