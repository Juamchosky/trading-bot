from dataclasses import dataclass
from typing import Literal


ExecutionMode = Literal["paper", "binance_testnet"]
MarketDataMode = Literal["simulated", "binance_historical"]


@dataclass(frozen=True)
class SimulationConfig:
    symbol: str = "BTCUSDT"
    initial_balance: float = 10_000.0
    fee_rate: float = 0.001
    market_data_mode: MarketDataMode = "simulated"
    candle_count: int = 300
    starting_price: float = 30_000.0
    volatility: float = 0.01
    random_seed: int = 5
    binance_spot_base_url: str = "https://api.binance.com"
    binance_interval: str = "1h"
    short_window: int = 8
    long_window: int = 20
    trend_filter_enabled: bool = False
    trend_window: int = 50
    volatility_filter_enabled: bool = False
    volatility_window: int = 20
    min_volatility_pct: float = 0.30
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.05
    position_size_pct: float = 0.20
    execution_mode: ExecutionMode = "paper"
    binance_test_order_qty: str = "0.001"


@dataclass(frozen=True)
class BinanceExecutionConfig:
    base_url: str = "https://testnet.binance.vision"
    live_trading_enabled: bool = False
    allowed_symbols: tuple[str, ...] = ("BTCUSDT",)
    max_order_size: float = 0.01
    recv_window_ms: int = 5_000
