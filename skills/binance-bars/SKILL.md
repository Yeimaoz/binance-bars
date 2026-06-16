---
name: binance-bars
description: >-
  Fetch Binance public-API market data (OHLCV klines, funding rate, open
  interest, basis) and Binance Vision aggTrades daily archives to Parquet — no
  API key. Use when backfilling or refreshing historical crypto bars/derivatives
  data for backtests or research. FOOTGUNS: `fetch` (klines) with no `--start`
  returns ONLY the most-recent 1000 bars — pass `--start` for history (klines
  DOES auto-paginate the start→end range). `funding-rate` and `basis` are
  SINGLE-REQUEST (no pagination) — full history needs a sliding-window loop (see
  recipe). aggTrades is daily-archive (one file per symbol-day, no loop) with a
  T+1 publish lag. NOT for live WebSocket, order book / depth, spot aggTrades, or
  order placement.
---

# binance-bars

Public-API market-data fetcher for Binance USDM-M Futures + Spot. CLI + Python
library, Parquet output, no API key required.

## 何時用 / 何時不用

**用於：**
- 歷史 / 增量 OHLCV klines（spot 或 futures，1m–1d）
- 永續資金費率 (`funding-rate`)、未平倉量 (`open-interest`)、基差 (`basis`)
- aggTrades 逐筆聚合成交「每日封存檔」(`aggtrades`，futures USDM-M)

**不用於：**
- 即時 WebSocket / streaming（本套件只打 REST + 靜態 CDN）
- 訂單簿 / depth / order book snapshot
- spot 的 aggTrades（封存只涵蓋 USDM-M futures）
- 下單 / 交易（無私鑰、無交易端點）

## 安裝

```bash
pip install "binance-bars @ git+https://github.com/Yeimaoz/binance-bars.git@v0.2.0"
```

依賴：`httpx` / `pandas` / `pyarrow`（aggTrades 額外只用 stdlib `urllib`，無新依賴）。

## CLI 速查

```bash
# 列出交易中的 symbol
python -m binance_bars list-symbols --market futures --quote USDT

# OHLCV klines（自動分頁 start→end）
python -m binance_bars fetch --market futures --symbol BTCUSDT --interval 1m \
    --start 2024-12-01 --end 2024-12-31 \
    --output ./BTCUSDT_1m.parquet --mode append

# 資金費率（單次請求）
python -m binance_bars funding-rate --symbol BTCUSDT \
    --start 2024-12-01 --output ./funding/BTCUSDT.parquet

# 未平倉量（自動分頁）
python -m binance_bars open-interest --symbol BTCUSDT --period 5m \
    --output ./oi/BTCUSDT.parquet

# 基差（單次請求）
python -m binance_bars basis --symbol BTC --interval 1d \
    --contract-type CURRENT_QUARTER --output ./basis/BTC.parquet

# aggTrades 每日封存（無分頁迴圈，逐日下載）
python -m binance_bars fetch-aggtrades --symbols BTCUSDT ETHUSDT \
    --date-from 2024-01-01 --date-to 2024-02-01 --output-dir ./agg
```

> ⚠️ **klines footgun**：`fetch` 不帶 `--start` 只回「最近 1000 根」。要歷史一定要給
> `--start`（給了 `--start`/`--end`，`fetch_klines` / `open-interest` 會自動分頁把整段抓齊）。
>
> ⚠️ **單次請求 footgun**：`funding-rate`（≤1000 筆）與 `basis`（≤500 筆）**不分頁**。
> 整段歷史超過一批就要自己用滑動視窗迴圈（見下方 recipe B）。

## ★ klines 全史 backfill recipe

`fetch_klines` 在你給定 `start`/`end` 時已自動分頁——所以「整段歷史」只是給對
`start`。真正需要寫迴圈的情境是**增量續抓**（resume-safe）與**單次請求端點**
（funding/basis）。

### Recipe A — klines 增量續抓（library，resume-safe）

