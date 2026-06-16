from pathlib import Path

import pandas as pd

from binance_bars.parquet_io import write_parquet, read_last_open_time, Mode


def _df(rows):
    return pd.DataFrame(rows, columns=["open_time", "open", "high", "low",
                                        "close", "volume", "close_time"])


def _funding_rate_df(rows):
    """funding_rate schema: funding_time, symbol, funding_rate, mark_price."""
    return pd.DataFrame(rows, columns=["funding_time", "symbol", "funding_rate", "mark_price"])


def _open_interest_df(rows):
    """open_interest schema: timestamp, symbol, open_interest, open_interest_value."""
    return pd.DataFrame(rows, columns=["timestamp", "symbol", "open_interest",
                                       "open_interest_value"])


def _basis_df(rows):
    """basis schema: timestamp, pair, futures_price, index_price, basis, basis_rate."""
    return pd.DataFrame(rows, columns=["timestamp", "pair", "futures_price",
                                       "index_price", "basis", "basis_rate"])


# ---------------------------------------------------------------------------
# Regression tests for non-klines schemas in APPEND mode (Critical KeyError fix)
# These tests MUST be red before the fix and green after.
# ---------------------------------------------------------------------------

def test_write_append_funding_rate_schema_no_crash(tmp_path):
    """APPEND mode must not KeyError when schema uses funding_time as primary key."""
    path = tmp_path / "funding_rate.parquet"
    df1 = _funding_rate_df([
        [1704067200000, "BTCUSDT", 0.0001, 42000.0],
        [1704081600000, "BTCUSDT", 0.0002, 42100.0],
    ])
    write_parquet(df1, path, mode=Mode.OVERWRITE)
    # Second write (append) — must not raise KeyError
    df2 = _funding_rate_df([
        [1704081600000, "BTCUSDT", 0.0002, 42100.0],  # duplicate
        [1704096000000, "BTCUSDT", 0.0003, 42200.0],  # new row
    ])
    write_parquet(df2, path, mode=Mode.APPEND, time_col="funding_time")
    out = pd.read_parquet(path)
    assert len(out) == 3, f"expected 3 rows after dedup, got {len(out)}"
    assert list(out["funding_time"]) == [1704067200000, 1704081600000, 1704096000000]


def test_write_append_open_interest_schema_no_crash(tmp_path):
    """APPEND mode must not KeyError when schema uses timestamp as primary key."""
    path = tmp_path / "open_interest.parquet"
    df1 = _open_interest_df([
        [1704067200000, "BTCUSDT", 1000.0, 42000000.0],
        [1704070800000, "BTCUSDT", 1010.0, 42420000.0],
    ])
    write_parquet(df1, path, mode=Mode.OVERWRITE)
    df2 = _open_interest_df([
        [1704070800000, "BTCUSDT", 1010.0, 42420000.0],  # duplicate
        [1704074400000, "BTCUSDT", 1020.0, 42840000.0],  # new row
    ])
    write_parquet(df2, path, mode=Mode.APPEND, time_col="timestamp")
    out = pd.read_parquet(path)
    assert len(out) == 3, f"expected 3 rows after dedup, got {len(out)}"
    assert list(out["timestamp"]) == [1704067200000, 1704070800000, 1704074400000]


def test_write_append_basis_schema_no_crash(tmp_path):
    """APPEND mode must not KeyError for basis schema (timestamp primary key)."""
    path = tmp_path / "basis.parquet"
    df1 = _basis_df([
        [1704067200000, "BTCUSDT", 43000.0, 42000.0, 1000.0, 0.0238],
        [1704153600000, "BTCUSDT", 43100.0, 42100.0, 1000.0, 0.0237],
    ])
    write_parquet(df1, path, mode=Mode.OVERWRITE)
    df2 = _basis_df([
        [1704153600000, "BTCUSDT", 43100.0, 42100.0, 1000.0, 0.0237],  # duplicate
        [1704240000000, "BTCUSDT", 43200.0, 42200.0, 1000.0, 0.0236],  # new row
    ])
    write_parquet(df2, path, mode=Mode.APPEND, time_col="timestamp")
    out = pd.read_parquet(path)
    assert len(out) == 3, f"expected 3 rows after dedup, got {len(out)}"
    assert list(out["timestamp"]) == [1704067200000, 1704153600000, 1704240000000]


def test_write_append_klines_default_time_col_unchanged(tmp_path):
    """Existing klines APPEND (no explicit time_col) must still work (backward compat)."""
    path = tmp_path / "klines.parquet"
    write_parquet(_df([[1000, 1.0, 2.0, 0.5, 1.5, 100.0, 1059],
                       [2000, 2.0, 3.0, 1.5, 2.5, 200.0, 2059]]),
                  path, mode=Mode.OVERWRITE)
    write_parquet(_df([[2000, 2.0, 3.0, 1.5, 2.5, 200.0, 2059],
                       [3000, 3.0, 4.0, 2.5, 3.5, 300.0, 3059]]),
                  path, mode=Mode.APPEND)
    out = pd.read_parquet(path)
    assert len(out) == 3
    assert list(out["open_time"]) == [1000, 2000, 3000]


