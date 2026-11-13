"""Stage non-candle readings (calendar, CoinMarketCap, CoinGlass) as one upload folder.
usage: python tools/snap_stage.py <fetched_at unix seconds, taken BEFORE the first call> <name>=<file.json> [...]
<name> is a snapshot id without "snap/" (e.g. tv_econ_us, cmc_global, coinglass_btc, coinglass_eth), listed in series.json.
<file.json> is the tool answer saved unchanged (calendar, CoinMarketCap), or for CoinGlass the rows file
{"as_of": ..., "rows": [...]} written as COINGLASS_TASK.md describes. Writes incoming/snap-<fetched_at>/."""
import json
import sys
from pathlib import Path

from mdlib import ROOT, check_snapshot, snapshot_registry


def main():
    fetched_at = int(sys.argv[1])
    reg = snapshot_registry()
    out = ROOT / "incoming" / f"snap-{fetched_at}"
    staged = []
    for arg in sys.argv[2:]:
        name, f = arg.split("=", 1)
        sid = "snap/" + name
        if sid not in reg:
            sys.exit(f"{sid} is not in series.json snapshots")
        payload = json.loads(Path(f).read_text(encoding="utf-8"))
        why = check_snapshot(reg[sid]["kind"], payload)
        if why:
            sys.exit(f"{f}: {why}")
        staged.append((name, payload))
    out.mkdir(parents=True, exist_ok=True)
    (out / "fetch.json").write_text(json.dumps({"source": "snap", "fetched_at": fetched_at}) + "\n")
    for name, payload in staged:
        (out / f"{name}.json").write_text(json.dumps({"payload": payload}) + "\n", encoding="utf-8")
        print(f"snap/{name}: staged")


if __name__ == "__main__":
    main()
