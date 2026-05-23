import sys
from unittest.mock import patch
import pandas as pd
import pytest

from binance_bars.cli import main


def _df():
    return pd.DataFrame({
        "open_time": [1704067200000],
        "open": [100.0], "high": [110.0], "low": [95.0], "close": [105.0],
        "volume": [1234.5], "close_time": [1704067259999],
    })


def test_cli_list_symbols_dispatches():
    with patch("binance_bars.cli.list_symbols", return_value=["BTCUSDT"]) as ls, \
         patch.object(sys, "argv", ["binance-bars", "list-symbols",
                                     "--market", "futures", "--quote", "USDT"]):
        rc = main()
    assert rc == 0
    ls.assert_called_once_with(market="futures", quote="USDT", trading_only=True)


def test_cli_fetch_writes_parquet(tmp_path):
    out = tmp_path / "BTC.parquet"
    with patch("binance_bars.cli.fetch_klines", return_value=_df()) as fk, \
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


def test_cli_no_subcommand_exits_nonzero():
    with patch.object(sys, "argv", ["binance-bars"]):
        with pytest.raises(SystemExit):
            main()
