from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path

from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.strategy.sma_cross import SMACrossStrategy

LOG_PATH = Path("binance_live_log.csv")
STATE_PATH = Path("binance_live_state.json")
PROFILE_CURRENT = "current"
PROFILE_ACTIVE = "active"
PROFILE_LIVE_SIMPLE = "live_simple"


class BinanceLiveRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateConfig:
    symbol: str = "BTCUSDT"
    short_window: int = 5
    long_window: int = 20
    stop_loss_pct: float = 0.01
    take_profit_pct: float = 0.05
    signal_confirmation_bars: int = 1
    position_size_pct: float = 0.5
    max_drawdown_limit_pct: float = 1.5
    trend_filter_enabled: bool = True
    trend_window: int = 50
    trend_slope_filter_enabled: bool = True
    trend_slope_lookback: int = 3
    volatility_filter_enabled: bool = False
    regime_filter_enabled: bool = False
    warmup_bars: int = 0
    binance_interval: str = "1h"
    candle_count: int = 300
    base_url: str = "https://api.binance.com"


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
class LiveState:
    last_action: str
    last_position_known: float
    equity_peak: float
    kill_switch_active: bool
    last_entry_price: float
    api_failure_count: int


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    base_asset: str
    quote_asset: str
    min_qty: Decimal
    step_size: Decimal
    tick_size: Decimal
    min_notional: Decimal


@dataclass(frozen=True)
class AccountSnapshot:
    base_free: Decimal
    base_locked: Decimal
    quote_free: Decimal
    quote_locked: Decimal

    @property
    def base_total(self) -> Decimal:
        return self.base_free + self.base_locked

    @property
    def quote_total(self) -> Decimal:
        return self.quote_free + self.quote_locked


