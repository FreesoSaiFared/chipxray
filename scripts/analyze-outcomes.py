"""Independent ChipXray reproduction metrics; writes a local JSON receipt."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from chipxray.facts import alias_map
from chipxray.query import Store
from chipxray.evidence import check
from chipxray.bench import score

root = Path(__file__).resolve().parents[1]
rows = []
for chip in ("esp32", "esp32s3", "esp32c3", "esp32c5", "esp32c61"):
    with (root / "results" / f"{chip}_librftest_baseline.csv").open(newline="", encoding="utf-8") as f:
        baseline = list(csv.DictReader(f))
    adc = next(r for r in baseline if r["name"] == "adctrig")
    rows.append({"chip": chip, "functions": len(baseline), "own_rank": int(adc["rank"]),
                 "inclusive_rank": int(adc["inclusive_rank"]), "score": int(adc["score"])})
reports = []
for file in sorted([*(root / "results" / "agent").glob("*.json"),
                    *(root / "results" / "oneshot").glob("*.json")]):
    if file.name.endswith(".transcript.json"):
        continue
    report = json.loads(file.read_text(encoding="utf-8"))
    meta = report["meta"]
    chip = meta["chip"]
    aliases = alias_map(str(root / "blobs" / "espressif" / f"{chip}_librftest.a"))
    decode = {v: k for k, v in aliases.items()} if meta["stripped"] else {}
    ranking = [decode.get(n, n) for n in report["ranking"]]
    reports.append({"file": str(file.relative_to(root)), "system": file.parent.name,
                    "model": meta["model"],
                    "chip": chip, "stripped": meta["stripped"],
                    "ranking": ranking, "adctrig_position": (ranking.index("adctrig") + 1 if "adctrig" in ranking else None),
                    "evidence_refs_checked": report["checked"]["supported"],
                    "evidence_refs_total": report["checked"]["claims"],
                    "tool_calls": meta.get("tool_calls"), "usage": meta.get("usage", {})})
store = Store("esp32s3")
known = store.fn["adctrig"]["mmio"][0]
fake = {"ranking": ["adctrig"], "findings": [
    {"function": "adctrig", "hypothesis": "ESP32 contains 128GB HBM",
     "evidence_level": "observed",
     "evidence": [{"kind": "mmio", "ref": known,
                   "claim": "This proves 128GB of HBM works inside ESP32"}],
     "counter_evidence": "", "alternatives": [], "validation": ""}]}
negative_probe = check(fake, store)
receipt = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
           "baselines": rows, "model_runs": reports,
           "adversarial_semantic_probe": {"meaning": "deliberately false claim using genuine MMIO address",
                                           "checker": negative_probe},
           "qualification": "Checker validates evidence references, not truth of natural-language claims"}
dest = root / "work" / "receipts" / "outcome-analysis.json"
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
print(json.dumps(receipt, indent=2))
