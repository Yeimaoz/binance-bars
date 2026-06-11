"""Real Binance public API tests. Network required. No auth.

Run with:
    RUN_E2E=1 pytest -m e2e -v

These tests are skipped by default (requires live network access).
"""

import os

import pytest

from binance_bars import fetch_klines, list_symbols

_E2E_REASON = "Set RUN_E2E=1 to run real Binance API tests (requires network)"


@pytest.mark.e2e
@pytest.mark.skipif(not os.environ.get("RUN_E2E"), reason=_E2E_REASON)
def test_e2e_list_symbols_futures():
    syms = list_symbols(market="futures", quote="USDT", trading_only=True)
    assert "BTCUSDT" in syms
    assert "ETHUSDT" in syms
    assert len(syms) > 50  # sanity check; Binance has hundreds


@pytest.mark.e2e
@pytest.mark.skipif(not os.environ.get("RUN_E2E"), reason=_E2E_REASON)
def test_e2e_list_symbols_spot():
    syms = list_symbols(market="spot", quote="USDT", trading_only=True)
    assert "BTCUSDT" in syms
    assert len(syms) > 100


@pytest.mark.e2e
@pytest.mark.skipif(not os.environ.get("RUN_E2E"), reason=_E2E_REASON)
def test_e2e_fetch_klines_futures_recent():
    df = fetch_klines(market="futures", symbol="BTCUSDT", interval="1m")
    assert len(df) > 0
    assert len(df) <= 1000
    # sanity check on price range (BTC > $1k throughout history)
    assert df["close"].min() > 1000
    # schema check
    assert list(df.columns) == ["open_time", "open", "high", "low", "close",
                                 "volume", "close_time"]
