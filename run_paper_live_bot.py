from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from bot.execution.paper_broker import PaperBroker
from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.strategy.sma_cross import SMACrossStrategy

LOG_PATH = Path("paper_live_log.csv")
STATE_PATH = Path("paper_live_state.json")
PROFILE_CURRENT = "current"
PROFILE_ACTIVE = "active"
PROFILE_LIVE_SIMPLE = "live_simple"


@dataclass(frozen=True)
class CandidateConfig:
    symbol: str = "BTCUSDT"
    short_window: int = 5
    long_window: int = 20
    stop_loss_pct: float = 0.01
    take_profit_pct: float = 0.05
    signal_confirmation_bars: int = 1
    position_size_pct: float = 0.5
    max_drawdown_limit_pct: float | None = 1.5
    trend_filter_enabled: bool = True
    trend_window: int = 50
    trend_slope_filter_enabled: bool = True
    trend_slope_lookback: int = 3
    volatility_filter_enabled: bool = False
    regime_filter_enabled: bool = False
    warmup_bars: int = 0
    market_data_mode: str = "binance_historical"
    binance_interval: str = "1h"
    binance_spot_base_url: str = "https://api.binance.com"
    candle_count: int = 300
    fee_rate: float = 0.001
    initial_cash: float = 10_000.0


STRATEGY_PROFILES: dict[str, CandidateConfig] = {
    PROFILE_CURRENT: CandidateConfig(),
    PROFILE_ACTIVE: CandidateConfig(
        signal_confirmation_bars=0,
        trend_slope_filter_enabled=False,
    ),
    PROFILE_LIVE_SIMPLE: CandidateConfig(
        signal_confirmation_bars=0,
        trend_filter_enabled=False,
        trend_slope_filter_enabled=False,
    ),
}


@dataclass
class PaperLiveState:
    cash: float
    position_qty: float
    entry_price: float
    last_processed_timestamp: int | None
    equity_peak: float
    kill_switch_active: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Runner single-run de paper trading con datos recientes de Binance. "
            "No envia ordenes reales."
        )
    )
    parser.add_argument("--symbol", default=CandidateConfig.symbol)
    parser.add_argument("--interval", default=CandidateConfig.binance_interval)
    parser.add_argument("--candle-count", type=int, default=CandidateConfig.candle_count)
    parser.add_argument("--historical-offset", type=int, default=0)
    parser.add_argument("--initial-cash", type=float, default=CandidateConfig.initial_cash)
    parser.add_argument("--fee-rate", type=float, default=CandidateConfig.fee_rate)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument(
        "--strategy-profile",
        choices=sorted(STRATEGY_PROFILES),
        default=PROFILE_CURRENT,
        help=(
            "Perfil de estrategia a usar: current mantiene la configuracion actual, "
            "active relaja confirmacion/pendiente, live_simple desactiva filtros de tendencia."
        ),
    )
    parser.add_argument(
        "--disable-state",
        action="store_true",
        help="Si se pasa, no lee/escribe estado JSON persistente.",
    )
    return parser.parse_args()


def resolve_candidate_config(args: argparse.Namespace) -> CandidateConfig:
    profile_config = STRATEGY_PROFILES[args.strategy_profile]
    return CandidateConfig(
        **{
            **asdict(profile_config),
            "symbol": args.symbol.upper(),
            "binance_interval": args.interval,
            "candle_count": args.candle_count,
            "fee_rate": args.fee_rate,
            "initial_cash": args.initial_cash,
        }
    )


