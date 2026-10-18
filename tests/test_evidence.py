from chipxray.evidence import check
from chipxray.query import Store

S = Store("esp32s3")


def _report(evidence, level="correlated", fn="adctrig"):
    return {"ranking": [fn], "findings": [{"function": fn, "hypothesis": "h", "evidence_level": level,
            "evidence": evidence, "counter_evidence": "", "alternatives": [], "validation": ""}]}


def test_supported_claims():
    r = check(_report([{"kind": "mmio", "ref": "0x60033d5c", "claim": "x"},
                       {"kind": "call", "ref": "tx_a_frame", "claim": "x"},
                       {"kind": "code", "ref": "*DAT_00010a9c & 0xfffffff0", "claim": "x"}]), S)
    assert r["claims"] == 3 and r["supported"] == 3 and r["unsupported_rate"] == 0.0


def test_short_snippets_and_malformed_items_are_not_supported():
    rep = _report([{"kind": "code", "ref": "memw()", "claim": "x"}, "just a string"])
    rep["findings"].append("not a dict")
    r = check(rep, S)
    assert r["supported"] == 0 and r["claims"] == 2 and r["malformed"] == 1
    assert check({"ranking": [], "findings": "oops"}, S)["claims"] == 0


def test_unsupported_claims_are_listed():
    r = check(_report([{"kind": "mmio", "ref": "0x60099999", "claim": "x"},
                       {"kind": "call", "ref": "made_up_fn", "claim": "x"},
                       {"kind": "code", "ref": "this text is not in the code", "claim": "x"},
                       {"kind": "vibes", "ref": "?", "claim": "x"}]), S)
    assert r["supported"] == 0 and len(r["unsupported"]) == 4 and r["unsupported_rate"] == 1.0


def test_unknown_function_and_validated_level():
    rep = _report([{"kind": "mmio", "ref": "0x60033d5c", "claim": "x"}], level="validated", fn="ghost")
    r = check(rep, S)
    assert r["unknown_functions"] == ["ghost"] and r["level_violations"] == 1
    assert rep["findings"][0]["evidence_level"] == "inferred"


def test_mmio_ref_accepts_any_hex_case():
    r = check(_report([{"kind": "mmio", "ref": "0x60033D5C", "claim": "x"}]), S)
    assert r["supported"] == 1


if __name__ == "__main__":
    test_supported_claims(); test_unsupported_claims_are_listed(); test_unknown_function_and_validated_level()
    test_mmio_ref_accepts_any_hex_case(); test_short_snippets_and_malformed_items_are_not_supported(); print("ok")
