"""Print the TradingView fetches needed now, as JSON, for the daily Claude task.
Only stale series are listed. A series with no history yet is 'seeded' with its seed_count;
at most --max-seed seeds per run, because one large TradingView answer is expensive to load.
usage: python tools/tv_plan.py [--max-seed 2]"""
import json
import math
import sys
import time

import datetime as dt

from mdlib import PERIOD, ROOT, load_json, series_registry, snapshot_registry

TV_INTERVAL = {"4H": "4h", "1D": "1D"}


def main():
    max_seed = int(sys.argv[sys.argv.index("--max-seed") + 1]) if "--max-seed" in sys.argv else 2
    man = load_json(ROOT / "manifest.json", {"series": {}})["series"]
    now = int(time.time())
    jobs, seeds, waiting = [], 0, []
    for sid, s in series_registry().items():
        if s["source"] != "tv" or s.get("frozen"):
            continue  # frozen = stored history only; it is never fetched again
        P = PERIOD[s["tf"]]
        m = man.get(sid)
        if not m:
            if seeds >= max_seed:
                waiting.append(sid)
                continue
            seeds += 1
            jobs.append({"id": sid, "symbol": s["symbol"], "interval": TV_INTERVAL[s["tf"]],
                         "count": s["seed_count"], "format": "columns", "seed": True})
            continue
        latest_closed_open = (now // P) * P - P  # open time of the newest candle that has closed
        if m["last_open"] >= latest_closed_open:
            continue  # already current
        missing = math.ceil((latest_closed_open - m["last_open"]) / P)
        jobs.append({"id": sid, "symbol": s["symbol"], "interval": TV_INTERVAL[s["tf"]],
                     "count": min(5000, missing + 6), "format": "columns", "seed": False})
    # non-candle readings this task also loads (economic calendar, CoinMarketCap): only when older than max_age_h
    snaps = load_json(ROOT / "manifest.json", {}).get("snapshots", {})
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    snap_jobs = []
    for sid, s in snapshot_registry().items():
        if s.get("task") != "daily-tv":
            continue
        got = snaps.get(sid, {}).get("fetched_at")
        if got and now - got < s["max_age_h"] * 3600:
            continue
        args = {k: (str(today - dt.timedelta(days=1)) if v == "<yesterday>" else str(today + dt.timedelta(days=15)) if v == "<today+15>" else v)
                for k, v in s.get("args", {}).items()}
        snap_jobs.append({"id": sid, "name": sid.split("/", 1)[1], "tool": s["tool"], "args": args})
    print(json.dumps({"now": now, "jobs": jobs, "seed_waiting": waiting, "snapshot_jobs": snap_jobs}, indent=1))


if __name__ == "__main__":
    main()
