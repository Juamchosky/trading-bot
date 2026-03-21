class SMACrossStrategy:
    def __init__(self, short_window: int, long_window: int) -> None:
        if short_window >= long_window:
            raise ValueError("short_window debe ser menor que long_window")
        self.short_window = short_window
        self.long_window = long_window

    def signal(self, closes: list[float]) -> str:
        if len(closes) < self.long_window:
            return "hold"

        short_sma = sum(closes[-self.short_window :]) / self.short_window
        long_sma = sum(closes[-self.long_window :]) / self.long_window

        if short_sma > long_sma:
            return "buy"
        if short_sma < long_sma:
            return "sell"
        return "hold"

