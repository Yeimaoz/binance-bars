"""Real Binance public API tests. Network required. No auth."""


from binance_bars import fetch_klines, list_symbols


def test_e2e_list_symbols_futures():
    syms = list_symbols(market="futures", quote="USDT", trading_only=True)
    assert "BTCUSDT" in syms
    assert "ETHUSDT" in syms
    assert len(syms) > 50  # sanity check; Binance has hundreds


def test_e2e_list_symbols_spot():
    syms = list_symbols(market="spot", quote="USDT", trading_only=True)
    assert "BTCUSDT" in syms
    assert len(syms) > 100


def test_e2e_fetch_klines_futures_recent():
    df = fetch_klines(market="futures", symbol="BTCUSDT", interval="1m")
    assert len(df) > 0
    assert len(df) <= 1000
    # sanity check on price range (BTC > $1k throughout history)
    assert df["close"].min() > 1000
    # schema check
    assert list(df.columns) == ["open_time", "open", "high", "low", "close",
                                 "volume", "close_time"]
