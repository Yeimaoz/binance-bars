"""Binance Vision aggTrades daily-archive downloader.

Downloads per-symbol-per-day aggregated-trade archives from the public
``data.binance.vision`` CDN (USDM-M futures) and writes them as canonical
zstd-compressed Parquet, one file per symbol-day.

Unlike :mod:`binance_bars.fetcher` (live REST API, row-merge append), aggTrades
uses **daily-archive** semantics:

- one Parquet per symbol-day (``{SYMBOL}/{SYMBOL}-aggTrades-{YYYY-MM-DD}.parquet``)
- file-level resume: a valid day-file is skipped, never re-downloaded
- no row-merge / dedup — each archive is already a complete, immutable day

Canonical output schema (5 columns)::

    agg_trade_id   int64    — unique aggregated-trade id per symbol
    price          float64  — trade price
    quantity       float64  — trade quantity (base asset)
    timestamp_ms   int64    — trade time, unix milliseconds UTC
    is_buyer_maker bool     — True = buyer is maker (ask-side fill)

Source archive: ``https://data.binance.vision/data/futures/um/daily/aggTrades/``

Vision is a static CDN with **T+1 lag**: a given day's archive is published the
*next* day. Fetching "today" therefore 404s; default ``date_to`` is yesterday
(UTC). Missing / pre-listing dates 404 gracefully (counted as ``failed``, no
exception) so a run self-heals on the next invocation.
"""

from __future__ import annotations

import io
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

BASE_URL = "https://data.binance.vision/data/futures/um/daily/aggTrades"

# Earliest date probed when a symbol directory has no existing files. Per-symbol
# real availability differs (USDT ~2019-12, USDC ~2024-01-04); earlier dates
# simply 404 (graceful). Kept generic — callers may pass an explicit date_from.
DEFAULT_EARLIEST = "2020-01-01"

# Column layout of the Binance Vision aggTrades CSV archive.
CSV_COLUMNS = [
    "agg_trade_id",
    "price",
    "quantity",
    "first_trade_id",
    "last_trade_id",
    "transact_time",
    "is_buyer_maker",
]
USECOLS = ["agg_trade_id", "price", "quantity", "transact_time", "is_buyer_maker"]
RENAME_MAP = {"transact_time": "timestamp_ms"}

CANONICAL_COLUMNS = ["agg_trade_id", "price", "quantity", "timestamp_ms", "is_buyer_maker"]
CANONICAL_DTYPES: dict[str, str] = {
    "agg_trade_id": "int64",
    "price": "float64",
    "quantity": "float64",
    "timestamp_ms": "int64",
    "is_buyer_maker": "bool",
}

_USER_AGENT = "binance-bars/aggtrades"


def yesterday_utc() -> str:
    """Return yesterday's date (UTC) as ``YYYY-MM-DD``.

    The Vision CDN publishes a day's archive on T+1, so yesterday is the most
    recent date that is reliably available.
    """
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def validate_symbol(symbol: str) -> None:
    """Raise ``ValueError`` if *symbol* contains a comma.

    A comma would be misinterpreted as a symbol-list separator and could
    produce a malformed output directory path.
    """
    if "," in symbol:
        raise ValueError(
            f"Symbol {symbol!r} contains a comma. "
            "Comma-joined symbol lists are not supported; pass symbols individually."
        )


def iter_dates(date_from: str, date_to: str) -> list[str]:
    """Return the inclusive list of ``YYYY-MM-DD`` dates from *date_from* to *date_to*."""
    start = datetime.strptime(date_from, "%Y-%m-%d")
    end = datetime.strptime(date_to, "%Y-%m-%d")
    out: list[str] = []
    d = start
    while d <= end:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


