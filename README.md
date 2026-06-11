# binance-bars

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Public-API OHLCV bar fetcher for Binance Spot + USDM-M Futures. CLI + Python lib dual API. Parquet output. No API key required.

## Install

```bash
pip install git+https://github.com/Yeimaoz/binance-bars.git@v0.1.1
```

## Quickstart

### CLI

```bash
# List symbols
python -m binance_bars list-symbols --market futures --quote USDT

# OHLCV klines
python -m binance_bars fetch \
    --market futures --symbol BTCUSDT --interval 1m \
    --start 2024-12-01 \
    --output ./BTCUSDT_1m.parquet --mode append

# Funding rate (perpetual)
python -m binance_bars funding-rate --symbol BTCUSDT \
    --start 2024-12-01 --output ./funding/BTCUSDT.parquet

# Open interest
python -m binance_bars open-interest --symbol BTCUSDT --period 5m \
    --output ./oi/BTCUSDT.parquet

# Basis (perp vs quarterly future)
python -m binance_bars basis --symbol BTC --interval 1d \
    --contract-type CURRENT_QUARTER --output ./basis/BTC.parquet
```

### Python lib

```python
from binance_bars import (
    fetch_klines, fetch_funding_rate, fetch_open_interest, fetch_basis,
    list_symbols,
)

# All return pandas DataFrame.
# fetch_klines and fetch_open_interest automatically paginate through all
# available data for the requested start/end range — no manual iteration needed.
df = fetch_klines(market="futures", symbol="BTCUSDT", interval="1m",
                  start="2024-12-01", end="2024-12-31")
# Returns the full date-range (e.g. ~44,640 rows for December 1m) across
# multiple paginated requests; Binance returns max 1,000 candles per request.
print(df.tail())

usdt_pairs = list_symbols(market="spot", quote="USDT")
```

## Capability matrix

| Subcommand | Lib method | Endpoint | Auth |
|---|---|---|---|
| `list-symbols` | `list_symbols` | `/exchangeInfo` | none |
| `fetch` | `fetch_klines` | `/klines` (spot or futures) | none |
| `funding-rate` | `fetch_funding_rate` | `/fapi/v1/fundingRate` | none |
| `open-interest` | `fetch_open_interest` | `/futures/data/openInterestHist` | none |
| `basis` | `fetch_basis` | `/futures/data/basis` | none |

## DataFrame schemas

Each fetcher returns a source-shaped DataFrame. Columns are NOT normalized across fetchers (Binance API returns different fields per endpoint; we pass them through).

### fetch_klines

| Column | dtype | Notes |
|---|---|---|
| `open_time` | int (ms UTC) | bar start |
| `open` / `high` / `low` / `close` | float | OHLC |
| `volume` | float | base-asset volume |
| `close_time` | int (ms UTC) | bar end |

### fetch_funding_rate

| Column | dtype |
|---|---|
| `funding_time` | int (ms UTC) |
| `symbol` | str |
| `funding_rate` | float |
| `mark_price` | float |

### fetch_open_interest

| Column | dtype |
|---|---|
| `timestamp` | int (ms UTC) |
| `symbol` | str |
| `open_interest` | float (contracts) |
| `open_interest_value` | float (USD notional) |

### fetch_basis

| Column | dtype |
|---|---|
| `timestamp` | int (ms UTC) |
| `pair` | str (e.g. "BTCUSDT") |
| `futures_price` | float |
| `index_price` | float |
| `basis` | float |
| `basis_rate` | float |

## Symbol format

Binance uses concatenated base+quote, uppercase, no separator: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`. `fetch_basis` takes the base only (e.g. `BTC`); the lib appends `USDT` internally to form the API pair.

## Schema diff vs `shioaji-bars`

Sibling lib `shioaji-bars` uses different conventions (`ts: datetime` instead of `open_time: int ms`; extra `amount` column for 成交金額; etc.). The two libs are intentionally independent — caller normalizes if joining across markets.

## Rate limit handling

- Binance public API uses IP-based weight limits (1200/min spot, 2400/min futures).
- Library reads `Retry-After` on HTTP 429 → sleeps + retries once.
- HTTP 418 (IP banned) → raises `IpBannedError` immediately (no retry).

## API limits

Binance public endpoints cap responses per request:

| Fetcher | Limit/request | Pagination |
|---|---|---|
| `fetch_klines` | 1,000 candles | automatic — pages until end is reached |
| `fetch_open_interest` | 500 records | automatic — pages until end is reached |
| `fetch_funding_rate` | 1,000 records | single request (Binance interval ~8 h → ~45 days) |
| `fetch_basis` | 500 records | single request |

For `fetch_funding_rate` and `fetch_basis`, if you need more than a single
batch worth of history, call with a sliding `start`/`end` window and
concatenate results.

## Testing

```bash
pip install -e .[dev]
pytest -v          # unit + parquet I/O + real-API e2e
```

E2E tests hit the real Binance public API (~10 weight total per run, well under any limit).

## License

MIT
