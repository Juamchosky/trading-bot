from bot.config import SimulationConfig
from bot.execution.paper_broker import PaperBroker
from bot.market.simulator import generate_candles
from bot.models import SimulationResult
from bot.strategy.sma_cross import SMACrossStrategy


def run_simulation(config: SimulationConfig) -> SimulationResult:
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
    broker = PaperBroker(cash=config.initial_balance, fee_rate=config.fee_rate)
    closes: list[float] = []
    closed_trade_pnls: list[float] = []
    total_trades = 0

    for candle in candles:
        if broker.position_qty > 0:
            stop_loss_price = broker.entry_price * (1.0 - config.stop_loss_pct)
            if candle.close <= stop_loss_price:
                trade = broker.sell_all(candle.close)
                if trade is not None:
                    total_trades += 1
                    closed_trade_pnls.append(trade.pnl)

        closes.append(candle.close)
        signal = strategy.signal(closes)
        if signal == "buy":
            trade = broker.buy_all(candle.close)
            if trade is not None:
                total_trades += 1
        elif signal == "sell":
            trade = broker.sell_all(candle.close)
            if trade is not None:
                total_trades += 1
                closed_trade_pnls.append(trade.pnl)

    last_price = candles[-1].close
    if broker.position_qty > 0:
        # Force close for final accounting.
        trade = broker.sell_all(last_price)
        if trade is not None:
            total_trades += 1
            closed_trade_pnls.append(trade.pnl)

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
