from __future__ import annotations

import argparse
import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.models import Candle, Trade
from bot.strategy.mean_reversion_zscore import MeanReversionZScoreStrategy
from simulate_live_paper import calculate_max_drawdown_pct, upsert_equity_point


OUTPUT_PATH = Path("mean_reversion_zscore_evaluation.csv")
TRADE_EQUITY_OUTPUT_PATH = Path("mean_reversion_zscore_trade_equity_curve.csv")
TRADE_DRAWDOWN_OUTPUT_PATH = Path("mean_reversion_zscore_trade_drawdown_curve.csv")
WALK_FORWARD_OUTPUT_PATH = Path("mean_reversion_zscore_walk_forward.csv")
ROBUSTNESS_SUMMARY_OUTPUT_PATH = Path("hybrid_robustness_summary.csv")


@dataclass(frozen=True)
class MeanReversionZScoreConfig:
    symbol: str = "BTCUSDT"
    binance_interval: str = "1h"
    candle_count: int = 300
    historical_offset: int = 0
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    position_size_pct: float = 0.5
    window: int = 20
    entry_zscore: float = -2.0
    exit_zscore: float = 0.0
    binance_spot_base_url: str = "https://api.binance.com"


@dataclass(frozen=True)
class MeanReversionZScoreEvaluation:
    strategy_name: str
    symbol: str
    interval: str
    candle_count: int
    historical_offset: int
    window: int
    entry_zscore: float
    exit_zscore: float
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
class CurvePoint:
    timestamp: int
    step: int
    equity: float
    peak_equity: float
    drawdown_pct: float


@dataclass(frozen=True)
class WalkForwardRow:
    row_type: str
    split_name: str
    train_start_index: int | str
    train_end_index: int | str
    test_start_index: int | str
    test_end_index: int | str
    train_return_pct: float | str
    test_return_pct: float | str
    train_max_drawdown_pct: float | str
    test_max_drawdown_pct: float | str
    train_closed_trades: int | str
    test_closed_trades: int | str
    avg_train_return_pct: float | str
    avg_test_return_pct: float | str
    std_test_return_pct: float | str
    positive_test_rate: float | str
    worst_test_return_pct: float | str


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


@dataclass
class FixedRiskPaperBroker:
    cash: float
    fee_rate: float = 0.001
    position_size_pct: float = 0.5
    position_qty: float = 0.0
    entry_price: float = 0.0

    def buy_position_sized(self, price: float) -> Trade | None:
        if self.position_qty > 0.0 or self.cash <= 0.0:
            return None

        invest_cash = self.cash * self.position_size_pct
        if invest_cash <= 0.0:
            return None

        qty = invest_cash / (price * (1.0 + self.fee_rate))
        if qty <= 0.0:
            return None

        self.position_qty = qty
        self.entry_price = price
        self.cash -= invest_cash
        return Trade(side="buy", price=price, quantity=qty)

    def sell_all(self, price: float) -> Trade | None:
        if self.position_qty <= 0.0:
            return None
        qty = self.position_qty
        gross_proceeds = qty * price
        sell_fee = gross_proceeds * self.fee_rate
        proceeds = gross_proceeds - sell_fee
        buy_cost = qty * self.entry_price
        buy_fee = buy_cost * self.fee_rate
        pnl = proceeds - (buy_cost + buy_fee)
        self.cash += proceeds
        self.position_qty = 0.0
        self.entry_price = 0.0
        return Trade(side="sell", price=price, quantity=qty, pnl=pnl)

    def equity(self, mark_price: float) -> float:
        return self.cash + (self.position_qty * mark_price)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluacion offline de mean reversion por z-score con exports y walk-forward."
    )
    parser.add_argument("--symbol", default=MeanReversionZScoreConfig.symbol)
    parser.add_argument("--interval", default=MeanReversionZScoreConfig.binance_interval)
    parser.add_argument("--candle-count", type=int, default=MeanReversionZScoreConfig.candle_count)
    parser.add_argument(
        "--historical-offset",
        type=int,
        default=MeanReversionZScoreConfig.historical_offset,
    )
    parser.add_argument("--initial-cash", type=float, default=MeanReversionZScoreConfig.initial_cash)
    parser.add_argument("--fee-rate", type=float, default=MeanReversionZScoreConfig.fee_rate)
    parser.add_argument(
        "--position-size-pct",
        type=float,
        default=MeanReversionZScoreConfig.position_size_pct,
        help="Porcentaje fijo del equity usado en cada entrada.",
    )
    parser.add_argument("--window", type=int, default=MeanReversionZScoreConfig.window)
    parser.add_argument(
        "--entry-zscore",
        type=float,
        default=MeanReversionZScoreConfig.entry_zscore,
    )
    parser.add_argument(
        "--exit-zscore",
        type=float,
        default=MeanReversionZScoreConfig.exit_zscore,
    )
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--trade-equity-output", type=Path, default=TRADE_EQUITY_OUTPUT_PATH)
    parser.add_argument("--trade-drawdown-output", type=Path, default=TRADE_DRAWDOWN_OUTPUT_PATH)
    parser.add_argument("--walk-forward-output", type=Path, default=WALK_FORWARD_OUTPUT_PATH)
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
    parser.add_argument(
        "--walk-forward-total-candles",
        type=int,
        default=1800,
        help="Cantidad total de velas para construir la base walk-forward.",
    )
    parser.add_argument(
        "--walk-forward-train-size",
        type=int,
        default=600,
        help="Tamano de la ventana in-sample.",
    )
    parser.add_argument(
        "--walk-forward-test-size",
        type=int,
        default=300,
        help="Tamano de la ventana out-of-sample.",
    )
    parser.add_argument(
        "--walk-forward-step-size",
        type=int,
        default=300,
        help="Desplazamiento entre splits consecutivos.",
    )
    return parser.parse_args()


