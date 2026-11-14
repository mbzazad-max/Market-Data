"""Merge uploaded candles from incoming/ into data/ and update manifest.json.

Each upload is one folder: incoming/<batch>/fetch.json + <SYMBOL>_<TF>.csv files.
fetch.json: {"source": "binance"|"tv", "fetched_at": <unix seconds UTC>, "margin_s": <optional int>,
            "files": {<file name>: <its own fetched_at>} (optional, overrides fetched_at per file)}
Snapshot uploads (source "snap") hold <name>.json files instead: {"payload": <the reading, unchanged>}.
A snapshot replaces data/snap/<name>.json only if it is listed in series.json "snapshots", passes its
kind check and is newer than the stored one; otherwise the last good reading stays.

Rules
- Closed candles only: a candle is kept only if open_time + period <= fetched_at - margin_s.
  The cutoff is the data's own fetch time, never the time this script runs.
- Merge by timestamp, no duplicates. A Binance candle that already exists must not change:
  if it does, that series is rejected for this upload and keeps its last good data.
  TradingView may revise closed index values by up to 1%: the newer value wins and is counted.
  A bigger change is treated like a Binance conflict (rejected, last good data kept).
- A failed series never overwrites good data. Errors are written to the manifest and
  make the script exit with code 2 after everything that is valid has been saved.
- Processed upload folders are deleted, so nothing is imported twice.
"""
import shutil
import sys
import time

import snap_history
from mdlib import (PERIOD, ROOT, check_snapshot, data_path, load_json, parse_csv, read_series,
                   same_values, save_json, series_registry, snap_path, snapshot_registry, write_csv)


def import_snapshots(b, meta, man, errors, changed, now):
    reg = snapshot_registry()
    fetched_at = meta["fetched_at"]
    snaps = man.setdefault("snapshots", {})
    for f in sorted(b.glob("*.json")):
        if f.name == "fetch.json":
            continue
        sid = "snap/" + f.stem
        if sid not in reg:
            errors.append(f"{b.name}/{f.name}: {sid} is not listed in series.json snapshots, ignored")
            continue
        try:
            payload = load_json(f)["payload"]
        except Exception as e:  # unreadable upload: keep the last good reading
            errors.append(f"{sid}: unreadable upload ({e}); kept last good reading")
            continue
        why = check_snapshot(reg[sid]["kind"], payload)
        if why:
            errors.append(f"{sid}: {why}; kept last good reading")
            snaps.setdefault(sid, {})["last_error"] = why
            continue
        prev = snaps.get(sid, {})
        if prev.get("fetched_at") and fetched_at <= prev["fetched_at"]:
            print(f"{sid}: upload from {fetched_at} is not newer than {prev['fetched_at']}, ignored")
            continue
        p = snap_path(sid)
        p.parent.mkdir(parents=True, exist_ok=True)
        save_json(p, {"id": sid, "fetched_at": fetched_at, "payload": payload})
        snaps[sid] = {"kind": reg[sid]["kind"], "fetched_at": fetched_at, "imported_at": now, "bytes": p.stat().st_size}
        changed.append(sid)
        print(f"{sid}: reading from {fetched_at} saved")
        try:  # one CSV row per load in data/history/ (a failure here never blocks the reading itself)
            h = snap_history.append(sid, fetched_at, payload)
            if h:
                print(f"{sid}: history row added to {h.relative_to(ROOT)}")
        except Exception as e:
            errors.append(f"{sid}: history CSV not updated ({e})")


def big_change(a, b, limit=0.01):
    """TradingView may restate a closed index candle slightly; more than 1% is treated as bad data."""
    return any(abs(float(y) - float(x)) > limit * max(abs(float(x)), 1e-12) for x, y in zip(a[1:5], b[1:5]))


def confirm_daily_from_4h(source, symbol, tf, P, inc, closed, f_fetched):
    """A Binance 1D candle that closed before the file was saved but inside the safety margin
    (the laptop download ran a few seconds after 00:00 UTC) is accepted only if its open, high, low
    and close equal those built from the six stored, closed Binance 4H candles of that day.
    Nothing is fetched; the check uses only data already in the repo."""
    if source != "binance" or tf != "1D":
        return {}
    h4 = None
    out = {}
    for t, r in inc.items():
        if t in closed or t + P > f_fetched:
            continue  # already closed, or really still forming when the file was saved
        if h4 is None:
            h4 = read_series(f"binance/{symbol}/4H")
        bars = [h4.get(t + k * 14400) for k in range(6)]
        if any(b is None for b in bars):
            continue
        o, h, l, c = float(bars[0][1]), max(float(b[2]) for b in bars), min(float(b[3]) for b in bars), float(bars[5][4])
        if (float(r[1]), float(r[2]), float(r[3]), float(r[4])) == (o, h, l, c):
            out[t] = r
    return out


