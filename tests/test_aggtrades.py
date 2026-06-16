"""Tests for the generic Binance Vision aggTrades archive downloader."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from binance_bars import aggtrades as agg


# ---------------------------------------------------------------------------
# Synthetic zip fixture (mirrors a Binance Vision daily aggTrades archive)
# ---------------------------------------------------------------------------

def _make_zip_bytes(
    rows: list[tuple[int, float, float, int, int, int, bool]] | None = None,
    *,
    inner_name: str = "BTCUSDT-aggTrades-2024-01-01.csv",
) -> bytes:
    """Build an in-memory zip containing a Binance-Vision-shaped aggTrades CSV.

    CSV columns (no header in real archives, but pandas usecols needs names; the
    real archives are headerless — we emit a header here and the parser reads by
    position via the declared column names).
    """
    if rows is None:
        rows = [
            # agg_trade_id, price, quantity, first_trade_id, last_trade_id,
            # transact_time, is_buyer_maker
            (1, 42000.0, 0.5, 10, 11, 1_704_067_200_000, True),
            (2, 42001.5, 1.25, 12, 12, 1_704_067_201_000, False),
        ]
    header = ",".join(agg.CSV_COLUMNS)
    lines = [header]
    for r in rows:
        lines.append(",".join(str(v) for v in r))
    csv_text = "\n".join(lines) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, csv_text)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# validate_symbol
# ---------------------------------------------------------------------------

def test_validate_symbol_rejects_comma():
    with pytest.raises(ValueError):
        agg.validate_symbol("BTCUSDT,ETHUSDT")


def test_validate_symbol_accepts_plain():
    agg.validate_symbol("BTCUSDT")  # no raise


# ---------------------------------------------------------------------------
# iter_dates
# ---------------------------------------------------------------------------

def test_iter_dates_inclusive():
    assert agg.iter_dates("2024-01-01", "2024-01-03") == [
        "2024-01-01", "2024-01-02", "2024-01-03",
    ]


def test_iter_dates_single_day():
    assert agg.iter_dates("2024-01-01", "2024-01-01") == ["2024-01-01"]


def test_iter_dates_empty_when_from_after_to():
    assert agg.iter_dates("2024-01-05", "2024-01-01") == []


# ---------------------------------------------------------------------------
# infer_date_from
# ---------------------------------------------------------------------------

def test_infer_date_from_empty_dir_default(tmp_path):
    assert agg.infer_date_from(tmp_path) == agg.DEFAULT_EARLIEST


def test_infer_date_from_resumes_next_day(tmp_path):
    (tmp_path / "BTCUSDT-aggTrades-2024-01-05.parquet").write_bytes(b"x")
    assert agg.infer_date_from(tmp_path) == "2024-01-06"


# ---------------------------------------------------------------------------
# is_file_valid
# ---------------------------------------------------------------------------

def test_is_file_valid_true_for_canonical(tmp_path):
    df = agg.parse_zip_to_df(_make_zip_bytes())
    p = tmp_path / "ok.parquet"
    agg.write_atomic(df, p)
    assert agg.is_file_valid(p) is True


def test_is_file_valid_false_when_missing(tmp_path):
    assert agg.is_file_valid(tmp_path / "nope.parquet") is False


def test_is_file_valid_false_missing_agg_trade_id(tmp_path):
    p = tmp_path / "bad.parquet"
    pd.DataFrame({"price": [1.0], "quantity": [2.0]}).to_parquet(p, index=False)
    assert agg.is_file_valid(p) is False


# ---------------------------------------------------------------------------
# parse_zip_to_df
# ---------------------------------------------------------------------------

def test_parse_zip_to_df_schema():
    df = agg.parse_zip_to_df(_make_zip_bytes())
    assert list(df.columns) == agg.CANONICAL_COLUMNS
    assert df["agg_trade_id"].dtype == "int64"
    assert df["timestamp_ms"].dtype == "int64"
    assert df["is_buyer_maker"].dtype == "bool"
    assert df["price"].dtype == "float64"
    assert df["quantity"].dtype == "float64"
    assert len(df) == 2
    assert df["agg_trade_id"].tolist() == [1, 2]
    assert df["is_buyer_maker"].tolist() == [True, False]


# ---------------------------------------------------------------------------
# write_atomic
# ---------------------------------------------------------------------------

def test_write_atomic_zstd_roundtrip(tmp_path):
    df = agg.parse_zip_to_df(_make_zip_bytes())
    p = tmp_path / "BTCUSDT-aggTrades-2024-01-01.parquet"
    agg.write_atomic(df, p)
    assert p.exists()
    # No leftover .tmp on success.
    assert not (tmp_path / "BTCUSDT-aggTrades-2024-01-01.parquet.tmp").exists()
    out = pd.read_parquet(p)
    assert df.equals(out)
    # zstd compression in column metadata.
    import pyarrow.parquet as pq
    meta = pq.ParquetFile(p).metadata
    comps = {
        meta.row_group(0).column(i).compression
        for i in range(meta.row_group(0).num_columns)
    }
    assert comps == {"ZSTD"}


# ---------------------------------------------------------------------------
# fetch_aggtrades download loop (mock urllib)
# ---------------------------------------------------------------------------

def test_fetch_aggtrades_download_loop(tmp_path):
    zip_bytes = _make_zip_bytes()

    def fake_download(url, timeout=30):
        # 404 graceful for the 2nd day, success otherwise.
        if "2024-01-02" in url:
            return None
        return zip_bytes

    with patch.object(agg, "download_zip", side_effect=fake_download):
        stats = agg.fetch_aggtrades(
            symbols=["BTCUSDT"],
            date_from="2024-01-01",
            date_to="2024-01-03",
            output_dir=tmp_path,
            sleep_between=0.0,
        )
    # day 01 + 03 downloaded, day 02 failed (404 graceful, no raise).
    assert stats == {"skipped": 0, "downloaded": 2, "failed": 1}
    assert (tmp_path / "BTCUSDT" / "BTCUSDT-aggTrades-2024-01-01.parquet").exists()
    assert not (tmp_path / "BTCUSDT" / "BTCUSDT-aggTrades-2024-01-02.parquet").exists()
    assert (tmp_path / "BTCUSDT" / "BTCUSDT-aggTrades-2024-01-03.parquet").exists()


def test_fetch_aggtrades_skips_valid_existing(tmp_path):
    zip_bytes = _make_zip_bytes()
    # Pre-write a valid day-01 file.
    sym_dir = tmp_path / "BTCUSDT"
    sym_dir.mkdir(parents=True)
    df = agg.parse_zip_to_df(zip_bytes)
    agg.write_atomic(df, sym_dir / "BTCUSDT-aggTrades-2024-01-01.parquet")

    calls: list[str] = []

    def fake_download(url, timeout=30):
        calls.append(url)
        return zip_bytes

    with patch.object(agg, "download_zip", side_effect=fake_download):
        stats = agg.fetch_aggtrades(
            symbols=["BTCUSDT"],
            date_from="2024-01-01",
            date_to="2024-01-02",
            output_dir=tmp_path,
            sleep_between=0.0,
        )
    assert stats == {"skipped": 1, "downloaded": 1, "failed": 0}
    # Only day-02 was actually downloaded.
    assert all("2024-01-01" not in u for u in calls)
    assert any("2024-01-02" in u for u in calls)


def test_fetch_aggtrades_redownloads_invalid(tmp_path):
    zip_bytes = _make_zip_bytes()
    sym_dir = tmp_path / "BTCUSDT"
    sym_dir.mkdir(parents=True)
    # Pre-write an INVALID day-01 file (missing canonical cols).
    bad = sym_dir / "BTCUSDT-aggTrades-2024-01-01.parquet"
    pd.DataFrame({"foo": [1]}).to_parquet(bad, index=False)

    with patch.object(agg, "download_zip", return_value=zip_bytes):
        stats = agg.fetch_aggtrades(
            symbols=["BTCUSDT"],
            date_from="2024-01-01",
            date_to="2024-01-01",
            output_dir=tmp_path,
            sleep_between=0.0,
        )
    assert stats == {"skipped": 0, "downloaded": 1, "failed": 0}
    assert agg.is_file_valid(bad)  # now valid after redownload


def test_fetch_aggtrades_incremental_from_existing(tmp_path):
    """date_from=None → resume from day after last existing file."""
    zip_bytes = _make_zip_bytes()
    sym_dir = tmp_path / "BTCUSDT"
    sym_dir.mkdir(parents=True)
    df = agg.parse_zip_to_df(zip_bytes)
    agg.write_atomic(df, sym_dir / "BTCUSDT-aggTrades-2024-01-05.parquet")

    calls: list[str] = []

    def fake_download(url, timeout=30):
        calls.append(url)
        return zip_bytes

    with patch.object(agg, "download_zip", side_effect=fake_download):
        agg.fetch_aggtrades(
            symbols=["BTCUSDT"],
            date_from=None,
            date_to="2024-01-07",
            output_dir=tmp_path,
            sleep_between=0.0,
        )
    # Resumes at 2024-01-06; never re-fetches 01-05 or earlier.
    assert any("2024-01-06" in u for u in calls)
    assert any("2024-01-07" in u for u in calls)
    assert all("2024-01-05" not in u for u in calls)


# ---------------------------------------------------------------------------
# Canonical schema contract (migration-safety gate) — P1-6
# ---------------------------------------------------------------------------

def test_canonical_schema_matches_contract():
    # Byte-identical to the downstream reader contract (5 columns).
    assert agg.CANONICAL_COLUMNS == [
        "agg_trade_id", "price", "quantity", "timestamp_ms", "is_buyer_maker",
    ]
    assert agg.CANONICAL_DTYPES == {
        "agg_trade_id": "int64",
        "price": "float64",
        "quantity": "float64",
        "timestamp_ms": "int64",
        "is_buyer_maker": "bool",
    }


def test_schema_equivalence_roundtrip(tmp_path):
    df = agg.parse_zip_to_df(_make_zip_bytes())
    # Every canonical dtype matches the contract.
    for col, dtype in agg.CANONICAL_DTYPES.items():
        assert str(df[col].dtype) == dtype
    p = tmp_path / "rt.parquet"
    agg.write_atomic(df, p)
    out = pd.read_parquet(p, columns=agg.CANONICAL_COLUMNS)
    assert df.equals(out)
    for col, dtype in agg.CANONICAL_DTYPES.items():
        assert str(out[col].dtype) == dtype
    import pyarrow.parquet as pq
    meta = pq.ParquetFile(p).metadata
    assert meta.row_group(0).column(0).compression == "ZSTD"


# ---------------------------------------------------------------------------
# CLI — P1-2
# ---------------------------------------------------------------------------

def test_cli_aggtrades_invokes_fetch(tmp_path):
    from binance_bars.cli import main

    captured: dict = {}

    def fake_fetch(symbols, date_from, date_to, output_dir, sleep_between=0.3):
        captured.update(
            symbols=symbols, date_from=date_from, date_to=date_to,
            output_dir=output_dir, sleep_between=sleep_between,
        )
        return {"skipped": 0, "downloaded": 2, "failed": 0}

    with patch("binance_bars.cli.fetch_aggtrades", side_effect=fake_fetch), \
         patch.object(sys, "argv", [
             "binance-bars", "fetch-aggtrades",
             "--symbols", "BTCUSDT", "ETHUSDT",
             "--date-from", "2024-01-01",
             "--date-to", "2024-01-02",
             "--output-dir", str(tmp_path),
         ]):
        rc = main()
    assert rc == 0
    assert captured["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert captured["date_from"] == "2024-01-01"
    assert captured["date_to"] == "2024-01-02"
    assert captured["output_dir"] == Path(tmp_path)
