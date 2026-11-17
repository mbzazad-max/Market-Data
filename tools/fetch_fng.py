"""Fetch the whole Crypto Fear & Greed Index history from alternative.me and write it as CSV.

Source: https://api.alternative.me/fng/?limit=0&format=json  (public, no key; one market-wide daily value,
0 = Extreme Fear .. 100 = Extreme Greed, history back to 1 Feb 2018). This is a DIFFERENT index from the
CoinMarketCap Fear & Greed reading stored in cmc_global; keep the two separate.

The API returns the full history every call, so this script rewrites the whole file each run: idempotent,
and any day the source adds or restates is picked up automatically (a few early days are missing at source).

Output: data/history/altme_fng.csv, one row per day, oldest first, columns: date,timestamp,value,classification.
  date        UTC calendar day (YYYY-MM-DD) of the reading
  timestamp   unix seconds, UTC midnight (the API key)
  value       integer 0..100
  classification  Extreme Fear / Fear / Neutral / Greed / Extreme Greed

Attribution (alternative.me terms): show "Data from alternative.me" next to the value wherever it is displayed.

usage: python3 -I tools/fetch_fng.py        (writes the CSV, prints a one-line report)
       python3 -I tools/fetch_fng.py --check (fetch and validate only, write nothing)
"""
import csv
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

URL = "https://api.alternative.me/fng/?limit=0&format=json"
OUT = Path(__file__).resolve().parent.parent / "data" / "history" / "altme_fng.csv"
COLS = ["date", "timestamp", "value", "classification"]
DAY = 86400


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "market-data-fng/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def parse(doc):
    meta = doc.get("metadata") or {}
    if meta.get("error"):
        raise SystemExit(f"API error: {meta['error']}")
    data = doc.get("data")
    if not isinstance(data, list) or not data:
        raise SystemExit("API returned no data")
    rows = []
    for e in data:
        ts = int(e["timestamp"])
        val = int(e["value"])
        cls = str(e["value_classification"]).strip()
        if not 0 <= val <= 100:
            raise SystemExit(f"value out of range at {ts}: {val}")
        if ts % DAY != 0:
            raise SystemExit(f"timestamp not on a UTC day boundary: {ts}")
        if not cls:
            raise SystemExit(f"missing classification at {ts}")
        rows.append((ts, val, cls))
    rows.sort(key=lambda r: r[0])  # oldest first
    seen = set()
    for ts, _, _ in rows:
        if ts in seen:
            raise SystemExit(f"duplicate day in source: {ts}")
        seen.add(ts)
    return rows


def write(rows):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLS)
        for ts, val, cls in rows:
            day = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
            w.writerow([day, ts, val, cls])


def main():
    rows = parse(fetch())
    first = dt.datetime.fromtimestamp(rows[0][0], dt.timezone.utc).strftime("%Y-%m-%d")
    last = dt.datetime.fromtimestamp(rows[-1][0], dt.timezone.utc).strftime("%Y-%m-%d")
    span_days = (rows[-1][0] - rows[0][0]) // DAY + 1
    missing = span_days - len(rows)
    if "--check" in sys.argv[1:]:
        print(f"OK (not written): {len(rows)} rows, {first}..{last}, {missing} day(s) missing at source, latest value {rows[-1][1]} ({rows[-1][2]})")
        return
    write(rows)
    print(f"wrote {OUT.name}: {len(rows)} rows, {first}..{last}, {missing} day(s) missing at source, latest value {rows[-1][1]} ({rows[-1][2]})")


if __name__ == "__main__":
    main()
