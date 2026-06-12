import sys
from unittest.mock import patch
import pandas as pd
import pytest

from binance_bars.cli import main


def _klines_df():
    return pd.DataFrame({
        "open_time": [1704067200000],
        "open": [100.0], "high": [110.0], "low": [95.0], "close": [105.0],
        "volume": [1234.5], "close_time": [1704067259999],
    })


def _funding_rate_df():
    return pd.DataFrame({
        "funding_time": [1704067200000],
        "symbol": ["BTCUSDT"],
        "funding_rate": [0.0001],
        "mark_price": [42000.0],
    })


def _open_interest_df():
    return pd.DataFrame({
        "timestamp": [1704067200000],
        "symbol": ["BTCUSDT"],
        "open_interest": [1000.0],
        "open_interest_value": [42000000.0],
    })


def _basis_df():
    return pd.DataFrame({
        "timestamp": [1704067200000],
        "pair": ["BTCUSDT"],
        "futures_price": [43000.0],
        "index_price": [42000.0],
        "basis": [1000.0],
        "basis_rate": [0.0238],
    })


def test_cli_list_symbols_dispatches():
    with patch("binance_bars.cli.list_symbols", return_value=["BTCUSDT"]) as ls, \
         patch.object(sys, "argv", ["binance-bars", "list-symbols",
                                     "--market", "futures", "--quote", "USDT"]):
        rc = main()
    assert rc == 0
    ls.assert_called_once_with(market="futures", quote="USDT", trading_only=True)


def test_cli_list_symbols_no_trading_only():
    """--no-trading-only must pass trading_only=False to list_symbols."""
    with patch("binance_bars.cli.list_symbols", return_value=["BTCUSDT", "OLDCOIN"]) as ls, \
         patch.object(sys, "argv", ["binance-bars", "list-symbols",
                                     "--market", "futures", "--no-trading-only"]):
        rc = main()
    assert rc == 0
    ls.assert_called_once_with(market="futures", quote=None, trading_only=False)


def test_cli_fetch_writes_parquet(tmp_path):
    out = tmp_path / "BTC.parquet"
    with patch("binance_bars.cli.fetch_klines", return_value=_klines_df()) as fk, \
         patch.object(sys, "argv", ["binance-bars", "fetch",
                                     "--market", "futures",
                                     "--symbol", "BTCUSDT",
                                     "--interval", "1m",
                                     "--start", "2024-01-01",
                                     "--output", str(out),
                                     "--mode", "overwrite"]):
        rc = main()
    assert rc == 0
    fk.assert_called_once()
    assert out.exists()
    df_read = pd.read_parquet(out)
    assert len(df_read) == 1


def test_cli_funding_rate_dispatches(tmp_path):
    """CLI funding-rate subcommand must dispatch fetch_funding_rate and write parquet."""
    out = tmp_path / "funding.parquet"
    with patch("binance_bars.cli.fetch_funding_rate", return_value=_funding_rate_df()) as ffr, \
         patch.object(sys, "argv", ["binance-bars", "funding-rate",
                                     "--symbol", "BTCUSDT",
                                     "--start", "2024-01-01",
                                     "--output", str(out),
                                     "--mode", "overwrite"]):
        rc = main()
    assert rc == 0
    ffr.assert_called_once()
    assert out.exists()
    df_read = pd.read_parquet(out)
    assert len(df_read) == 1


def test_cli_open_interest_dispatches(tmp_path):
    """CLI open-interest subcommand must dispatch fetch_open_interest with --period."""
    out = tmp_path / "oi.parquet"
    with patch("binance_bars.cli.fetch_open_interest", return_value=_open_interest_df()) as foi, \
         patch.object(sys, "argv", ["binance-bars", "open-interest",
                                     "--symbol", "BTCUSDT",
                                     "--period", "1h",
                                     "--output", str(out),
                                     "--mode", "overwrite"]):
        rc = main()
    assert rc == 0
    foi.assert_called_once()
    call_kwargs = foi.call_args[1]
    assert call_kwargs.get("period") == "1h" or foi.call_args[0][1] == "1h"
    assert out.exists()
    df_read = pd.read_parquet(out)
    assert len(df_read) == 1


def test_cli_basis_dispatches(tmp_path):
    """CLI basis subcommand must dispatch fetch_basis with --interval and write parquet."""
    out = tmp_path / "basis.parquet"
    with patch("binance_bars.cli.fetch_basis", return_value=_basis_df()) as fb, \
         patch.object(sys, "argv", ["binance-bars", "basis",
                                     "--symbol", "BTC",
                                     "--interval", "1d",
                                     "--contract-type", "PERPETUAL",
                                     "--output", str(out),
                                     "--mode", "overwrite"]):
        rc = main()
    assert rc == 0
    fb.assert_called_once()
    assert out.exists()
    df_read = pd.read_parquet(out)
    assert len(df_read) == 1


def test_cli_no_subcommand_exits_nonzero():
    with patch.object(sys, "argv", ["binance-bars"]):
        with pytest.raises(SystemExit):
            main()
