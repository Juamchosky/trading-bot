from bot.config import BinanceExecutionConfig, SimulationConfig
from bot.execution.binance_executor import (
    BinanceExecutionError,
    BinanceExecutor,
    BinanceOrderRequest,
)
from bot.execution.paper_broker import PaperBroker
from bot.market.simulator import generate_candles
from bot.models import SimulationResult
from bot.strategy.sma_cross import SMACrossStrategy


def run_simulation(config: SimulationConfig) -> SimulationResult:
    binance_executor = _build_binance_executor(config)

    candles = generate_candles(
        candle_count=config.candle_count,
        start_price=config.starting_price,
        volatility=config.volatility,
        seed=config.random_seed,
    )
    strategy = SMACrossStrategy(
        short_window=config.short_window,
        long_window=config.long_window,
    )
    broker = PaperBroker(
        cash=config.initial_balance,
        fee_rate=config.fee_rate,
        position_size_pct=config.position_size_pct,
    )
    closes: list[float] = []
    closed_trade_pnls: list[float] = []
    total_trades = 0

    for candle in candles:
        if broker.position_qty > 0:
            stop_loss_price = broker.entry_price * (1.0 - config.stop_loss_pct)
            take_profit_price = broker.entry_price * (1.0 + config.take_profit_pct)
            if candle.close >= take_profit_price:
                trade = broker.sell_all(candle.close)
                if trade is not None:
                    total_trades += 1
                    closed_trade_pnls.append(trade.pnl)
                    _maybe_send_test_order(config, binance_executor, side="SELL")
            elif candle.close <= stop_loss_price:
                trade = broker.sell_all(candle.close)
                if trade is not None:
                    total_trades += 1
                    closed_trade_pnls.append(trade.pnl)
                    _maybe_send_test_order(config, binance_executor, side="SELL")

        closes.append(candle.close)
        signal = strategy.signal(closes)
        if signal == "buy":
            trade = broker.buy_all(candle.close)
            if trade is not None:
                total_trades += 1
                _maybe_send_test_order(config, binance_executor, side="BUY")
        elif signal == "sell":
            trade = broker.sell_all(candle.close)
            if trade is not None:
                total_trades += 1
                closed_trade_pnls.append(trade.pnl)
                _maybe_send_test_order(config, binance_executor, side="SELL")

    last_price = candles[-1].close
    if broker.position_qty > 0:
        # Force close for final accounting.
        trade = broker.sell_all(last_price)
        if trade is not None:
            total_trades += 1
            closed_trade_pnls.append(trade.pnl)
            _maybe_send_test_order(config, binance_executor, side="SELL")

    final_balance = broker.equity(last_price)
    return_pct = ((final_balance / config.initial_balance) - 1.0) * 100.0
    wins = sum(1 for pnl in closed_trade_pnls if pnl > 0)
    win_rate = (wins / len(closed_trade_pnls) * 100.0) if closed_trade_pnls else 0.0

    return SimulationResult(
        initial_balance=config.initial_balance,
        final_balance=final_balance,
        return_pct=return_pct,
        total_trades=total_trades,
        win_rate_pct=win_rate,
    )


def _build_binance_executor(config: SimulationConfig) -> BinanceExecutor | None:
    if config.execution_mode == "paper":
        return None
    if config.execution_mode != "binance_testnet":
        raise ValueError(f"Unsupported execution_mode: {config.execution_mode}")

    # Safety guard: this engine only supports Binance Spot Testnet test orders.
    binance_config = BinanceExecutionConfig()
    if binance_config.live_trading_enabled:
        raise ValueError("Live trading must remain disabled for binance_testnet mode.")

    return BinanceExecutor(
        base_url=binance_config.base_url,
        live_trading_enabled=False,
        allowed_symbols=binance_config.allowed_symbols,
        max_order_size=binance_config.max_order_size,
        recv_window_ms=binance_config.recv_window_ms,
    )


def _maybe_send_test_order(
    config: SimulationConfig,
    executor: BinanceExecutor | None,
    *,
    side: str,
) -> None:
    if executor is None:
        return

    print(f"[Binance] TEST ORDER -> {side} {config.symbol}")

    try:
        response = executor.test_order(
            BinanceOrderRequest(
                symbol=config.symbol,
                side=side,
                order_type="MARKET",
                quantity=config.binance_test_order_qty,
            )
        )
        print(f"[Binance] OK -> {response}")

    except BinanceExecutionError as exc:
        print(f"[Binance] ERROR -> {exc}")