```python
from pathlib import Path
from binance_bars import fetch_klines, write_parquet, read_last_open_time, Mode

def backfill_klines(symbol, interval, output: Path, end=None):
    """Resume-safe：從 parquet 已有的最後一根之後接著抓，APPEND 去重。"""
    last = read_last_open_time(output)          # None 代表全新檔
    start = (last + 1) if last is not None else "2020-01-01"
    df = fetch_klines(market="futures", symbol=symbol, interval=interval,
                      start=start, end=end)     # 內部已分頁整段 start→end
    if not df.empty:
        write_parquet(df, output, mode=Mode.APPEND, time_col="open_time")
    return len(df)
```

`write_parquet(mode=APPEND)` 會把新舊資料 concat、依 `open_time` 去重、排序後原子寫入
（`.tmp` → rename）；重複跑同一指令安全、不會重複列。

### Recipe B — 單次請求端點的滑動視窗（funding-rate / basis）

```python
import pandas as pd
from datetime import datetime, timedelta, timezone
from binance_bars import fetch_funding_rate

def backfill_funding(symbol, start_iso, end=None, window_days=40):
    """funding-rate 單次回最多 1000 筆（約 45 天）；用滑動視窗串接整段歷史。"""
    start = datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc)
    stop = datetime.now(timezone.utc) if end is None else \
        datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    frames = []
    cur = start
    while cur < stop:
        nxt = min(cur + timedelta(days=window_days), stop)
        frames.append(fetch_funding_rate(symbol=symbol, start=cur, end=nxt))
        cur = nxt
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(subset=["funding_time"]).sort_values("funding_time")
```

### Recipe C — 純 CLI klines（增量 append）

```bash
# 重複呼叫安全：mode=append 會去重 open_time。
python -m binance_bars fetch --market futures --symbol BTCUSDT --interval 1m \
    --start 2024-01-01 --output ./BTCUSDT_1m.parquet --mode append
```

## ★ aggTrades backfill 用法

aggTrades 走 Binance Vision **靜態 CDN 的每日封存**——一個 parquet = 一個 symbol 一天的
完整逐筆聚合成交。**沒有分頁迴圈**：傳 `--date-from` / `--date-to`，套件逐日下載。

```bash
python -m binance_bars fetch-aggtrades --symbols BTCUSDT --date-from 2024-01-01 \
    --date-to 2024-02-01 --output-dir ./agg
# → ./agg/BTCUSDT/BTCUSDT-aggTrades-2024-01-01.parquet ...
```

```python
from binance_bars import fetch_aggtrades
stats = fetch_aggtrades(symbols=["BTCUSDT"], date_from="2024-01-01",
                        date_to="2024-02-01", output_dir="./agg")
# stats == {"skipped": ..., "downloaded": ..., "failed": ...}
```

- **resume-safe**：已存在且有效的日檔自動 skip；`date_from=None` 從最後一個日檔的隔天續抓。
- **無效檔自癒**：偵測到缺欄位的壞檔會先刪再重抓。

### 防呆 / Vision 限制（必讀）

- **T+1 延遲**：某一天的封存隔天才上架。抓「今天」一定 404；`--date-to` 預設「昨天 UTC」。
- **404 graceful**：缺檔 / 上市前日期 → 計入 `failed`、**不丟例外**，下次重跑自癒。
- **earliest availability**：USDT 約 2019-12 起、USDC 約 2024-01-04 起；更早的日期一律 404。
- **全史 = GB 級**：單一 symbol 全史是數 GB 等級。請限定日期範圍、留意磁碟。

## 資料 schema

### klines (`fetch_klines`)
| 欄位 | dtype | 說明 |
|---|---|---|
| `open_time` | int (ms UTC) | bar 起始 |
| `open`/`high`/`low`/`close` | float | OHLC |
| `volume` | float | base-asset 量 |
| `close_time` | int (ms UTC) | bar 結束 |

### funding_rate (`fetch_funding_rate`)
`funding_time` int(ms) / `symbol` str / `funding_rate` float / `mark_price` float

