"""FOMC rate odds and company BTC purchases from the SoSoValue API (added 28 Nov 2026), run by sosovalue.yml.

snap/fomc_odds   GET /macro/fomc-probabilities (market-implied odds per target range for the next ~11 FOMC meetings)
                 + GET /macro/rates (SOFR, to place the current target range). The payload keeps the full matrix and
                 adds "current_range" and, per meeting, p_cut / p_hold / p_hike (in %, vs the current range).
snap/btc_treasuries  GET /btc-treasuries (company list) + GET /btc-treasuries/{ticker}/purchase-history?limit=100 per
                 company. Purchases are merged into the stored history by the importer (key: ticker + date).
                 The list is walked once a day (the 02:40 UTC run, or --treasuries); other runs load FOMC only.
Writes incoming/snap-<fetched_at>/<name>.json and data/status/sosovalue_macro.json (never the key).
usage: python3 tools/sosovalue_macro.py [--treasuries] [--dry-run]"""
import json
import os
import sys
import time

from mdlib import ROOT, check_snapshot
from sosovalue_flows import get

DRY = "--dry-run" in sys.argv


def ok_data(ans):
    return isinstance(ans, dict) and ans.get("code") == 0, (ans or {}).get("data") if isinstance(ans, dict) else None


def err(ans):
    return {"ok": False, "code": (ans or {}).get("code") if isinstance(ans, dict) else None,
            "message": str((ans or {}).get("message") if isinstance(ans, dict) else ans)[:200]}


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fomc(key, status):
    ok, d = ok_data(get("/macro/fomc-probabilities", {}, key))
    if not ok or not isinstance(d, dict) or not isinstance(d.get("rate_ranges"), list) or not isinstance(d.get("meetings"), list):
        status["fomc"] = err(d if not ok else {"code": "shape", "message": "no rate_ranges / meetings"})
        return None
    time.sleep(3.2)
    sofr = None
    ok2, r = ok_data(get("/macro/rates", {}, key))
    if ok2 and isinstance(r, list):
        for x in r:
            if isinstance(x, dict) and str(x.get("code")).lower() == "sofr":
                sofr = {"value": fnum(x.get("latest_value")), "date": x.get("latest_date")}
    ranges = [str(x) for x in d["rate_ranges"]]
    bounds = []
    for s in ranges:
        try:
            lo, hi = (int(p) for p in s.split("-"))
        except ValueError:
            lo = hi = None
        bounds.append((lo, hi))
    cur = None
    if sofr and sofr["value"] is not None:
        bp = sofr["value"] * 100
        inside = [i for i, (lo, hi) in enumerate(bounds) if lo is not None and lo <= bp < hi]
        if inside:
            cur = inside[0]
        else:  # SOFR a few bp outside the range: take the nearest range
            near = sorted((min(abs(bp - lo), abs(bp - hi)), i) for i, (lo, hi) in enumerate(bounds) if lo is not None)
            cur = near[0][1] if near and near[0][0] <= 15 else None
    meetings = []
    for m in d["meetings"]:
        ps = [fnum(p) for p in (m.get("probabilities") or [])]
        row = {"meeting_date": str(m.get("meeting_date"))[:10], "probabilities": ps}
        if cur is not None and len(ps) == len(ranges):
            row["p_cut"] = round(sum(p for i, p in enumerate(ps) if p is not None and i != cur and bounds[i][0] is not None and bounds[i][0] < bounds[cur][0]), 2)
            row["p_hold"] = round(ps[cur] or 0.0, 2)
            row["p_hike"] = round(sum(p for i, p in enumerate(ps) if p is not None and i != cur and bounds[i][0] is not None and bounds[i][0] > bounds[cur][0]), 2)
        meetings.append(row)
    p = {"as_of_ms": d.get("as_of"), "rate_ranges": ranges, "current_range": ranges[cur] if cur is not None else None,
         "sofr": sofr, "meetings": meetings}
    status["fomc"] = {"ok": True, "ranges": len(ranges), "meetings": len(meetings), "current_range": p["current_range"],
                      "next": meetings[0] if meetings else None}
    return p


def treasuries(key, status):
    ok, d = ok_data(get("/btc-treasuries", {}, key))
    lst = d if isinstance(d, list) else (d or {}).get("list") if isinstance(d, dict) else None
    if not ok or not isinstance(lst, list):
        status["treasuries"] = err(d if not ok else {"code": "shape", "message": "no company list"})
        return None
    comps, fails = {}, {}
    for c in lst:
        t = str((c or {}).get("ticker") or "").strip()
        if not t:
            continue
        time.sleep(3.2)
        ok2, h = ok_data(get(f"/btc-treasuries/{t}/purchase-history", {"limit": 100}, key))
        if not ok2 or not isinstance(h, list):
            fails[t] = (h or {}).get("message") if isinstance(h, dict) else "no list"
            continue
        rows = []
        for x in h:
            dte = str(x.get("date") or "")[:10]
            acq, hold = fnum(x.get("btc_acq")), fnum(x.get("btc_holding"))
            if len(dte) == 10 and (acq is not None or hold is not None):
                rows.append([dte, acq, hold, fnum(x.get("acq_cost")), fnum(x.get("avg_btc_cost"))])
        comps[t] = {"name": c.get("name"), "list_location": c.get("list_location"), "purchases": sorted(rows)}
    status["treasuries"] = {"ok": bool(comps), "companies_listed": len(lst), "loaded": len(comps),
                            "purchases": sum(len(v["purchases"]) for v in comps.values()), "failed": dict(list(fails.items())[:20])}
    return {"columns": ["date", "btc_acq", "btc_holding", "acq_cost_usd", "avg_btc_cost_usd"], "companies": comps} if comps else None


def main():
    key = os.environ.get("SOSOVALUE_API_KEY", "").strip()
    fetched_at = int(time.time())
    status = {"fetched_at": fetched_at, "time_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(fetched_at))}
    readings = {}
    if not key:
        status["error"] = "secret SOSOVALUE_API_KEY is not set"
    else:
        f = fomc(key, status)
        if f:
            readings["fomc_odds"] = f
        if "--treasuries" in sys.argv or time.gmtime(fetched_at).tm_hour == 2 or os.environ.get("TREASURIES") == "1":
            time.sleep(3.2)
            t = treasuries(key, status)
            if t:
                readings["btc_treasuries"] = t
    kinds = {"fomc_odds": "fomc_odds", "btc_treasuries": "btc_treasuries"}
    for n in list(readings):
        why = check_snapshot(kinds[n], readings[n])
        if why:
            status[n + "_rejected"] = why
            readings.pop(n)
    if readings and not DRY:
        out = ROOT / "incoming" / f"snap-{fetched_at + 1}"   # +1 s: never the same folder as the flows upload
        out.mkdir(parents=True, exist_ok=True)
        (out / "fetch.json").write_text(json.dumps({"source": "snap", "fetched_at": fetched_at + 1}) + "\n")
        for n, p in readings.items():
            (out / f"{n}.json").write_text(json.dumps({"payload": p}) + "\n", encoding="utf-8")
    status["staged"] = sorted(readings) if not DRY else []
    p = ROOT / "data" / "status" / "sosovalue_macro.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(status, indent=1, default=str) + "\n")
    print(json.dumps(status, default=str)[:2000])
    return 0 if readings or DRY else 1


if __name__ == "__main__":
    sys.exit(main())
