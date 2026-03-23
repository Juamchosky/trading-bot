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
from bot.utils import (
    export_backtest_summary_to_csv,
    export_backtest_trades_to_csv,
    export_equity_curve_to_csv,
)


def run_simulation(config: SimulationConfig) -> SimulationResult:
    binance_executor = _build_binance_executor(config)
    candles = _load_market_candles(config)
    strategy = SMACrossStrategy(
        short_window=config.short_window,
        long_window=config.long_window,
        trend_filter_enabled=config.trend_filter_enabled,
        trend_window=config.trend_window,
        trend_slope_filter_enabled=config.trend_slope_filter_enabled,
        trend_slope_lookback=config.trend_slope_lookback,
        volatility_filter_enabled=config.volatility_filter_enabled,
        volatility_window=config.volatility_window,
        min_volatility_pct=config.min_volatility_pct,
        regime_filter_enabled=config.regime_filter_enabled,
        regime_window=config.regime_window,
        min_regime_volatility_pct=config.min_regime_volatility_pct,
        signal_confirmation_bars=config.signal_confirmation_bars,
        warmup_bars=config.warmup_bars,
        momentum_filter_enabled=config.momentum_filter_enabled,
        momentum_window=config.momentum_window,
        min_momentum_rsi=config.min_momentum_rsi,
        breakout_filter_enabled=config.breakout_filter_enabled,
        breakout_strict_mode=config.breakout_strict_mode,
        breakout_lookback=config.breakout_lookback,
        min_trend_strength_pct=config.min_trend_strength_pct,
    )
    broker = PaperBroker(
        cash=config.initial_balance,
        fee_rate=config.fee_rate,
        position_size_pct=config.position_size_pct,
    )
    closes: list[float] = []
    closed_trade_pnls: list[float] = []
    backtest_trades: list[BacktestTrade] = []
    equity_curve: list[tuple[int, float]] = []
    total_trades = 0
    open_position_entry_timestamp: int | None = None
    drawdown_limit_active = (
        config.execution_mode == "paper" and config.max_drawdown_limit_pct is not None
    )
    kill_switch_active = False
    equity_peak: float | None = None
    running_max_drawdown_pct = 0.0

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
        if signal == "buy" and not kill_switch_active:
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

        current_equity = broker.equity(candle.close)
        _upsert_equity_point(equity_curve, candle.timestamp, current_equity)
        if drawdown_limit_active:
            _, equity_peak, running_max_drawdown_pct = _update_drawdown_tracking(
                current_equity,
                equity_peak=equity_peak,
                running_max_drawdown_pct=running_max_drawdown_pct,
            )
            if running_max_drawdown_pct >= config.max_drawdown_limit_pct:
                kill_switch_active = True

    last_price = candles[-1].close if candles else config.starting_price
    if candles and broker.position_qty > 0:
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
    if candles:
        _upsert_equity_point(equity_curve, candles[-1].timestamp, final_balance)

    max_drawdown_pct = _calculate_max_drawdown_pct(equity_curve)

    return_pct = ((final_balance / config.initial_balance) - 1.0) * 100.0
    metrics = _calculate_closed_trade_metrics(closed_trade_pnls)

    result = SimulationResult(
        initial_balance=config.initial_balance,
        final_balance=final_balance,
        return_pct=return_pct,
        total_trades=total_trades,
        win_rate_pct=metrics["win_rate_pct"],
        closed_trades=metrics["closed_trades"],
        avg_pnl=metrics["avg_pnl"],
        best_trade_pnl=metrics["best_trade_pnl"],
        worst_trade_pnl=metrics["worst_trade_pnl"],
        profit_factor=metrics["profit_factor"],
        avg_win_pnl=metrics["avg_win_pnl"],
        avg_loss_pnl=metrics["avg_loss_pnl"],
        trades=backtest_trades,
        max_drawdown_pct=max_drawdown_pct,
        equity_curve=equity_curve,
    )
    export_backtest_trades_to_csv(result.trades)
    export_backtest_summary_to_csv(config, result)
    export_equity_curve_to_csv(result.equity_curve)
    return result


def _upsert_equity_point(
    equity_curve: list[tuple[int, float]],
    timestamp: int,
    equity: float,
) -> None:
    if not equity_curve or equity_curve[-1][0] != timestamp:
        equity_curve.append((timestamp, equity))
        return

    equity_curve[-1] = (timestamp, equity)


def _calculate_max_drawdown_pct(equity_curve: list[tuple[int, float]]) -> float:
    equity_peak: float | None = None
    max_drawdown_pct = 0.0

    for _, equity in equity_curve:
        if equity_peak is None or equity > equity_peak:
            equity_peak = equity
            continue

        if equity_peak <= 0:
            continue

        drawdown_pct = ((equity_peak - equity) / equity_peak) * 100.0
        if drawdown_pct > max_drawdown_pct:
            max_drawdown_pct = drawdown_pct

    return max_drawdown_pct


def _update_drawdown_tracking(
    equity: float,
    *,
    equity_peak: float | None,
    running_max_drawdown_pct: float,
) -> tuple[float, float | None, float]:
    if equity_peak is None or equity > equity_peak:
        return 0.0, equity, running_max_drawdown_pct

    if equity_peak <= 0:
        return 0.0, equity_peak, running_max_drawdown_pct

    drawdown_pct = ((equity_peak - equity) / equity_peak) * 100.0
    if drawdown_pct > running_max_drawdown_pct:
        running_max_drawdown_pct = drawdown_pct

    return drawdown_pct, equity_peak, running_max_drawdown_pct


def _calculate_closed_trade_metrics(closed_trade_pnls: list[float]) -> dict[str, float | int]:
    closed_trades = len(closed_trade_pnls)
    if closed_trades == 0:
        return {
            "closed_trades": 0,
            "win_rate_pct": 0.0,
            "avg_pnl": 0.0,
            "best_trade_pnl": 0.0,
            "worst_trade_pnl": 0.0,
            "profit_factor": 0.0,
            "avg_win_pnl": 0.0,
            "avg_loss_pnl": 0.0,
        }

    winning_pnls = [pnl for pnl in closed_trade_pnls if pnl > 0]
    losing_pnls = [pnl for pnl in closed_trade_pnls if pnl < 0]
    gross_profit = sum(winning_pnls)
    gross_loss_abs = abs(sum(losing_pnls))

    if gross_loss_abs == 0:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss_abs

    return {
        "closed_trades": closed_trades,
        "win_rate_pct": (len(winning_pnls) / closed_trades) * 100.0,
        "avg_pnl": sum(closed_trade_pnls) / closed_trades,
        "best_trade_pnl": max(closed_trade_pnls),
        "worst_trade_pnl": min(closed_trade_pnls),
        "profit_factor": profit_factor,
        "avg_win_pnl": (sum(winning_pnls) / len(winning_pnls)) if winning_pnls else 0.0,
        "avg_loss_pnl": (sum(losing_pnls) / len(losing_pnls)) if losing_pnls else 0.0,
    }


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
                historical_offset=config.historical_offset,
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
