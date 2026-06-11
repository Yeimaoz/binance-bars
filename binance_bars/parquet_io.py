"""Parquet read/write with append/overwrite/skip modes.

Schema-aware: different fetchers use different primary-key columns.
Use the ``PRIMARY_KEYS`` registry to look up the correct ``time_col`` per
data type, or pass ``time_col`` explicitly to :func:`write_parquet` /
:func:`read_last_open_time`.
"""

from __future__ import annotations

import enum
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Maps data-type name → primary time column used for dedup + sort.
PRIMARY_KEYS: dict[str, str] = {
    "klines": "open_time",
    "funding_rate": "funding_time",
    "open_interest": "timestamp",
    "basis": "timestamp",
}


class Mode(str, enum.Enum):
    APPEND = "append"
    OVERWRITE = "overwrite"
    SKIP = "skip"


def write_parquet(
    df: pd.DataFrame,
    path: Path,
    *,
    mode: Mode = Mode.APPEND,
    time_col: str = "open_time",
) -> None:
    """Write df to parquet path with given mode.

    Args:
        df: DataFrame to write.
        path: Destination parquet file path.
        mode: APPEND (default) | OVERWRITE | SKIP.
        time_col: Column used as the dedup + sort key in APPEND mode.
            Defaults to ``"open_time"`` (klines schema) for backward
            compatibility. Pass the correct key for other schemas:
            ``"funding_time"`` for funding_rate, ``"timestamp"`` for
            open_interest / basis (see :data:`PRIMARY_KEYS`).

    Modes:
        APPEND: merge with existing (if any), dedup on *time_col*, sort, write.
        OVERWRITE: replace file unconditionally.
        SKIP: no-op if file exists; else write fresh.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if mode == Mode.SKIP and path.exists():
        logger.info("[parquet_io] skip — %s already exists", path)
        return

    if mode == Mode.APPEND and path.exists():
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=[time_col], keep="last")
        df = df.sort_values(time_col).reset_index(drop=True)

    # Atomic write: stage to a sibling .tmp file, then rename. If the
    # process is killed mid-write (OOM / SIGKILL / power loss / WSL
    # restart), the original parquet remains intact and only the .tmp
    # orphan is left (next run overwrites it).
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)
    logger.info("[parquet_io] wrote %s (%d rows, mode=%s)", path, len(df), mode.value)


def read_last_open_time(path: Path, *, time_col: str = "open_time") -> int | None:
    """Return max(*time_col*) from parquet, or None if file missing/empty.

    Args:
        path: Path to the parquet file.
        time_col: Time column to query. Defaults to ``"open_time"`` (klines).
            Use ``"funding_time"`` or ``"timestamp"`` for other schemas.
    """
    path = Path(path)
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=[time_col])
    if df.empty:
        return None
    return int(df[time_col].max())
