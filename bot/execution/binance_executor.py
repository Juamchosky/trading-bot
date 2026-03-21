import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class BinanceExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class BinanceOrderRequest:
    symbol: str
    side: str
    order_type: str = "MARKET"
    quantity: str = "0"


class BinanceExecutor:
    """Binance Spot executor with safe defaults for Testnet."""

    def __init__(
        self,
        *,
        base_url: str = "https://testnet.binance.vision",
        live_trading_enabled: bool = False,
        allowed_symbols: tuple[str, ...] = ("BTCUSDT",),
        max_order_size: float = 0.01,
        recv_window_ms: int = 5_000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.live_trading_enabled = live_trading_enabled
        self.allowed_symbols = {symbol.upper() for symbol in allowed_symbols}
        self.max_order_size = Decimal(str(max_order_size))
        self.recv_window_ms = recv_window_ms

        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_API_SECRET")
        if not self.api_key or not self.api_secret:
            raise BinanceExecutionError(
                "Missing BINANCE_API_KEY or BINANCE_API_SECRET environment variables."
            )

    def test_order(self, order: BinanceOrderRequest) -> dict:
        """Sends a test order to /api/v3/order/test (does not execute trades)."""
        params = self._build_order_params(order)
        return self._signed_request("POST", "/api/v3/order/test", params)

    def place_order(self, order: BinanceOrderRequest) -> dict:
        """Places a live order only when explicitly enabled."""
        if not self.live_trading_enabled:
            raise BinanceExecutionError(
                "Live trading is disabled. Set live_trading_enabled=True to place real orders."
            )
        params = self._build_order_params(order)
        return self._signed_request("POST", "/api/v3/order", params)

    def _build_order_params(self, order: BinanceOrderRequest) -> dict[str, str]:
        symbol = order.symbol.upper()
        side = order.side.upper()
        order_type = order.order_type.upper()
        quantity = self._parse_quantity(order.quantity)

        if symbol not in self.allowed_symbols:
            raise BinanceExecutionError(
                f"Symbol {symbol} not allowed. Allowed symbols: {sorted(self.allowed_symbols)}"
            )
        if quantity <= Decimal("0"):
            raise BinanceExecutionError("Order quantity must be greater than zero.")
        if quantity > self.max_order_size:
            raise BinanceExecutionError(
                f"Order quantity {quantity} exceeds max_order_size {self.max_order_size}."
            )
        if side not in {"BUY", "SELL"}:
            raise BinanceExecutionError("Order side must be BUY or SELL.")

        return {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": self._normalize_decimal(quantity),
            "recvWindow": str(self.recv_window_ms),
            "timestamp": str(int(time.time() * 1000)),
        }

    def _signed_request(
        self,
        method: str,
        path: str,
        params: dict[str, str],
    ) -> dict:
        query_string = urllib.parse.urlencode(params, safe=".")
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        body = f"{query_string}&signature={signature}".encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise BinanceExecutionError(
                f"Binance API error ({exc.code}) on {path}: {details}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BinanceExecutionError(f"Network error calling Binance: {exc}") from exc

    @staticmethod
    def _parse_quantity(value: str) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise BinanceExecutionError(f"Invalid quantity: {value}") from exc

    @staticmethod
    def _normalize_decimal(value: Decimal) -> str:
        return format(value.normalize(), "f")
