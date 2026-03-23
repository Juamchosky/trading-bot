from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from bot.config import SimulationConfig
from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.models import BacktestTrade, Candle, SimulationResult, Trade
from bot.strategy.sma_cross import SMACrossStrategy


SUMMARY_OUTPUT_PATH = Path("live_paper_summary.csv")
EQUITY_OUTPUT_PATH = Path("live_paper_equity_curve.csv")

BASE_CONFIG = SimulationConfig(
    execution_mode="paper",
    market_data_mode="binance_historical",
    symbol="BTCUSDT",
    short_window=5,
    long_window=20,
    stop_loss_pct=0.01,
    take_profit_pct=0.05,
    position_size_pct=0.5,
    max_drawdown_limit_pct=1.5,
    trend_filter_enabled=True,
    trend_window=50,
    trend_slope_filter_enabled=True,
    trend_slope_lookback=3,
    volatility_filter_enabled=False,
    regime_filter_enabled=False,
    warmup_bars=0,
)

CONFIG_VARIANTS: dict[str, dict[str, int | float]] = {
    "CONFIG_A": {
        "short_window": 5,
        "long_window": 20,
        "stop_loss_pct": 0.01,
        "take_profit_pct": 0.05,
        "signal_confirmation_bars": 0,
    },
    "CONFIG_B": {
        "short_window": 5,
        "long_window": 20,
        "stop_loss_pct": 0.01,
        "take_profit_pct": 0.05,
        "signal_confirmation_bars": 1,
    },
}


@dataclass(frozen=True)
class ModeRunResult:
    mode_name: str
    config_name: str
    symbol: str
    candle_count: int
    historical_offset: int
    fee_rate: float
    slippage_pct: float
    initial_balance: float
    result: SimulationResult
    equity_curve: list[tuple[int, float]]


@dataclass
class SlippagePaperBroker:
    cash: float
    fee_rate: float
    position_size_pct: float
    slippage_pct: float
    position_qty: float = 0.0
    entry_price: float = 0.0

    def buy_all(self, market_price: float) -> Trade | None:
        if self.position_qty > 0.0 or self.cash <= 0.0:
            return None

        invest_cash = self.cash * self.position_size_pct
        if invest_cash <= 0.0:
            return None

        execution_price = market_price * (1.0 + self.slippage_pct / 100.0)
        qty = invest_cash / (execution_price * (1.0 + self.fee_rate))
        self.position_qty = qty
        self.entry_price = execution_price
        self.cash -= invest_cash
        return Trade(side="buy", price=execution_price, quantity=qty)

    def sell_all(self, market_price: float) -> Trade | None:
        if self.position_qty <= 0.0:
            return None

        execution_price = market_price * (1.0 - self.slippage_pct / 100.0)
        qty = self.position_qty
        gross_proceeds = qty * execution_price
        sell_fee = gross_proceeds * self.fee_rate
        proceeds = gross_proceeds - sell_fee
        buy_cost = qty * self.entry_price
        buy_fee = buy_cost * self.fee_rate
        pnl = proceeds - (buy_cost + buy_fee)
        self.cash += proceeds
        self.position_qty = 0.0
        self.entry_price = 0.0
        return Trade(side="sell", price=execution_price, quantity=qty, pnl=pnl)

    def equity(self, mark_price: float) -> float:
        return self.cash + (self.position_qty * mark_price)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulacion live/paper secuencial sobre datos historicos recientes."
    )
    parser.add_argument(
        "--mode",
        choices=("config_a", "config_b", "portfolio", "all"),
        default="all",
        help="Modo a ejecutar: config individual, portfolio 50/50 o todos.",
    )
    parser.add_argument(
        "--symbol",
        default=BASE_CONFIG.symbol,
        help="Par a evaluar con market_data_mode=binance_historical.",
    )
    parser.add_argument(
        "--interval",
        default=BASE_CONFIG.binance_interval,
        help="Intervalo Binance, por ejemplo 1h.",
    )
    parser.add_argument(
        "--candle-count",
        type=int,
        default=300,
        help="Cantidad fija de velas recientes a simular.",
    )
    parser.add_argument(
        "--historical-offset",
        type=int,
        default=0,
        help="Offset historico desde la vela mas reciente.",
    )
    parser.add_argument(
        "--initial-balance",
        type=float,
        default=BASE_CONFIG.initial_balance,
        help="Capital total de la simulacion.",
    )
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=BASE_CONFIG.fee_rate,
        help="Fee por operacion, reutilizando el valor del sistema.",
    )
    parser.add_argument(
        "--slippage-pct",
        type=float,
        default=0.05,
        help="Slippage simple aplicado en buy/sell como porcentaje.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=SUMMARY_OUTPUT_PATH,
        help="CSV de resumen por modo.",
    )
    parser.add_argument(
        "--equity-output",
        type=Path,
        default=EQUITY_OUTPUT_PATH,
        help="CSV de equity curve exportable.",
    )
    return parser.parse_args()


