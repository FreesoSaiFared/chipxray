import gzip, json, re
from chipxray.facts import alias_map

SRC = "blobs/espressif/esp32s3_librftest.a"


def _load(tag):
    with gzip.open(f"facts/decomp/{tag}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


def test_normal_has_adctrig_code():
    d = _load("esp32s3_librftest")
    fns = {f["name"]: f for o in d["objects"] for f in o["functions"]}
    assert "adctrig" in fns and len(fns["adctrig"]["c"]) > 200


def test_stripped_leaks_no_defined_names():
    text = json.dumps(_load("esp32s3_librftest_stripped"))
    # whole identifiers, plus Ghidra-derived labels like PTR_<name>_00010ad8
    leaked = [n for n in alias_map(SRC)
              if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text) or f"PTR_{n}_" in text]
    assert leaked == [], leaked[:10]


def test_stripped_uses_same_aliases_as_facts():
    d = _load("esp32s3_librftest_stripped")
    names = {f["name"] for o in d["objects"] for f in o["functions"]}
    assert set(alias_map(SRC).values()) <= names


def test_no_defined_name_inside_strings_on_any_chip():
    for chip in ["esp32", "esp32s3", "esp32c3", "esp32c5", "esp32c61"]:
        text = json.dumps(_load(f"{chip}_librftest_stripped"))
        names = alias_map(f"blobs/espressif/{chip}_librftest.a")
        leaked = [n for n in names if re.search(rf'\\"[^"]*(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])[^"]*\\"', text)]
        assert leaked == [], (chip, leaked[:5])
        assert "adctrig" not in text, chip


def test_redact_strings_only_touches_string_literals():
    from chipxray.decompile import redact_strings
    c = 'if (strcmp(p,"adctrig") == 0) adctrig_helper(); x = "adctrig_x";'
    out = redact_strings(c, {"adctrig": "fn_28"})
    assert '"fn_28"' in out and "adctrig_helper()" in out and '"adctrig_x"' in out


if __name__ == "__main__":
    test_normal_has_adctrig_code(); test_stripped_leaks_no_defined_names(); test_stripped_uses_same_aliases_as_facts()
    test_no_defined_name_inside_strings_on_any_chip(); test_redact_strings_only_touches_string_literals(); print("ok")
