from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from bot.execution.paper_broker import PaperBroker
from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.models import Candle
from run_paper_live_bot import (
    PROFILE_ACTIVE,
    PROFILE_CURRENT,
    PROFILE_LIVE_SIMPLE,
    STRATEGY_PROFILES,
    CandidateConfig,
    build_strategy,
)
from simulate_live_paper import (
    calculate_closed_trade_metrics,
    calculate_max_drawdown_pct,
    format_metric,
    upsert_equity_point,
)

PROFILE_BALANCED = "balanced"
OUTPUT_PATH = Path("live_profile_comparison.csv")


@dataclass(frozen=True)
class ProfileEvaluation:
    strategy_profile: str
    total_signals_buy: int
    total_signals_sell: int
    total_signals_hold: int
    total_buys_executed: int
    total_sells_executed: int
    final_equity: float
    return_pct: float
    max_drawdown_pct: float
    closed_trades: int
    win_rate_pct: float
    profit_factor: float
    ranking_score: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Comparacion paper/offline de perfiles live sobre las mismas velas historicas "
            "sin tocar el runner real de Binance."
        )
    )
    parser.add_argument("--symbol", default=CandidateConfig.symbol)
    parser.add_argument("--interval", default=CandidateConfig.binance_interval)
    parser.add_argument("--candle-count", type=int, default=CandidateConfig.candle_count)
    parser.add_argument("--historical-offset", type=int, default=0)
    parser.add_argument("--initial-cash", type=float, default=CandidateConfig.initial_cash)
    parser.add_argument("--fee-rate", type=float, default=CandidateConfig.fee_rate)
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--include-balanced-profile",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Incluye PROFILE_BALANCED solo en esta comparacion paper. "
            "No modifica run_binance_live_bot.py."
        ),
    )
    return parser.parse_args()


def build_profile_configs(args: argparse.Namespace) -> dict[str, CandidateConfig]:
    profile_configs = {
        profile_name: replace(
            profile_config,
            symbol=args.symbol.upper(),
            binance_interval=args.interval,
            candle_count=args.candle_count,
            initial_cash=args.initial_cash,
            fee_rate=args.fee_rate,
        )
        for profile_name, profile_config in STRATEGY_PROFILES.items()
    }

    if args.include_balanced_profile:
        profile_configs[PROFILE_BALANCED] = build_balanced_profile(profile_configs[PROFILE_LIVE_SIMPLE])

    return profile_configs


def build_balanced_profile(base_profile: CandidateConfig) -> CandidateConfig:
    # Cambio minimo sobre live_simple: conserva buys sin el filtro SMA largo,
    # pero reactiva pendiente de tendencia para bajar ruido y drawdown.
    return replace(
        base_profile,
        signal_confirmation_bars=0,
        trend_filter_enabled=False,
        trend_slope_filter_enabled=True,
    )


def load_shared_candles(config: CandidateConfig, historical_offset: int) -> list[Candle]:
    if config.market_data_mode != "binance_historical":
        raise ValueError("evaluate_live_profiles.py requiere market_data_mode='binance_historical'.")

    try:
        candles = fetch_historical_candles(
            symbol=config.symbol,
            interval=config.binance_interval,
            limit=config.candle_count,
            historical_offset=historical_offset,
            base_url=config.binance_spot_base_url,
        )
    except BinanceMarketDataError as exc:
        raise RuntimeError(f"No se pudieron cargar velas historicas de Binance: {exc}") from exc

    if not candles:
        raise RuntimeError("No se recibieron velas para evaluar.")

    return candles


def evaluate_profile(config: CandidateConfig, candles: Sequence[Candle], strategy_profile: str) -> ProfileEvaluation:
    strategy = build_strategy(config)
    broker = PaperBroker(
        cash=config.initial_cash,
        fee_rate=config.fee_rate,
        position_size_pct=config.position_size_pct,
    )

    closes: list[float] = []
    equity_curve: list[tuple[int, float]] = []
    closed_trade_pnls: list[float] = []
    equity_peak = config.initial_cash
    kill_switch_active = False

    total_signals_buy = 0
    total_signals_sell = 0
    total_signals_hold = 0
    total_buys_executed = 0
    total_sells_executed = 0

    for candle in candles:
        closes.append(candle.close)
        signal = strategy.signal(closes)
        if signal == "buy":
            total_signals_buy += 1
        elif signal == "sell":
            total_signals_sell += 1
        else:
            total_signals_hold += 1

        if broker.position_qty > 0.0:
            stop_loss_price = broker.entry_price * (1.0 - config.stop_loss_pct)
            take_profit_price = broker.entry_price * (1.0 + config.take_profit_pct)
            if candle.low <= stop_loss_price:
                trade = broker.sell_all(stop_loss_price)
                if trade is not None:
                    total_sells_executed += 1
                    closed_trade_pnls.append(trade.pnl)
            elif candle.high >= take_profit_price:
                trade = broker.sell_all(take_profit_price)
                if trade is not None:
                    total_sells_executed += 1
                    closed_trade_pnls.append(trade.pnl)

        if signal == "buy" and not kill_switch_active:
            trade = broker.buy_all(candle.close)
            if trade is not None:
                total_buys_executed += 1
        elif signal == "sell":
            trade = broker.sell_all(candle.close)
            if trade is not None:
                total_sells_executed += 1
                closed_trade_pnls.append(trade.pnl)

        current_equity = broker.equity(candle.close)
        upsert_equity_point(equity_curve, candle.timestamp, current_equity)

        if current_equity > equity_peak:
            equity_peak = current_equity
        elif config.max_drawdown_limit_pct is not None and equity_peak > 0.0:
            drawdown_pct = ((equity_peak - current_equity) / equity_peak) * 100.0
            if drawdown_pct >= config.max_drawdown_limit_pct:
                kill_switch_active = True

    last_price = candles[-1].close
    final_equity = broker.equity(last_price)
    upsert_equity_point(equity_curve, candles[-1].timestamp, final_equity)
    max_drawdown_pct = calculate_max_drawdown_pct(equity_curve)
    trade_metrics = calculate_closed_trade_metrics(closed_trade_pnls)

    result = ProfileEvaluation(
        strategy_profile=strategy_profile,
        total_signals_buy=total_signals_buy,
        total_signals_sell=total_signals_sell,
        total_signals_hold=total_signals_hold,
        total_buys_executed=total_buys_executed,
        total_sells_executed=total_sells_executed,
        final_equity=final_equity,
        return_pct=((final_equity / config.initial_cash) - 1.0) * 100.0,
        max_drawdown_pct=max_drawdown_pct,
        closed_trades=int(trade_metrics["closed_trades"]),
        win_rate_pct=float(trade_metrics["win_rate_pct"]),
        profit_factor=float(trade_metrics["profit_factor"]),
        ranking_score=0.0,
    )
    return replace(result, ranking_score=calculate_ranking_score(result))