def format_metric(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.6f}"


def safe_mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def build_curve_point(
    curve: list[CurvePoint],
    *,
    timestamp: int,
    equity: float,
) -> None:
    peak_equity = equity if not curve else max(curve[-1].peak_equity, equity)
    drawdown_pct = 0.0 if peak_equity <= 0.0 else ((peak_equity - equity) / peak_equity) * 100.0
    curve.append(
        CurvePoint(
            timestamp=timestamp,
            step=len(curve),
            equity=equity,
            peak_equity=peak_equity,
            drawdown_pct=drawdown_pct,
        )
    )


def export_trade_curve_csv(points: Sequence[CurvePoint], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["timestamp", "step", "equity", "peak_equity", "drawdown_pct"],
        )
        writer.writeheader()
        for point in points:
            writer.writerow(
                {
                    "timestamp": point.timestamp,
                    "step": point.step,
                    "equity": f"{point.equity:.6f}",
                    "peak_equity": f"{point.peak_equity:.6f}",
                    "drawdown_pct": f"{point.drawdown_pct:.6f}",
                }
            )


def export_drawdown_curve_csv(points: Sequence[CurvePoint], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["timestamp", "step", "peak_equity", "equity", "drawdown_pct"],
        )
        writer.writeheader()
        for point in points:
            writer.writerow(
                {
                    "timestamp": point.timestamp,
                    "step": point.step,
                    "peak_equity": f"{point.peak_equity:.6f}",
                    "equity": f"{point.equity:.6f}",
                    "drawdown_pct": f"{point.drawdown_pct:.6f}",
                }
            )


def load_candles(
    *,
    symbol: str,
    interval: str,
    candle_count: int,
    historical_offset: int,
    base_url: str,
) -> list[Candle]:
    try:
        candles = fetch_historical_candles(
            symbol=symbol,
            interval=interval,
            limit=candle_count,
            historical_offset=historical_offset,
            base_url=base_url,
        )
    except BinanceMarketDataError as exc:
        raise RuntimeError(f"No se pudieron cargar velas historicas de Binance: {exc}") from exc

    if not candles:
        raise RuntimeError("No se recibieron velas para evaluar.")
    return candles


