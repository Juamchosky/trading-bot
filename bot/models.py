from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    index: int
    close: float


@dataclass
class Trade:
    side: str
    price: float
    quantity: float
    pnl: float = 0.0


@dataclass(frozen=True)
class SimulationResult:
    initial_balance: float
    final_balance: float
    return_pct: float
    total_trades: int
    win_rate_pct: float

