"""Parquet read/write with append/overwrite/skip modes.

Supports multiple schemas:
- klines: time key = open_time
- funding_rate: time key = funding_time
- open_interest / basis: time key = timestamp

The time key is auto-detected from df.columns (open_time > funding_time > timestamp).
"""

from __future__ import annotations

import enum
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


_TIME_KEY_CANDIDATES = ("open_time", "funding_time", "timestamp")


def _detect_time_key(df: pd.DataFrame) -> str:
    """Return the first recognised time column present in df.columns.

    Priority: open_time > funding_time > timestamp.
    Raises KeyError if none found.
    """
    for col in _TIME_KEY_CANDIDATES:
        if col in df.columns:
            return col
    raise KeyError(
        f"Cannot auto-detect time key: none of {_TIME_KEY_CANDIDATES} found in "
        f"columns {list(df.columns)}"
    )


class Mode(str, enum.Enum):
    APPEND = "append"
    OVERWRITE = "overwrite"
    SKIP = "skip"


def write_parquet(df: pd.DataFrame, path: Path, *, mode: Mode = Mode.APPEND) -> None:
    """Write df to parquet path with given mode.

    APPEND: merge with existing (if any), dedup on the time key, sort, write.
           Time key is auto-detected: open_time (klines), funding_time (funding),
           or timestamp (open_interest / basis).
    OVERWRITE: replace file unconditionally.
    SKIP: no-op if file exists; else write fresh.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if mode == Mode.SKIP and path.exists():
        logger.info("[parquet_io] skip — %s already exists", path)
        return

    if mode == Mode.APPEND and path.exists():
        time_key = _detect_time_key(df)
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=[time_key], keep="last")
        df = df.sort_values(time_key).reset_index(drop=True)

    # Atomic write: stage to a sibling .tmp file, then rename. If the
    # process is killed mid-write (OOM / SIGKILL / power loss / WSL
    # restart), the original parquet remains intact and only the .tmp
    # orphan is left (next run overwrites it).
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)
    logger.info("[parquet_io] wrote %s (%d rows, mode=%s)", path, len(df), mode.value)


def read_last_open_time(path: Path) -> int | None:
    """Return max(open_time) from parquet, or None if file missing/empty."""
    path = Path(path)
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=["open_time"])
    if df.empty:
        return None
    return int(df["open_time"].max())
