"""binance-bars — public OHLCV fetcher for Binance Spot + USDM-M Futures."""

from importlib.metadata import PackageNotFoundError, version

from binance_bars.aggtrades import (
    BASE_URL,
    CANONICAL_COLUMNS,
    CANONICAL_DTYPES,
    fetch_aggtrades,
    infer_date_from,
    is_file_valid,
    iter_dates,
    parse_zip_to_df,
    validate_symbol,
    write_atomic,
)
from binance_bars.fetcher import (
    fetch_basis,
    fetch_funding_rate,
    fetch_klines,
    fetch_open_interest,
    list_symbols,
)
from binance_bars.parquet_io import Mode, read_last_open_time, write_parquet
from binance_bars.rate_limit import IpBannedError, RateLimitedError

try:
    __version__ = version("binance-bars")
except PackageNotFoundError:  # package not installed (e.g. running from source tree)
    __version__ = "0.0.0+dev"

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
    # aggTrades daily-archive module
    "fetch_aggtrades",
    "parse_zip_to_df",
    "write_atomic",
    "is_file_valid",
    "infer_date_from",
    "iter_dates",
    "validate_symbol",
    "CANONICAL_COLUMNS",
    "CANONICAL_DTYPES",
    "BASE_URL",
]
