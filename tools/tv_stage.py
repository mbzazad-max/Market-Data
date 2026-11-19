"""Turn saved TradingView get-ohlcv answers (JSON, format=columns) into one upload folder.
usage: python tools/tv_stage.py <fetched_at unix seconds, taken BEFORE the first call> <answer.json> [...]
Each answer must contain "symbol", "interval" and bars {t,o,h,l,c,v}. Writes incoming/tv-<fetched_at>/.
The importer then drops any candle that had not closed at fetched_at (TradingView's last bar is forming)."""
import json
import sys
from pathlib import Path

from mdlib import ROOT, series_registry, write_csv

TF = {"1h": "1H", "60": "1H", "4h": "4H", "240": "4H", "1D": "1D", "D": "1D"}


def main():
    fetched_at = int(sys.argv[1])
    reg = series_registry()
    out = ROOT / "incoming" / f"tv-{fetched_at}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "fetch.json").write_text(json.dumps({"source": "tv", "fetched_at": fetched_at}) + "\n")
    for f in sys.argv[2:]:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        if d.get("success") is False or "bars" not in d:
            sys.exit(f"{f}: not a successful get-ohlcv answer")
        sym, tf = d["symbol"], TF.get(str(d["interval"]))
        sid = f"tv/{sym.replace(':', '_')}/{tf}"
        if sid not in reg:
            sys.exit(f"{f}: {sid} is not in series.json")
        b = d["bars"]
        rows = {}
        for i, t in enumerate(b["t"]):
            v = b["v"][i] if b.get("v") else None
            # TradingView sends no volume for some indices; the original page treats a missing volume as 0
            rows[int(t)] = [str(int(t))] + [json.dumps(b[k][i]) for k in "ohlc"] + [json.dumps(v if v is not None else 0)]
        write_csv(out / f"{sym.replace(':', '_')}_{tf}.csv", rows)
        print(f"{sid}: {len(rows)} bars staged")


if __name__ == "__main__":
    main()
