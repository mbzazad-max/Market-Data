"""Upload new Binance candles from this laptop to GitHub repo mbzazad-max/market-data in ONE commit.

What it does
1. Reads series.json and manifest.json from GitHub to learn which series exist and their last candle.
2. For each Binance series, opens the local Excel file (SPOT/LTF/<SYMBOL>_4H.xlsx or SPOT/HTF/<SYMBOL>_D.xlsx)
   and takes only the candles after GitHub's last candle (plus 5 overlapping ones as a check).
   A series GitHub has never seen is sent in full.
3. Writes them as small CSV files (text, not Excel) into incoming/binance-<time>/ with fetch.json,
   and makes ONE commit with all of them. GitHub then merges them and rebuilds the dashboards.

Closed candles: each file's own "last modified" time is sent as its fetch time, minus a 5 minute margin.
GitHub keeps only candles that had closed by then. Your downloader already keeps only closed candles; this is a second guard.

Needs: Python 3 and openpyxl (pip install openpyxl). No Git needed.
"""
import base64
import csv
import datetime as dt
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
REPO = CONFIG["repo"]
LOCAL = Path(CONFIG["spot_folder"])
CRED = HERE / "github_token.dpapi"
FOLDER = {"4H": ("LTF", "4H"), "1D": ("HTF", "D")}
PERIOD = {"4H": 14400, "1D": 86400}
MARGIN_S = 300
OVERLAP = 5


def token():
    if os.getenv("MARKET_DATA_TOKEN"):
        return os.environ["MARKET_DATA_TOKEN"].strip()
    if not CRED.exists():
        raise SystemExit("No token yet. Double-click SETUP_TOKEN.bat first.")
    path = str(CRED).replace("'", "''")
    ps = ("$ErrorActionPreference='Stop';"
          f"$raw=(Get-Content -LiteralPath '{path}' -Raw).Trim([char]0xFEFF).Trim();"
          "$s=ConvertTo-SecureString -String $raw;"
          "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
          "try{[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p)}"
          "finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("Cannot read the saved token: " + r.stderr.strip())
    return r.stdout.strip()


def api(method, path, tok, payload=None, raw=False):
    data = json.dumps(payload).encode() if payload is not None else None
    for i in range(4):
        req = urllib.request.Request("https://api.github.com" + path, data=data, method=method, headers={
            "Authorization": "Bearer " + tok, "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
            "User-Agent": "market-data-uploader", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                body = r.read()
                return body.decode() if raw else json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 404 and raw:
                return None
            if e.code in (429, 500, 502, 503, 504) and i < 3:
                time.sleep(2 ** i)
                continue
            raise SystemExit(f"GitHub HTTP {e.code} on {path}: {e.read().decode(errors='replace')[:300]}")
        except urllib.error.URLError as e:
            if i < 3:
                time.sleep(2 ** i)
                continue
            raise SystemExit(f"Network error: {e}")


def epoch(v):
    if isinstance(v, dt.datetime):
        return int(v.replace(tzinfo=dt.timezone.utc).timestamp())
    if isinstance(v, (int, float)):
        return int(v / 1000) if v > 1e12 else int(v)
    return int(dt.datetime.fromisoformat(str(v).strip()).replace(tzinfo=dt.timezone.utc).timestamp())


def read_xlsx(path):
    from openpyxl import load_workbook
    for attempt in range(2):
        before = path.stat()
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            it = wb.worksheets[0].iter_rows(values_only=True)
            head = [str(x).strip().lower() for x in next(it)][:6]
            if head != ["time", "open", "high", "low", "close", "volume"]:
                raise SystemExit(f"{path}: unexpected columns {head}")
            rows = [(epoch(r[0]), *[float(x) for x in r[1:6]]) for r in it if r and r[0] is not None]
        finally:
            wb.close()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
            return rows, int(after.st_mtime)
        time.sleep(5)
    raise SystemExit(f"{path} keeps changing; wait for the download to finish")


def main():
    print("Market data uploader -> https://github.com/" + REPO)
    tok = token()
    series = json.loads(api("GET", f"/repos/{REPO}/contents/series.json?ref=main", tok, raw=True))["series"]
    man_txt = api("GET", f"/repos/{REPO}/contents/manifest.json?ref=main", tok, raw=True)
    man = json.loads(man_txt)["series"] if man_txt else {}
    stamp = int(time.time())
    batch = f"incoming/binance-{stamp}"
    files, fetched, summary, missing = {}, {}, [], []
    for sid, s in series.items():
        if s["source"] != "binance":
            continue
        sub, suffix = FOLDER[s["tf"]]
        path = LOCAL / sub / f"{s['symbol']}_{suffix}.xlsx"
        if not path.exists():
            missing.append(str(path))
            continue
        rows, mtime = read_xlsx(path)
        last = man.get(sid, {}).get("last_open")
        if last is not None:
            if rows and rows[-1][0] <= last:
                continue  # nothing new
            rows = [r for r in rows if r[0] > last - OVERLAP * PERIOD[s["tf"]]]
        if not rows:
            continue
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow([r[0]] + [repr(x) for x in r[1:]])
        name = f"{s['symbol']}_{s['tf']}.csv"
        files[f"{batch}/{name}"] = out.getvalue()
        fetched[name] = mtime
        summary.append(f"{name}: {len(rows)} rows")
    for m in missing:
        print("Not found on this laptop (skipped):", m)
    if not files:
        print("Nothing new to upload.")
        return
    files[f"{batch}/fetch.json"] = json.dumps({"source": "binance", "fetched_at": min(fetched.values()),
                                               "margin_s": MARGIN_S, "files": fetched}, indent=1) + "\n"
    blobs = {}
    for p, text in files.items():
        blobs[p] = api("POST", f"/repos/{REPO}/git/blobs", tok,
                       {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"})["sha"]
    for attempt in range(6):
        head = api("GET", f"/repos/{REPO}/git/ref/heads/main", tok)["object"]["sha"]
        base = api("GET", f"/repos/{REPO}/git/commits/{head}", tok)["tree"]["sha"]
        tree = api("POST", f"/repos/{REPO}/git/trees", tok, {"base_tree": base, "tree": [
            {"path": p, "mode": "100644", "type": "blob", "sha": sha} for p, sha in blobs.items()]})["sha"]
        commit = api("POST", f"/repos/{REPO}/git/commits", tok, {
            "message": f"Upload Binance candles ({len(fetched)} series)", "tree": tree, "parents": [head]})["sha"]
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/git/refs/heads/main",
                                     data=json.dumps({"sha": commit, "force": False}).encode(), method="PATCH",
                                     headers={"Authorization": "Bearer " + tok, "User-Agent": "market-data-uploader",
                                              "Accept": "application/vnd.github+json"})
        try:
            urllib.request.urlopen(req, timeout=60).close()
            print("\n".join(summary))
            print(f"Done: {len(fetched)} series in one commit {commit[:7]}.")
            return
        except urllib.error.HTTPError as e:
            if e.code == 422 and attempt < 5:
                time.sleep(2 + attempt * 2)  # main moved; rebuild on the new head
                continue
            raise SystemExit(f"Could not publish the commit: HTTP {e.code}")


if __name__ == "__main__":
    try:
        main()
    finally:
        if os.name == "nt" and sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close")
