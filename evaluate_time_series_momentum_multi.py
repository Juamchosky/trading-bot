from __future__ import annotations

import argparse
import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from bot.execution.paper_broker import PaperBroker
from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.models import Candle
from bot.strategy.time_series_momentum_multi import TimeSeriesMomentumMultiStrategy
from simulate_live_paper import calculate_max_drawdown_pct, upsert_equity_point


OUTPUT_PATH = Path("time_series_momentum_multi_evaluation.csv")
ROBUSTNESS_SUMMARY_OUTPUT_PATH = Path("time_series_momentum_multi_robustness_summary.csv")


@dataclass(frozen=True)
class TimeSeriesMomentumMultiConfig:
    symbol: str = "BTCUSDT"
    binance_interval: str = "1h"
    candle_count: int = 300
    historical_offset: int = 0
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    position_size_pct: float = 0.5
    binance_spot_base_url: str = "https://api.binance.com"


@dataclass(frozen=True)
class TimeSeriesMomentumMultiEvaluation:
    strategy_name: str
    symbol: str
    interval: str
    candle_count: int
    historical_offset: int
    total_signals_buy: int
    total_signals_sell: int
    total_signals_hold: int
    total_buys_executed: int
    total_sells_executed: int
    exposure_pct: float
    final_equity: float
    return_pct: float
    max_drawdown_pct: float
    closed_trades: int
    win_rate_pct: float
    profit_factor: float
    avg_trade_return_pct: float


@dataclass(frozen=True)
class RobustnessRow:
    row_type: str
    historical_offset: int | str
    return_pct: float | str
    max_drawdown_pct: float | str
    profit_factor: float | str
    avg_return_pct: float | str
    std_return_pct: float | str
    worst_return_pct: float | str
    best_return_pct: float | str
    avg_drawdown: float | str
    worst_drawdown: float | str
    robustness_score: float | str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluacion offline de baseline TSMOM multi-horizon long/flat."
    )
    parser.add_argument("--symbol", default=TimeSeriesMomentumMultiConfig.symbol)
    parser.add_argument(
        "--interval",
        default=TimeSeriesMomentumMultiConfig.binance_interval,
    )
    parser.add_argument(
        "--candle-count",
        type=int,
        default=TimeSeriesMomentumMultiConfig.candle_count,
    )
    parser.add_argument(
        "--historical-offset",
        type=int,
        default=TimeSeriesMomentumMultiConfig.historical_offset,
    )
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=TimeSeriesMomentumMultiConfig.initial_cash,
    )
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=TimeSeriesMomentumMultiConfig.fee_rate,
    )
    parser.add_argument(
        "--position-size-pct",
        type=float,
        default=TimeSeriesMomentumMultiConfig.position_size_pct,
    )
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--robustness-offsets",
        default="",
        help="Lista separada por comas de offsets para analisis de robustez, por ejemplo 0,500,1000,1500.",
    )
    parser.add_argument(
        "--robustness-summary-output",
        type=Path,
        default=ROBUSTNESS_SUMMARY_OUTPUT_PATH,
    )
    return parser.parse_args()


def parse_offsets(raw_offsets: str) -> list[int]:
    if not raw_offsets.strip():
        return []
    return [int(part.strip()) for part in raw_offsets.split(",") if part.strip()]


def format_metric(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.6f}"


def safe_mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def load_candles(config: TimeSeriesMomentumMultiConfig) -> list[Candle]:
    try:
        candles = fetch_historical_candles(
            symbol=config.symbol,
            interval=config.binance_interval,
            limit=config.candle_count,
            historical_offset=config.historical_offset,
            base_url=config.binance_spot_base_url,
        )
    except BinanceMarketDataError as exc:
        raise RuntimeError(
            f"No se pudieron cargar velas historicas de Binance: {exc}"
        ) from exc

    if not candles:
        raise RuntimeError("No se recibieron velas para evaluar.")
    return candles


