class SMACrossStrategy:
    def __init__(
        self,
        short_window: int,
        long_window: int,
        trend_filter_enabled: bool = False,
        trend_window: int = 50,
        trend_slope_filter_enabled: bool = False,
        trend_slope_lookback: int = 3,
        volatility_filter_enabled: bool = False,
        volatility_window: int = 20,
        min_volatility_pct: float = 0.30,
        regime_filter_enabled: bool = False,
        regime_window: int = 50,
        min_regime_range_pct: float = 1.5,
        signal_confirmation_bars: int = 0,
        warmup_bars: int = 0,
    ) -> None:
        if short_window >= long_window:
            raise ValueError("short_window debe ser menor que long_window")
        if trend_window <= 0:
            raise ValueError("trend_window debe ser mayor que cero")
        if trend_slope_lookback <= 0:
            raise ValueError("trend_slope_lookback debe ser mayor que cero")
        if volatility_window <= 1:
            raise ValueError("volatility_window debe ser mayor que 1")
        if min_volatility_pct < 0:
            raise ValueError("min_volatility_pct no puede ser negativo")
        if regime_window <= 0:
            raise ValueError("regime_window debe ser mayor que cero")
        if min_regime_range_pct < 0:
            raise ValueError("min_regime_range_pct no puede ser negativo")
        if signal_confirmation_bars < 0:
            raise ValueError("signal_confirmation_bars no puede ser negativo")
        if warmup_bars < 0:
            raise ValueError("warmup_bars no puede ser negativo")
        self.short_window = short_window
        self.long_window = long_window
        self.trend_filter_enabled = trend_filter_enabled
        self.trend_window = trend_window
        self.trend_slope_filter_enabled = trend_slope_filter_enabled
        self.trend_slope_lookback = trend_slope_lookback
        self.volatility_filter_enabled = volatility_filter_enabled
        self.volatility_window = volatility_window
        self.min_volatility_pct = min_volatility_pct
        self.regime_filter_enabled = regime_filter_enabled
        self.regime_window = regime_window
        self.min_regime_range_pct = min_regime_range_pct
        self.signal_confirmation_bars = signal_confirmation_bars
        self.warmup_bars = warmup_bars

    def signal(self, closes: list[float]) -> str:
        if len(closes) <= self.warmup_bars:
            return "hold"
        if len(closes) < self.long_window:
            return "hold"

        short_sma = sum(closes[-self.short_window :]) / self.short_window
        long_sma = sum(closes[-self.long_window :]) / self.long_window
        trend_sma = None
        long_sma_past = None
        long_cross_confirmed = True
        current_close = closes[-1]

        if self.trend_filter_enabled:
            if len(closes) < self.trend_window:
                return "hold"
            trend_sma = sum(closes[-self.trend_window :]) / self.trend_window

        if self.trend_slope_filter_enabled:
            if len(closes) < (self.long_window + self.trend_slope_lookback):
                return "hold"
            long_sma_past = (
                sum(
                    closes[
                        -self.long_window
                        - self.trend_slope_lookback : -self.trend_slope_lookback
                    ]
                )
                / self.long_window
            )

        if self.signal_confirmation_bars > 0:
            required_closes = (
                max(self.short_window, self.long_window) + self.signal_confirmation_bars
            )
            if len(closes) < required_closes:
                return "hold"
            long_cross_confirmed = _cross_persisted(
                closes,
                short_window=self.short_window,
                long_window=self.long_window,
                confirmation_bars=self.signal_confirmation_bars,
            )

        if short_sma > long_sma:
            if not long_cross_confirmed:
                return "hold"
            if self.trend_filter_enabled and trend_sma is not None and current_close <= trend_sma:
                return "hold"
            if (
                self.trend_slope_filter_enabled
                and long_sma_past is not None
                and long_sma <= long_sma_past
            ):
                return "hold"
            if self.volatility_filter_enabled:
                if len(closes) < self.volatility_window:
                    return "hold"
                recent_closes = closes[-self.volatility_window :]
                volatility_pct = _average_abs_return_pct(recent_closes)
                if volatility_pct < self.min_volatility_pct:
                    return "hold"
            if self.regime_filter_enabled:
                if len(closes) < self.regime_window:
                    return "hold"
                recent_closes = closes[-self.regime_window :]
                regime_range_pct = _close_range_pct(recent_closes)
                if regime_range_pct < self.min_regime_range_pct:
                    return "hold"
            return "buy"
        if short_sma < long_sma:
            return "sell"
        return "hold"


def _average_abs_return_pct(closes: list[float]) -> float:
    if len(closes) < 2:
        return 0.0

    abs_returns_pct: list[float] = []
    for previous_close, current_close in zip(closes[:-1], closes[1:]):
        if previous_close <= 0:
            continue
        abs_return_pct = abs((current_close - previous_close) / previous_close) * 100.0
        abs_returns_pct.append(abs_return_pct)

    if not abs_returns_pct:
        return 0.0
    return sum(abs_returns_pct) / len(abs_returns_pct)


def _close_range_pct(closes: list[float]) -> float:
    if not closes:
        return 0.0

    min_close = min(closes)
    if min_close <= 0:
        return 0.0

    max_close = max(closes)
    return ((max_close - min_close) / min_close) * 100.0


def _cross_persisted(
    closes: list[float],
    *,
    short_window: int,
    long_window: int,
    confirmation_bars: int,
) -> bool:
    for bars_ago in range(confirmation_bars + 1):
        end_index = len(closes) - bars_ago
        if end_index < long_window:
            return False
        window_closes = closes[:end_index]
        short_sma = sum(window_closes[-short_window:]) / short_window
        long_sma = sum(window_closes[-long_window:]) / long_window
        if short_sma <= long_sma:
            return False
    return True
