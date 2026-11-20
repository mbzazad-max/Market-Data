# Daily TradingView load (for the scheduled Claude task)

**Since 20 Nov 2026 this task loads the US economic calendar only (step 6).** TradingView gauge candles come from the owner's PC
every 4 hours (TradingView Desktop downloader + upload_gauges.py). Skip steps 4-5: never call mcp-tv-get-ohlcv and never stage
incoming/tv-* here, even if `tv_plan.py` lists candle jobs. The scheduled task's own prompt is the authority.

Claude only LOADS data here. It does not calculate anything for any dashboard.

1. Clone this repo (`mbzazad-max/market-data`, push access) and `cd` into it.
2. `python3 tools/tv_plan.py` prints the jobs: only TradingView series that are missing closed candles, plus `snapshot_jobs` (step 6).
   New series are seeded at most 2 per run (`seed: true`), because a seed answer is large; the rest wait for the next run.
   If `jobs` and `snapshot_jobs` are both empty, stop and report "TradingView data already current".
3. Run `date -u +%s` and keep the number as FETCHED_AT. Do this BEFORE the first TradingView call.
   The importer drops every candle that had not closed at FETCHED_AT (TradingView's last bar is always forming).
4. For each job call the TradingView connector `mcp-tv-get-ohlcv` with exactly its symbol, interval, count and format=columns.
   Large answers are saved to a file by the tool; small answers appear inline: save each inline answer, unchanged,
   as a JSON file under /tmp/tv/. Never edit numbers.
5. `python3 tools/tv_stage.py FETCHED_AT /tmp/tv/*.json <saved answer files...>` writes `incoming/tv-FETCHED_AT/`.
6. Non-candle readings: `tv_plan.py` also prints `snapshot_jobs` (the US economic calendar, on every run: no age check since 14 Nov 2026; CoinMarketCap and CoinGlass moved to READINGS_TASK.md on 14 Nov 2026). For each job call its tool with exactly its args:
   - `mcp-tv-get-economic-calendar` (TradingView connector) with the job's countries, min_importance, date_from, date_to;
   (no CoinMarketCap here any more: see READINGS_TASK.md).
   Save each answer unchanged as JSON (descriptive prose fields such as "comment" or "definition" may be dropped; never edit
   numbers or dates), then: `python3 tools/snap_stage.py FETCHED_AT <name>=<file> ...` (name = the job's "name").
   Never use CryptoRank.
7. Commit the staged folders (incoming/tv-FETCHED_AT/ and incoming/snap-FETCHED_AT/) in ONE commit
   ("TradingView load FETCHED_AT") and push to main. GitHub then imports them, updates manifest.json and tells the dashboards to rebuild.
8. Report: series loaded, series still waiting to be seeded, readings loaded, and any failed call (symbol or tool + error).
   Do not retry a failed call more than once. A failed reading keeps its last good copy.
