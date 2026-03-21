class SMACrossStrategy:
    def __init__(
        self,
        short_window: int,
        long_window: int,
        trend_filter_enabled: bool = False,
        trend_window: int = 50,
    ) -> None:
        if short_window >= long_window:
            raise ValueError("short_window debe ser menor que long_window")
        if trend_window <= 0:
            raise ValueError("trend_window debe ser mayor que cero")
        self.short_window = short_window
        self.long_window = long_window
        self.trend_filter_enabled = trend_filter_enabled
        self.trend_window = trend_window

    def signal(self, closes: list[float]) -> str:
        if len(closes) < self.long_window:
            return "hold"

        short_sma = sum(closes[-self.short_window :]) / self.short_window
        long_sma = sum(closes[-self.long_window :]) / self.long_window
        trend_sma = None
        current_close = closes[-1]

        if self.trend_filter_enabled:
            if len(closes) < self.trend_window:
                return "hold"
            trend_sma = sum(closes[-self.trend_window :]) / self.trend_window

        if short_sma > long_sma:
            if self.trend_filter_enabled and current_close <= trend_sma:
                return "hold"
            return "buy"
        if short_sma < long_sma:
            return "sell"
        return "hold"