def load_candles(config: SimulationConfig) -> list[Candle]:
    if config.market_data_mode != "binance_historical":
        raise ValueError("simulate_live_paper.py requiere market_data_mode=binance_historical.")

    try:
        return fetch_historical_candles(
            symbol=config.symbol,
            interval=config.binance_interval,
            limit=config.candle_count,
            historical_offset=config.historical_offset,
            base_url=config.binance_spot_base_url,
        )
    except BinanceMarketDataError as exc:
        raise ValueError(f"No se pudieron cargar velas historicas de Binance: {exc}") from exc


def build_strategy(config: SimulationConfig) -> SMACrossStrategy:
    return SMACrossStrategy(
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


def run_live_paper_simulation(
    *,
    config: SimulationConfig,
    candles: Sequence[Candle],
    slippage_pct: float,
) -> SimulationResult:
    strategy = build_strategy(config)
    broker = SlippagePaperBroker(
        cash=config.initial_balance,
        fee_rate=config.fee_rate,
        position_size_pct=config.position_size_pct,
        slippage_pct=slippage_pct,
    )
    closes: list[float] = []
    closed_trade_pnls: list[float] = []
    backtest_trades: list[BacktestTrade] = []
    equity_curve: list[tuple[int, float]] = []
    total_trades = 0
    open_position_entry_timestamp: int | None = None
    drawdown_limit_active = config.max_drawdown_limit_pct is not None
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
                        build_backtest_trade(
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
            elif candle.high >= take_profit_price:
                entry_price = broker.entry_price
                trade = broker.sell_all(take_profit_price)
                if trade is not None:
                    total_trades += 1
                    closed_trade_pnls.append(trade.pnl)
                    backtest_trades.append(
                        build_backtest_trade(
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

        closes.append(candle.close)
        signal = strategy.signal(closes)
        if signal == "buy" and not kill_switch_active:
            trade = broker.buy_all(candle.close)
            if trade is not None:
                total_trades += 1
                open_position_entry_timestamp = candle.timestamp
        elif signal == "sell":
            entry_price = broker.entry_price
            trade = broker.sell_all(candle.close)
            if trade is not None:
                total_trades += 1
                closed_trade_pnls.append(trade.pnl)
                backtest_trades.append(
                    build_backtest_trade(
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

        current_equity = broker.equity(candle.close)
        upsert_equity_point(equity_curve, candle.timestamp, current_equity)
        if drawdown_limit_active:
            _, equity_peak, running_max_drawdown_pct = update_drawdown_tracking(
                current_equity,
                equity_peak=equity_peak,
                running_max_drawdown_pct=running_max_drawdown_pct,
            )
            if running_max_drawdown_pct >= config.max_drawdown_limit_pct:
                kill_switch_active = True

    last_price = candles[-1].close if candles else config.starting_price
    if candles and broker.position_qty > 0:
        entry_price = broker.entry_price
        trade = broker.sell_all(last_price)
        if trade is not None:
            total_trades += 1
            closed_trade_pnls.append(trade.pnl)
            backtest_trades.append(
                build_backtest_trade(
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

    final_balance = broker.equity(last_price)
    if candles:
        upsert_equity_point(equity_curve, candles[-1].timestamp, final_balance)

    max_drawdown_pct = calculate_max_drawdown_pct(equity_curve)
    metrics = calculate_closed_trade_metrics(closed_trade_pnls)

    return SimulationResult(
        initial_balance=config.initial_balance,
        final_balance=final_balance,
        return_pct=((final_balance / config.initial_balance) - 1.0) * 100.0,
        total_trades=total_trades,
        win_rate_pct=float(metrics["win_rate_pct"]),
        closed_trades=int(metrics["closed_trades"]),
        avg_pnl=float(metrics["avg_pnl"]),
        best_trade_pnl=float(metrics["best_trade_pnl"]),
        worst_trade_pnl=float(metrics["worst_trade_pnl"]),
        profit_factor=float(metrics["profit_factor"]),
        avg_win_pnl=float(metrics["avg_win_pnl"]),
        avg_loss_pnl=float(metrics["avg_loss_pnl"]),
        trades=backtest_trades,
        max_drawdown_pct=max_drawdown_pct,
        equity_curve=equity_curve,
    )


def upsert_equity_point(
    equity_curve: list[tuple[int, float]],
    timestamp: int,
    equity: float,
) -> None:
    if not equity_curve or equity_curve[-1][0] != timestamp:
        equity_curve.append((timestamp, equity))
        return
    equity_curve[-1] = (timestamp, equity)


def build_backtest_trade(
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
        raise ValueError("Cierre detectado sin timestamp de entrada asociado.")

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


def update_drawdown_tracking(
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


def calculate_max_drawdown_pct(equity_curve: Sequence[tuple[int, float]]) -> float:
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


def calculate_closed_trade_metrics(closed_trade_pnls: Sequence[float]) -> dict[str, float | int]:
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


def build_variant_config(
    variant_name: str,
    *,
    symbol: str,
    interval: str,
    candle_count: int,
    historical_offset: int,
    initial_balance: float,
    fee_rate: float,
) -> SimulationConfig:
    if variant_name not in CONFIG_VARIANTS:
        raise ValueError(f"Variant no soportada: {variant_name}")

    params = CONFIG_VARIANTS[variant_name]
    return replace(
        BASE_CONFIG,
        symbol=symbol,
        binance_interval=interval,
        candle_count=candle_count,
        historical_offset=historical_offset,
        initial_balance=initial_balance,
        fee_rate=fee_rate,
        short_window=int(params["short_window"]),
        long_window=int(params["long_window"]),
        stop_loss_pct=float(params["stop_loss_pct"]),
        take_profit_pct=float(params["take_profit_pct"]),
        signal_confirmation_bars=int(params["signal_confirmation_bars"]),
    )


def combine_equity_curves(results: Sequence[ModeRunResult]) -> list[tuple[int, float]]:
    if not results:
        return []

    lengths = {len(row.equity_curve) for row in results}
    if len(lengths) != 1:
        raise ValueError("No se pudieron combinar equity curves con longitudes distintas.")

    combined: list[tuple[int, float]] = []
    for points in zip(*(row.equity_curve for row in results)):
        timestamps = {timestamp for timestamp, _ in points}
        if len(timestamps) != 1:
            raise ValueError("No se pudieron combinar equity curves con timestamps distintos.")
        timestamp = points[0][0]
        combined_equity = sum(equity for _, equity in points)
        combined.append((timestamp, combined_equity))
    return combined


def build_mode_result(
    mode_name: str,
    config_name: str,
    config: SimulationConfig,
    result: SimulationResult,
) -> ModeRunResult:
    return ModeRunResult(
        mode_name=mode_name,
        config_name=config_name,
        symbol=config.symbol,
        candle_count=config.candle_count,
        historical_offset=config.historical_offset,
        fee_rate=config.fee_rate,
        slippage_pct=0.0,
        initial_balance=config.initial_balance,
        result=result,
        equity_curve=result.equity_curve,
    )


def export_summary_csv(rows: Sequence[ModeRunResult], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "mode_name",
                "config_name",
                "symbol",
                "candle_count",
                "historical_offset",
                "initial_balance",
                "fee_rate",
                "slippage_pct",
                "final_balance",
                "return_pct",
                "max_drawdown_pct",
                "total_trades",
                "closed_trades",
                "win_rate_pct",
                "profit_factor",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "mode_name": row.mode_name,
                    "config_name": row.config_name,
                    "symbol": row.symbol,
                    "candle_count": row.candle_count,
                    "historical_offset": row.historical_offset,
                    "initial_balance": f"{row.initial_balance:.6f}",
                    "fee_rate": f"{row.fee_rate:.6f}",
                    "slippage_pct": f"{row.slippage_pct:.6f}",
                    "final_balance": f"{row.result.final_balance:.6f}",
                    "return_pct": f"{row.result.return_pct:.6f}",
                    "max_drawdown_pct": f"{row.result.max_drawdown_pct:.6f}",
                    "total_trades": row.result.total_trades,
                    "closed_trades": row.result.closed_trades,
                    "win_rate_pct": f"{row.result.win_rate_pct:.6f}",
                    "profit_factor": format_metric(row.result.profit_factor),
                }
            )


def export_equity_curve_csv(rows: Sequence[ModeRunResult], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["mode_name", "config_name", "timestamp", "equity"],
        )
        writer.writeheader()
        for row in rows:
            for timestamp, equity in row.equity_curve:
                writer.writerow(
                    {
                        "mode_name": row.mode_name,
                        "config_name": row.config_name,
                        "timestamp": timestamp,
                        "equity": f"{equity:.6f}",
                    }
                )


def format_metric(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.6f}"


def print_console_summary(rows: Sequence[ModeRunResult]) -> None:
    print("Simulacion live/paper secuencial")
    for row in rows:
        print(f"\n{row.mode_name}")
        print(f"- config_name: {row.config_name}")
        print(f"- symbol: {row.symbol}")
        print(f"- candle_count: {row.candle_count}")
        print(f"- historical_offset: {row.historical_offset}")
        print(f"- fee_rate: {row.fee_rate:.6f}")
        print(f"- slippage_pct: {row.slippage_pct:.6f}")
        print(f"- final_balance: {row.result.final_balance:.2f}")
        print(f"- return_pct: {row.result.return_pct:.2f}%")
        print(f"- max_drawdown_pct: {row.result.max_drawdown_pct:.2f}%")
        print(f"- total_trades: {row.result.total_trades}")
        print(f"- closed_trades: {row.result.closed_trades}")
        print(f"- win_rate_pct: {row.result.win_rate_pct:.2f}%")
        print(f"- profit_factor: {format_metric(row.result.profit_factor)}")


def resolve_modes(mode: str) -> list[str]:
    if mode == "config_a":
        return ["CONFIG_A"]
    if mode == "config_b":
        return ["CONFIG_B"]
    if mode == "portfolio":
        return ["PORTFOLIO_AB"]
    return ["CONFIG_A", "CONFIG_B", "PORTFOLIO_AB"]


def main() -> None:
    args = parse_args()
    requested_modes = resolve_modes(args.mode)
    summary_rows: list[ModeRunResult] = []

    config_a = build_variant_config(
        "CONFIG_A",
        symbol=args.symbol,
        interval=args.interval,
        candle_count=args.candle_count,
        historical_offset=args.historical_offset,
        initial_balance=args.initial_balance if "PORTFOLIO_AB" not in requested_modes else args.initial_balance / 2.0,
        fee_rate=args.fee_rate,
    )
    config_b = build_variant_config(
        "CONFIG_B",
        symbol=args.symbol,
        interval=args.interval,
        candle_count=args.candle_count,
        historical_offset=args.historical_offset,
        initial_balance=args.initial_balance if "PORTFOLIO_AB" not in requested_modes else args.initial_balance / 2.0,
        fee_rate=args.fee_rate,
    )

    shared_candles = load_candles(
        replace(
            BASE_CONFIG,
            symbol=args.symbol,
            binance_interval=args.interval,
            candle_count=args.candle_count,
            historical_offset=args.historical_offset,
        )
    )

    if "CONFIG_A" in requested_modes:
        config_a_single = replace(config_a, initial_balance=args.initial_balance)
        result_a = run_live_paper_simulation(
            config=config_a_single,
            candles=shared_candles,
            slippage_pct=args.slippage_pct,
        )
        summary_rows.append(
            ModeRunResult(
                mode_name="CONFIG_A",
                config_name="CONFIG_A",
                symbol=config_a_single.symbol,
                candle_count=config_a_single.candle_count,
                historical_offset=config_a_single.historical_offset,
                fee_rate=config_a_single.fee_rate,
                slippage_pct=args.slippage_pct,
                initial_balance=config_a_single.initial_balance,
                result=result_a,
                equity_curve=result_a.equity_curve,
            )
        )

    if "CONFIG_B" in requested_modes:
        config_b_single = replace(config_b, initial_balance=args.initial_balance)
        result_b = run_live_paper_simulation(
            config=config_b_single,
            candles=shared_candles,
            slippage_pct=args.slippage_pct,
        )
        summary_rows.append(
            ModeRunResult(
                mode_name="CONFIG_B",
                config_name="CONFIG_B",
                symbol=config_b_single.symbol,
                candle_count=config_b_single.candle_count,
                historical_offset=config_b_single.historical_offset,
                fee_rate=config_b_single.fee_rate,
                slippage_pct=args.slippage_pct,
                initial_balance=config_b_single.initial_balance,
                result=result_b,
                equity_curve=result_b.equity_curve,
            )
        )

    if "PORTFOLIO_AB" in requested_modes:
        portfolio_initial_balance = args.initial_balance
        config_a_portfolio = replace(config_a, initial_balance=portfolio_initial_balance / 2.0)
        config_b_portfolio = replace(config_b, initial_balance=portfolio_initial_balance / 2.0)
        result_a_portfolio = run_live_paper_simulation(
            config=config_a_portfolio,
            candles=shared_candles,
            slippage_pct=args.slippage_pct,
        )
        result_b_portfolio = run_live_paper_simulation(
            config=config_b_portfolio,
            candles=shared_candles,
            slippage_pct=args.slippage_pct,
        )
        combined_equity_curve = combine_equity_curves(
            [
                ModeRunResult(
                    mode_name="CONFIG_A",
                    config_name="CONFIG_A",
                    symbol=config_a_portfolio.symbol,
                    candle_count=config_a_portfolio.candle_count,
                    historical_offset=config_a_portfolio.historical_offset,
                    fee_rate=config_a_portfolio.fee_rate,
                    slippage_pct=args.slippage_pct,
                    initial_balance=config_a_portfolio.initial_balance,
                    result=result_a_portfolio,
                    equity_curve=result_a_portfolio.equity_curve,
                ),
                ModeRunResult(
                    mode_name="CONFIG_B",
                    config_name="CONFIG_B",
                    symbol=config_b_portfolio.symbol,
                    candle_count=config_b_portfolio.candle_count,
                    historical_offset=config_b_portfolio.historical_offset,
                    fee_rate=config_b_portfolio.fee_rate,
                    slippage_pct=args.slippage_pct,
                    initial_balance=config_b_portfolio.initial_balance,
                    result=result_b_portfolio,
                    equity_curve=result_b_portfolio.equity_curve,
                ),
            ]
        )
        portfolio_final_balance = result_a_portfolio.final_balance + result_b_portfolio.final_balance
        portfolio_closed_pnls = [trade.pnl for trade in result_a_portfolio.trades] + [
            trade.pnl for trade in result_b_portfolio.trades
        ]
        portfolio_metrics = calculate_closed_trade_metrics(portfolio_closed_pnls)
        portfolio_result = SimulationResult(
            initial_balance=portfolio_initial_balance,
            final_balance=portfolio_final_balance,
            return_pct=((portfolio_final_balance / portfolio_initial_balance) - 1.0) * 100.0,
            total_trades=result_a_portfolio.total_trades + result_b_portfolio.total_trades,
            win_rate_pct=float(portfolio_metrics["win_rate_pct"]),
            closed_trades=int(portfolio_metrics["closed_trades"]),
            avg_pnl=float(portfolio_metrics["avg_pnl"]),
            best_trade_pnl=float(portfolio_metrics["best_trade_pnl"]),
            worst_trade_pnl=float(portfolio_metrics["worst_trade_pnl"]),
            profit_factor=float(portfolio_metrics["profit_factor"]),
            avg_win_pnl=float(portfolio_metrics["avg_win_pnl"]),
            avg_loss_pnl=float(portfolio_metrics["avg_loss_pnl"]),
            trades=[*result_a_portfolio.trades, *result_b_portfolio.trades],
            max_drawdown_pct=calculate_max_drawdown_pct(combined_equity_curve),
            equity_curve=combined_equity_curve,
        )
        summary_rows.append(
            ModeRunResult(
                mode_name="PORTFOLIO_AB",
                config_name="CONFIG_A+CONFIG_B",
                symbol=args.symbol,
                candle_count=args.candle_count,
                historical_offset=args.historical_offset,
                fee_rate=args.fee_rate,
                slippage_pct=args.slippage_pct,
                initial_balance=portfolio_initial_balance,
                result=portfolio_result,
                equity_curve=combined_equity_curve,
            )
        )

    export_summary_csv(summary_rows, args.summary_output)
    export_equity_curve_csv(summary_rows, args.equity_output)
    print_console_summary(summary_rows)
    print(f"\nCSV resumen: {args.summary_output}")
    print(f"CSV equity curve: {args.equity_output}")


if __name__ == "__main__":
    main()
