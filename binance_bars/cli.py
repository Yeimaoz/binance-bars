"""CLI entry: `python -m binance_bars <subcommand> ...`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from binance_bars.fetcher import fetch_klines, list_symbols
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

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.cmd == "list-symbols":
        return _cmd_list_symbols(args)
    if args.cmd == "fetch":
        return _cmd_fetch(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
