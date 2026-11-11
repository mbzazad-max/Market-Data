"""Print the TradingView fetches needed now, as JSON, for the daily Claude task.
Only stale series are listed. A series with no history yet is 'seeded' with its seed_count;
at most --max-seed seeds per run, because one large TradingView answer is expensive to load.
usage: python tools/tv_plan.py [--max-seed 2]"""
import json
import math
import sys
import time

from mdlib import PERIOD, ROOT, load_json, series_registry

TV_INTERVAL = {"4H": "4h", "1D": "1D"}


def main():
    max_seed = int(sys.argv[sys.argv.index("--max-seed") + 1]) if "--max-seed" in sys.argv else 2
    man = load_json(ROOT / "manifest.json", {"series": {}})["series"]
    now = int(time.time())
    jobs, seeds, waiting = [], 0, []
    for sid, s in series_registry().items():
        if s["source"] != "tv":
            continue
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
    print(json.dumps({"now": now, "jobs": jobs, "seed_waiting": waiting}, indent=1))


if __name__ == "__main__":
    main()
