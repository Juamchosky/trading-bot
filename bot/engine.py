from bot.config import BinanceExecutionConfig, SimulationConfig
from bot.execution.binance_executor import (
    BinanceExecutionError,
    BinanceExecutor,
    BinanceOrderRequest,
)
from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.execution.paper_broker import PaperBroker
from bot.market.simulator import generate_candles
from bot.models import BacktestTrade, Candle, SimulationResult
from bot.strategy.sma_cross import SMACrossStrategy
from bot.utils import export_backtest_trades_to_csv


def run_simulation(config: SimulationConfig) -> SimulationResult:
    binance_executor = _build_binance_executor(config)
    candles = _load_market_candles(config)
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
    backtest_trades: list[BacktestTrade] = []
    total_trades = 0
    open_position_entry_timestamp: int | None = None

    for candle in candles:
        if broker.position_qty > 0:
            stop_loss_price = broker.entry_price * (1.0 - config.stop_loss_pct)
            take_profit_price = broker.entry_price * (1.0 + config.take_profit_pct)
            if candle.low <= stop_loss_price:
                entry_price = broker.entry_price
                trade = broker.sell_all(stop_loss_price)
                if trade is not None:
                    total_trades += 1
                    closed_trade_pnls.append(trade.pnl)
                    backtest_trades.append(
                        _build_backtest_trade(
                            entry_timestamp=open_position_entry_timestamp,
                            exit_timestamp=candle.timestamp,
                            side="long",
                            entry_price=entry_price,
                            exit_price=trade.price,
                            quantity=trade.quantity,
                            pnl=trade.pnl,
                            exit_reason="stop_loss",
                        )
                    )
                    open_position_entry_timestamp = None
                    _maybe_send_test_order(config, binance_executor, side="SELL")
            elif candle.high >= take_profit_price:
                entry_price = broker.entry_price
                trade = broker.sell_all(take_profit_price)
                if trade is not None:
                    total_trades += 1
                    closed_trade_pnls.append(trade.pnl)
                    backtest_trades.append(
                        _build_backtest_trade(
                            entry_timestamp=open_position_entry_timestamp,
                            exit_timestamp=candle.timestamp,
                            side="long",
                            entry_price=entry_price,
                            exit_price=trade.price,
                            quantity=trade.quantity,
                            pnl=trade.pnl,
                            exit_reason="take_profit",
                        )
                    )
                    open_position_entry_timestamp = None
                    _maybe_send_test_order(config, binance_executor, side="SELL")

        closes.append(candle.close)
        signal = strategy.signal(closes)
        if signal == "buy":
            trade = broker.buy_all(candle.close)
            if trade is not None:
                total_trades += 1
                open_position_entry_timestamp = candle.timestamp
                _maybe_send_test_order(config, binance_executor, side="BUY")
        elif signal == "sell":
            entry_price = broker.entry_price
            trade = broker.sell_all(candle.close)
            if trade is not None:
                total_trades += 1
                closed_trade_pnls.append(trade.pnl)
                backtest_trades.append(
                    _build_backtest_trade(
                        entry_timestamp=open_position_entry_timestamp,
                        exit_timestamp=candle.timestamp,
                        side="long",
                        entry_price=entry_price,
                        exit_price=trade.price,
                        quantity=trade.quantity,
                        pnl=trade.pnl,
                        exit_reason="signal",
                    )
                )
                open_position_entry_timestamp = None
                _maybe_send_test_order(config, binance_executor, side="SELL")

    last_price = candles[-1].close
    if broker.position_qty > 0:
        # Force close for final accounting.
        entry_price = broker.entry_price
        trade = broker.sell_all(last_price)
        if trade is not None:
            total_trades += 1
            closed_trade_pnls.append(trade.pnl)
            backtest_trades.append(
                _build_backtest_trade(
                    entry_timestamp=open_position_entry_timestamp,
                    exit_timestamp=candles[-1].timestamp,
                    side="long",
                    entry_price=entry_price,
                    exit_price=trade.price,
                    quantity=trade.quantity,
                    pnl=trade.pnl,
                    exit_reason="forced_close",
                )
            )
            open_position_entry_timestamp = None
            _maybe_send_test_order(config, binance_executor, side="SELL")

    final_balance = broker.equity(last_price)
    return_pct = ((final_balance / config.initial_balance) - 1.0) * 100.0
    wins = sum(1 for pnl in closed_trade_pnls if pnl > 0)
    win_rate = (wins / len(closed_trade_pnls) * 100.0) if closed_trade_pnls else 0.0

    result = SimulationResult(
        initial_balance=config.initial_balance,
        final_balance=final_balance,
        return_pct=return_pct,
        total_trades=total_trades,
        win_rate_pct=win_rate,
        trades=backtest_trades,
    )
    export_backtest_trades_to_csv(result.trades)
    return result


def _build_backtest_trade(
    *,
    entry_timestamp: int | None,
    exit_timestamp: int,
    side: str,
    entry_price: float,
    exit_price: float,
    quantity: float,
    pnl: float,
    exit_reason: str,
) -> BacktestTrade:
    if entry_timestamp is None:
        raise ValueError("Backtest trade close detected without a matching entry timestamp.")

    return BacktestTrade(
        entry_timestamp=entry_timestamp,
        exit_timestamp=exit_timestamp,
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        pnl=pnl,
        exit_reason=exit_reason,
    )


def _load_market_candles(config: SimulationConfig) -> list[Candle]:
    if config.market_data_mode == "simulated":
        return generate_candles(
            candle_count=config.candle_count,
            start_price=config.starting_price,
            volatility=config.volatility,
            seed=config.random_seed,
        )

    if config.market_data_mode == "binance_historical":
        try:
            return fetch_historical_candles(
                symbol=config.symbol,
                interval=config.binance_interval,
                limit=config.candle_count,
                base_url=config.binance_spot_base_url,
            )
        except BinanceMarketDataError as exc:
            raise ValueError(f"Failed to load Binance historical candles: {exc}") from exc

    raise ValueError(f"Unsupported market_data_mode: {config.market_data_mode}")


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
