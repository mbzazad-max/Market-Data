# market-data

Shared candles for all dashboards. Each series is stored once, as CSV text (`data/<source>/<SYMBOL>_<TF>.csv`,
columns `time,open,high,low,close,volume`, time = candle open in unix seconds UTC), merged by time with no duplicates.

- `series.json`: every series this repo keeps. `dashboards.json`: which dashboard repos rebuild when their series change.
- `manifest.json`: per series, last closed candle, fetch time and row count. Check it before fetching anything; fetch only what is stale.
- Every dashboard reads its candles from this repo only; no dashboard fetches Binance or TradingView itself.
- Timeframes: **1H**, **4H** and **1D** (1W and longer are built by each dashboard from 1D).
- **Binance** candles: the GitHub workflow `binance.yml` (`tools/binance_fetch.py`) fetches them from the Binance klines API
  (data-api.binance.vision first, api.binance.com second) every 4 hours, 7 min after each 4H close, for every Binance series in
  `series.json`: 1H, 4H and 1D are topped up together (1H arrives four candles at a time). A new Binance series with a
  `seed_count` is seeded there too (its newest N closed candles), so adding a coin is one line in `series.json`.
  The laptop uploader (`uploader/`, see its README.txt) still works as the fallback for any Binance series.
- **TradingView** candles (market gauges, 1H and 4H) come from the owner's PC every 4 hours (since 20 Nov 2026):
  the TradingView Desktop downloader + `upload_gauges.py` (folder `SPOT\tvdl`, `download_and_upload.bat`) send only new candles
  as `incoming/tv-<time>/`, one commit per run ("Upload TradingView gauges from desktop"). The daily 11:30 Sydney Claude task
  (`TV_TASK.md`) now loads only the US economic calendar and reports if the PC uploads look stalled; it no longer fetches candles.
- `.github/workflows/import.yml` merges `incoming/` into `data/`, updates the manifest and asks the dashboards in
  `dashboards.json` that use a changed series to rebuild. Other workflows: `binance.yml` (above), `check.yml` (Check dashboards), `fng.yml`.

Closed candles only: a candle is kept only if it had closed by the data's own fetch time (never the time the import runs).
A Binance candle that already exists must never change; if it does, that upload is rejected and the last good data stays.

## Check dashboards (on demand)
Actions → **Check dashboards** → **Run workflow**. It compares every dashboard in `dashboards.json` with `manifest.json`: last closed candle and row count per series, reading times, the dashboard's last build, and the live page (`site`) against its repo. The report is on the run's **Summary** page; the run turns red when something needs attention. Tick "rebuild" to also restart every dashboard that is behind or failed. Script: `tools/check_dashboards.py`.

## Readings history (CSV)
CoinGlass and CoinMarketCap readings (loaded by the daily 11:30 task in READINGS_TASK.md, or any time with "Run now")
are also kept as history, one row per load, in `data/history/`:
`coinglass_btc.csv`, `coinglass_eth.csv`, `coinglass_sol.csv`, `coinglass_bnb.csv` (funding, open interest, liquidations),
`cmc_global.csv` (market cap, volume, fear & greed, altcoin season, dominance, open interest, funding, ETF assets) and
`cmc_quotes.csv` (SOL and BNB price, rank, market cap, volume, % changes). Plain numbers; `fetched_at` (unix s, UTC) is the key.
The importer adds the rows (tools/snap_history.py); `python3 tools/snap_history.py backfill` rebuilds them from git history.