def main():
    reg = series_registry()
    man = load_json(ROOT / "manifest.json", {"series": {}})
    man.setdefault("series", {})
    now = int(time.time())
    inbox = ROOT / "incoming"
    batches = sorted(p for p in inbox.iterdir() if p.is_dir()) if inbox.exists() else []
    errors, changed = [], []
    for b in batches:
        meta = load_json(b / "fetch.json")
        if meta and meta.get("source") == "snap" and isinstance(meta.get("fetched_at"), int):
            import_snapshots(b, meta, man, errors, changed, now)
            shutil.rmtree(b)
            continue
        if not meta or meta.get("source") not in ("binance", "tv") or not isinstance(meta.get("fetched_at"), int):
            errors.append(f"{b.name}: missing or invalid fetch.json, upload ignored")
            shutil.rmtree(b)
            continue
        source, fetched_at, margin = meta["source"], meta["fetched_at"], int(meta.get("margin_s", 0))
        cutoff = fetched_at - margin
        for f in sorted(b.glob("*.csv")):
            stem = f.stem
            if "_" not in stem:
                errors.append(f"{b.name}/{f.name}: file name must be <SYMBOL>_<TF>.csv")
                continue
            symbol, tf = stem.rsplit("_", 1)
            sid = f"{source}/{symbol}/{tf}"
            if sid not in reg or tf not in PERIOD:
                errors.append(f"{b.name}/{f.name}: {sid} is not listed in series.json, ignored")
                continue
            P = PERIOD[tf]
            f_fetched = int(meta.get("files", {}).get(f.name, fetched_at))
            cutoff = f_fetched - margin
            try:
                inc = parse_csv(f.read_text(encoding="utf-8"), f"{b.name}/{f.name}")
                old = read_series(sid)
            except ValueError as e:
                errors.append(f"{sid}: {e}; kept last good data")
                man["series"].setdefault(sid, {})["last_error"] = str(e)
                continue
            closed = {t: r for t, r in inc.items() if t + P <= cutoff}
            confirmed = confirm_daily_from_4h(source, symbol, tf, P, inc, closed, f_fetched)
            if confirmed:
                closed.update(confirmed)
                print(f"{sid}: {len(confirmed)} candle(s) inside the safety margin accepted, they match the stored closed 4H candles")
            dropped = len(inc) - len(closed)
            conflict, revised, added = [], 0, 0
            merged = dict(old)
            for t, r in closed.items():
                if t in old:
                    if not same_values(old[t], r):
                        if source == "binance" or big_change(old[t], r):
                            conflict.append(t)
                        else:
                            merged[t] = r
                            revised += 1
                else:
                    merged[t] = r
                    added += 1
            if conflict:
                msg = f"{len(conflict)} existing closed candle(s) changed value (first {conflict[0]}); upload rejected, kept last good data"
                errors.append(f"{sid}: {msg}")
                man["series"].setdefault(sid, {})["last_error"] = msg
                continue
            if not merged:
                errors.append(f"{sid}: no closed candles in upload")
                continue
            ts = sorted(merged)
            gaps = sum(1 for a, c in zip(ts, ts[1:]) if c - a > P) if source == "binance" else None
            if added or revised or not data_path(sid).exists():
                write_csv(data_path(sid), merged)
                changed.append(sid)
            prev = man["series"].get(sid, {})
            man["series"][sid] = {
                "source": source, "symbol": reg[sid]["symbol"], "tf": tf, "period_s": P,
                "rows": len(ts), "first_open": ts[0], "last_open": ts[-1], "last_close": ts[-1] + P,
                "fetched_at": f_fetched if (added or revised) else prev.get("fetched_at", f_fetched),
                "checked_at": f_fetched, "imported_at": now,
                "added_last_import": added, "revised_last_import": revised,
                "forming_dropped_last_import": dropped, "gaps": gaps,
            }
            print(f"{sid}: +{added} new, {revised} revised, {dropped} forming/too-new dropped, last {ts[-1]}")
        shutil.rmtree(b)
    man["generated_at"] = now
    man["errors_last_import"] = errors
    save_json(ROOT / "manifest.json", man)
    (ROOT / "changed.txt").write_text("\n".join(changed) + ("\n" if changed else ""), encoding="utf-8")
    for e in errors:
        print("::error::" + e)
    print(f"{len(changed)} series changed, {len(errors)} error(s)")
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