def evaluate_strategy(
    config: MeanReversionZScoreConfig,
    candles: Sequence[Candle],
    *,
    warmup_candles: Sequence[Candle] = (),
) -> tuple[MeanReversionZScoreEvaluation, list[tuple[int, float]], list[CurvePoint]]:
    strategy = MeanReversionZScoreStrategy(
        window=config.window,
        entry_zscore=config.entry_zscore,
        exit_zscore=config.exit_zscore,
    )
    broker = FixedRiskPaperBroker(
        cash=config.initial_cash,
        fee_rate=config.fee_rate,
        position_size_pct=config.position_size_pct,
    )

    history: list[Candle] = list(warmup_candles)
    equity_curve: list[tuple[int, float]] = []
    trade_equity_curve: list[CurvePoint] = []
    closed_trade_pnls: list[float] = []
    closed_trade_returns_pct: list[float] = []
    total_signals_buy = 0
    total_signals_sell = 0
    total_signals_hold = 0
    total_buys_executed = 0
    total_sells_executed = 0
    bars_in_market = 0

    first_timestamp = candles[0].timestamp if candles else 0
    build_curve_point(trade_equity_curve, timestamp=first_timestamp, equity=config.initial_cash)

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
                closed_trade_returns_pct.append(((trade.price / entry_price) - 1.0) * 100.0)
                build_curve_point(
                    trade_equity_curve,
                    timestamp=candle.timestamp,
                    equity=broker.equity(candle.close),
                )
        elif signal == "buy" and broker.position_qty == 0.0:
            trade = broker.buy_position_sized(candle.close)
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
            closed_trade_returns_pct.append(((trade.price / entry_price) - 1.0) * 100.0)
            upsert_equity_point(
                equity_curve,
                final_candle.timestamp,
                broker.equity(final_candle.close),
            )
            build_curve_point(
                trade_equity_curve,
                timestamp=final_candle.timestamp,
                equity=broker.equity(final_candle.close),
            )

    final_equity = broker.equity(candles[-1].close) if candles else config.initial_cash
    closed_trades = len(closed_trade_pnls)
    winning_trades = sum(1 for pnl in closed_trade_pnls if pnl > 0.0)
    gross_profit = sum(pnl for pnl in closed_trade_pnls if pnl > 0.0)
    gross_loss = abs(sum(pnl for pnl in closed_trade_pnls if pnl < 0.0))

    row = MeanReversionZScoreEvaluation(
        strategy_name=(
            f"mean_reversion_zscore_sma{config.window}_std{config.window}"
            f"_entry{config.entry_zscore:g}_exit{config.exit_zscore:g}_long_flat"
        ),
        symbol=config.symbol,
        interval=config.binance_interval,
        candle_count=config.candle_count,
        historical_offset=config.historical_offset,
        window=config.window,
        entry_zscore=config.entry_zscore,
        exit_zscore=config.exit_zscore,
        total_signals_buy=total_signals_buy,
        total_signals_sell=total_signals_sell,
        total_signals_hold=total_signals_hold,
        total_buys_executed=total_buys_executed,
        total_sells_executed=total_sells_executed,
        exposure_pct=(bars_in_market / len(candles)) * 100.0 if candles else 0.0,
        final_equity=final_equity,
        return_pct=((final_equity / config.initial_cash) - 1.0) * 100.0,
        max_drawdown_pct=calculate_max_drawdown_pct(equity_curve),
        closed_trades=closed_trades,
        win_rate_pct=(winning_trades / closed_trades) * 100.0 if closed_trades > 0 else 0.0,
        profit_factor=(
            float("inf")
            if gross_loss == 0.0 and gross_profit > 0.0
            else gross_profit / gross_loss
            if gross_loss > 0.0
            else 0.0
        ),
        avg_trade_return_pct=(
            sum(closed_trade_returns_pct) / closed_trades if closed_trades > 0 else 0.0
        ),
    )
    return row, equity_curve, trade_equity_curve


