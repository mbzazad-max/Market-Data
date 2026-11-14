# market-data

Shared candles for all dashboards. Each series is stored once, as CSV text (`data/<source>/<SYMBOL>_<TF>.csv`,
columns `time,open,high,low,close,volume`, time = candle open in unix seconds UTC), merged by time with no duplicates.

- `series.json`: every series this repo keeps. `dashboards.json`: which dashboard repos rebuild when their series change.
- `manifest.json`: per series, last closed candle, fetch time and row count. Check it before fetching anything; fetch only what is stale.
- **Binance** candles come from the laptop uploader (`uploader/`, see its README.txt). One upload = one commit.
- **TradingView** candles come from the daily Claude task (`TV_TASK.md`). One load = one commit.
- `.github/workflows/import.yml` (the only workflow) merges `incoming/` into `data/`, updates the manifest and asks dashboards to rebuild.

Closed candles only: a candle is kept only if it had closed by the data's own fetch time (never the time the import runs).
A Binance candle that already exists must never change; if it does, that upload is rejected and the last good data stays.

## Check dashboards (on demand)
Actions → **Check dashboards** → **Run workflow**. It compares every dashboard in `dashboards.json` with `manifest.json`: last closed candle and row count per series, reading times, the dashboard's last build, and the live page (`site`) against its repo. The report is on the run's **Summary** page; the run turns red when something needs attention. Tick "rebuild" to also restart every dashboard that is behind or failed. Script: `tools/check_dashboards.py`.