def evaluate_strategy(
    config: TimeSeriesMomentumMultiConfig,
    candles: Sequence[Candle],
) -> TimeSeriesMomentumMultiEvaluation:
    strategy = TimeSeriesMomentumMultiStrategy()
    broker = PaperBroker(
        cash=config.initial_cash,
        fee_rate=config.fee_rate,
        position_size_pct=config.position_size_pct,
    )

    history: list[Candle] = []
    equity_curve: list[tuple[int, float]] = []
    closed_trade_pnls: list[float] = []
    closed_trade_returns_pct: list[float] = []
    total_signals_buy = 0
    total_signals_sell = 0
    total_signals_hold = 0
    total_buys_executed = 0
    total_sells_executed = 0
    bars_in_market = 0

    for candle in candles:
        history.append(candle)
        signal = strategy.signal(history, in_position=broker.position_qty > 0.0)

        if signal == "buy":
            total_signals_buy += 1
        elif signal == "sell":
            total_signals_sell += 1
        else:
            total_signals_hold += 1

        if signal == "sell" and broker.position_qty > 0.0:
            entry_price = broker.entry_price
            trade = broker.sell_all(candle.close)
            if trade is not None:
                total_sells_executed += 1
                closed_trade_pnls.append(trade.pnl)
                closed_trade_returns_pct.append(
                    ((trade.price / entry_price) - 1.0) * 100.0
                )
        elif signal == "buy" and broker.position_qty == 0.0:
            trade = broker.buy_all(candle.close)
            if trade is not None:
                total_buys_executed += 1

        if broker.position_qty > 0.0:
            bars_in_market += 1

        upsert_equity_point(equity_curve, candle.timestamp, broker.equity(candle.close))

    if candles and broker.position_qty > 0.0:
        final_candle = candles[-1]
        entry_price = broker.entry_price
        trade = broker.sell_all(final_candle.close)
        if trade is not None:
            total_sells_executed += 1
            closed_trade_pnls.append(trade.pnl)
            closed_trade_returns_pct.append(
                ((trade.price / entry_price) - 1.0) * 100.0
            )
            upsert_equity_point(
                equity_curve,
                final_candle.timestamp,
                broker.equity(final_candle.close),
            )

    final_equity = broker.equity(candles[-1].close) if candles else config.initial_cash
    closed_trades = len(closed_trade_pnls)
    winning_trades = sum(1 for pnl in closed_trade_pnls if pnl > 0.0)
    gross_profit = sum(pnl for pnl in closed_trade_pnls if pnl > 0.0)
    gross_loss = abs(sum(pnl for pnl in closed_trade_pnls if pnl < 0.0))

    win_rate_pct = (winning_trades / closed_trades) * 100.0 if closed_trades > 0 else 0.0
    if gross_loss == 0.0:
        profit_factor = float("inf") if gross_profit > 0.0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss
    exposure_pct = (bars_in_market / len(candles)) * 100.0 if candles else 0.0
    avg_trade_return_pct = (
        sum(closed_trade_returns_pct) / closed_trades if closed_trades > 0 else 0.0
    )

    return TimeSeriesMomentumMultiEvaluation(
        strategy_name="time_series_momentum_multi_l50_l100_l200_vote2_long_flat",
        symbol=config.symbol,
        interval=config.binance_interval,
        candle_count=config.candle_count,
        historical_offset=config.historical_offset,
        total_signals_buy=total_signals_buy,
        total_signals_sell=total_signals_sell,
        total_signals_hold=total_signals_hold,
        total_buys_executed=total_buys_executed,
        total_sells_executed=total_sells_executed,
        exposure_pct=exposure_pct,
        final_equity=final_equity,
        return_pct=((final_equity / config.initial_cash) - 1.0) * 100.0,
        max_drawdown_pct=calculate_max_drawdown_pct(equity_curve),
        closed_trades=closed_trades,
        win_rate_pct=win_rate_pct,
        profit_factor=profit_factor,
        avg_trade_return_pct=avg_trade_return_pct,
    )


