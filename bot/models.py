from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    index: int = 0


@dataclass
class Trade:
    side: str
    price: float
    quantity: float
    pnl: float = 0.0


@dataclass(frozen=True)
class BacktestTrade:
    entry_timestamp: int
    exit_timestamp: int
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    exit_reason: str


@dataclass(frozen=True)
class SimulationResult:
    initial_balance: float
    final_balance: float
    return_pct: float
    total_trades: int
    win_rate_pct: float
    trades: list[BacktestTrade]
