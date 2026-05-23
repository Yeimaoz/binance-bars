"""Binance public-API klines + symbols fetcher.

Endpoints:
- Spot:    GET https://api.binance.com/api/v3/klines + /exchangeInfo
- Futures: GET https://fapi.binance.com/fapi/v1/klines + /exchangeInfo
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

from binance_bars.rate_limit import get_with_backoff

logger = logging.getLogger(__name__)

Market = Literal["spot", "futures"]

_BASE_URLS = {
    "spot": "https://api.binance.com",
    "futures": "https://fapi.binance.com",
}

_KLINES_PATH = {
    "spot": "/api/v3/klines",
    "futures": "/fapi/v1/klines",
}

_EXCHANGE_INFO_PATH = {
    "spot": "/api/v3/exchangeInfo",
    "futures": "/fapi/v1/exchangeInfo",
}

_KLINE_LIMIT = 1000  # max candles per request


def _to_ms(t: str | datetime | int | None) -> int | None:
    """Convert flexible time input → unix ms int."""
    if t is None:
        return None
    if isinstance(t, int):
        return t
    if isinstance(t, str):
        # parse YYYY-MM-DD or ISO datetime
        t = datetime.fromisoformat(t)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return int(t.timestamp() * 1000)


def _http_get(url: str, params: dict) -> dict | list:
    """GET with rate-limit handling + JSON parse."""
    resp = get_with_backoff(url, params)
    return resp.json()


def list_symbols(
    market: Market = "futures",
    quote: str | None = None,
    trading_only: bool = True,
) -> list[str]:
    """List symbols on a given market.

    Args:
        market: "spot" | "futures"
        quote: filter by quote asset (e.g. "USDT"). None = no filter.
        trading_only: keep only symbols with status="TRADING".
    """
    if market not in _BASE_URLS:
        raise ValueError(f"unknown market: {market!r}")
    url = _BASE_URLS[market] + _EXCHANGE_INFO_PATH[market]
    data = _http_get(url, {})
    out = []
    for s in data.get("symbols", []):
        if trading_only and s.get("status") != "TRADING":
            continue
        if quote is not None and s.get("quoteAsset") != quote:
            continue
        out.append(s["symbol"])
    return out


def fetch_klines(
    market: Market,
    symbol: str,
    interval: str,
    start: str | datetime | int | None = None,
    end: str | datetime | int | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV klines from Binance public API.

    Args:
        market: "spot" | "futures"
        symbol: e.g. "BTCUSDT"
        interval: "1m" | "5m" | "15m" | "1h" | "4h" | "1d" (passes through to API)
        start: optional. str date | datetime | int (ms). Defaults to most-recent 1000.
        end: optional. None = now.

    Returns:
        DataFrame with columns: open_time, open, high, low, close, volume, close_time
        open_time / close_time = int ms UTC; OHLCV = float
    """
    if market not in _BASE_URLS:
        raise ValueError(f"unknown market: {market!r}")
    url = _BASE_URLS[market] + _KLINES_PATH[market]
    params = {"symbol": symbol, "interval": interval, "limit": _KLINE_LIMIT}
    start_ms = _to_ms(start)
    end_ms = _to_ms(end)
    if start_ms is not None:
        params["startTime"] = start_ms
    if end_ms is not None:
        params["endTime"] = end_ms
    rows = _http_get(url, params)
    if not rows:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close",
                                      "volume", "close_time"])
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "_qav", "_ntrades", "_taker_base", "_taker_quote", "_ignore",
    ])
    df = df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    for c in ("open_time", "close_time"):
        df[c] = df[c].astype("int64")
    return df
