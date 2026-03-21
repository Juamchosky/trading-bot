import json
import urllib.error
import urllib.parse
import urllib.request

from bot.models import Candle


class BinanceMarketDataError(RuntimeError):
    pass


def fetch_historical_candles(
    *,
    symbol: str,
    interval: str,
    limit: int,
    base_url: str = "https://api.binance.com",
) -> list[Candle]:
    if limit <= 0:
        raise BinanceMarketDataError("limit must be greater than zero.")

    params = urllib.parse.urlencode(
        {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": str(limit),
        }
    )
    url = f"{base_url.rstrip('/')}/api/v3/klines?{params}"
    request = urllib.request.Request(url=url, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise BinanceMarketDataError(
            f"Binance market data error ({exc.code}): {details}"
        ) from exc
    except urllib.error.URLError as exc:
        raise BinanceMarketDataError(f"Network error calling Binance: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BinanceMarketDataError("Invalid JSON response from Binance.") from exc

    if not isinstance(payload, list) or not payload:
        raise BinanceMarketDataError("Binance returned no kline data.")

    candles: list[Candle] = []
    for index, entry in enumerate(payload):
        try:
            timestamp = int(entry[0])
            open_price = float(entry[1])
            high = float(entry[2])
            low = float(entry[3])
            close = float(entry[4])
            volume = float(entry[5])
        except (IndexError, TypeError, ValueError) as exc:
            raise BinanceMarketDataError("Unexpected kline format from Binance.") from exc
        candles.append(
            Candle(
                timestamp=timestamp,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                index=index,
            )
        )

    return candles
