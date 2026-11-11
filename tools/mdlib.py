"""Shared helpers for the market-data repo (no third-party packages)."""
import csv
import io
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERIOD = {"4H": 4 * 3600, "1D": 86400}
HEADER = ["time", "open", "high", "low", "close", "volume"]


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def series_registry():
    return load_json(ROOT / "series.json")["series"]


def data_path(sid):
    source, symbol, tf = sid.split("/")
    return ROOT / "data" / source / f"{symbol}_{tf}.csv"


def file_name(sid):
    _, symbol, tf = sid.split("/")
    return f"{symbol}_{tf}.csv"


def parse_csv(text, where):
    """Rows as {time:int -> [time, o, h, l, c, v] strings}. Raises ValueError on bad data.
    The original number text is kept exactly, so nothing is re-rounded."""
    rows = {}
    reader = csv.reader(io.StringIO(text))
    head = next(reader, None)
    if [h.strip().lower() for h in (head or [])] != HEADER:
        raise ValueError(f"{where}: header must be {','.join(HEADER)}")
    for n, rec in enumerate(reader, start=2):
        if not rec:
            continue
        if len(rec) != 6:
            raise ValueError(f"{where} line {n}: expected 6 columns")
        rec = [x.strip() for x in rec]
        try:
            t = int(rec[0])
            o, h, l, c, v = (float(x) for x in rec[1:])
        except ValueError:
            raise ValueError(f"{where} line {n}: not a number")
        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
            raise ValueError(f"{where} line {n}: non-finite value")
        if t < 1_000_000_000 or t > 4_000_000_000:
            raise ValueError(f"{where} line {n}: time must be unix seconds UTC")
        if h < l or v < 0:
            raise ValueError(f"{where} line {n}: high below low or negative volume")
        if t in rows and rows[t][1:] != rec[1:]:
            raise ValueError(f"{where}: two different candles for time {t}")
        rows[t] = rec
    return rows


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(HEADER)
    for t in sorted(rows):
        w.writerow(rows[t])
    path.write_text(out.getvalue(), encoding="utf-8")


def read_series(sid):
    p = data_path(sid)
    return parse_csv(p.read_text(encoding="utf-8"), str(p)) if p.exists() else {}


def same_values(a, b):
    return all(float(x) == float(y) for x, y in zip(a[1:], b[1:]))
