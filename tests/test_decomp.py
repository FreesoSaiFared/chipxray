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


if __name__ == "__main__":
    test_normal_has_adctrig_code(); test_stripped_leaks_no_defined_names(); test_stripped_uses_same_aliases_as_facts(); print("ok")
