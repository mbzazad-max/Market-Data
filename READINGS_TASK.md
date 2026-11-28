# Daily readings load: CoinMarketCap + CoinGlass (one scheduled Claude task, 11:30 Sydney, on the owner's computer)

Claude only LOADS data here. Every run loads everything, whenever it runs (the 11:30 schedule or "Run now"): there is
NO age check and no "already current" stop. It stores seven readings: `snap/cmc_global`, `snap/cmc_quotes` (SOL, BNB),
`snap/coinglass_btc`, `snap/coinglass_eth`, `snap/coinglass_sol`, `snap/coinglass_bnb` and `snap/etf_flows` (US spot ETF net flows). Each load also becomes one row in
the history CSVs in data/history/ (see tools/snap_history.py). It does not calculate anything for any dashboard and never
suggests futures trades. Never use CryptoRank. Work unattended; do not ask questions.

1. Clone this repo (`mbzazad-max/market-data`, push access) and `cd` into it.
2. (No age check: always load.)
3. Run `date -u +%s` and keep it as FETCHED_AT, BEFORE the first CoinMarketCap call.
   CoinMarketCap (CoinMarketCap connector; save each answer unchanged as JSON, long "definition" texts may be dropped,
   never change numbers or dates):
   - `get_global_metrics_latest` (no arguments) -> cmc_global.json
   - `get_crypto_quotes_latest` with id "5426,1839" (SOL and BNB, one call) -> cmc_quotes.json
   If the connector fails twice or needs re-authorisation, leave CoinMarketCap out of this run and carry on with CoinGlass.
   CoinGlass:
4. Load the `built-in-browser` skill, open https://www.coinglass.com/FundingRate, set the viewport to 1440×900 and wait ~5 s.
   If the built-in browser cannot be reached (computer asleep or app closed), skip CoinGlass this run (its last good readings stay)
   and go straight to step 8 with the CoinMarketCap files only; say so in the report.
   Read with JavaScript (`document.body.innerText` and `document.querySelectorAll('table tr')`):
   - after "Accumulated Funding Rate" each value comes BEFORE its label:
     [BTC OI-W] "BTC OI-Weighted…" [ETH OI-W] "ETH OI-Weighted…" [BTC Vol-W] "BTC Volume-Weighted…" [ETH Vol-W] "ETH Volume-Weighted…";
   - table rows starting "BTC" and "ETH": per-exchange rates (columns Binance, OKX, Bybit, …);
   - the header: market open interest (+24h %), 24h liquidation, 24h long/short.
   SOL and BNB have no OI-weighted or volume-weighted rate on that page: open https://www.coinglass.com/FundingRate/SOL and
   /FundingRate/BNB (wait ~4 s each) and read "SOL AVG Funding" / "BNB AVG Funding" plus the per-exchange table (Binance, OKX, Bybit, …).
5. https://www.coinglass.com/LiquidationData (wait ~5 s): table rows "1 BTC …", "2 ETH …", "<n> SOL …" and "<n> BNB …" = price, 24h %, then 1h/4h/12h/24h long and short
   (the rank number in front changes, e.g. "3 SOL", "9 BNB": match the row by its symbol);
   the "Total Liquidations" text = all-market 1h/4h/12h/24h long and short; "According to CoinGlass …" = trader count and largest order.
6. https://www.coinglass.com/open-interest/BTC, /open-interest/ETH, /open-interest/SOL and /open-interest/BNB (wait ~3 s each): table rows All, CME, Binance, OKX, Bybit
   = open interest in coins and $, share, 1h, 4h, 24h change. Then reset the viewport to "desktop" and close the tab.
