import csv
from pathlib import Path
from typing import Sequence

from bot.models import BacktestTrade


BACKTEST_TRADES_CSV_FILENAME = "backtest_trades.csv"
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


def export_backtest_trades_to_csv(
    trades: Sequence[BacktestTrade],
    output_path: str | Path = BACKTEST_TRADES_CSV_FILENAME,
) -> Path:
    csv_path = Path(output_path)
    if not csv_path.is_absolute():
        csv_path = _PROJECT_ROOT / csv_path

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
