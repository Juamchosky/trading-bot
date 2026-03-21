from dataclasses import dataclass


@dataclass(frozen=True)
class SimulationConfig:
    symbol: str = "BTCUSDT"
    initial_balance: float = 10_000.0
    fee_rate: float = 0.001
    candle_count: int = 300
    starting_price: float = 30_000.0
    volatility: float = 0.01
    random_seed: int = 5
    short_window: int = 10
    long_window: int = 15
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    position_size_pct: float = 0.25
