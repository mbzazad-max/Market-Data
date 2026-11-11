"""Merge uploaded candles from incoming/ into data/ and update manifest.json.

Each upload is one folder: incoming/<batch>/fetch.json + <SYMBOL>_<TF>.csv files.
fetch.json: {"source": "binance"|"tv", "fetched_at": <unix seconds UTC>, "margin_s": <optional int>,
            "files": {<file name>: <its own fetched_at>} (optional, overrides fetched_at per file)}

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

from mdlib import (PERIOD, ROOT, data_path, load_json, parse_csv, read_series,
                   same_values, save_json, series_registry, write_csv)


def big_change(a, b, limit=0.01):
    """TradingView may restate a closed index candle slightly; more than 1% is treated as bad data."""
    return any(abs(float(y) - float(x)) > limit * max(abs(float(x)), 1e-12) for x, y in zip(a[1:5], b[1:5]))


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
