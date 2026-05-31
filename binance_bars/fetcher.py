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
    start_ms = _to_ms(start)
    end_ms = _to_ms(end)

    all_rows: list = []
    cursor = start_ms  # None = "most recent" (no pagination needed)

    while True:
        params: dict = {"symbol": symbol, "interval": interval, "limit": _KLINE_LIMIT}
        if cursor is not None:
            params["startTime"] = cursor
        if end_ms is not None:
            params["endTime"] = end_ms

        rows = _http_get(url, params)
        if not rows:
            break
        all_rows.extend(rows)

        # Stop if we got fewer rows than the page limit — no more pages.
        if len(rows) < _KLINE_LIMIT:
            break

        # Advance cursor past the last candle's close_time.
        # rows[-1][6] is close_time (index 6 in Binance kline tuple).
        last_close_ms = int(rows[-1][6])
        cursor = last_close_ms + 1

        # If end_ms is set and we've already reached it, stop.
        if end_ms is not None and cursor > end_ms:
            break

    if not all_rows:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close",
                                      "volume", "close_time"])
    df = pd.DataFrame(all_rows, columns=[
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "_qav", "_ntrades", "_taker_base", "_taker_quote", "_ignore",
    ])
    df = df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    for c in ("open_time", "close_time"):
        df[c] = df[c].astype("int64")
    return df


def fetch_funding_rate(
    symbol: str,
    start: str | datetime | int | None = None,
    end: str | datetime | int | None = None,
) -> pd.DataFrame:
    """Fetch perpetual funding rate history (futures only)."""
    url = _BASE_URLS["futures"] + "/fapi/v1/fundingRate"
    params = {"symbol": symbol, "limit": 1000}
    if (s := _to_ms(start)) is not None:
        params["startTime"] = s
    if (e := _to_ms(end)) is not None:
        params["endTime"] = e
    rows = _http_get(url, params)
    if not rows:
        return pd.DataFrame(columns=["funding_time", "symbol", "funding_rate",
                                      "mark_price"])
    if len(rows) == 1000 and start is not None:
        logger.warning(
            "[fetch_funding_rate] response hit limit=1000 — results may be truncated; "
            "consider narrowing the time range."
        )
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "funding_time": df["fundingTime"].astype("int64"),
        "symbol": df["symbol"],
        "funding_rate": df["fundingRate"].astype(float),
        "mark_price": df["markPrice"].astype(float),
    })


def fetch_open_interest(
    symbol: str,
    period: str = "5m",
    start: str | datetime | int | None = None,
    end: str | datetime | int | None = None,
) -> pd.DataFrame:
    """Fetch open interest history (futures only).

    period: "5m" | "15m" | "30m" | "1h" | "2h" | "4h" | "6h" | "12h" | "1d"
    """
    url = _BASE_URLS["futures"] + "/futures/data/openInterestHist"
    params = {"symbol": symbol, "period": period, "limit": 500}
    if (s := _to_ms(start)) is not None:
        params["startTime"] = s
    if (e := _to_ms(end)) is not None:
        params["endTime"] = e
    rows = _http_get(url, params)
    if not rows:
        return pd.DataFrame(columns=["timestamp", "symbol", "open_interest",
                                      "open_interest_value"])
    if len(rows) == 500 and start is not None:
        logger.warning(
            "[fetch_open_interest] response hit limit=500 — results may be truncated; "
            "consider narrowing the time range."
        )
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "timestamp": df["timestamp"].astype("int64"),
        "symbol": df["symbol"],
        "open_interest": df["sumOpenInterest"].astype(float),
        "open_interest_value": df["sumOpenInterestValue"].astype(float),
    })


def fetch_basis(
    symbol: str,
    interval: str = "1d",
    pair_contract_type: str = "CURRENT_QUARTER",
    start: str | datetime | int | None = None,
    end: str | datetime | int | None = None,
) -> pd.DataFrame:
    """Fetch basis (futures - index) history.

    symbol: base symbol e.g. "BTC" (passed as `pair=BTCUSDT`)
    pair_contract_type: "CURRENT_QUARTER" | "NEXT_QUARTER" | "PERPETUAL"
    """
    url = _BASE_URLS["futures"] + "/futures/data/basis"
    params = {
        "pair": f"{symbol}USDT",
        "contractType": pair_contract_type,
        "period": interval,
        "limit": 500,
    }
    if (s := _to_ms(start)) is not None:
        params["startTime"] = s
    if (e := _to_ms(end)) is not None:
        params["endTime"] = e
    rows = _http_get(url, params)
    if not rows:
        return pd.DataFrame(columns=["timestamp", "pair", "futures_price",
                                      "index_price", "basis", "basis_rate"])
    if len(rows) == 500 and start is not None:
        logger.warning(
            "[fetch_basis] response hit limit=500 — results may be truncated; "
            "consider narrowing the time range."
        )
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "timestamp": df["timestamp"].astype("int64"),
        "pair": df["pair"],
        "futures_price": df["futuresPrice"].astype(float),
        "index_price": df["indexPrice"].astype(float),
        "basis": df["basis"].astype(float),
        "basis_rate": df["basisRate"].astype(float),
    })
