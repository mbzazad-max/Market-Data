# Daily TradingView load (for the scheduled Claude task)

Claude only LOADS data here. It does not calculate anything for any dashboard.

1. Clone this repo (`mbzazad-max/market-data`, push access) and `cd` into it.
2. `python3 tools/tv_plan.py` prints the jobs: only TradingView series that are missing closed candles.
   New series are seeded at most 2 per run (`seed: true`), because a seed answer is large; the rest wait for the next run.
   If `jobs` is empty, stop and report "TradingView data already current".
3. Run `date -u +%s` and keep the number as FETCHED_AT. Do this BEFORE the first TradingView call.
   The importer drops every candle that had not closed at FETCHED_AT (TradingView's last bar is always forming).
4. For each job call the TradingView connector `mcp-tv-get-ohlcv` with exactly its symbol, interval, count and format=columns.
   Large answers are saved to a file by the tool; small answers appear inline: save each inline answer, unchanged,
   as a JSON file under /tmp/tv/. Never edit numbers.
5. `python3 tools/tv_stage.py FETCHED_AT /tmp/tv/*.json <saved answer files...>` writes `incoming/tv-FETCHED_AT/`.
6. Commit only that folder in ONE commit ("TradingView load FETCHED_AT") and push to main.
   GitHub then imports it, updates manifest.json and tells the dashboards to rebuild.
7. Report: series loaded, series still waiting to be seeded, and any failed call (symbol + error). Do not retry a failed call more than once.
