"""US spot ETF daily net flows from the SoSoValue API (added 28 Nov 2026), run by .github/workflows/sosovalue.yml.

GET https://openapi.sosovalue.com/openapi/v1/etfs/summary-history?symbol=<SYM>&country_code=US&limit=40
(header x-soso-api-key = secret SOSOVALUE_API_KEY). The API serves only the most recent month per call, for
BTC, ETH, SOL, LTC, HBAR, XRP, DOGE, LINK, AVAX and DOT. ZEC and HYPE are not in the API: the owner's PC readings
script loads them (Farside / SoSoValue page), together with BTC, ETH and SOL from Farside.

Writes incoming/snap-<fetched_at>/etf_flows.json (reading snap/etf_flows, US$ millions per US trading day); the
importer merges it into the stored history (a newer upload replaces a day's value). Always writes
data/status/sosovalue.json (per symbol: days loaded or the API's error code/message; never the key), so a failure
can be read from the repo.
usage: python3 tools/sosovalue_flows.py [--dry-run]"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from mdlib import ROOT, check_snapshot

BASE = "https://openapi.sosovalue.com/openapi/v1"
SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "LTC", "HBAR", "AVAX", "DOT"]
DRY = "--dry-run" in sys.argv


def get(path, params, key):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-soso-api-key": key, "Accept": "application/json",
                                               "User-Agent": "market-data/1.0 (github actions)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429 and attempt < 2:
                time.sleep(5)
                continue
            try:
                return json.loads(body)
            except ValueError:
                return {"code": f"http {e.code}", "message": body}
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 2:
                return {"code": "network", "message": str(e)[:200]}
            time.sleep(4)


def main():
    key = os.environ.get("SOSOVALUE_API_KEY", "").strip()
    fetched_at = int(time.time())
    status = {"fetched_at": fetched_at, "time_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(fetched_at)), "symbols": {}}
    assets = {}
    if not key:
        status["error"] = "secret SOSOVALUE_API_KEY is not set"
    else:
        for i, sym in enumerate(SYMBOLS):
            if i:
                time.sleep(3.2)  # stay under 20 requests a minute
            ans = get("/etfs/summary-history", {"symbol": sym, "country_code": "US", "limit": 40}, key)
            data = ans.get("data") if isinstance(ans, dict) else None
            if not isinstance(ans, dict) or ans.get("code") != 0 or not isinstance(data, list):
                status["symbols"][sym] = {"ok": False, "code": (ans or {}).get("code"), "message": str((ans or {}).get("message"))[:200]}
                continue
            days, na = [], None
            for r in sorted(data, key=lambda x: str(x.get("date"))):
                d, v = str(r.get("date", ""))[:10], r.get("total_net_inflow")
                try:
                    v = round(float(v) / 1e6, 4)
                except (TypeError, ValueError):
                    continue
                if len(d) == 10:
                    days.append([d, v])
                try:
                    na = round(float(r.get("total_net_assets")) / 1e6, 2)
                except (TypeError, ValueError):
                    pass
            if not days:
                status["symbols"][sym] = {"ok": False, "code": 0, "message": "no rows with a date and total_net_inflow"}
                continue
            a = {"source": "SoSoValue API (etfs/summary-history, US)", "days": days}
            if na is not None:
                a["net_assets_musd"] = na
            assets[sym] = a
            status["symbols"][sym] = {"ok": True, "days": len(days), "first": days[0][0], "last": days[-1][0], "last_musd": days[-1][1]}
    payload = {"as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(fetched_at)),
               "unit": "US$ millions, net flow per US trading day (negative = outflow)", "assets": assets}
    staged = False
    if assets:
        why = check_snapshot("etf_flows", payload)
        if why:
            status["error"] = "payload rejected: " + why
        elif not DRY:
            out = ROOT / "incoming" / f"snap-{fetched_at}"
            out.mkdir(parents=True, exist_ok=True)
            (out / "fetch.json").write_text(json.dumps({"source": "snap", "fetched_at": fetched_at}) + "\n")
            (out / "etf_flows.json").write_text(json.dumps({"payload": payload}) + "\n", encoding="utf-8")
            staged = True
    status["staged"] = staged
    p = ROOT / "data" / "status" / "sosovalue.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(status, indent=1) + "\n")
    for s, x in status["symbols"].items():
        print(s, x)
    print("staged" if staged else "nothing staged", status.get("error", ""))
    return 0 if staged or DRY else 1


if __name__ == "__main__":
    sys.exit(main())
