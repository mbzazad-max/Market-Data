"""Shared helpers for the market-data repo (no third-party packages)."""
import csv
import io
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERIOD = {"1H": 3600, "4H": 4 * 3600, "1D": 86400}
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


# ---- snapshots: non-candle readings (calendar, CoinMarketCap, CoinGlass), one JSON file each ----

def snapshot_registry():
    return load_json(ROOT / "series.json").get("snapshots", {})


def snap_path(sid):
    return ROOT / "data" / "snap" / (sid.split("/", 1)[1] + ".json")


def check_snapshot(kind, payload):
    """Return None if the payload looks like a real reading of this kind, else the reason it is rejected."""
    if not isinstance(payload, dict):
        return "payload is not a JSON object"
    if kind == "tv_econ":
        if payload.get("status") != "ok" or not isinstance(payload.get("result"), list):
            return "economic calendar answer without status ok and a result list"
        for e in payload["result"]:
            if not isinstance(e, dict) or "date" not in e or "title" not in e:
                return "calendar event without date or title"
        return None
    if kind == "cmc_global":
        try:
            idx = payload["sentiment"]["fear_greed"]["current"]["index"]
        except (KeyError, TypeError):
            return "no sentiment.fear_greed.current.index"
        if not isinstance(idx, (int, float)) or not 0 <= idx <= 100:
            return "Fear & Greed index out of range"
        return None
    if kind == "coinglass":
        rows = payload.get("rows")
        if not isinstance(rows, list) or not rows:
            return "no rows"
        ids = {r.get("id") for r in rows if isinstance(r, dict)}
        need = {"as_of", "funding_oiw", "funding_vw", "oi_total", "liq_btc_24h", "liq_mkt_24h"}
        if not need <= ids:
            return "missing rows: " + ", ".join(sorted(need - ids))
        for r in rows:
            if r.get("id") != "as_of" and r.get("num") is not None and not isinstance(r.get("num"), (int, float)):
                return f"row {r.get('id')}: num must be a number or null"
            for k in ("long_1h", "short_1h", "long_4h", "short_4h", "long_24h", "short_24h"):
                if k in r and (not isinstance(r[k], (int, float)) or r[k] < 0):
                    return f"row {r.get('id')}: {k} must be a dollar amount (number, not text)"
        return None
    if kind == "etf_flows":
        assets = payload.get("assets")
        if not isinstance(assets, dict) or not assets:
            return "no assets"
        for sym, a in assets.items():
            days = a.get("days") if isinstance(a, dict) else None
            if not isinstance(days, list) or not days:
                return f"{sym}: no days"
            for d in days:
                if not (isinstance(d, list) and len(d) == 2 and isinstance(d[0], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d[0])
                        and isinstance(d[1], (int, float)) and not isinstance(d[1], bool) and abs(d[1]) < 50000):
                    return f"{sym}: each day must be [\"YYYY-MM-DD\", flow in US$ millions], got {d!r}"
        return None
    if kind == "cmc_quotes":
        # get_crypto_quotes_latest answer for 2+ ids: {"headers": [...], "rows": [[...], ...]}; 1 id: a list of objects
        if isinstance(payload.get("headers"), list) and isinstance(payload.get("rows"), list) and payload["rows"]:
            h = payload["headers"]
            if not {"id", "symbol", "price", "market_cap"} <= set(h):
                return "quotes answer without id, symbol, price and market_cap columns"
            for r in payload["rows"]:
                v = r[h.index("price")] if isinstance(r, list) and len(r) == len(h) else None
                if not isinstance(v, (int, float)) or v <= 0:
                    return "quote row without a positive price"
            return None
        return "quotes answer without headers and rows"
    return f"unknown snapshot kind {kind}"