def load_state(path: Path, *, initial_cash: float) -> PaperLiveState:
    if not path.exists():
        return PaperLiveState(
            cash=initial_cash,
            position_qty=0.0,
            entry_price=0.0,
            last_processed_timestamp=None,
            equity_peak=initial_cash,
            kill_switch_active=False,
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_last_processed = payload.get("last_processed_timestamp")
    if raw_last_processed is None:
        last_processed_timestamp = None
    else:
        last_processed_timestamp = int(raw_last_processed)
    return PaperLiveState(
        cash=float(payload.get("cash", initial_cash)),
        position_qty=float(payload.get("position_qty", 0.0)),
        entry_price=float(payload.get("entry_price", 0.0)),
        last_processed_timestamp=last_processed_timestamp,
        equity_peak=float(payload.get("equity_peak", initial_cash)),
        kill_switch_active=bool(payload.get("kill_switch_active", False)),
    )


def save_state(path: Path, state: PaperLiveState) -> None:
    path.write_text(
        json.dumps(asdict(state), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def append_log_row(
    path: Path,
    *,
    symbol: str,
    strategy_profile: str,
    signal: str,
    action_taken: str,
    price: float,
    position_qty: float,
    cash: float,
    equity: float,
    notes: str,
) -> None:
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "strategy_profile": strategy_profile,
        "signal": signal,
        "action_taken": action_taken,
        "price": f"{price:.8f}",
        "position_qty": f"{position_qty:.8f}",
        "cash": f"{cash:.8f}",
        "equity": f"{equity:.8f}",
        "notes": notes,
    }
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "timestamp",
                "symbol",
                "strategy_profile",
                "signal",
                "action_taken",
                "price",
                "position_qty",
                "cash",
                "equity",
                "notes",
            ],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def build_strategy(config: CandidateConfig) -> SMACrossStrategy:
    return SMACrossStrategy(
        short_window=config.short_window,
        long_window=config.long_window,
        trend_filter_enabled=config.trend_filter_enabled,
        trend_window=config.trend_window,
        trend_slope_filter_enabled=config.trend_slope_filter_enabled,
        trend_slope_lookback=config.trend_slope_lookback,
        volatility_filter_enabled=config.volatility_filter_enabled,
        regime_filter_enabled=config.regime_filter_enabled,
        signal_confirmation_bars=config.signal_confirmation_bars,
        warmup_bars=config.warmup_bars,
    )


def main() -> None:
    args = parse_args()
    config = resolve_candidate_config(args)
    strategy_profile = args.strategy_profile

    if config.market_data_mode != "binance_historical":
        raise ValueError("Este runner esta fijado a market_data_mode='binance_historical'.")

    if args.disable_state:
        state = PaperLiveState(
            cash=config.initial_cash,
            position_qty=0.0,
            entry_price=0.0,
            last_processed_timestamp=None,
            equity_peak=config.initial_cash,
            kill_switch_active=False,
        )
    else:
        state = load_state(args.state_path, initial_cash=config.initial_cash)
    broker = PaperBroker(
        cash=state.cash,
        fee_rate=config.fee_rate,
        position_size_pct=config.position_size_pct,
        position_qty=state.position_qty,
        entry_price=state.entry_price,
    )

    try:
        candles = fetch_historical_candles(
            symbol=config.symbol,
            interval=config.binance_interval,
            limit=config.candle_count,
            historical_offset=args.historical_offset,
            base_url=config.binance_spot_base_url,
        )
    except BinanceMarketDataError as exc:
        raise RuntimeError(f"No se pudieron obtener velas de Binance: {exc}") from exc

    if not candles:
        raise RuntimeError("No se recibieron velas para evaluar.")

    strategy = build_strategy(config)
    closes: list[float] = []
    current_signal = "hold"
    action_taken = "hold"
    notes = "no_new_candles"
    last_processed_timestamp = state.last_processed_timestamp
    equity_peak = state.equity_peak
    kill_switch_active = state.kill_switch_active

    for candle in candles:
        closes.append(candle.close)
        signal = strategy.signal(closes)

        if last_processed_timestamp is not None and candle.timestamp <= last_processed_timestamp:
            continue

        action_taken = "hold"
        current_signal = signal
        notes = ""

        if broker.position_qty > 0.0:
            stop_loss_price = broker.entry_price * (1.0 - config.stop_loss_pct)
            take_profit_price = broker.entry_price * (1.0 + config.take_profit_pct)
            if candle.low <= stop_loss_price:
                trade = broker.sell_all(stop_loss_price)
                if trade is not None:
                    action_taken = "sell"
                    notes = "stop_loss"
            elif candle.high >= take_profit_price:
                trade = broker.sell_all(take_profit_price)
                if trade is not None:
                    action_taken = "sell"
                    notes = "take_profit"

        if action_taken == "hold":
            if signal == "buy" and not kill_switch_active:
                trade = broker.buy_all(candle.close)
                if trade is not None:
                    action_taken = "buy"
                    notes = "signal"
            elif signal == "sell":
                trade = broker.sell_all(candle.close)
                if trade is not None:
                    action_taken = "sell"
                    notes = "signal"

        equity = broker.equity(candle.close)
        if equity > equity_peak:
            equity_peak = equity
        elif equity_peak > 0:
            drawdown_pct = ((equity_peak - equity) / equity_peak) * 100.0
            if (
                config.max_drawdown_limit_pct is not None
                and drawdown_pct >= config.max_drawdown_limit_pct
            ):
                kill_switch_active = True
                if notes:
                    notes = f"{notes};drawdown_kill_switch"
                else:
                    notes = "drawdown_kill_switch"

        last_processed_timestamp = candle.timestamp
        if action_taken == "hold" and not notes:
            notes = "signal_hold"

    latest_price = candles[-1].close
    final_equity = broker.equity(latest_price)

    if action_taken == "hold" and notes == "no_new_candles":
        current_signal = strategy.signal(closes)

    append_log_row(
        args.log_path,
        symbol=config.symbol,
        strategy_profile=strategy_profile,
        signal=current_signal,
        action_taken=action_taken,
        price=latest_price,
        position_qty=broker.position_qty,
        cash=broker.cash,
        equity=final_equity,
        notes=notes,
    )

    if not args.disable_state:
        save_state(
            args.state_path,
            PaperLiveState(
                cash=broker.cash,
                position_qty=broker.position_qty,
                entry_price=broker.entry_price,
                last_processed_timestamp=last_processed_timestamp,
                equity_peak=equity_peak,
                kill_switch_active=kill_switch_active,
            ),
        )

    position_state = "in_position" if broker.position_qty > 0 else "flat"
    print(f"symbol: {config.symbol}")
    print(f"strategy_profile: {strategy_profile}")
    print(f"current_price: {latest_price:.2f}")
    print(f"current_signal: {current_signal}")
    print(f"position_state: {position_state}")
    print(f"equity_estimated: {final_equity:.2f}")
    print(f"action_taken: {action_taken}")
    print(f"log_csv: {args.log_path}")
    if not args.disable_state:
        print(f"state_json: {args.state_path}")


if __name__ == "__main__":
    main()
