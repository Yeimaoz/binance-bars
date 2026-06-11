from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from binance_bars.fetcher import (
    fetch_basis,
    fetch_funding_rate,
    fetch_klines,
    fetch_open_interest,
    list_symbols,
    _KLINE_LIMIT,
)


def _kline_row(open_time_ms: int, close_ms: int) -> list:
    """Binance kline raw row format (12 fields)."""
    return [
        open_time_ms,
        "100.0", "110.0", "95.0", "105.0", "1234.5",
        close_ms,
        "129500.0", 10, "617.0", "64750.0", "0",
    ]


def test_fetch_klines_futures_returns_dataframe():
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = [_kline_row(1704067200000, 1704067259999)]
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {"X-MBX-USED-WEIGHT-1M": "5"}
    with patch("binance_bars.rate_limit.httpx.Client.get", return_value=mock_resp):
        df = fetch_klines(market="futures", symbol="BTCUSDT", interval="1m",
                          start="2024-01-01", end="2024-01-01")
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open_time", "open", "high", "low", "close",
                                 "volume", "close_time"]
    assert df["open_time"].iloc[0] == 1704067200000
    assert df["close"].iloc[0] == 105.0


def test_fetch_klines_spot_uses_spot_endpoint():
    mock_resp = MagicMock(status_code=200, headers={"X-MBX-USED-WEIGHT-1M": "5"})
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()
    with patch("binance_bars.rate_limit.httpx.Client.get", return_value=mock_resp) as g:
        fetch_klines(market="spot", symbol="BTCUSDT", interval="1m",
                     start="2024-01-01", end="2024-01-01")
    called_url = g.call_args[0][0]
    assert "api.binance.com/api/v3/klines" in called_url