def calculate_ranking_score(result: ProfileEvaluation) -> float:
    total_signals = max(
        1,
        result.total_signals_buy + result.total_signals_sell + result.total_signals_hold,
    )
    buy_signal_ratio = result.total_signals_buy / total_signals
    hold_ratio = result.total_signals_hold / total_signals
    sell_signal_ratio = result.total_signals_sell / total_signals
    buy_execution_score = min(result.total_buys_executed, 5) / 5.0

    if math.isinf(result.profit_factor):
        profit_factor_score = 1.0
    else:
        profit_factor_score = min(max(result.profit_factor, 0.0), 3.0) / 3.0

    return_score = math.tanh(result.return_pct / 5.0)
    drawdown_penalty = min(result.max_drawdown_pct, 15.0) / 15.0
    sell_bias_penalty = max(0.0, sell_signal_ratio - buy_signal_ratio)

    return (
        0.35 * buy_execution_score
        + 0.20 * buy_signal_ratio
        + 0.20 * profit_factor_score
        + 0.15 * return_score
        - 0.20 * hold_ratio
        - 0.15 * sell_bias_penalty
        - 0.15 * drawdown_penalty
    )


def export_comparison_csv(rows: Sequence[ProfileEvaluation], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "strategy_profile",
                "total_signals_buy",
                "total_signals_sell",
                "total_signals_hold",
                "total_buys_executed",
                "total_sells_executed",
                "final_equity",
                "return_pct",
                "max_drawdown_pct",
                "closed_trades",
                "win_rate_pct",
                "profit_factor",
                "ranking_score",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "strategy_profile": row.strategy_profile,
                    "total_signals_buy": row.total_signals_buy,
                    "total_signals_sell": row.total_signals_sell,
                    "total_signals_hold": row.total_signals_hold,
                    "total_buys_executed": row.total_buys_executed,
                    "total_sells_executed": row.total_sells_executed,
                    "final_equity": f"{row.final_equity:.6f}",
                    "return_pct": f"{row.return_pct:.6f}",
                    "max_drawdown_pct": f"{row.max_drawdown_pct:.6f}",
                    "closed_trades": row.closed_trades,
                    "win_rate_pct": f"{row.win_rate_pct:.6f}",
                    "profit_factor": format_metric(row.profit_factor),
                    "ranking_score": f"{row.ranking_score:.6f}",
                }
            )


def print_console_summary(rows: Sequence[ProfileEvaluation], output_path: Path) -> None:
    ranked_rows = sorted(rows, key=lambda row: row.ranking_score, reverse=True)

    print("Evaluacion paper/offline de perfiles live")
    print("Base ranking: actividad buy + PF + retorno, penalizando hold dominante, sesgo sell-only y drawdown.")

    for row in rows:
        print(f"\n[{row.strategy_profile}]")
        print(
            "signals "
            f"buy/sell/hold: {row.total_signals_buy}/"
            f"{row.total_signals_sell}/{row.total_signals_hold}"
        )
        print(
            "executions "
            f"buy/sell: {row.total_buys_executed}/{row.total_sells_executed}"
        )
        print(f"final_equity: {row.final_equity:.2f}")
        print(f"return_pct: {row.return_pct:.2f}%")
        print(f"max_drawdown_pct: {row.max_drawdown_pct:.2f}%")
        print(f"closed_trades: {row.closed_trades}")
        print(f"win_rate_pct: {row.win_rate_pct:.2f}%")
        print(f"profit_factor: {format_metric(row.profit_factor)}")
        print(f"ranking_score: {row.ranking_score:.4f}")

    print("\nRanking final")
    for index, row in enumerate(ranked_rows, start=1):
        print(
            f"{index}. {row.strategy_profile} | "
            f"score={row.ranking_score:.4f} | "
            f"buys={row.total_buys_executed} | "
            f"pf={format_metric(row.profit_factor)} | "
            f"dd={row.max_drawdown_pct:.2f}% | "
            f"ret={row.return_pct:.2f}%"
        )

    print(f"\nCSV exportado: {output_path}")


def main() -> None:
    args = parse_args()
    profile_configs = build_profile_configs(args)

    shared_candles = load_shared_candles(
        profile_configs[PROFILE_CURRENT],
        historical_offset=args.historical_offset,
    )

    rows = [
        evaluate_profile(config, shared_candles, strategy_profile)
        for strategy_profile, config in profile_configs.items()
    ]

    export_comparison_csv(rows, args.output_path)
    print_console_summary(rows, args.output_path)


if __name__ == "__main__":
    main()
