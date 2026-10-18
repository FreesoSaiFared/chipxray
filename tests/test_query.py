import json
from chipxray.facts import alias_map
from chipxray.query import Store, dispatch, TOOLS

S = Store("esp32s3")


def test_candidates_sorted_by_inclusive_score():
    c = S.candidates(top=5)["candidates"]
    assert len(c) == 5
    assert [x["inclusive_score"] for x in c] == sorted((x["inclusive_score"] for x in c), reverse=True)


def test_function_reports_classified_mmio_and_code():
    f = S.function("adctrig")
    kinds = {m["addr"]: m["kind"] for m in f["mmio"]}
    assert kinds["0x60033d5c"] == "unmapped" and kinds["0x600c101c"] == "documented"
    assert "memw" in f["c"] and "callees" in f and "callers" in f


def test_address_lists_functions_touching_it():
    a = S.address("0x60033d5c")
    assert a["kind"] == "unmapped" and "adctrig" in a["functions"]


def test_unknown_inputs_return_errors_not_exceptions():
    assert "error" in S.function("no_such_fn")
    assert "error" in S.address("not-hex")
    assert "error" in dispatch(S, "no_such_tool", {})


def test_search_finds_code_pattern():
    assert S.search("memw", limit=5)["matches"]


def test_stripped_store_leaks_no_names():
    st = Store("esp32s3", stripped=True)
    alias = alias_map("blobs/espressif/esp32s3_librftest.a")
    text = json.dumps([st.candidates(top=30), st.function(alias["adctrig"]), st.address("0x60033d5c")])
    assert "adctrig" not in text and alias["adctrig"] in text


def test_tools_schema_matches_dispatch():
    for t in TOOLS:
        assert "error" not in dispatch(S, t["function"]["name"], {"name": "adctrig", "addr": "0x60033d5c", "pattern": "memw"}) or t["function"]["name"] == "callers_of"


if __name__ == "__main__":
    for t in [test_candidates_sorted_by_inclusive_score, test_function_reports_classified_mmio_and_code,
              test_address_lists_functions_touching_it, test_unknown_inputs_return_errors_not_exceptions,
              test_search_finds_code_pattern, test_stripped_store_leaks_no_names, test_tools_schema_matches_dispatch]:
        t()
    print("ok")
