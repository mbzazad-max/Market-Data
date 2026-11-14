# Daily CoinGlass load (for the scheduled Claude task on the owner's computer)

Claude only LOADS data here: it reads CoinGlass in the built-in browser and stores the numbers as two readings,
`snap/coinglass_btc` and `snap/coinglass_eth`. It does not calculate anything for any dashboard. Never use CryptoRank.

1. Clone this repo (`mbzazad-max/market-data`, push access) and `cd` into it.
2. Check `manifest.json` → `snapshots`: if both readings were fetched less than 20 hours ago, stop and report "CoinGlass already current".
   Exception: when the owner asks for a CoinGlass load directly in chat, skip this check and load straight away, without asking questions.
3. Run `date -u +%s` and keep it as FETCHED_AT, BEFORE opening CoinGlass.
4. Load the `built-in-browser` skill, open https://www.coinglass.com/FundingRate, set the viewport to 1440×900 and wait ~5 s.
   If the built-in browser cannot be reached (computer asleep or app closed), stop and report it: the last good readings stay.
   Read with JavaScript (`document.body.innerText` and `document.querySelectorAll('table tr')`):
   - after "Accumulated Funding Rate" each value comes BEFORE its label:
     [BTC OI-W] "BTC OI-Weighted…" [ETH OI-W] "ETH OI-Weighted…" [BTC Vol-W] "BTC Volume-Weighted…" [ETH Vol-W] "ETH Volume-Weighted…";
   - table rows starting "BTC" and "ETH": per-exchange rates (columns Binance, OKX, Bybit, …);
   - the header: market open interest (+24h %), 24h liquidation, 24h long/short.
5. https://www.coinglass.com/LiquidationData (wait ~5 s): table rows "1 BTC …" and "2 ETH …" = price, 24h %, then 1h/4h/12h/24h long and short;
   the "Total Liquidations" text = all-market 1h/4h/12h/24h long and short; "According to CoinGlass …" = trader count and largest order.
6. https://www.coinglass.com/open-interest/BTC and /open-interest/ETH (wait ~3 s each): table rows All, CME, Binance, OKX, Bybit
   = open interest in coins and $, share, 1h, 4h, 24h change. Then reset the viewport to "desktop" and close the tab.
7. Write two files, coinglass_btc.json and coinglass_eth.json, each `{"as_of": "<ISO time with +11:00>", "rows": [...]}` with these row ids
   (copy the shape and wording style of the stored readings in data/snap/):
   as_of (value = "13 Nov 2026, 16:40 AEDT" style), funding_oiw, funding_vw, oi_total, liq_btc_24h (that coin's own liquidations, also for ETH),
   liq_mkt_24h, read (two or three plain sentences on what the numbers mean for a spot buyer; no futures trade ideas).
   Each row: group, id, metric, value (text as shown), num, signal, note. num: funding_oiw / funding_vw = rate in %;
   oi_total = 4h open-interest change in % (and num_note "4h OI change, %"); liq_btc_24h = that coin's 24h SHORT share as a fraction;
   liq_mkt_24h = market 24h short share as a fraction; as_of and read = null.
   On the liq_btc_24h row also add the coin's liquidations in US dollars as plain numbers (from its "1 BTC" / "2 ETH" row on
   /LiquidationData): long_1h, short_1h, long_4h, short_4h, long_24h, short_24h (e.g. $444.31M -> 444310000).
   The dashboard's spot buy checklist uses long_1h and long_4h ("flush over").
   In "read", describe what the numbers mean for a spot buyer in plain words; the dashboard adds the spot buy checklist itself. Copy numbers exactly as read; if a table does not load,
   leave that coin out of this run (its last good reading stays) rather than guessing.
8. `python3 tools/snap_stage.py FETCHED_AT coinglass_btc=coinglass_btc.json coinglass_eth=coinglass_eth.json`, commit only
   incoming/snap-FETCHED_AT/ in ONE commit ("CoinGlass load FETCHED_AT") and push to main.
9. Report one line per coin: funding, open interest 4h/24h, 24h liquidations (long/short), or why it was not loaded.
