"""Rules-only baseline: rank functions by undocumented MMIO they touch. Reads no names, uses no LLM.

Usage: python -m chipxray.baseline facts/esp32s3_librftest.json blobs/svd/esp32s3.svd
"""
import csv, json, sys
from pathlib import Path
from chipxray.svd import classify, load_svd

WEIGHT = {"unmapped": 3, "undocumented_offset": 2, "documented": 0}
FIELDS = ["name", "object", "score", "unmapped", "undoc_offset", "documented", "rank",
          "inclusive_score", "inclusive_rank"]
DEPTH = 3  # ponytail: fixed call depth; tune only if Phase 3 shows it matters


def _competition_rank(rows, key, out):
    for r in rows:
        r[out] = sum(x[key] >= r[key] for x in rows)


def rank(facts, periphs, depth=DEPTH):
    rows, calls = [], {}
    for o in facts["objects"]:
        for a, b in o.get("calls", []):
            calls.setdefault(a, set()).add(b)
        for f in o["functions"]:
            kinds = [classify(int(a, 16), periphs)[0] for a in f["mmio"]]
            rows.append(dict(name=f["name"], object=o["name"], score=sum(WEIGHT[k] for k in kinds),
                             unmapped=kinds.count("unmapped"), undoc_offset=kinds.count("undocumented_offset"),
                             documented=kinds.count("documented")))
    own = {r["name"]: r["score"] for r in rows}
    if len(own) != len(rows):  # ponytail: key by (object, name) when a library has duplicate static names
        raise ValueError("duplicate function names in library; call-graph scoring would merge them")
    for r in rows:
        seen = frontier = {r["name"]}
        for _ in range(depth):
            frontier = {c for f in frontier for c in calls.get(f, ()) if c in own and c not in seen}
            seen = seen | frontier
        r["inclusive_score"] = sum(own[n] for n in seen)
    _competition_rank(rows, "score", "rank")
    _competition_rank(rows, "inclusive_score", "inclusive_rank")
    rows.sort(key=lambda r: (-r["score"], r["name"]))
    return rows


if __name__ == "__main__":
    facts_path, svd_path = sys.argv[1], sys.argv[2]
    with open(facts_path, encoding="utf-8") as fh:
        rows = rank(json.load(fh), load_svd(svd_path))
    out = Path("results") / (Path(facts_path).stem + "_baseline.csv")
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(out)
    for r in sorted(rows, key=lambda r: (-r["inclusive_score"], r["name"]))[:10]:
        print(f"{r['inclusive_rank']:>4} {r['inclusive_score']:>4} (own {r['score']:>3}) {r['name']}")