def infer_date_from(sym_dir: Path) -> str:
    """Return the day *after* the latest existing parquet in *sym_dir*.

    Used for incremental resume. Falls back to :data:`DEFAULT_EARLIEST` when the
    directory has no recognizable day-files.
    """
    parquets = sorted(Path(sym_dir).glob("*.parquet"))
    if not parquets:
        return DEFAULT_EARLIEST
    # filename: {SYMBOL}-aggTrades-YYYY-MM-DD.parquet
    last = parquets[-1].stem
    parts = last.rsplit("-", 3)
    if len(parts) >= 3:
        date_str = "-".join(parts[-3:])
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            return (d + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return DEFAULT_EARLIEST


def is_file_valid(path: Path) -> bool:
    """Return True if *path* exists and looks like a canonical aggTrades parquet."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        cols = pd.read_parquet(path).columns.tolist()
        return "agg_trade_id" in cols and len(cols) >= 5
    except Exception:
        return False


def download_zip(url: str, timeout: int = 30) -> bytes | None:
    """Download *url*, returning the raw bytes, or ``None`` on 404 / network error.

    Vision is a static CDN; there is no rate limiting and no backoff. A 404
    (archive not yet published / pre-listing date) returns ``None`` so callers
    can count it as ``failed`` without raising.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()  # type: ignore[no-any-return]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.info("[aggtrades] 404 (no archive): %s", url)
            return None
        logger.warning("[aggtrades] HTTP error %s for %s", e.code, url)
        return None
    except Exception as e:
        logger.warning("[aggtrades] download failed for %s: %s", url, e)
        return None


def parse_zip_to_df(zip_data: bytes) -> pd.DataFrame:
    """Extract the CSV from a Vision aggTrades zip and return a canonical DataFrame.

    Output columns / dtypes are exactly :data:`CANONICAL_COLUMNS` /
    :data:`CANONICAL_DTYPES`.
    """
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        csv_data = zf.read(zf.namelist()[0])
    df = pd.read_csv(io.BytesIO(csv_data), usecols=USECOLS)
    df = df.rename(columns=RENAME_MAP)
    df = df[CANONICAL_COLUMNS]
    df["agg_trade_id"] = df["agg_trade_id"].astype("int64")
    df["timestamp_ms"] = df["timestamp_ms"].astype("int64")
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(bool)
    df["price"] = df["price"].astype("float64")
    df["quantity"] = df["quantity"].astype("float64")
    return df


def write_atomic(df: pd.DataFrame, out_path: Path) -> None:
    """Write *df* to *out_path* as zstd Parquet atomically (``.tmp`` then rename).

    If the process is killed mid-write the original file (if any) stays intact
    and only a ``.tmp`` orphan is left, which the next run overwrites.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    try:
        df.to_parquet(tmp_path, compression="zstd", index=False)
        tmp_path.replace(out_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def fetch_aggtrades(
    symbols: list[str],
    date_from: str | None,
    date_to: str | None,
    output_dir: Path,
    sleep_between: float = 0.3,
) -> dict[str, int]:
    """Download daily aggTrades archives for *symbols* over a date range.

    Args:
        symbols: list of Binance symbols, e.g. ``["BTCUSDT", "ETHUSDT"]``.
        date_from: inclusive start ``YYYY-MM-DD``. ``None`` → per-symbol
            incremental resume (day after the last existing file).
        date_to: inclusive end ``YYYY-MM-DD``. ``None`` → :func:`yesterday_utc`
            (Vision T+1 lag; today's archive is not yet published).
        output_dir: root output directory. Files are written to
            ``output_dir/{SYMBOL}/{SYMBOL}-aggTrades-{YYYY-MM-DD}.parquet``.
        sleep_between: politeness delay (seconds) between downloads.

    Returns:
        ``{"skipped": int, "downloaded": int, "failed": int}`` aggregated across
        all symbols. A missing archive (404) increments ``failed`` and does NOT
        raise — re-run to self-heal once the archive is published.
    """
    for sym in symbols:
        validate_symbol(sym)

    output_dir = Path(output_dir)
    resolved_date_to = date_to or yesterday_utc()
    stats = {"skipped": 0, "downloaded": 0, "failed": 0}

    for sym in symbols:
        sym_dir = output_dir / sym
        sym_dir.mkdir(parents=True, exist_ok=True)

        resolved_date_from = date_from or infer_date_from(sym_dir)
        dates = iter_dates(resolved_date_from, resolved_date_to)
        if not dates:
            logger.info(
                "[aggtrades] %s: no dates to process (%s -> %s)",
                sym, resolved_date_from, resolved_date_to,
            )
            continue

        sym_encoded = urllib.parse.quote(sym, safe="")
        logger.info(
            "[aggtrades] %s: %d dates (%s -> %s)",
            sym, len(dates), dates[0], dates[-1],
        )

        for date_str in dates:
            out_path = sym_dir / f"{sym}-aggTrades-{date_str}.parquet"

            if is_file_valid(out_path):
                logger.debug("[aggtrades] %s %s: skip (valid)", sym, date_str)
                stats["skipped"] += 1
                continue

            # File exists but is invalid — remove before re-download.
            if out_path.exists():
                logger.info(
                    "[aggtrades] %s %s: invalid file, removing for re-download",
                    sym, date_str,
                )
                out_path.unlink()

            url = f"{BASE_URL}/{sym_encoded}/{sym_encoded}-aggTrades-{date_str}.zip"
            zip_data = download_zip(url)
            if zip_data is None:
                stats["failed"] += 1
                continue

            try:
                df = parse_zip_to_df(zip_data)
                write_atomic(df, out_path)
                logger.info(
                    "[aggtrades] %s %s: %d rows -> %.1f MB",
                    sym, date_str, len(df), out_path.stat().st_size / 1024 / 1024,
                )
                stats["downloaded"] += 1
            except Exception as e:
                logger.warning(
                    "[aggtrades] %s %s: parse/write failed: %s", sym, date_str, e
                )
                stats["failed"] += 1

            if sleep_between:
                time.sleep(sleep_between)

    return stats