def export_evaluation_csv(
    row: TimeSeriesMomentumMultiEvaluation,
    output_path: Path,
) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "strategy_name",
                "symbol",
                "interval",
                "candle_count",
                "historical_offset",
                "total_signals_buy",
                "total_signals_sell",
                "total_signals_hold",
                "total_buys_executed",
                "total_sells_executed",
                "exposure_pct",
                "final_equity",
                "return_pct",
                "max_drawdown_pct",
                "closed_trades",
                "win_rate_pct",
                "profit_factor",
                "avg_trade_return_pct",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "strategy_name": row.strategy_name,
                "symbol": row.symbol,
                "interval": row.interval,
                "candle_count": row.candle_count,
                "historical_offset": row.historical_offset,
                "total_signals_buy": row.total_signals_buy,
                "total_signals_sell": row.total_signals_sell,
                "total_signals_hold": row.total_signals_hold,
                "total_buys_executed": row.total_buys_executed,
                "total_sells_executed": row.total_sells_executed,
                "exposure_pct": f"{row.exposure_pct:.6f}",
                "final_equity": f"{row.final_equity:.6f}",
                "return_pct": f"{row.return_pct:.6f}",
                "max_drawdown_pct": f"{row.max_drawdown_pct:.6f}",
                "closed_trades": row.closed_trades,
                "win_rate_pct": f"{row.win_rate_pct:.6f}",
                "profit_factor": format_metric(row.profit_factor),
                "avg_trade_return_pct": f"{row.avg_trade_return_pct:.6f}",
            }
        )


def build_robustness_rows(
    config: TimeSeriesMomentumMultiConfig,
    offsets: Sequence[int],
) -> list[RobustnessRow]:
    if not offsets:
        return []

    per_offset_rows: list[RobustnessRow] = []
    returns: list[float] = []
    drawdowns: list[float] = []

    for offset in offsets:
        offset_config = TimeSeriesMomentumMultiConfig(
            symbol=config.symbol,
            binance_interval=config.binance_interval,
            candle_count=config.candle_count,
            historical_offset=offset,
            initial_cash=config.initial_cash,
            fee_rate=config.fee_rate,
            position_size_pct=config.position_size_pct,
        )
        candles = load_candles(offset_config)
        result = evaluate_strategy(offset_config, candles)
        returns.append(result.return_pct)
        drawdowns.append(result.max_drawdown_pct)
        per_offset_rows.append(
            RobustnessRow(
                row_type="offset",
                historical_offset=offset,
                return_pct=result.return_pct,
                max_drawdown_pct=result.max_drawdown_pct,
                profit_factor=result.profit_factor,
                avg_return_pct="",
                std_return_pct="",
                worst_return_pct="",
                best_return_pct="",
                avg_drawdown="",
                worst_drawdown="",
                robustness_score="",
            )
        )

    avg_return_pct = safe_mean(returns)
    std_return_pct = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    worst_return_pct = min(returns) if returns else 0.0
    best_return_pct = max(returns) if returns else 0.0
    avg_drawdown = safe_mean(drawdowns)
    worst_drawdown = max(drawdowns) if drawdowns else 0.0
    robustness_score = avg_return_pct - std_return_pct - worst_drawdown

    per_offset_rows.append(
        RobustnessRow(
            row_type="aggregate",
            historical_offset="aggregate",
            return_pct="",
            max_drawdown_pct="",
            profit_factor="",
            avg_return_pct=avg_return_pct,
            std_return_pct=std_return_pct,
            worst_return_pct=worst_return_pct,
            best_return_pct=best_return_pct,
            avg_drawdown=avg_drawdown,
            worst_drawdown=worst_drawdown,
            robustness_score=robustness_score,
        )
    )
    return per_offset_rows


