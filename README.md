# binance-bars

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Public-API OHLCV bar fetcher for Binance Spot + USDM-M Futures. CLI + Python lib dual API. Parquet output. No API key required.

## Install

```bash
pip install git+https://github.com/Yeimaoz/binance-bars.git@v0.2.0
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

# aggTrades daily archives (Binance Vision, futures USDM-M)
python -m binance_bars aggtrades --symbols BTCUSDT \
    --date-from 2024-01-01 --date-to 2024-02-01 --output-dir ./agg
# daily archive (one file per symbol-day), T+1 publish lag, full history is GB-scale
```

> ⚠️ **`fetch` footgun**: without `--start`, `fetch` returns only the most-recent
> 1000 bars. Pass `--start` for history — `fetch_klines` then auto-paginates the
> whole `start`→`end` range. `funding-rate` and `basis` are single-request (no
> pagination); for long history use a sliding-window loop (see the bundled skill).

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
| `aggtrades` | `fetch_aggtrades` | `data.binance.vision` daily archive | none |

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

### fetch_aggtrades

Daily-archive downloader (Binance Vision CDN, futures USDM-M). One Parquet per
symbol-day at `{output_dir}/{SYMBOL}/{SYMBOL}-aggTrades-{YYYY-MM-DD}.parquet`,
zstd-compressed. Returns `{"skipped", "downloaded", "failed"}`. Valid existing
day-files are skipped (resume-safe); missing archives 404 gracefully (counted
`failed`, no raise) — re-run to self-heal. T+1 publish lag: `date_to` defaults
to yesterday-UTC.

| Column | dtype | Notes |
|---|---|---|
| `agg_trade_id` | int64 | aggregated-trade id (unique per symbol) |
| `price` | float64 | trade price |
| `quantity` | float64 | trade quantity (base asset) |
| `timestamp_ms` | int64 | trade time, ms UTC |
| `is_buyer_maker` | bool | True = buyer is maker (ask-side fill) |

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
pytest -v          # unit tests (e2e skipped by default)
RUN_E2E=1 pytest -m e2e -v  # 3 real-API e2e tests (requires network)
```

E2E tests hit the real Binance public API (~10 weight total per run, well under any limit).
They are skipped by default; set `RUN_E2E=1` to enable them.

## Known Limitations

- **`fetch_basis` parameter naming**: The `interval` parameter of `fetch_basis` (and the `--interval` flag of the `basis` CLI subcommand) maps to the Binance API `period` key. The sibling `fetch_open_interest` correctly uses `period` for the same concept. Renaming this parameter would be a breaking change and is deferred to a future minor-version bump.

## License

MIT
