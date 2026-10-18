"""Check every claim in a report against the fact store. A claim counts only if the facts contain it."""

LEVELS = ("observed", "correlated", "inferred")


def _supported(store, fn, kind, ref):
    if kind == "mmio":
        try:
            return f"0x{int(ref, 16):08x}" in store.fn[fn]["mmio"], "address not touched by this function"
        except ValueError:
            return False, "not a hex address"
    if kind == "call":
        return ref in store.callees[fn] or ref in store.callers[fn], "no such call edge"
    if kind == "code":
        return bool(ref) and ref in store.c.get(fn, ""), "text not found in decompiled code"
    return False, f"unknown evidence kind {kind!r}"


def check(report, store):
    out = {"claims": 0, "supported": 0, "unsupported": [], "unknown_functions": [], "level_violations": 0}
    for f in report.get("findings", []):
        fn = f.get("function", "")
        if f.get("evidence_level") not in LEVELS:
            out["level_violations"] += 1
            f["evidence_level"] = "inferred"
        if fn not in store.fn:
            out["unknown_functions"].append(fn)
        for e in f.get("evidence", []):
            out["claims"] += 1
            kind, ref = e.get("kind", ""), str(e.get("ref", ""))
            ok, why = _supported(store, fn, kind, ref) if fn in store.fn else (False, "unknown function")
            if ok:
                out["supported"] += 1
            else:
                out["unsupported"].append({"function": fn, "kind": kind, "ref": ref, "why": why})
    out["unsupported_rate"] = round(1 - out["supported"] / out["claims"], 3) if out["claims"] else 0.0
    return out
