"""CLI entry: `python -m binance_bars <subcommand> ...`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from binance_bars.fetcher import (
    fetch_basis,
    fetch_funding_rate,
    fetch_klines,
    fetch_open_interest,
    list_symbols,
)
from binance_bars.parquet_io import Mode, write_parquet


def _cmd_list_symbols(args: argparse.Namespace) -> int:
    syms = list_symbols(market=args.market, quote=args.quote,
                        trading_only=args.trading_only)
    for s in syms:
        print(s)
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    df = fetch_klines(
        market=args.market,
        symbol=args.symbol,
        interval=args.interval,
        start=args.start,
        end=args.end,
    )
    write_parquet(df, Path(args.output), mode=Mode(args.mode))
    return 0


def _cmd_funding_rate(args: argparse.Namespace) -> int:
    df = fetch_funding_rate(symbol=args.symbol, start=args.start, end=args.end)
    write_parquet(df, Path(args.output), mode=Mode(args.mode))
    return 0


def _cmd_open_interest(args: argparse.Namespace) -> int:
    df = fetch_open_interest(symbol=args.symbol, period=args.period,
                              start=args.start, end=args.end)
    write_parquet(df, Path(args.output), mode=Mode(args.mode))
    return 0


def _cmd_basis(args: argparse.Namespace) -> int:
    df = fetch_basis(symbol=args.symbol, interval=args.interval,
                      pair_contract_type=args.contract_type,
                      start=args.start, end=args.end)
    write_parquet(df, Path(args.output), mode=Mode(args.mode))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="binance-bars")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ls = sub.add_parser("list-symbols", help="List trading symbols")
    p_ls.add_argument("--market", choices=["spot", "futures"], default="futures")
    p_ls.add_argument("--quote", default=None, help="filter by quote asset (e.g. USDT)")
    p_ls.add_argument("--trading-only", action="store_true", default=True,
                      help="keep only status=TRADING")

    p_fetch = sub.add_parser("fetch", help="Fetch OHLCV klines -> parquet")
    p_fetch.add_argument("--market", choices=["spot", "futures"], required=True)
    p_fetch.add_argument("--symbol", required=True)
    p_fetch.add_argument("--interval", required=True,
                          choices=["1m", "5m", "15m", "1h", "4h", "1d"])
    p_fetch.add_argument("--start", default=None)
    p_fetch.add_argument("--end", default=None)
    p_fetch.add_argument("--output", required=True)
    p_fetch.add_argument("--mode", choices=["append", "overwrite", "skip"],
                          default="append")

    p_fr = sub.add_parser("funding-rate", help="Funding rate history (futures)")
    p_fr.add_argument("--symbol", required=True)
    p_fr.add_argument("--start", default=None)
    p_fr.add_argument("--end", default=None)
    p_fr.add_argument("--output", required=True)
    p_fr.add_argument("--mode", choices=["append", "overwrite", "skip"],
                       default="append")

    p_oi = sub.add_parser("open-interest", help="Open interest history (futures)")
    p_oi.add_argument("--symbol", required=True)
    p_oi.add_argument("--period", default="5m")
    p_oi.add_argument("--start", default=None)
    p_oi.add_argument("--end", default=None)
    p_oi.add_argument("--output", required=True)
    p_oi.add_argument("--mode", choices=["append", "overwrite", "skip"],
                       default="append")

    p_b = sub.add_parser("basis", help="Basis (futures - index) history")
    p_b.add_argument("--symbol", required=True)
    p_b.add_argument("--interval", default="1d")
    p_b.add_argument("--contract-type", default="CURRENT_QUARTER",
                      choices=["CURRENT_QUARTER", "NEXT_QUARTER", "PERPETUAL"])
    p_b.add_argument("--start", default=None)
    p_b.add_argument("--end", default=None)
    p_b.add_argument("--output", required=True)
    p_b.add_argument("--mode", choices=["append", "overwrite", "skip"],
                       default="append")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.cmd == "list-symbols":
        return _cmd_list_symbols(args)
    if args.cmd == "fetch":
        return _cmd_fetch(args)
    if args.cmd == "funding-rate":
        return _cmd_funding_rate(args)
    if args.cmd == "open-interest":
        return _cmd_open_interest(args)
    if args.cmd == "basis":
        return _cmd_basis(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
