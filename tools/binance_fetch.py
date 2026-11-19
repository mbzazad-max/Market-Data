"""Top up the Binance series from Binance's public market-data API (run by .github/workflows/binance.yml).

It does the same job as the laptop uploader, from GitHub instead of the laptop:
1. Reads series.json and manifest.json. Only Binance series that already exist in the manifest are
   topped up (no new series, no history download).
2. For each one that has a newly closed candle due, asks Binance for the candles from 5 before the
   stored last candle onwards (the 5 overlapping candles are the check that the data matches).
3. Writes them into incoming/binance-<time>/ with fetch.json, exactly like the laptop uploader.
   The existing importer (import.yml) then merges them, keeps closed candles only, rejects any
   changed candle, updates manifest.json and tells the dashboards to rebuild.

GitHub runs in the US, where api.binance.com is blocked (HTTP 451), so data-api.binance.vision
(Binance's public market-data mirror, same /api/v3/klines answer) is tried first.
If a series cannot be fetched it is listed as an error and the run fails, so GitHub emails you;
everything that was fetched is still uploaded. Then the laptop upload is the fallback.

--dry-run: fetch every series (even if nothing is due) and compare the overlapping candles with
the stored ones; write nothing. Use it to test that Binance answers GitHub.
No third-party packages.
"""
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.request

from mdlib import PERIOD, ROOT, load_json, read_series, same_values

HOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]
INTERVAL = {"4H": "4h", "1D": "1d"}
OVERLAP = 5
MARGIN_S = 60  # a candle counts as closed only 60 s after its close time


def get_klines(symbol, interval, start_ms):
    last_err = None
    for host in HOSTS:
        url = f"{host}/api/v3/klines?symbol={symbol}&interval={interval}&startTime={start_ms}&limit=1000"
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "market-data-binance-fetch"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read()), host
            except urllib.error.HTTPError as e:
                last_err = f"{host} HTTP {e.code}"
                if e.code in (418, 429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 + attempt * 3)
                    continue
                break  # 451 (blocked location), 400 (bad symbol), ...: try the next host
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                last_err = f"{host} {e}"
                if attempt < 2:
                    time.sleep(2 + attempt * 3)
                    continue
                break
    raise RuntimeError(last_err or "no host answered")


def main():
    dry = "--dry-run" in sys.argv
    series = load_json(ROOT / "series.json")["series"]
    man = load_json(ROOT / "manifest.json", {"series": {}}).get("series", {})
    now = int(time.time())
    stamp = now
    files, fetched, errors, report, hosts = {}, {}, [], [], {}
    checked = matched = 0
    for sid, s in sorted(series.items()):
        if s["source"] != "binance" or s["tf"] not in INTERVAL:
            continue
        m = man.get(sid)
        if not m or m.get("last_open") is None:
            report.append(f"{sid}: not in manifest yet, skipped (laptop seeds new series)")
            continue
        P = PERIOD[s["tf"]]
        last = m["last_open"]
        if last + 2 * P > now - MARGIN_S and not dry:  # the next candle has not closed yet
            report.append(f"{sid}: current (last {last}), nothing due")
            continue
        start = last - OVERLAP * P
        try:
            kl, host = get_klines(s["symbol"], INTERVAL[s["tf"]], start * 1000)
        except RuntimeError as e:
            errors.append(f"{sid}: could not fetch ({e})")
            continue
        hosts[host] = hosts.get(host, 0) + 1
        fetch_time = int(time.time())
        rows = []
        for k in kl:
            t = int(k[0]) // 1000
            if t < start or t % P:
                continue
            rows.append([str(t), k[1], k[2], k[3], k[4], k[5]])
        if not rows:
            errors.append(f"{sid}: Binance returned no candles from {start}")
            continue
        old = read_series(sid)
        overlap = [r for r in rows if int(r[0]) in old]
        bad = [r[0] for r in overlap if not same_values(old[int(r[0])], r)]
        checked += len(overlap)
        matched += len(overlap) - len(bad)
        new_closed = [r for r in rows if int(r[0]) > last and int(r[0]) + P <= fetch_time - MARGIN_S]
        if bad:
            errors.append(f"{sid}: {len(bad)} overlapping candle(s) differ from stored data (first {bad[0]}); not uploaded")
            continue
        report.append(f"{sid}: {len(new_closed)} new closed candle(s), {len(overlap)} overlap checked OK")
        if not new_closed:
            continue
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        w.writerows(rows)
        name = f"{s['symbol']}_{s['tf']}.csv"
        files[name] = out.getvalue()
        fetched[name] = fetch_time

    print("\n".join(report))
    print(f"Hosts used: {hosts or 'none'}; overlap candles checked {checked}, identical {matched}")
    if files and not dry:
        batch = ROOT / "incoming" / f"binance-{stamp}"
        batch.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (batch / name).write_text(text, encoding="utf-8")
        (batch / "fetch.json").write_text(json.dumps({
            "source": "binance", "fetched_at": min(fetched.values()), "margin_s": MARGIN_S,
            "files": fetched, "via": "github-binance-fetch"}, indent=1) + "\n", encoding="utf-8")
        print(f"Staged {len(files)} series in {batch.relative_to(ROOT)}")
    elif dry:
        print(f"Dry run: {len(files)} series would be uploaded, nothing written")
    else:
        print("Nothing new to upload.")
    for e in errors:
        print("::error::" + e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