class BinanceSpotClient:
    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_API_SECRET")
        if not self.api_key or not self.api_secret:
            raise BinanceLiveRunnerError(
                "Missing BINANCE_API_KEY or BINANCE_API_SECRET environment variables."
            )

    def _public_request(self, *, method: str, path: str, params: dict[str, str]) -> dict:
        query = urllib.parse.urlencode(params, safe=".")
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(url=url, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise BinanceLiveRunnerError(
                f"Binance public API error ({exc.code}) on {path}: {details}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BinanceLiveRunnerError(f"Network error calling Binance: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BinanceLiveRunnerError("Invalid JSON response from Binance.") from exc

class BinanceSpotClient:
    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_API_SECRET")
        if not self.api_key or not self.api_secret:
            raise BinanceLiveRunnerError(
                "Missing BINANCE_API_KEY or BINANCE_API_SECRET environment variables."
            )

    def _public_request(self, *, method: str, path: str, params: dict[str, str]) -> dict:
        query = urllib.parse.urlencode(params, safe=".")
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(url=url, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise BinanceLiveRunnerError(
                f"Binance public API error ({exc.code}) on {path}: {details}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BinanceLiveRunnerError(f"Network error calling Binance: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BinanceLiveRunnerError("Invalid JSON response from Binance.") from exc


    def _signed_request(self, *, method: str, path: str, params: dict[str, str]) -> dict:
        signed_params = {
            **params,
            "recvWindow": "5000",
            "timestamp": str(int(time.time() * 1000)),
        }

        query_string = urllib.parse.urlencode(signed_params, safe=".")
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        final_query = f"{query_string}&signature={signature}"

        if method.upper() == "GET":
            url = f"{self.base_url}{path}?{final_query}"
            request = urllib.request.Request(
                url=url,
                method="GET",
                headers={
                    "X-MBX-APIKEY": self.api_key,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        else:
            body = final_query.encode("utf-8")
            request = urllib.request.Request(
                url=f"{self.base_url}{path}",
                data=body,
                method=method.upper(),
                headers={
                    "X-MBX-APIKEY": self.api_key,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise BinanceLiveRunnerError(
                f"Binance signed API error ({exc.code}) on {path}: {details}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BinanceLiveRunnerError(f"Network error calling Binance: {exc}") from exc
            

    def get_symbol_rules(self, symbol: str) -> SymbolRules:
        payload = self._public_request(
            method="GET",
            path="/api/v3/exchangeInfo",
            params={"symbol": symbol.upper()},
        )
        symbols = payload.get("symbols", [])
        if not symbols:
            raise BinanceLiveRunnerError(f"Symbol {symbol.upper()} not found on Binance Spot.")
        symbol_info = symbols[0]
        filters = {entry.get("filterType"): entry for entry in symbol_info.get("filters", [])}
        lot_filter = filters.get("LOT_SIZE")
        price_filter = filters.get("PRICE_FILTER")
        min_notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL")
        if lot_filter is None or price_filter is None or min_notional_filter is None:
            raise BinanceLiveRunnerError("Unable to parse symbol filters from exchangeInfo.")
        return SymbolRules(
            symbol=symbol_info["symbol"],
            base_asset=symbol_info["baseAsset"],
            quote_asset=symbol_info["quoteAsset"],
            min_qty=_parse_decimal(lot_filter["minQty"]),
            step_size=_parse_decimal(lot_filter["stepSize"]),
            tick_size=_parse_decimal(price_filter["tickSize"]),
            min_notional=_parse_decimal(min_notional_filter["minNotional"]),
        )

    def get_account_snapshot(self, *, base_asset: str, quote_asset: str) -> AccountSnapshot:
        payload = self._signed_request(method="GET", path="/api/v3/account", params={})
        balances = payload.get("balances", [])
        balance_map = {entry.get("asset"): entry for entry in balances}
        base = balance_map.get(base_asset, {"free": "0", "locked": "0"})
        quote = balance_map.get(quote_asset, {"free": "0", "locked": "0"})
        return AccountSnapshot(
            base_free=_parse_decimal(base.get("free", "0")),
            base_locked=_parse_decimal(base.get("locked", "0")),
            quote_free=_parse_decimal(quote.get("free", "0")),
            quote_locked=_parse_decimal(quote.get("locked", "0")),
        )

    def place_market_order(self, *, symbol: str, side: str, quantity: Decimal) -> dict:
        if quantity <= Decimal("0"):
            raise BinanceLiveRunnerError("Order quantity must be > 0.")
        return self._signed_request(
            method="POST",
            path="/api/v3/order",
            params={
                "symbol": symbol.upper(),
                "side": side.upper(),
                "type": "MARKET",
                "quantity": _normalize_decimal(quantity),
            },
        )

    def _public_request(self, *, method: str, path: str, params: dict[str, str]) -> dict:
        query = urllib.parse.urlencode(params, safe=".")
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(url=url, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise BinanceLiveRunnerError(
                f"Binance public API error ({exc.code}) on {path}: {details}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BinanceLiveRunnerError(f"Network error calling Binance: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BinanceLiveRunnerError("Invalid JSON response from Binance.") from exc

def _signed_request(self, *, method: str, path: str, params: dict[str, str]) -> dict:
    signed_params = {
        **params,
        "recvWindow": "5000",
        "timestamp": str(int(time.time() * 1000)),
    }

    query_string = urllib.parse.urlencode(signed_params, safe=".")
    signature = hmac.new(
        self.api_secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    final_query = f"{query_string}&signature={signature}"

    # ✅ GET: firma en URL, SIN body
    if method.upper() == "GET":
        url = f"{self.base_url}{path}?{final_query}"
        request = urllib.request.Request(
            url=url,
            method="GET",
            headers={
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    else:
        # ✅ POST: firma en body
        body = final_query.encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            method=method.upper(),
            headers={
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise BinanceLiveRunnerError(
            f"Binance signed API error ({exc.code}) on {path}: {details}"
        ) from exc
    except urllib.error.URLError as exc:
        raise BinanceLiveRunnerError(f"Network error calling Binance: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Runner real-controlado para Binance Spot con safety gates y trazabilidad."
    )
    parser.add_argument("--symbol", default=CandidateConfig.symbol)
    parser.add_argument("--interval", default=CandidateConfig.binance_interval)
    parser.add_argument("--candle-count", type=int, default=CandidateConfig.candle_count)
    parser.add_argument("--max-usd-notional", type=float, default=100.0)
    parser.add_argument("--max-api-failures", type=int, default=3)
    parser.add_argument("--min-position-qty", type=float, default=1e-8)
    parser.add_argument("--base-url", default=CandidateConfig.base_url)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--disable-state", action="store_true")
    parser.add_argument("--live", action="store_true", help="Habilita ordenes reales.")
    parser.add_argument("--dry-run", action="store_true", help="Fuerza modo dry-run.")
    parser.add_argument(
        "--strategy-profile",
        choices=sorted(STRATEGY_PROFILES),
        default=PROFILE_CURRENT,
        help=(
            "Perfil de estrategia a usar: current mantiene la configuracion actual, "
            "active relaja confirmacion/pendiente, live_simple desactiva filtros de tendencia."
        ),
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
            "base_url": args.base_url,
        }
    )


def load_state(path: Path) -> LiveState:
    if not path.exists():
        return LiveState(
            last_action="none",
            last_position_known=0.0,
            equity_peak=0.0,
            kill_switch_active=False,
            last_entry_price=0.0,
            api_failure_count=0,
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return LiveState(
        last_action=str(payload.get("last_action", "none")),
        last_position_known=float(payload.get("last_position_known", 0.0)),
        equity_peak=float(payload.get("equity_peak", 0.0)),
        kill_switch_active=bool(payload.get("kill_switch_active", False)),
        last_entry_price=float(payload.get("last_entry_price", 0.0)),
        api_failure_count=int(payload.get("api_failure_count", 0)),
    )


def save_state(path: Path, state: LiveState) -> None:
    path.write_text(json.dumps(asdict(state), ensure_ascii=True, indent=2), encoding="utf-8")


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


def append_log_row(
    path: Path,
    *,
    symbol: str,
    strategy_profile: str,
    mode: str,
    signal: str,
    action_taken: str,
    price_reference: float,
    quantity: Decimal,
    cash_estimated: Decimal,
    position_qty: Decimal,
    equity_estimated: Decimal,
    status: str,
    notes: str,
) -> None:
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "strategy_profile": strategy_profile,
        "mode": mode,
        "signal": signal,
        "action_taken": action_taken,
        "price_reference": f"{price_reference:.8f}",
        "quantity": _normalize_decimal(quantity),
        "cash_estimated": _normalize_decimal(cash_estimated),
        "position_qty": _normalize_decimal(position_qty),
        "equity_estimated": _normalize_decimal(equity_estimated),
        "status": status,
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
                "mode",
                "signal",
                "action_taken",
                "price_reference",
                "quantity",
                "cash_estimated",
                "position_qty",
                "equity_estimated",
                "status",
                "notes",
            ],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def quantize_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= Decimal("0"):
        return value
    units = (value / step).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return (units * step).quantize(step)


def safe_call(state: LiveState, max_failures: int, fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        state.api_failure_count = 0
        return result
    except Exception:
        state.api_failure_count += 1
        if state.api_failure_count >= max_failures:
            state.kill_switch_active = True
        raise


def main() -> None:
    args = parse_args()
    live_mode = bool(args.live and not args.dry_run)
    mode_label = "live" if live_mode else "dry-run"
    if args.max_api_failures <= 0:
        raise BinanceLiveRunnerError("--max-api-failures must be greater than zero.")
    if args.max_usd_notional <= 0:
        raise BinanceLiveRunnerError("--max-usd-notional must be greater than zero.")

    config = resolve_candidate_config(args)
    strategy_profile = args.strategy_profile
    strategy = build_strategy(config)
    state = load_state(args.state_path) if not args.disable_state else LiveState(
        last_action="none",
        last_position_known=0.0,
        equity_peak=0.0,
        kill_switch_active=False,
        last_entry_price=0.0,
        api_failure_count=0,
    )

    signal = "hold"
    action_taken = "hold"
    status = "ok"
    notes: list[str] = []
    order_qty = Decimal("0")
    reference_price_float = 0.0
    final_position = Decimal("0")
    final_cash = Decimal("0")
    final_equity = Decimal("0")

    try:
        client = BinanceSpotClient(base_url=config.base_url)
        symbol_rules = safe_call(
            state, args.max_api_failures, client.get_symbol_rules, config.symbol
        )
        candles = safe_call(
            state,
            args.max_api_failures,
            fetch_historical_candles,
            symbol=config.symbol,
            interval=config.binance_interval,
            limit=config.candle_count,
            base_url=config.base_url,
        )
        if not candles:
            raise BinanceLiveRunnerError("No candles received from Binance.")
        closes = [candle.close for candle in candles]
        signal = strategy.signal(closes)
        last_candle = candles[-1]
        reference_price = Decimal(str(last_candle.close))
        tick_adjusted_price = quantize_step(reference_price, symbol_rules.tick_size)
        reference_price_float = float(tick_adjusted_price)

        account = safe_call(
            state,
            args.max_api_failures,
            client.get_account_snapshot,
            base_asset=symbol_rules.base_asset,
            quote_asset=symbol_rules.quote_asset,
        )

        min_position_qty = Decimal(str(args.min_position_qty))
        in_position = account.base_total > min_position_qty
        if state.last_position_known < 0:
            state.kill_switch_active = True
            notes.append("state_reconciliation_failed")
            status = "kill_switch"

        cash_estimated = account.quote_total
        equity_estimated = cash_estimated + (account.base_total * reference_price)
        
        peak = Decimal(str(state.equity_peak))
        if state.equity_peak <= Decimal ("0"):
            state.equity_peak = float(equity_estimated)
            peak = Decimal (str(state.equity_peak))

        if equity_estimated > peak:
            state.equity_peak = float(equity_estimated)
        else:
            if peak > Decimal("0"):
                drawdown = ((peak - equity_estimated) / peak) * Decimal ("100")
                if drawdown >= Decimal(str(config.max_drawdown_limit_pct)):
                    state.kill_switch_active = True
                    status = "kill_switch"
                    notes.append("drawdown_kill_switch")
                    
            stop_loss_hit = False
            take_profit_hit = False
        if in_position and state.last_entry_price > 0:
            entry = Decimal(str(state.last_entry_price))
            stop_level = entry * (Decimal("1") - Decimal(str(config.stop_loss_pct)))
            take_level = entry * (Decimal("1") + Decimal(str(config.take_profit_pct)))
            if reference_price <= stop_level:
                stop_loss_hit = True
            elif reference_price >= take_level:
                take_profit_hit = True

        desired_action = "hold"
        if stop_loss_hit:
            desired_action = "sell"
            notes.append("stop_loss")
        elif take_profit_hit:
            desired_action = "sell"
            notes.append("take_profit")
        elif signal == "buy":
            desired_action = "buy"
        elif signal == "sell":
            desired_action = "sell"

        if state.kill_switch_active:
            desired_action = "hold"
            action_taken = "hold"
            status = "kill_switch"
            if "kill_switch_active" not in notes:
                notes.append("kill_switch_active")
        elif desired_action == "buy":
            if in_position:
                action_taken = "hold"
                status = "blocked"
                notes.append("already_in_position")
            else:
                max_usd_notional = Decimal(str(args.max_usd_notional))
                budget = min(
                    max_usd_notional,
                    account.quote_free * Decimal(str(config.position_size_pct)),
                )
                tentative_qty = quantize_step(budget / reference_price, symbol_rules.step_size)
                notional = tentative_qty * reference_price
                if tentative_qty < symbol_rules.min_qty:
                    action_taken = "hold"
                    status = "blocked"
                    notes.append("below_min_qty")
                elif notional < symbol_rules.min_notional:
                    action_taken = "hold"
                    status = "blocked"
                    notes.append("below_min_notional")
                elif tentative_qty <= Decimal("0"):
                    action_taken = "hold"
                    status = "blocked"
                    notes.append("non_positive_qty")
                else:
                    order_qty = tentative_qty
                    if live_mode:
                        safe_call(
                            state,
                            args.max_api_failures,
                            client.place_market_order,
                            symbol=config.symbol,
                            side="BUY",
                            quantity=order_qty,
                        )
                        action_taken = "buy"
                        state.last_entry_price = float(reference_price)
                        notes.append("market_buy_sent")
                    else:
                        action_taken = "buy"
                        state.last_entry_price = float(reference_price)
                        notes.append("dry_run_buy")
        elif desired_action == "sell":
            if not in_position:
                action_taken = "hold"
                status = "blocked"
                notes.append("no_position_to_sell")
            else:
                tentative_qty = quantize_step(account.base_free, symbol_rules.step_size)
                notional = tentative_qty * reference_price
                if tentative_qty < symbol_rules.min_qty:
                    action_taken = "hold"
                    status = "blocked"
                    notes.append("below_min_qty_sell")
                elif notional < symbol_rules.min_notional:
                    action_taken = "hold"
                    status = "blocked"
                    notes.append("below_min_notional_sell")
                else:
                    order_qty = tentative_qty
                    if live_mode:
                        safe_call(
                            state,
                            args.max_api_failures,
                            client.place_market_order,
                            symbol=config.symbol,
                            side="SELL",
                            quantity=order_qty,
                        )
                        action_taken = "sell"
                        state.last_entry_price = 0.0
                        notes.append("market_sell_sent")
                    else:
                        action_taken = "sell"
                        state.last_entry_price = 0.0
                        notes.append("dry_run_sell")
        else:
            action_taken = "hold"
            if not notes:
                notes.append("signal_hold")

        if action_taken in {"buy", "sell"}:
            post_account = safe_call(
                state,
                args.max_api_failures,
                client.get_account_snapshot,
                base_asset=symbol_rules.base_asset,
                quote_asset=symbol_rules.quote_asset,
            )
        else:
            post_account = account

        final_position = post_account.base_total
        final_cash = post_account.quote_total
        final_equity = final_cash + (final_position * reference_price)
        state.last_action = action_taken
        state.last_position_known = float(final_position)

        append_log_row(
            args.log_path,
            symbol=config.symbol,
            strategy_profile=strategy_profile,
            mode=mode_label,
            signal=signal,
            action_taken=action_taken,
            price_reference=reference_price_float,
            quantity=order_qty,
            cash_estimated=final_cash,
            position_qty=final_position,
            equity_estimated=final_equity,
            status=status,
            notes=";".join(notes),
        )

        if not args.disable_state:
            save_state(args.state_path, state)

        print(f"symbol: {config.symbol}")
        print(f"strategy_profile: {strategy_profile}")
        print(f"mode: {mode_label}")
        print(f"signal: {signal}")
        print(f"action_taken: {action_taken}")
        print(f"position_qty: {_normalize_decimal(final_position)} {symbol_rules.base_asset}")
        print(f"cash_estimated: {_normalize_decimal(final_cash)} {symbol_rules.quote_asset}")
        print(f"equity_estimated: {_normalize_decimal(final_equity)} {symbol_rules.quote_asset}")
        print(f"kill_switch_active: {state.kill_switch_active}")
        print(f"notes: {';'.join(notes)}")
        print(f"log_csv: {args.log_path}")
        if not args.disable_state:
            print(f"state_json: {args.state_path}")
    except (BinanceMarketDataError, BinanceLiveRunnerError, InvalidOperation) as exc:
        state.kill_switch_active = True
        state.last_action = "hold"
        status = "error"
        notes.append(f"error:{exc}")
        try:
            append_log_row(
                args.log_path,
                symbol=config.symbol,
                strategy_profile=strategy_profile,
                mode=mode_label,
                signal=signal,
                action_taken="hold",
                price_reference=reference_price_float,
                quantity=Decimal("0"),
                cash_estimated=final_cash,
                position_qty=final_position,
                equity_estimated=final_equity,
                status=status,
                notes=";".join(notes),
            )
        except Exception:
            pass
        if not args.disable_state:
            save_state(args.state_path, state)
        raise RuntimeError(f"Runner stopped by safety guard: {exc}") from exc


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BinanceLiveRunnerError(f"Invalid numeric value from Binance: {value}") from exc


def _normalize_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


if __name__ == "__main__":
    main()
