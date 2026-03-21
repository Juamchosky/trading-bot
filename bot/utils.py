import csv
import math
from pathlib import Path
from typing import Sequence

from bot.config import SimulationConfig
from bot.models import BacktestTrade
from bot.models import SimulationResult


BACKTEST_TRADES_CSV_FILENAME = "backtest_trades.csv"
BACKTEST_SUMMARY_CSV_FILENAME = "backtest_summary.csv"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKTEST_TRADES_HEADERS = (
    "entry_timestamp",
    "exit_timestamp",
    "side",
    "entry_price",
    "exit_price",
    "quantity",
    "pnl",
    "exit_reason",
)
_BACKTEST_SUMMARY_HEADERS = (
    "execution_mode",
    "market_data_mode",
    "symbol",
    "candle_count",
    "short_window",
    "long_window",
    "stop_loss_pct",
    "take_profit_pct",
    "position_size_pct",
    "fee_rate",
    "final_balance",
    "return_pct",
    "total_trades",
    "closed_trades",
    "win_rate_pct",
    "avg_pnl",
    "best_trade_pnl",
    "worst_trade_pnl",
    "profit_factor",
    "avg_win_pnl",
    "avg_loss_pnl",
)


def export_backtest_trades_to_csv(
    trades: Sequence[BacktestTrade],
    output_path: str | Path = BACKTEST_TRADES_CSV_FILENAME,
) -> Path:
    csv_path = _resolve_output_path(output_path)

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=_BACKTEST_TRADES_HEADERS)
        writer.writeheader()
        for trade in trades:
            writer.writerow(
                {
                    "entry_timestamp": trade.entry_timestamp,
                    "exit_timestamp": trade.exit_timestamp,
                    "side": trade.side,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "quantity": trade.quantity,
                    "pnl": trade.pnl,
                    "exit_reason": trade.exit_reason,
                }
            )

    return csv_path


def export_backtest_summary_to_csv(
    config: SimulationConfig,
    result: SimulationResult,
    output_path: str | Path = BACKTEST_SUMMARY_CSV_FILENAME,
) -> Path:
    csv_path = _resolve_output_path(output_path)
    file_exists = csv_path.exists()

    with csv_path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=_BACKTEST_SUMMARY_HEADERS)
        if not file_exists:
            writer.writeheader()

        writer.writerow(
            {
                "execution_mode": config.execution_mode,
                "market_data_mode": config.market_data_mode,
                "symbol": config.symbol,
                "candle_count": config.candle_count,
                "short_window": config.short_window,
                "long_window": config.long_window,
                "stop_loss_pct": config.stop_loss_pct,
                "take_profit_pct": config.take_profit_pct,
                "position_size_pct": config.position_size_pct,
                "fee_rate": config.fee_rate,
                "final_balance": result.final_balance,
                "return_pct": result.return_pct,
                "total_trades": result.total_trades,
                "closed_trades": result.closed_trades,
                "win_rate_pct": result.win_rate_pct,
                "avg_pnl": result.avg_pnl,
                "best_trade_pnl": result.best_trade_pnl,
                "worst_trade_pnl": result.worst_trade_pnl,
                "profit_factor": _format_csv_metric(result.profit_factor),
                "avg_win_pnl": result.avg_win_pnl,
                "avg_loss_pnl": result.avg_loss_pnl,
            }
        )

    return csv_path


def _resolve_output_path(output_path: str | Path) -> Path:
    csv_path = Path(output_path)
    if not csv_path.is_absolute():
        csv_path = _PROJECT_ROOT / csv_path
    return csv_path


def _format_csv_metric(value: float) -> float | str:
    if math.isinf(value):
        return "inf"
    return value
