from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from binance_bars.fetcher import (
    fetch_basis,
    fetch_funding_rate,
    fetch_klines,
    fetch_open_interest,
    list_symbols,
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