def export_robustness_summary_csv(rows: Sequence[RobustnessRow], output_path: Path) -> None:
    if not rows:
        return

    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "row_type",
                "historical_offset",
                "return_pct",
                "max_drawdown_pct",
                "profit_factor",
                "avg_return_pct",
                "std_return_pct",
                "worst_return_pct",
                "best_return_pct",
                "avg_drawdown",
                "worst_drawdown",
                "robustness_score",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "row_type": row.row_type,
                    "historical_offset": row.historical_offset,
                    "return_pct": (
                        f"{float(row.return_pct):.6f}" if row.return_pct != "" else ""
                    ),
                    "max_drawdown_pct": (
                        f"{float(row.max_drawdown_pct):.6f}"
                        if row.max_drawdown_pct != ""
                        else ""
                    ),
                    "profit_factor": (
                        format_metric(float(row.profit_factor))
                        if row.profit_factor != ""
                        else ""
                    ),
                    "avg_return_pct": (
                        f"{float(row.avg_return_pct):.6f}"
                        if row.avg_return_pct != ""
                        else ""
                    ),
                    "std_return_pct": (
                        f"{float(row.std_return_pct):.6f}"
                        if row.std_return_pct != ""
                        else ""
                    ),
                    "worst_return_pct": (
                        f"{float(row.worst_return_pct):.6f}"
                        if row.worst_return_pct != ""
                        else ""
                    ),
                    "best_return_pct": (
                        f"{float(row.best_return_pct):.6f}"
                        if row.best_return_pct != ""
                        else ""
                    ),
                    "avg_drawdown": (
                        f"{float(row.avg_drawdown):.6f}"
                        if row.avg_drawdown != ""
                        else ""
                    ),
                    "worst_drawdown": (
                        f"{float(row.worst_drawdown):.6f}"
                        if row.worst_drawdown != ""
                        else ""
                    ),
                    "robustness_score": (
                        f"{float(row.robustness_score):.6f}"
                        if row.robustness_score != ""
                        else ""
                    ),
                }
            )


def print_evaluation(
    row: TimeSeriesMomentumMultiEvaluation,
    output_path: Path,
) -> None:
    print("Evaluacion TSMOM multi-horizon long/flat")
    print(f"strategy_name: {row.strategy_name}")
    print(f"symbol: {row.symbol}")
    print(f"interval: {row.interval}")
    print(f"candle_count: {row.candle_count}")
    print(f"historical_offset: {row.historical_offset}")
    print(
        "signals buy/sell/hold: "
        f"{row.total_signals_buy}/{row.total_signals_sell}/{row.total_signals_hold}"
    )
    print(
        "executions buy/sell: "
        f"{row.total_buys_executed}/{row.total_sells_executed}"
    )
    print(f"exposure_pct: {row.exposure_pct:.2f}%")
    print(f"final_equity: {row.final_equity:.2f}")
    print(f"return_pct: {row.return_pct:.2f}%")
    print(f"max_drawdown_pct: {row.max_drawdown_pct:.2f}%")
    print(f"closed_trades: {row.closed_trades}")
    print(f"win_rate_pct: {row.win_rate_pct:.2f}%")
    print(f"profit_factor: {format_metric(row.profit_factor)}")
    print(f"avg_trade_return_pct: {row.avg_trade_return_pct:.2f}%")
    print(f"CSV exportado: {output_path}")


def main() -> None:
    args = parse_args()
    config = TimeSeriesMomentumMultiConfig(
        symbol=args.symbol.upper(),
        binance_interval=args.interval,
        candle_count=args.candle_count,
        historical_offset=args.historical_offset,
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
        position_size_pct=args.position_size_pct,
    )
    candles = load_candles(config)
    result = evaluate_strategy(config, candles)
    export_evaluation_csv(result, args.output_path)
    robustness_rows = build_robustness_rows(config, parse_offsets(args.robustness_offsets))
    export_robustness_summary_csv(robustness_rows, args.robustness_summary_output)
    print_evaluation(result, args.output_path)
    if robustness_rows:
        print(f"CSV robustness summary: {args.robustness_summary_output}")


if __name__ == "__main__":
    main()
