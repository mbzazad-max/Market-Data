"""Print the dashboards (repo workflow) whose series changed in this import, one per line."""
import json
from mdlib import ROOT
changed = [l.strip() for l in (ROOT / "changed.txt").read_text().splitlines() if l.strip()] if (ROOT / "changed.txt").exists() else []
for d in json.loads((ROOT / "dashboards.json").read_text())["dashboards"]:
    if any(c.startswith(p) for c in changed for p in d["uses"]):
        print(d["repo"], d["workflow"])
