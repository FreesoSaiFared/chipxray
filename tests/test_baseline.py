import json
from chipxray.baseline import rank
from chipxray.svd import load_svd

P = load_svd("blobs/svd/esp32s3.svd")


def test_scoring_mechanics():
    facts = {"objects": [{"name": "x.o", "calls": [], "functions": [
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
    key = lambda rows: sorted((x["score"], x["inclusive_score"], x["rank"], x["inclusive_rank"]) for x in rows)
    assert key(rank(normal, P)) == key(rank(stripped, P))


def test_inclusive_score_follows_calls():
    facts = {"objects": [{"name": "x.o", "calls": [["a", "b"], ["c", "d"], ["d", "e"], ["e", "f"], ["f", "g"], ["a", "ext_rom_fn"]],
                          "functions": [
        {"name": "a", "mmio": []}, {"name": "b", "mmio": ["0x60033d5c"]},
        {"name": "c", "mmio": []}, {"name": "d", "mmio": []}, {"name": "e", "mmio": []},
        {"name": "f", "mmio": ["0x60033d5c"]}, {"name": "g", "mmio": ["0x60033d5c"]},
    ]}]}
    r = {x["name"]: x for x in rank(facts, P)}
    assert r["a"]["inclusive_score"] == 3          # a -> b (3); external callee ignored
    assert r["c"]["inclusive_score"] == 3          # c -> d -> e -> f within depth 3; g is depth 4
    assert r["d"]["inclusive_score"] == 6          # d -> e -> f -> g
    assert r["b"]["inclusive_score"] == 3 and r["b"]["inclusive_rank"] == 7  # a,b,c,g = 3; d,e,f = 6


def test_undocumented_offset_weight():
    name, base, size, regs = next(p for p in P if p[0] == "SENSITIVE")
    off = next(o for o in range(0, size, 4) if o not in regs)
    facts = {"objects": [{"name": "x.o", "calls": [], "functions": [{"name": "u", "mmio": [f"0x{base + off:08x}"]}]}]}
    assert rank(facts, P)[0]["score"] == 2


if __name__ == "__main__":
    test_scoring_mechanics(); test_names_do_not_matter(); test_inclusive_score_follows_calls()
    test_undocumented_offset_weight(); print("ok")