def test_write_overwrite_replaces_file(tmp_path):
    path = tmp_path / "x.parquet"
    write_parquet(_df([[1000, 1.0, 2.0, 0.5, 1.5, 100.0, 1059]]), path,
                  mode=Mode.OVERWRITE)
    write_parquet(_df([[2000, 2.0, 3.0, 1.5, 2.5, 200.0, 2059]]), path,
                  mode=Mode.OVERWRITE)
    out = pd.read_parquet(path)
    assert len(out) == 1
    assert out["open_time"].iloc[0] == 2000


def test_write_append_dedups_and_sorts(tmp_path):
    path = tmp_path / "x.parquet"
    write_parquet(_df([[2000, 2.0, 3.0, 1.5, 2.5, 200.0, 2059],
                        [1000, 1.0, 2.0, 0.5, 1.5, 100.0, 1059]]),
                  path, mode=Mode.OVERWRITE)
    write_parquet(_df([[1000, 1.0, 2.0, 0.5, 1.5, 100.0, 1059],
                        [3000, 3.0, 4.0, 2.5, 3.5, 300.0, 3059]]),
                  path, mode=Mode.APPEND)
    out = pd.read_parquet(path)
    assert len(out) == 3
    assert list(out["open_time"]) == [1000, 2000, 3000]  # sorted + deduped


def test_write_skip_if_exists_noop(tmp_path):
    path = tmp_path / "x.parquet"
    write_parquet(_df([[1000, 1.0, 2.0, 0.5, 1.5, 100.0, 1059]]),
                  path, mode=Mode.OVERWRITE)
    write_parquet(_df([[2000, 2.0, 3.0, 1.5, 2.5, 200.0, 2059]]),
                  path, mode=Mode.SKIP)
    out = pd.read_parquet(path)
    assert len(out) == 1
    assert out["open_time"].iloc[0] == 1000


def test_write_empty_df_overwrite_preserves_existing(tmp_path):
    """OVERWRITE with an empty df must NOT clobber an existing file.

    A producer that yields zero rows (API hiccup / empty window) must never
    erase already-persisted data.
    """
    path = tmp_path / "x.parquet"
    write_parquet(_df([[1000, 1.0, 2.0, 0.5, 1.5, 100.0, 1059],
                       [2000, 2.0, 3.0, 1.5, 2.5, 200.0, 2059]]),
                  path, mode=Mode.OVERWRITE)
    empty = _df([])
    assert empty.empty
    write_parquet(empty, path, mode=Mode.OVERWRITE)
    out = pd.read_parquet(path)
    assert len(out) == 2  # existing data intact, not overwritten
    assert list(out["open_time"]) == [1000, 2000]


def test_write_empty_df_overwrite_no_file_is_noop(tmp_path):
    """OVERWRITE with an empty df + no existing file writes nothing (no empty file)."""
    path = tmp_path / "x.parquet"
    write_parquet(_df([]), path, mode=Mode.OVERWRITE)
    assert not path.exists()


def test_write_empty_df_append_skips(tmp_path):
    """APPEND with an empty df must leave an existing file untouched."""
    path = tmp_path / "x.parquet"
    write_parquet(_df([[1000, 1.0, 2.0, 0.5, 1.5, 100.0, 1059]]),
                  path, mode=Mode.OVERWRITE)
    write_parquet(_df([]), path, mode=Mode.APPEND)
    out = pd.read_parquet(path)
    assert len(out) == 1
    assert out["open_time"].iloc[0] == 1000


def test_read_last_open_time_existing(tmp_path):
    path = tmp_path / "x.parquet"
    write_parquet(_df([[1000, 1.0, 2.0, 0.5, 1.5, 100.0, 1059],
                        [3000, 3.0, 4.0, 2.5, 3.5, 300.0, 3059]]),
                  path, mode=Mode.OVERWRITE)
    assert read_last_open_time(path) == 3000


def test_read_last_open_time_missing(tmp_path):
    assert read_last_open_time(tmp_path / "nope.parquet") is None


def test_write_atomic_preserves_prior_on_simulated_crash(tmp_path, monkeypatch):
    """If df.to_parquet raises mid-write, the prior parquet must be intact.

    Atomic write contract: stage to .tmp + rename. A crash before rename
    leaves the original file untouched and only an orphan .tmp behind.
    """
    path = tmp_path / "x.parquet"
    write_parquet(_df([[1000, 1.0, 2.0, 0.5, 1.5, 100.0, 1059]]),
                  path, mode=Mode.OVERWRITE)
    assert read_last_open_time(path) == 1000

    # Simulate a crash mid-write by making pandas raise on to_parquet
    real_to_parquet = pd.DataFrame.to_parquet

    def crashing_to_parquet(self, *args, **kwargs):
        # Touch the tmp path so we observe it being orphaned
        if args and str(args[0]).endswith(".tmp"):
            Path(args[0]).write_bytes(b"PARTIAL_GARBAGE")
        raise OSError("simulated crash")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", crashing_to_parquet)

    try:
        write_parquet(_df([[2000, 2.0, 3.0, 1.5, 2.5, 200.0, 2059]]),
                      path, mode=Mode.APPEND)
    except OSError:
        pass  # expected

    # Restore + verify original parquet still readable + unchanged
    monkeypatch.setattr(pd.DataFrame, "to_parquet", real_to_parquet)
    assert path.exists()
    assert read_last_open_time(path) == 1000  # prior data intact
