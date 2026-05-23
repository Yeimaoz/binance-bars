"""binance-bars — public OHLCV fetcher for Binance Spot + USDM-M Futures."""

from binance_bars.fetcher import (
    fetch_basis,
    fetch_funding_rate,
    fetch_klines,
    fetch_open_interest,
    list_symbols,
)
from binance_bars.parquet_io import Mode, read_last_open_time, write_parquet
from binance_bars.rate_limit import IpBannedError, RateLimitedError

__version__ = "0.1.0"

__all__ = [
    "fetch_klines",
    "fetch_funding_rate",
    "fetch_open_interest",
    "fetch_basis",
    "list_symbols",
    "Mode",
    "read_last_open_time",
    "write_parquet",
    "IpBannedError",
    "RateLimitedError",
]
