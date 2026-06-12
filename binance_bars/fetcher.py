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
    """Convert flexible time input → unix milliseconds int.

    Args:
        t: One of:
            - ``None`` — returned as-is (means "no bound").
            - ``str``  — ISO date or datetime (e.g. ``"2024-01-01"``); parsed as UTC.
            - ``datetime`` — naive datetimes are assumed UTC.
            - ``int`` — **must be unix milliseconds** (e.g. 1_704_067_200_000).
              Passing a unix-seconds value (e.g. ``int(time.time())`` ≈ 1_704_067_200)
              is silently wrong: it would be interpreted as a timestamp in January 1970.
              Values below 10_000_000_000 (< year 2286 in ms, > year 2001 in seconds)
              trigger a warning to catch the common mistake of passing seconds.

    Returns:
        Unix milliseconds as int, or None.
    """
    if t is None:
        return None
    if isinstance(t, int):
        if t < 10_000_000_000:  # likely seconds (year 2001 boundary)
            logger.warning(
                "_to_ms received int %d which looks like unix seconds, not milliseconds. "
                "Pass unix milliseconds (multiply by 1000) to avoid silently fetching "
                "wrong time range.", t
            )
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
    """Fetch OHLCV klines from Binance public API with automatic pagination.

    Binance returns at most ``_KLINE_LIMIT`` (1000) candles per request.
    This function issues additional requests whenever a full batch is returned,
    advancing the ``startTime`` to the close_time of the last bar + 1 ms, until
    the batch is smaller than the limit or all data up to *end* is collected.

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
    next_start = start_ms

    while True:
        params: dict = {"symbol": symbol, "interval": interval, "limit": _KLINE_LIMIT}
        if next_start is not None:
            params["startTime"] = next_start
        if end_ms is not None:
            params["endTime"] = end_ms

        rows = _http_get(url, params)
        if not rows:
            break
        all_rows.extend(rows)

        # If we received a full batch and there is a defined end boundary that
        # hasn't been reached yet, advance the cursor and fetch the next page.
        if len(rows) == _KLINE_LIMIT:
            last_close_time = int(rows[-1][6])  # close_time is index 6 in raw row
            if end_ms is None or last_close_time < end_ms:
                next_start = last_close_time + 1
                continue
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


_FUNDING_LIMIT = 1000  # Binance fundingRate max per request (single request, no pagination)


def fetch_funding_rate(
    symbol: str,
    start: str | datetime | int | None = None,
    end: str | datetime | int | None = None,
) -> pd.DataFrame:
    """Fetch perpetual funding rate history (futures only).

    Single request, max ``_FUNDING_LIMIT`` records; a full batch with a start
    bound triggers a truncation warning (see README API limits table).
    """
    url = _BASE_URLS["futures"] + "/fapi/v1/fundingRate"
    params = {"symbol": symbol, "limit": _FUNDING_LIMIT}
    if (s := _to_ms(start)) is not None:
        params["startTime"] = s
    if (e := _to_ms(end)) is not None:
        params["endTime"] = e
    rows = _http_get(url, params)
    if not rows:
        return pd.DataFrame(columns=["funding_time", "symbol", "funding_rate",
                                      "mark_price"])
    if len(rows) == _FUNDING_LIMIT and "startTime" in params:
        logger.warning(
            "[fetch_funding_rate] response hit limit=%d; results may be "
            "truncated, narrow the time range to fetch the rest",
            _FUNDING_LIMIT,
        )
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "funding_time": df["fundingTime"].astype("int64"),
        "symbol": df["symbol"],
        "funding_rate": df["fundingRate"].astype(float),
        "mark_price": df["markPrice"].astype(float),
    })


_OI_LIMIT = 500  # Binance openInterestHist max per request


def fetch_open_interest(
    symbol: str,
    period: str = "5m",
    start: str | datetime | int | None = None,
    end: str | datetime | int | None = None,
) -> pd.DataFrame:
    """Fetch open interest history (futures only) with automatic pagination.

    Binance ``openInterestHist`` returns at most 500 records per request.
    This function pages through results by advancing ``startTime`` to the
    last returned timestamp + 1 ms whenever a full batch is returned.

    period: "5m" | "15m" | "30m" | "1h" | "2h" | "4h" | "6h" | "12h" | "1d"
    """
    url = _BASE_URLS["futures"] + "/futures/data/openInterestHist"
    end_ms = _to_ms(end)
    next_start = _to_ms(start)

    all_batches: list[pd.DataFrame] = []

    while True:
        params: dict = {"symbol": symbol, "period": period, "limit": _OI_LIMIT}
        if next_start is not None:
            params["startTime"] = next_start
        if end_ms is not None:
            params["endTime"] = end_ms

        rows = _http_get(url, params)
        if not rows:
            break

        batch_df = pd.DataFrame(rows)
        all_batches.append(pd.DataFrame({
            "timestamp": batch_df["timestamp"].astype("int64"),
            "symbol": batch_df["symbol"],
            "open_interest": batch_df["sumOpenInterest"].astype(float),
            "open_interest_value": batch_df["sumOpenInterestValue"].astype(float),
        }))

        if len(rows) == _OI_LIMIT:
            last_ts = int(rows[-1]["timestamp"])
            if end_ms is None or last_ts < end_ms:
                next_start = last_ts + 1
                continue
        break

    if not all_batches:
        return pd.DataFrame(columns=["timestamp", "symbol", "open_interest",
                                      "open_interest_value"])
    return pd.concat(all_batches, ignore_index=True)


_BASIS_LIMIT = 500  # Binance basis max per request (single request, no pagination)


def fetch_basis(
    symbol: str,
    interval: str = "1d",
    pair_contract_type: str = "CURRENT_QUARTER",
    start: str | datetime | int | None = None,
    end: str | datetime | int | None = None,
) -> pd.DataFrame:
    """Fetch basis (futures - index) history.

    symbol: base symbol e.g. "BTC" (passed as ``pair=BTCUSDT``)
    pair_contract_type: "CURRENT_QUARTER" | "NEXT_QUARTER" | "PERPETUAL"

    Known Limitation — parameter naming inconsistency:
        The ``interval`` parameter here maps to the Binance API ``period`` key and
        accepts the same period strings used by ``fetch_open_interest`` (e.g. "5m",
        "1d").  The sibling function ``fetch_open_interest`` correctly calls this
        parameter ``period``.  Renaming ``fetch_basis(interval=...)`` to
        ``fetch_basis(period=...)`` would be a breaking change and is deferred to a
        future minor-version bump.  The CLI ``basis --interval`` flag carries the
        same inconsistency relative to ``open-interest --period``.
    """
    url = _BASE_URLS["futures"] + "/futures/data/basis"
    params = {
        "pair": f"{symbol}USDT",
        "contractType": pair_contract_type,
        "period": interval,
        "limit": _BASIS_LIMIT,
    }
    if (s := _to_ms(start)) is not None:
        params["startTime"] = s
    if (e := _to_ms(end)) is not None:
        params["endTime"] = e
    rows = _http_get(url, params)
    if not rows:
        return pd.DataFrame(columns=["timestamp", "pair", "futures_price",
                                      "index_price", "basis", "basis_rate"])
    if len(rows) == _BASIS_LIMIT and "startTime" in params:
        logger.warning(
            "[fetch_basis] response hit limit=%d; results may be "
            "truncated, narrow the time range to fetch the rest",
            _BASIS_LIMIT,
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