def export_evaluation_csv(
    row: MeanReversionZScoreEvaluation,
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
                "window",
                "entry_zscore",
                "exit_zscore",
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
                "window": row.window,
                "entry_zscore": f"{row.entry_zscore:.6f}",
                "exit_zscore": f"{row.exit_zscore:.6f}",
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


def build_walk_forward_rows(
    config: MeanReversionZScoreConfig,
    candles: Sequence[Candle],
    *,
    train_size: int,
    test_size: int,
    step_size: int,
) -> list[WalkForwardRow]:
    if train_size <= 0 or test_size <= 0 or step_size <= 0:
        raise ValueError("Las ventanas walk-forward deben ser mayores que cero.")
    if len(candles) < train_size + test_size:
        raise ValueError("No hay suficientes velas para construir al menos un split walk-forward.")

    rows: list[WalkForwardRow] = []
    split_index = 1
    max_start = len(candles) - (train_size + test_size)

    for start_index in range(0, max_start + 1, step_size):
        train_start = start_index
        train_end = train_start + train_size
        test_start = train_end
        test_end = test_start + test_size

        train_candles = candles[train_start:train_end]
        test_candles = candles[test_start:test_end]
        if len(train_candles) < train_size or len(test_candles) < test_size:
            continue

        train_result, _, _ = evaluate_strategy(config, train_candles)
        test_result, _, _ = evaluate_strategy(
            config,
            test_candles,
            warmup_candles=train_candles,
        )
        rows.append(
            WalkForwardRow(
                row_type="split",
                split_name=f"split_{split_index}",
                train_start_index=train_start,
                train_end_index=train_end - 1,
                test_start_index=test_start,
                test_end_index=test_end - 1,
                train_return_pct=train_result.return_pct,
                test_return_pct=test_result.return_pct,
                train_max_drawdown_pct=train_result.max_drawdown_pct,
                test_max_drawdown_pct=test_result.max_drawdown_pct,
                train_closed_trades=train_result.closed_trades,
                test_closed_trades=test_result.closed_trades,
                avg_train_return_pct="",
                avg_test_return_pct="",
                std_test_return_pct="",
                positive_test_rate="",
                worst_test_return_pct="",
            )
        )
        split_index += 1

    test_returns = [float(row.test_return_pct) for row in rows]
    train_returns = [float(row.train_return_pct) for row in rows]
    positive_test_runs = sum(1 for value in test_returns if value > 0.0)
    aggregate = WalkForwardRow(
        row_type="aggregate",
        split_name="aggregate",
        train_start_index="",
        train_end_index="",
        test_start_index="",
        test_end_index="",
        train_return_pct="",
        test_return_pct="",
        train_max_drawdown_pct="",
        test_max_drawdown_pct="",
        train_closed_trades="",
        test_closed_trades="",
        avg_train_return_pct=safe_mean(train_returns),
        avg_test_return_pct=safe_mean(test_returns),
        std_test_return_pct=statistics.pstdev(test_returns) if len(test_returns) > 1 else 0.0,
        positive_test_rate=(positive_test_runs / len(rows)) if rows else 0.0,
        worst_test_return_pct=min(test_returns) if test_returns else 0.0,
    )
    return [*rows, aggregate]


def export_walk_forward_csv(rows: Sequence[WalkForwardRow], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "row_type",
                "split_name",
                "train_start_index",
                "train_end_index",
                "test_start_index",
                "test_end_index",
                "train_return_pct",
                "test_return_pct",
                "train_max_drawdown_pct",
                "test_max_drawdown_pct",
                "train_closed_trades",
                "test_closed_trades",
                "avg_train_return_pct",
                "avg_test_return_pct",
                "std_test_return_pct",
                "positive_test_rate",
                "worst_test_return_pct",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "row_type": row.row_type,
                    "split_name": row.split_name,
                    "train_start_index": row.train_start_index,
                    "train_end_index": row.train_end_index,
                    "test_start_index": row.test_start_index,
                    "test_end_index": row.test_end_index,
                    "train_return_pct": (
                        f"{float(row.train_return_pct):.6f}" if row.train_return_pct != "" else ""
                    ),
                    "test_return_pct": (
                        f"{float(row.test_return_pct):.6f}" if row.test_return_pct != "" else ""
                    ),
                    "train_max_drawdown_pct": (
                        f"{float(row.train_max_drawdown_pct):.6f}"
                        if row.train_max_drawdown_pct != ""
                        else ""
                    ),
                    "test_max_drawdown_pct": (
                        f"{float(row.test_max_drawdown_pct):.6f}"
                        if row.test_max_drawdown_pct != ""
                        else ""
                    ),
                    "train_closed_trades": row.train_closed_trades,
                    "test_closed_trades": row.test_closed_trades,
                    "avg_train_return_pct": (
                        f"{float(row.avg_train_return_pct):.6f}"
                        if row.avg_train_return_pct != ""
                        else ""
                    ),
                    "avg_test_return_pct": (
                        f"{float(row.avg_test_return_pct):.6f}"
                        if row.avg_test_return_pct != ""
                        else ""
                    ),
                    "std_test_return_pct": (
                        f"{float(row.std_test_return_pct):.6f}"
                        if row.std_test_return_pct != ""
                        else ""
                    ),
                    "positive_test_rate": (
                        f"{float(row.positive_test_rate):.6f}"
                        if row.positive_test_rate != ""
                        else ""
                    ),
                    "worst_test_return_pct": (
                        f"{float(row.worst_test_return_pct):.6f}"
                        if row.worst_test_return_pct != ""
                        else ""
                    ),
                }
            )


