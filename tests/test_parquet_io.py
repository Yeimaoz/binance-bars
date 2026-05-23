import pandas as pd

from binance_bars.parquet_io import write_parquet, read_last_open_time, Mode


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
