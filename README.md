# binance-bars

Public-API OHLCV bar fetcher for Binance Spot + USDM-M Futures. CLI + Python lib dual API. Parquet output.

## Quickstart

```bash
pip install git+https://github.com/Yeimaoz/binance-bars.git@v0.1.0

# CLI
python -m binance_bars fetch --market futures --symbol BTCUSDT --interval 1m \
    --start 2024-01-01 --output ./BTCUSDT_1m.parquet --mode append

# Lib
python -c "from binance_bars import fetch_klines; print(fetch_klines(market='futures', symbol='BTCUSDT', interval='1m', start='2024-12-01').tail())"
```

See subcommand list with `python -m binance_bars --help`.

## License

MIT