def parse_offsets(raw_offsets: str) -> list[int]:
    if not raw_offsets.strip():
        return []
    return [int(part.strip()) for part in raw_offsets.split(",") if part.strip()]


def build_robustness_rows(
    config: MeanReversionZScoreConfig,
    offsets: Sequence[int],
) -> list[RobustnessRow]:
    if not offsets:
        return []

    per_offset_rows: list[RobustnessRow] = []
    returns: list[float] = []
    drawdowns: list[float] = []

    for offset in offsets:
        candles = load_candles(
            symbol=config.symbol,
            interval=config.binance_interval,
            candle_count=config.candle_count,
            historical_offset=offset,
            base_url=config.binance_spot_base_url,
        )
        result, _, _ = evaluate_strategy(
            MeanReversionZScoreConfig(
                symbol=config.symbol,
                binance_interval=config.binance_interval,
                candle_count=config.candle_count,
                historical_offset=offset,
                initial_cash=config.initial_cash,
                fee_rate=config.fee_rate,
                position_size_pct=config.position_size_pct,
                window=config.window,
                entry_zscore=config.entry_zscore,
                exit_zscore=config.exit_zscore,
            ),
            candles,
        )
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
    row: MeanReversionZScoreEvaluation,
    output_path: Path,
    trade_equity_output: Path,
    trade_drawdown_output: Path,
    walk_forward_output: Path,
) -> None:
    print("Evaluacion mean reversion z-score")
    print(f"strategy_name: {row.strategy_name}")
    print(f"symbol: {row.symbol}")
    print(f"interval: {row.interval}")
    print(f"candle_count: {row.candle_count}")
    print(f"historical_offset: {row.historical_offset}")
    print(f"window: {row.window}")
    print(f"entry_zscore: {row.entry_zscore:.2f}")
    print(f"exit_zscore: {row.exit_zscore:.2f}")
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
    print(f"CSV resumen: {output_path}")
    print(f"CSV trade equity curve: {trade_equity_output}")
    print(f"CSV trade drawdown curve: {trade_drawdown_output}")
    print(f"CSV walk-forward: {walk_forward_output}")


def main() -> None:
    args = parse_args()
    config = MeanReversionZScoreConfig(
        symbol=args.symbol.upper(),
        binance_interval=args.interval,
        candle_count=args.candle_count,
        historical_offset=args.historical_offset,
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
        position_size_pct=args.position_size_pct,
        window=args.window,
        entry_zscore=args.entry_zscore,
        exit_zscore=args.exit_zscore,
    )

    candles = load_candles(
        symbol=config.symbol,
        interval=config.binance_interval,
        candle_count=config.candle_count,
        historical_offset=config.historical_offset,
        base_url=config.binance_spot_base_url,
    )
    result, _, trade_equity_curve = evaluate_strategy(config, candles)
    export_evaluation_csv(result, args.output_path)
    export_trade_curve_csv(trade_equity_curve, args.trade_equity_output)
    export_drawdown_curve_csv(trade_equity_curve, args.trade_drawdown_output)

    walk_forward_candles = load_candles(
        symbol=config.symbol,
        interval=config.binance_interval,
        candle_count=args.walk_forward_total_candles,
        historical_offset=config.historical_offset,
        base_url=config.binance_spot_base_url,
    )
    walk_forward_rows = build_walk_forward_rows(
        config,
        walk_forward_candles,
        train_size=args.walk_forward_train_size,
        test_size=args.walk_forward_test_size,
        step_size=args.walk_forward_step_size,
    )
    export_walk_forward_csv(walk_forward_rows, args.walk_forward_output)

    robustness_offsets = parse_offsets(args.robustness_offsets)
    robustness_rows = build_robustness_rows(config, robustness_offsets)
    export_robustness_summary_csv(robustness_rows, args.robustness_summary_output)

    print_evaluation(
        result,
        args.output_path,
        args.trade_equity_output,
        args.trade_drawdown_output,
        args.walk_forward_output,
    )
    if robustness_rows:
        print(f"CSV robustness summary: {args.robustness_summary_output}")


if __name__ == "__main__":
    main()
