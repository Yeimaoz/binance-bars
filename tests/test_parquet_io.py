from pathlib import Path

import pandas as pd
import pytest

from binance_bars.parquet_io import write_parquet, read_last_open_time, Mode, _detect_time_key


def _df(rows):
    return pd.DataFrame(rows, columns=["open_time", "open", "high", "low",
                                        "close", "volume", "close_time"])


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


# ---------------------------------------------------------------------------
# Tests for non-kline schemas (funding_time / timestamp keys)
# ---------------------------------------------------------------------------

def _funding_df(rows):
    """Minimal funding-rate shaped DataFrame (no open_time column)."""
    return pd.DataFrame(
        rows,
        columns=["funding_time", "symbol", "funding_rate", "mark_price"],
    )


def _oi_df(rows):
    """Minimal open-interest shaped DataFrame (timestamp key, no open_time)."""
    return pd.DataFrame(
        rows,
        columns=["timestamp", "symbol", "open_interest", "open_interest_value"],
    )


def test_detect_time_key_open_time():
    df = pd.DataFrame({"open_time": [1], "close": [2]})
    assert _detect_time_key(df) == "open_time"


def test_detect_time_key_funding_time():
    df = pd.DataFrame({"funding_time": [1], "funding_rate": [0.0001]})
    assert _detect_time_key(df) == "funding_time"


def test_detect_time_key_timestamp():
    df = pd.DataFrame({"timestamp": [1], "open_interest": [1000.0]})
    assert _detect_time_key(df) == "timestamp"


def test_detect_time_key_unknown_raises():
    df = pd.DataFrame({"price": [42.0]})
    with pytest.raises(KeyError, match="open_time"):
        _detect_time_key(df)


def test_append_funding_schema_dedups_and_sorts(tmp_path):
    """APPEND on a funding_rate DataFrame (no open_time) must not raise KeyError."""
    path = tmp_path / "funding.parquet"

    # Initial write
    write_parquet(
        _funding_df([
            [2_000_000, "BTCUSDT", 0.0002, 42100.0],
            [1_000_000, "BTCUSDT", 0.0001, 42000.0],
        ]),
        path,
        mode=Mode.OVERWRITE,
    )

    # Append — row 1_000_000 is a duplicate (keep="last"), row 3_000_000 is new
    write_parquet(
        _funding_df([
            [1_000_000, "BTCUSDT", 0.0001, 42000.0],
            [3_000_000, "BTCUSDT", 0.0003, 42200.0],
        ]),
        path,
        mode=Mode.APPEND,
    )

    out = pd.read_parquet(path)
    assert len(out) == 3
    assert list(out["funding_time"]) == [1_000_000, 2_000_000, 3_000_000]
    assert "open_time" not in out.columns  # schema must remain funding-shaped


def test_append_oi_schema_dedups_and_sorts(tmp_path):
    """APPEND on an open_interest DataFrame (timestamp key) must not raise KeyError."""
    path = tmp_path / "oi.parquet"

    write_parquet(
        _oi_df([[1_000_000, "BTCUSDT", 500.0, 21_000_000.0]]),
        path,
        mode=Mode.OVERWRITE,
    )

    write_parquet(
        _oi_df([
            [1_000_000, "BTCUSDT", 500.0, 21_000_000.0],   # duplicate
            [2_000_000, "BTCUSDT", 600.0, 25_200_000.0],   # new
        ]),
        path,
        mode=Mode.APPEND,
    )

    out = pd.read_parquet(path)
    assert len(out) == 2
    assert list(out["timestamp"]) == [1_000_000, 2_000_000]
