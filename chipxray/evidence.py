"""Check every claim in a report against the fact store. A claim counts only if the facts contain it."""
from chipxray.query import MAX_C

LEVELS = ("observed", "correlated", "inferred")
MIN_CODE = 12  # shorter snippets ("(", "if") match almost any function


def _supported(store, fn, kind, ref):
    if kind == "mmio":
        try:
            return f"0x{int(ref, 16):08x}" in store.fn[fn]["mmio"], "address not touched by this function"
        except ValueError:
            return False, "not a hex address"
    if kind == "call":
        return ref in store.callees[fn] or ref in store.callers[fn], "no such call edge"
    if kind == "code":
        ref = ref.strip()
        if len(ref) < MIN_CODE:
            return False, f"code snippet shorter than {MIN_CODE} characters"
        return ref in store.c.get(fn, "")[:MAX_C], "text not found in the decompiled code that was shown"
    return False, f"unknown evidence kind {kind!r}"


def check(report, store):
    out = {"claims": 0, "supported": 0, "unsupported": [], "unknown_functions": [], "level_violations": 0, "malformed": 0}
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    for f in findings:
        if not isinstance(f, dict):
            out["malformed"] += 1
            continue
        fn = f.get("function", "")
        fn = fn if isinstance(fn, str) else str(fn)
        if f.get("evidence_level") not in LEVELS:
            out["level_violations"] += 1
            f["evidence_level"] = "inferred"
        if fn not in store.fn:
            out["unknown_functions"].append(fn)
        for e in f.get("evidence") if isinstance(f.get("evidence"), list) else []:
            out["claims"] += 1
            if not isinstance(e, dict):
                out["unsupported"].append({"function": fn, "kind": "", "ref": str(e)[:80], "why": "malformed evidence"})
                continue
            kind, ref = str(e.get("kind", "")), str(e.get("ref", ""))
            ok, why = _supported(store, fn, kind, ref) if fn in store.fn else (False, "unknown function")
            if ok:
                out["supported"] += 1
            else:
                out["unsupported"].append({"function": fn, "kind": kind, "ref": ref, "why": why})
    out["unsupported_rate"] = round(1 - out["supported"] / out["claims"], 3) if out["claims"] else 0.0
    return out