### open_interest (`fetch_open_interest`)
`timestamp` int(ms) / `symbol` str / `open_interest` float(契約) / `open_interest_value` float(USD)

### basis (`fetch_basis`)
`timestamp` int(ms) / `pair` str / `futures_price` float / `index_price` float / `basis` float / `basis_rate` float

### aggTrades (`fetch_aggtrades`) — canonical 5 欄
| 欄位 | dtype | 說明 |
|---|---|---|
| `agg_trade_id` | int64 | 每 symbol 唯一的聚合成交 id |
| `price` | float64 | 成交價 |
| `quantity` | float64 | 成交量（base asset） |
| `timestamp_ms` | int64 | 成交時間，unix 毫秒 UTC |
| `is_buyer_maker` | bool | True = 買方為 maker（賣方主動吃單 / ask-side fill） |

## 寫檔語意

- **klines / funding / OI / basis**：`write_parquet` APPEND——concat + 依 time_col 去重 + 排序 +
  原子寫入（`.tmp` → rename）。重複跑安全。
- **aggTrades**：每日檔原子寫入（`.tmp` → rename）。中斷只留 `.tmp` 孤兒、原檔不壞；
  日檔即完整不需 row-merge。

## 限流與錯誤

- **REST 端點**（klines/funding/OI/basis）：Binance 採 IP 權重限制。套件在 HTTP 429 讀
  `Retry-After` → 睡眠後重試一次（`RateLimitedError`）；HTTP 418（IP 封禁）→ 立刻丟
  `IpBannedError`、不重試。
- **aggTrades（Vision CDN）**：靜態 CDN 無限流、無 backoff；404 → 計 `failed`，用
  `sleep_between` 做禮貌延遲即可。

## 姊妹套件對照（vs shioaji-bars）

`binance-bars`（公開 crypto）與 `shioaji-bars`（authenticated 台股 / 台指期）是
姊妹 OSS 套件，刻意維持對齊的能力面與 API 形狀——學會一邊就能轉移到另一邊。
依「概念」對照本套件函式 ↔ sibling 函式：

| 概念 | binance-bars（本套件） | shioaji-bars（sibling） |
|---|---|---|
| 認證 | —（公開 REST，無金鑰） | `login()` / `logout()` |
| OHLCV bars | `fetch_klines(market, symbol, interval, start, end)` | `fetch_kbars(api, contract, interval, start, end)` |
| 逐筆成交 | `fetch_aggtrades(symbols, date_from, date_to, output_dir)` → stats（聚合·多 symbol × 多日·自寫檔；CLI `fetch-aggtrades`） | `fetch_ticks(api, contract, date)` → DataFrame 8 欄（逐筆·單合約單日·caller 寫檔；CLI `fetch-ticks`） |
| 即時快照 | —（改提供 funding / OI / basis 衍生資料） | `fetch_snapshots(api, contracts)` |
| 衍生資料 | `fetch_funding_rate` / `fetch_open_interest` / `fetch_basis` | — |
| 標的清單 | `list_symbols` | `list_contracts` |
| 寫檔 / 游標 | `write_parquet` / `read_last_open_time` | `write_parquet` / `read_last_ts` |
| 逐筆時間欄 | `timestamp_ms`（int64 unix-ms） | `ts`（datetime64[ns, UTC]） |
| 逐筆方向欄 | `is_buyer_maker`（taker 側） | `tick_type`（內外盤，**≠** `is_buyer_maker`） |

**關鍵差異（逐筆成交）：** 兩邊逐筆語意不同——本套件是 **producer**
（Binance Vision 批次封存，逐日自寫檔、多 symbol × 多日 resume-safe）；
shioaji-bars 是 **reader**（走 shioaji per-day 配額，單日回 DataFrame、由 caller
自行寫檔）。schema 風格各自延續本家 bars：本套件 int-ms（`timestamp_ms`），
sibling tz-aware datetime（`ts`）。方向欄 `is_buyer_maker`（交易所 taker 側）
與 `tick_type`（broker 內外盤）**語意不等價**，跨市場 order-flow 比較前必先正規化。