def test_list_symbols_futures_returns_trading_only():
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "symbols": [
            {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT"},
            {"symbol": "OLDCOIN", "status": "SETTLING", "quoteAsset": "USDT"},
            {"symbol": "BTCBUSD", "status": "TRADING", "quoteAsset": "BUSD"},
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    with patch("binance_bars.rate_limit.httpx.Client.get", return_value=mock_resp):
        syms = list_symbols(market="futures", quote="USDT", trading_only=True)
    assert syms == ["BTCUSDT"]


def test_list_symbols_unknown_market_raises():
    with pytest.raises(ValueError, match="market"):
        list_symbols(market="bogus")


def test_fetch_funding_rate_returns_dataframe():
    mock_resp = MagicMock(status_code=200, headers={"X-MBX-USED-WEIGHT-1M": "1"})
    mock_resp.json.return_value = [
        {"symbol": "BTCUSDT", "fundingTime": 1704067200000,
         "fundingRate": "0.0001", "markPrice": "42000.0"},
    ]
    mock_resp.raise_for_status = MagicMock()
    with patch("binance_bars.rate_limit.httpx.Client.get", return_value=mock_resp):
        df = fetch_funding_rate(symbol="BTCUSDT", start="2024-01-01")
    assert "funding_rate" in df.columns
    assert df["funding_rate"].iloc[0] == 0.0001


def test_fetch_open_interest_returns_dataframe():
    mock_resp = MagicMock(status_code=200, headers={"X-MBX-USED-WEIGHT-1M": "1"})
    mock_resp.json.return_value = [
        {"symbol": "BTCUSDT", "sumOpenInterest": "1000.0",
         "sumOpenInterestValue": "42000000.0", "timestamp": 1704067200000},
    ]
    mock_resp.raise_for_status = MagicMock()
    with patch("binance_bars.rate_limit.httpx.Client.get", return_value=mock_resp):
        df = fetch_open_interest(symbol="BTCUSDT", period="5m")
    assert "open_interest" in df.columns
    assert df["open_interest"].iloc[0] == 1000.0


def test_fetch_basis_returns_dataframe():
    mock_resp = MagicMock(status_code=200, headers={"X-MBX-USED-WEIGHT-1M": "1"})
    mock_resp.json.return_value = [
        {"pair": "BTCUSDT", "contractType": "CURRENT_QUARTER",
         "futuresPrice": "43000.0", "indexPrice": "42000.0",
         "basis": "1000.0", "basisRate": "0.0238", "timestamp": 1704067200000},
    ]
    mock_resp.raise_for_status = MagicMock()
    with patch("binance_bars.rate_limit.httpx.Client.get", return_value=mock_resp):
        df = fetch_basis(symbol="BTC", interval="1d")
    assert "basis" in df.columns
    assert df["basis"].iloc[0] == 1000.0


# ---------------------------------------------------------------------------
# Regression tests for pagination (High: silent data truncation)
# These tests MUST be red before pagination is implemented and green after.
# ---------------------------------------------------------------------------

def _make_kline_batch(start_ms: int, count: int, interval_ms: int = 60_000) -> list:
    """Generate `count` synthetic kline rows starting at start_ms."""
    rows = []
    for i in range(count):
        open_time = start_ms + i * interval_ms
        close_time = open_time + interval_ms - 1
        rows.append(_kline_row(open_time, close_time))
    return rows


def test_fetch_klines_paginates_when_result_equals_limit(monkeypatch):
    """When first batch returns exactly _KLINE_LIMIT rows, fetch_klines must
    continue fetching subsequent pages until data is exhausted.

    Setup: batch1 = 1000 rows (full), batch2 = 500 rows (partial → stop).
    Expected: DataFrame with 1500 rows total.
    """
    interval_ms = 60_000
    start_ms = 1_700_000_000_000
    # batch 1: exactly LIMIT rows (triggers next page)
    batch1 = _make_kline_batch(start_ms, _KLINE_LIMIT, interval_ms)
    # batch 2: fewer than LIMIT rows (terminates pagination)
    batch2_start = start_ms + _KLINE_LIMIT * interval_ms
    batch2 = _make_kline_batch(batch2_start, 500, interval_ms)

    call_count = 0

    def fake_http_get(url, params):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return batch1
        else:
            return batch2

    monkeypatch.setattr("binance_bars.fetcher._http_get", fake_http_get)
    end_ms = start_ms + 2000 * interval_ms  # wide enough to cover both batches
    df = fetch_klines(
        market="futures", symbol="BTCUSDT", interval="1m",
        start=start_ms, end=end_ms,
    )
    assert call_count == 2, f"expected 2 HTTP calls (pagination), got {call_count}"
    assert len(df) == 1500, f"expected 1500 rows total, got {len(df)}"
    # Rows must be monotonically increasing by open_time
    assert df["open_time"].is_monotonic_increasing


def test_fetch_klines_no_extra_request_when_partial_batch(monkeypatch):
    """When first batch is smaller than LIMIT, no second request must be made."""
    start_ms = 1_700_000_000_000
    batch1 = _make_kline_batch(start_ms, 42, 60_000)

    call_count = 0

    def fake_http_get(url, params):
        nonlocal call_count
        call_count += 1
        return batch1

    monkeypatch.setattr("binance_bars.fetcher._http_get", fake_http_get)
    df = fetch_klines(
        market="futures", symbol="BTCUSDT", interval="1m",
        start=start_ms, end=start_ms + 100 * 60_000,
    )
    assert call_count == 1, f"expected exactly 1 HTTP call, got {call_count}"
    assert len(df) == 42


def test_fetch_open_interest_paginates_when_result_equals_limit(monkeypatch):
    """fetch_open_interest must paginate when batch equals its limit (500)."""
    _OI_LIMIT = 500
    period_ms = 5 * 60_000  # 5m
    start_ms = 1_700_000_000_000

    def _make_oi_batch(start_ms: int, count: int) -> list:
        return [
            {
                "symbol": "BTCUSDT",
                "sumOpenInterest": "1000.0",
                "sumOpenInterestValue": "42000000.0",
                "timestamp": start_ms + i * period_ms,
            }
            for i in range(count)
        ]

    batch1 = _make_oi_batch(start_ms, _OI_LIMIT)
    batch2_start = start_ms + _OI_LIMIT * period_ms
    batch2 = _make_oi_batch(batch2_start, 200)

    call_count = 0

    def fake_http_get(url, params):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return batch1
        else:
            return batch2

    monkeypatch.setattr("binance_bars.fetcher._http_get", fake_http_get)
    end_ms = start_ms + 1000 * period_ms
    df = fetch_open_interest(
        symbol="BTCUSDT", period="5m",
        start=start_ms, end=end_ms,
    )
    assert call_count == 2, f"expected 2 HTTP calls (pagination), got {call_count}"
    assert len(df) == 700, f"expected 700 rows total, got {len(df)}"
    assert df["timestamp"].is_monotonic_increasing
