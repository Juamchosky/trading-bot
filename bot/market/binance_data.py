import json
import urllib.error
import urllib.parse
import urllib.request

from bot.models import Candle


_MAX_KLINE_BATCH_LIMIT = 1000


class BinanceMarketDataError(RuntimeError):
    pass


def fetch_historical_candles(
    *,
    symbol: str,
    interval: str,
    limit: int,
    historical_offset: int = 0,
    base_url: str = "https://api.binance.com",
) -> list[Candle]:
    if limit <= 0:
        raise BinanceMarketDataError("limit must be greater than zero.")
    if historical_offset < 0:
        raise BinanceMarketDataError("historical_offset must be zero or greater.")

    requested_limit = limit + historical_offset
    raw_batches: list[list[object]] = []
    oldest_open_time: int | None = None

    while len(raw_batches) < requested_limit:
        batch_limit = min(_MAX_KLINE_BATCH_LIMIT, requested_limit - len(raw_batches))
        payload = _fetch_kline_batch(
            symbol=symbol,
            interval=interval,
            limit=batch_limit,
            end_time=oldest_open_time - 1 if oldest_open_time is not None else None,
            base_url=base_url,
        )
        if not payload:
            break

        if oldest_open_time is not None:
            payload = [
                entry
                for entry in payload
                if _extract_open_time(entry) < oldest_open_time
            ]
        if not payload:
            break

        raw_batches = payload + raw_batches
        oldest_open_time = _extract_open_time(payload[0])

        if len(payload) < batch_limit:
            break

    if not raw_batches:
        raise BinanceMarketDataError("Binance returned no kline data.")

    candles: list[Candle] = []
    for index, entry in enumerate(raw_batches[-requested_limit:]):
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

    if historical_offset == 0:
        return candles

    # Apply the offset from the most recent candle backwards, then restore
    # chronological order for the rest of the engine.
    recent_first = list(reversed(candles))
    selected = list(reversed(recent_first[historical_offset : historical_offset + limit]))

    return [
        Candle(
            timestamp=candle.timestamp,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            index=index,
        )
        for index, candle in enumerate(selected)
    ]


def _fetch_kline_batch(
    *,
    symbol: str,
    interval: str,
    limit: int,
    end_time: int | None,
    base_url: str,
) -> list[list[object]]:
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": str(limit),
    }
    if end_time is not None:
        params["endTime"] = str(end_time)

    url = f"{base_url.rstrip('/')}/api/v3/klines?{urllib.parse.urlencode(params)}"
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

    if not isinstance(payload, list):
        raise BinanceMarketDataError("Unexpected kline payload from Binance.")

    return payload


def _extract_open_time(entry: object) -> int:
    try:
        return int(entry[0])  # type: ignore[index]
    except (IndexError, TypeError, ValueError) as exc:
        raise BinanceMarketDataError("Unexpected kline format from Binance.") from exc
