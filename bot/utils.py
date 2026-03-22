import csv
import math
from pathlib import Path
from typing import Sequence

from bot.config import SimulationConfig
from bot.models import BacktestTrade
from bot.models import SimulationResult


BACKTEST_TRADES_CSV_FILENAME = "backtest_trades.csv"
BACKTEST_SUMMARY_CSV_FILENAME = "backtest_summary.csv"
BACKTEST_EQUITY_CURVE_CSV_FILENAME = "equity_curve.csv"
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
    "trend_filter_enabled",
    "trend_window",
    "trend_slope_filter_enabled",
    "trend_slope_lookback",
    "volatility_filter_enabled",
    "volatility_window",
    "min_volatility_pct",
    "regime_filter_enabled",
    "regime_window",
    "min_regime_volatility_pct",
    "signal_confirmation_bars",
    "warmup_bars",
    "stop_loss_pct",
    "take_profit_pct",
    "max_drawdown_limit_pct",
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
    "max_drawdown_pct",
)
_BACKTEST_EQUITY_CURVE_HEADERS = (
    "timestamp",
    "equity",
)
_SUMMARY_HEADER_RENAMES = {
    "min_regime_range_pct": "min_regime_volatility_pct",
}


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
    active_headers = _ensure_summary_headers(csv_path, _BACKTEST_SUMMARY_HEADERS)
    file_exists = csv_path.exists()

    with csv_path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=active_headers, extrasaction="ignore")
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
                "trend_filter_enabled": config.trend_filter_enabled,
                "trend_window": config.trend_window,
                "trend_slope_filter_enabled": config.trend_slope_filter_enabled,
                "trend_slope_lookback": config.trend_slope_lookback,
                "volatility_filter_enabled": config.volatility_filter_enabled,
                "volatility_window": config.volatility_window,
                "min_volatility_pct": config.min_volatility_pct,
                "regime_filter_enabled": config.regime_filter_enabled,
                "regime_window": config.regime_window,
                "min_regime_volatility_pct": config.min_regime_volatility_pct,
                "signal_confirmation_bars": config.signal_confirmation_bars,
                "warmup_bars": config.warmup_bars,
                "stop_loss_pct": config.stop_loss_pct,
                "take_profit_pct": config.take_profit_pct,
                "max_drawdown_limit_pct": config.max_drawdown_limit_pct,
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
                "max_drawdown_pct": result.max_drawdown_pct,
            }
        )

    return csv_path


def export_equity_curve_to_csv(
    equity_curve: Sequence[tuple[int, float]],
    output_path: str | Path = BACKTEST_EQUITY_CURVE_CSV_FILENAME,
) -> Path:
    csv_path = _resolve_output_path(output_path)

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=_BACKTEST_EQUITY_CURVE_HEADERS)
        writer.writeheader()
        for timestamp, equity in equity_curve:
            writer.writerow(
                {
                    "timestamp": timestamp,
                    "equity": equity,
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


def _ensure_summary_headers(csv_path: Path, required_headers: Sequence[str]) -> tuple[str, ...]:
    required = tuple(required_headers)
    if not csv_path.exists():
        return required

    with csv_path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.reader(csv_file)
        existing_headers = next(reader, [])

    if not existing_headers:
        return required

    migrated_headers = _migrate_summary_headers(csv_path, existing_headers)
    if migrated_headers != tuple(existing_headers):
        existing_headers = list(migrated_headers)

    missing = [header for header in required if header not in existing_headers]
    if not missing:
        return tuple(existing_headers)

    merged_headers = list(existing_headers) + missing
    _rewrite_csv_with_headers(csv_path, existing_headers, merged_headers)
    return tuple(merged_headers)


def _rewrite_csv_with_headers(
    csv_path: Path,
    existing_headers: Sequence[str],
    merged_headers: Sequence[str],
) -> None:
    with csv_path.open("r", newline="", encoding="utf-8") as source_file:
        rows = list(csv.DictReader(source_file))

    with csv_path.open("w", newline="", encoding="utf-8") as target_file:
        writer = csv.DictWriter(target_file, fieldnames=merged_headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _migrate_summary_headers(csv_path: Path, existing_headers: Sequence[str]) -> tuple[str, ...]:
    renamed_headers = list(existing_headers)
    rename_map: dict[str, str] = {}
    remove_old_headers: set[str] = set()

    for old_header, new_header in _SUMMARY_HEADER_RENAMES.items():
        if old_header in renamed_headers and new_header not in renamed_headers:
            header_index = renamed_headers.index(old_header)
            renamed_headers[header_index] = new_header
            rename_map[old_header] = new_header
            continue
        if old_header in renamed_headers and new_header in renamed_headers:
            remove_old_headers.add(old_header)
            renamed_headers = [header for header in renamed_headers if header != old_header]

    if not rename_map and not remove_old_headers:
        return tuple(existing_headers)

    with csv_path.open("r", newline="", encoding="utf-8") as source_file:
        rows = list(csv.DictReader(source_file))

    with csv_path.open("w", newline="", encoding="utf-8") as target_file:
        writer = csv.DictWriter(target_file, fieldnames=renamed_headers)
        writer.writeheader()
        for row in rows:
            normalized_row = dict(row)
            for old_header, new_header in rename_map.items():
                if old_header in normalized_row and new_header not in normalized_row:
                    normalized_row[new_header] = normalized_row.pop(old_header)
            for old_header, new_header in _SUMMARY_HEADER_RENAMES.items():
                if old_header in remove_old_headers:
                    old_value = normalized_row.get(old_header, "")
                    new_value = normalized_row.get(new_header, "")
                    if old_value and not new_value:
                        normalized_row[new_header] = old_value
                    normalized_row.pop(old_header, None)
            writer.writerow(normalized_row)

    return tuple(renamed_headers)
