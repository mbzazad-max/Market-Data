"""History of the non-candle readings as CSV files, one row per load, for any dashboard and for later study.

data/history/coinglass_<coin>.csv   CoinGlass per coin (btc, eth, sol, bnb): funding, open interest, liquidations
data/history/cmc_global.csv         CoinMarketCap whole market: market cap, volume, fear & greed, altcoin season,
                                    dominance, open interest, funding, BTC liquidations, US spot ETF assets
data/history/cmc_quotes.csv         CoinMarketCap per coin quotes (SOL, BNB): price, rank, market cap, volume, % changes

The stored reading (data/snap/<name>.json) stays the source; these files only flatten it. Numbers are plain
(no $, %, K/M/B/T); an empty cell = not shown that day. fetched_at (unix s, UTC) is the key: a load is written once.
usage: python3 tools/snap_history.py backfill   (rebuild every CSV from the git history of data/snap/)
       import_incoming.py calls append() for every reading it saves."""
import csv
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

from mdlib import ROOT

HIST = ROOT / "data" / "history"

CG_COLS = ["fetched_at", "time_utc", "as_of", "funding_oiw_pct", "funding_vw_pct", "funding_signal",
           "oi_coins", "oi_usd", "oi_chg_1h_pct", "oi_chg_4h_pct", "oi_chg_24h_pct", "oi_signal",
           "liq_long_1h", "liq_short_1h", "liq_long_4h", "liq_short_4h", "liq_long_24h", "liq_short_24h",
           "liq_short_share_24h", "liq_signal", "mkt_liq_24h", "mkt_liq_short_share_24h", "mkt_long_1h", "mkt_short_1h",
           "mkt_long_4h", "mkt_short_4h", "mkt_long_24h", "mkt_short_24h", "mkt_oi_usd", "mkt_oi_chg_24h_pct",
           "mkt_long_ratio_pct", "price", "price_chg_24h_pct", "read_signal"]
GL_COLS = ["fetched_at", "time_utc", "cmc_day", "total_mcap", "mcap_chg_24h_pct", "mcap_chg_7d_pct", "mcap_chg_30d_pct",
           "volume_24h", "spot_volume_24h", "perp_volume_24h", "fear_greed", "fear_greed_label", "altcoin_season",
           "btc_dom_pct", "eth_dom_pct", "others_dom_pct", "oi_total", "oi_chg_24h_pct", "funding_avg_pct",
           "btc_liq_24h", "etf_btc_aum", "etf_eth_aum"]
QT_COLS = ["fetched_at", "time_utc", "symbol", "cmc_id", "price", "rank", "market_cap", "dominance_pct", "volume_24h",
           "chg_1h_pct", "chg_24h_pct", "chg_7d_pct", "chg_30d_pct", "chg_90d_pct", "chg_ytd_pct", "chg_1y_pct",
           "circulating_supply", "quote_time"]

MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def num(text):
    """'$46.96B' -> 46960000000, '−1.27%' -> -1.27, '2.3 T' -> 2.3e12, '687.75K BTC' -> 687750; None if no number."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return text
    m = re.search(r"([+\-−]?)\$?\s*([\d,]*\.?\d+)\s*([KMBT])?(?![a-z])", str(text))
    if not m:
        return None
    v = float(m.group(2).replace(",", "")) * MULT.get(m.group(3) or "", 1)
    return -v if m.group(1) in ("-", "−") else v


def fmt(v):
    if v is None or v == "":
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e18 else f"{v:.10g}"
    return str(v)


def utc(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def pct_after(label, text):
    """'1h +0.08%, 4h −1.27%, 24h −6.77%' -> pct_after('4h', ...) = -1.27"""
    m = re.search(r"(?<![\d.])" + re.escape(label) + r"\s*:?\s*([+\-−]?[\d.]+)%", text or "")
    return num(m.group(1) + "%") if m else None


def coinglass_row(fetched_at, p):
    rows = {r.get("id"): r for r in p.get("rows", [])}
    g = lambda i: rows.get(i, {})
    oi, liq, mkt = g("oi_total"), g("liq_btc_24h"), g("liq_mkt_24h")
    oiv = oi.get("value") or ""
    usd = re.search(r"\(\$?([\d.,]+\s*[KMBT]?)\)", oiv)
    mnote = mkt.get("note") or ""
    lnote = liq.get("note") or ""
    four = re.search(r"4h:?\s*longs?\s*(\$[\d.,]+[KMBT]?)\s*vs\s*shorts?\s*(\$[\d.,]+[KMBT]?)", mnote)
    one = re.search(r"1h:?\s*(?:longs?\s*)?(\$[\d.,]+[KMBT]?)\s*vs\s*(?:shorts?\s*)?(\$[\d.,]+[KMBT]?)", mnote)
    day = re.search(r"longs?\s*(\$[\d.,]+[KMBT]?)\s*vs\s*shorts?\s*(\$[\d.,]+[KMBT]?)", mnote)
    moi = re.search(r"OI\s*(\$[\d.,]+[KMBT]?)\s*\(([+\-−][\d.]+)%", mnote)
    lsr = re.search(r"long/short\s*([\d.]+)\s*/", mnote)
    px = re.search(r"\$([\d,]+\.?\d*),\s*([+\-−][\d.]+)%\s*on the day", lnote)
    short_share = liq.get("num")
    return {
        "fetched_at": fetched_at, "time_utc": utc(fetched_at), "as_of": p.get("as_of", ""),
        "funding_oiw_pct": num(g("funding_oiw").get("num")), "funding_vw_pct": num(g("funding_vw").get("num")),
        "funding_signal": g("funding_oiw").get("signal", ""),
        "oi_coins": num(oiv.split("(")[0]) if oiv else None,
        "oi_usd": oi.get("oi_usd") or (num("$" + usd.group(1)) if usd else None),
        "oi_chg_1h_pct": oi.get("oi_chg_1h", pct_after("1h", oi.get("note"))),
        "oi_chg_4h_pct": oi.get("num"),
        "oi_chg_24h_pct": oi.get("oi_chg_24h", pct_after("24h", oi.get("note"))),
        "oi_signal": oi.get("signal", ""),
        **{"liq_" + k: liq.get(k) for k in ("long_1h", "short_1h", "long_4h", "short_4h", "long_24h", "short_24h")},
        "liq_short_share_24h": short_share, "liq_signal": liq.get("signal", ""),
        "mkt_liq_24h": num(mkt.get("value")), "mkt_liq_short_share_24h": mkt.get("num"),
        "mkt_long_1h": mkt.get("long_1h", num(one.group(1)) if one else None),
        "mkt_short_1h": mkt.get("short_1h", num(one.group(2)) if one else None),
        "mkt_long_4h": mkt.get("long_4h", num(four.group(1)) if four else None),
        "mkt_short_4h": mkt.get("short_4h", num(four.group(2)) if four else None),
        "mkt_long_24h": mkt.get("long_24h", num(day.group(1)) if day else None),
        "mkt_short_24h": mkt.get("short_24h", num(day.group(2)) if day else None),
        "mkt_oi_usd": mkt.get("oi_usd", num(moi.group(1)) if moi else None),
        "mkt_oi_chg_24h_pct": mkt.get("oi_chg_24h", num(moi.group(2) + "%") if moi else None),
        "mkt_long_ratio_pct": mkt.get("long_ratio", float(lsr.group(1)) if lsr else None),
        "price": liq.get("price", num("$" + px.group(1)) if px else None),
        "price_chg_24h_pct": liq.get("price_chg_24h", num(px.group(2) + "%") if px else None),
        "read_signal": g("read").get("signal", ""),
    }


def cmc_global_row(fetched_at, p):
    def d(*path):
        v = p
        for k in path:
            v = v.get(k) if isinstance(v, dict) else None
        return v
    mc = d("market_size", "total_crypto_market_cap_usd") or {}
    fg = d("sentiment", "fear_greed", "current") or {}
    return {
        "fetched_at": fetched_at, "time_utc": utc(fetched_at), "cmc_day": p.get("last_updated", ""),
        "total_mcap": num(mc.get("current")), "mcap_chg_24h_pct": num(d("market_size", "total_crypto_market_cap_usd", "percent_change", "24h")),
        "mcap_chg_7d_pct": num(d("market_size", "total_crypto_market_cap_usd", "percent_change", "7d")),
        "mcap_chg_30d_pct": num(d("market_size", "total_crypto_market_cap_usd", "percent_change", "30d")),
        "volume_24h": num(d("liquidity", "volume24h", "total", "current")),
        "spot_volume_24h": num(d("liquidity", "volume24h", "spot", "current")),
        "perp_volume_24h": num(d("liquidity", "volume24h", "derivatives", "perpetuals", "current")),
        "fear_greed": fg.get("index"), "fear_greed_label": fg.get("value", ""),
        "altcoin_season": d("rotation", "altcoin_season", "current", "index"),
        "btc_dom_pct": num(d("dominance", "btc", "current")), "eth_dom_pct": num(d("dominance", "eth", "current")),
        "others_dom_pct": num(d("dominance", "others", "current")),
        "oi_total": num(d("leverage", "open_interest", "total", "current")),
        "oi_chg_24h_pct": num(d("leverage", "open_interest", "total", "percent_change", "24h")),
        "funding_avg_pct": num(d("leverage", "funding_rate", "average", "current")),
        "btc_liq_24h": num(d("leverage", "liquidations", "btc", "total_usd24h")),
        "etf_btc_aum": num(d("trad_fi_flows", "etf_aum", "btc", "current")),
        "etf_eth_aum": num(d("trad_fi_flows", "etf_aum", "eth", "current")),
    }


def cmc_quote_rows(fetched_at, p):
    if isinstance(p, list):  # one id: a list of objects
        items = p
    else:
        h = p.get("headers", [])
        items = [dict(zip(h, r)) for r in p.get("rows", [])]
    out = []
    for q in items:
        f = lambda k: q.get(k)
        out.append({"fetched_at": fetched_at, "time_utc": utc(fetched_at), "symbol": f("symbol"), "cmc_id": f("id"),
                    "price": f("price"), "rank": f("rank"), "market_cap": f("market_cap"), "dominance_pct": f("market_cap_dominance"),
                    "volume_24h": f("volume_24h"), "chg_1h_pct": f("percent_change_1h"), "chg_24h_pct": f("percent_change_24h"),
                    "chg_7d_pct": f("percent_change_7d"), "chg_30d_pct": f("percent_change_30d"), "chg_90d_pct": f("percent_change_90d"),
                    "chg_ytd_pct": f("percent_change_ytd"), "chg_1y_pct": f("percent_change_1y"),
                    "circulating_supply": f("circulating_supply"), "quote_time": f("last_updated_time")})
    return out


def target(sid):
    """(csv file, columns, rows function) for a reading id, or None if it has no history file."""
    name = sid.split("/", 1)[1]
    if name.startswith("coinglass_"):
        return HIST / f"{name}.csv", CG_COLS, lambda t, p: [coinglass_row(t, p)]
    if name == "cmc_global":
        return HIST / "cmc_global.csv", GL_COLS, lambda t, p: [cmc_global_row(t, p)]
    if name == "cmc_quotes":
        return HIST / "cmc_quotes.csv", QT_COLS, cmc_quote_rows
    return None


def read(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (int(r["fetched_at"]), str(r.get("symbol", ""))))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: fmt(r.get(c)) for c in cols})


def append(sid, fetched_at, payload):
    """Add one load to its CSV (a load already there, same fetched_at, is replaced). Returns the file or None."""
    t = target(sid)
    if not t:
        return None
    path, cols, fn = t
    keep = [r for r in read(path) if int(r["fetched_at"]) != fetched_at]
    write(path, cols, keep + fn(fetched_at, payload))
    return path


def backfill():
    """Rebuild every CSV from each committed version of data/snap/*.json (needs the repo's history: fetch it deep)."""
    for f in sorted((ROOT / "data" / "snap").glob("*.json")):
        sid = "snap/" + f.stem
        t = target(sid)
        if not t:
            continue
        rel = f.relative_to(ROOT).as_posix()
        shas = subprocess.run(["git", "log", "--format=%H", "--", rel], cwd=ROOT, capture_output=True, text=True).stdout.split()
        seen = {}
        for sha in shas:
            try:
                doc = json.loads(subprocess.run(["git", "show", f"{sha}:{rel}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
            except Exception:
                continue
            seen.setdefault(doc["fetched_at"], doc["payload"])
        path, cols, fn = t
        rows = [r for r in read(path) if int(r["fetched_at"]) not in seen]
        for ts, p in seen.items():
            rows += fn(ts, p)
        write(path, cols, rows)
        print(f"{path.relative_to(ROOT)}: {len(rows)} rows ({len(seen)} loads in history)")


if __name__ == "__main__":
    if sys.argv[1:] == ["backfill"]:
        backfill()
    else:
        sys.exit(__doc__)
