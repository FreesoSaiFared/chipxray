import json
from chipxray.baseline import rank
from chipxray.svd import load_svd

P = load_svd("blobs/svd/esp32s3.svd")


def test_scoring_mechanics():
    facts = {"objects": [{"name": "x.o", "functions": [
        {"name": "a", "mmio": ["0x60033d5c"]},        # unmapped -> 3
        {"name": "b", "mmio": ["0x600c101c"]},        # documented -> 0
        {"name": "c", "mmio": []},
    ]}]}
    r = {x["name"]: x for x in rank(facts, P)}
    assert r["a"]["score"] == 3 and r["a"]["rank"] == 1
    assert r["b"]["score"] == 0 and r["b"]["rank"] == 3  # ties with c, pessimistic


def test_names_do_not_matter():
    normal = json.load(open("facts/esp32s3_librftest.json"))
    stripped = json.load(open("facts/esp32s3_librftest_stripped.json"))
    assert [x["score"] for x in rank(normal, P)] == [x["score"] for x in rank(stripped, P)]


if __name__ == "__main__":
    test_scoring_mechanics(); test_names_do_not_matter(); print("ok")
