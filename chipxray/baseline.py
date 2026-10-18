"""Rules-only baseline: rank functions by undocumented MMIO they touch. Reads no names, uses no LLM.

Usage: python -m chipxray.baseline facts/esp32s3_librftest.json blobs/svd/esp32s3.svd
"""
import csv, json, sys
from pathlib import Path
from chipxray.svd import classify, load_svd

WEIGHT = {"unmapped": 3, "undocumented_offset": 2, "documented": 0}


def rank(facts, periphs):
    rows = []
    for o in facts["objects"]:
        for f in o["functions"]:
            kinds = [classify(int(a, 16), periphs)[0] for a in f["mmio"]]
            rows.append(dict(name=f["name"], object=o["name"], score=sum(WEIGHT[k] for k in kinds),
                             unmapped=kinds.count("unmapped"), undoc_offset=kinds.count("undocumented_offset"),
                             documented=kinds.count("documented")))
    rows.sort(key=lambda r: -r["score"])
    for r in rows:
        r["rank"] = sum(x["score"] >= r["score"] for x in rows)
    return rows


if __name__ == "__main__":
    facts_path, svd_path = sys.argv[1], sys.argv[2]
    rows = rank(json.load(open(facts_path)), load_svd(svd_path))
    out = Path("results") / (Path(facts_path).stem + "_baseline.csv")
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(out)
    for r in rows[:10]:
        print(f"{r['rank']:>4} {r['score']:>3} {r['name']}")