7. Write four files, coinglass_btc.json, coinglass_eth.json, coinglass_sol.json and coinglass_bnb.json, each `{"as_of": "<ISO time with +11:00>", "rows": [...]}` with these row ids
   (copy the shape and wording style of the stored readings in data/snap/):
   as_of (value = "13 Nov 2026, 16:40 AEDT" style), funding_oiw, funding_vw, oi_total, liq_btc_24h (that coin's own liquidations, also for ETH),
   liq_mkt_24h, read (two or three plain sentences on what the numbers mean for a spot buyer; no futures trade ideas).
   Each row: group, id, metric, value (text as shown), num, signal, note. num: funding_oiw / funding_vw = rate in %;
   for SOL and BNB put the "AVG Funding" rate in BOTH funding_oiw and funding_vw, with metrics "SOL average funding (8h)" /
   "SOL funding by exchange (8h)" (BNB likewise) and the per-exchange rates in funding_vw's note;
   oi_total = 4h open-interest change in % (and num_note "4h OI change, %"); liq_btc_24h = that coin's 24h SHORT share as a fraction;
   liq_mkt_24h = market 24h short share as a fraction; as_of and read = null.
   Plain-number fields for the history CSVs (copy from the page; % without the sign symbol, e.g. −1.27% -> -1.27; $ in dollars):
   on oi_total: oi_usd, oi_chg_1h, oi_chg_24h; on liq_btc_24h: price, price_chg_24h; on liq_mkt_24h: long_1h, short_1h,
   long_4h, short_4h, long_24h, short_24h (all-market), oi_usd, oi_chg_24h (market-wide OI), long_ratio (e.g. 48.51).
   On the liq_btc_24h row also add the coin's liquidations in US dollars as plain numbers (from its "1 BTC" / "2 ETH" / "<n> SOL" / "<n> BNB" row on
   /LiquidationData): long_1h, short_1h, long_4h, short_4h, long_24h, short_24h (e.g. $444.31M -> 444310000).
   The dashboard's spot buy checklist uses long_1h and long_4h ("flush over").
   In "read", describe what the numbers mean for a spot buyer in plain words; the dashboard adds the spot buy checklist itself. Copy numbers exactly as read; if a table does not load,
   leave that coin out of this run (its last good reading stays) rather than guessing.
7b. US spot ETF net flows (added 28 Nov 2026), in the same built-in browser session (skip with the CoinGlass steps if the browser
   cannot be reached):
   - Farside: open https://farside.co.uk/btc/ (wait ~4 s), then read /btc/, /eth/, /sol/ and /zec/ in ONE JavaScript call from that tab:
     for each page `fetch('/<coin>/')`, parse it with DOMParser, take its largest table, keep rows whose first cell is a date like
     "27 Nov 2026" and read the LAST cell (Total, US$ millions). Brackets mean negative: "(389.0)" -> -389.0, "1,045.0" -> 1045.0.
     A "-" cell (no data yet for that day) is left out. Each page shows about the last 14 trading days: keep them all.
   - HYPE: open https://sosovalue.com/assets/etf/us-hype-spot (wait ~6 s) and read from `document.body.innerText` the
     "Daily Total Net Inflow" value and the "As of <Mon DD>" date after it (e.g. "-$1.03M" "As of Nov 27" -> ["2026-11-27", -1.03];
     $K -> /1000, $B -> x1000), and "Total Net Assets" in US$ millions.
   - Write etf_flows.json:
     `{"as_of": "<ISO time with +11:00>", "unit": "US$ millions, net flow per US trading day (negative = outflow)", "assets": {
       "BTC": {"source": "Farside (farside.co.uk/btc/), Total column", "days": [["2026-11-27", -389.0], ...]},
       "ETH": {...}, "SOL": {...}, "ZEC": {...},
       "HYPE": {"source": "SoSoValue (sosovalue.com/assets/etf/us-hype-spot), Daily Total Net Inflow", "days": [["2026-11-27", -1.03]], "net_assets_musd": 283.22}}}`
     Dates are the US trading day as shown (YYYY-MM-DD). Copy numbers exactly; leave out an asset whose page does not load rather
     than guessing. Only recent days are needed: the importer merges them into the stored history (a newer value replaces a day).
8. `python3 tools/snap_stage.py FETCHED_AT cmc_global=cmc_global.json cmc_quotes=cmc_quotes.json coinglass_btc=coinglass_btc.json coinglass_eth=coinglass_eth.json coinglass_sol=coinglass_sol.json coinglass_bnb=coinglass_bnb.json etf_flows=etf_flows.json`
   (leave out anything not loaded this run), commit only incoming/snap-FETCHED_AT/ in ONE commit ("Readings load FETCHED_AT")
   and push to main (fetch and rebase on origin/main first if the push is rejected). GitHub then imports it, adds one row per
   reading to the CSV files in data/history/, and the dashboards rebuild themselves.
9. Report: ETF flows (latest day per coin, and BTC's 5-day total), then CoinMarketCap (fear & greed, total market cap, BTC dominance; SOL and BNB price and rank), then one line per coin
   (BTC, ETH, SOL, BNB): funding, open interest 4h/24h, 24h liquidations (long/short), or why something was not loaded.
