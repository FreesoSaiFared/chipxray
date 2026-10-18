Phase 1 plan: a rules-only baseline that ranks functions by how much undocumented hardware they touch.

# Phase 1: Rules-Only Baseline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For each chip, rank every `librftest` function by how many undocumented hardware registers it touches, and report where `adctrig` and the negative controls land. No LLM, no function names.

**Architecture:** `facts.py` gains a per-function `mmio` list (addresses in the peripheral window). Xtensa: read the literal pool that sits before each function's entry in its own `.text.<fn>` section. RISC-V: decode `lui` + following `addi`/load/store. `svd.py` turns esp-pacs SVD files into peripheral/register maps and classifies an address as documented / undocumented offset / unmapped. `baseline.py` scores and ranks.

**Tech Stack:** Python 3.10 stdlib only (`struct`, `xml.etree`, `csv`, `json`). Git Bash on Windows. Tests are plain `assert` files run with `PYTHONPATH=. python tests/<file>.py`.

## Global Constraints
- Stdlib only. No pytest, no new dependencies.
- Never write to C:. Never modify files in `blobs/` by hand.
- Run everything from the repo root with `PYTHONPATH=.`.
- Peripheral window: `0x6000_0000–0x600F_FFFF` for all chips, plus `0x3FF0_0000–0x3FF7_FFFF` for ESP32.
- Inputs pinned: esp-phy-lib `20f1db053a0e6cb9f1c09d255c43bf42483041d0`, esp-pacs `fed196c2f4b46f28f67e197ddbc007acd9804d3b`.
- The baseline must not read function names (it must give identical ranks in normal and stripped mode).
- Facts verified before planning (2026-10-18): S3 `adctrig` literal pool contains `0x60033d5c`, `0x60033d60`, `0x600c101c`, `0x6001c02c`; C3 `adctrig` uses `lui 0x60034000`, `0x6001c000`, `0x600c1000`; in the S3 SVD only `0x600c101c` is documented (`SENSITIVE.INTERNAL_SRAM_USAGE_3`).

## File map
| File | Responsibility |
|---|---|
| `.gitignore` | ignore `work/`, `__pycache__/`, `blobs/` |
| `fetch_inputs.sh` | download pinned blobs + SVDs, write/verify `SHA256SUMS` |
| `chipxray/facts.py` (modify) | add `mmio` per function |
| `chipxray/svd.py` (new) | SVD → peripherals; `classify(addr)` |
| `chipxray/baseline.py` (new) | score + rank, write `results/<chip>_baseline.csv` |
| `tests/test_facts.py` (modify) | MMIO extraction checks |
| `tests/test_svd.py` (new) | classify checks |
| `tests/test_baseline.py` (new) | scoring mechanics + name-independence |
| `results/baseline.md` (new) | result table |
| `wiki/esp32-adctrig.md` (modify) | new facts |

---

### Task 0: Git + reproducible inputs

**Files:**
- Create: `.gitignore`, `fetch_inputs.sh`, `SHA256SUMS`

**Interfaces:**
- Produces: `blobs/espressif/<chip>_librftest.a` and `blobs/svd/<chip>.svd` for chip in `esp32 esp32s3 esp32c3 esp32c5 esp32c61`.

- [ ] **Step 1: Write `.gitignore`**

```
work/
__pycache__/
blobs/
```

- [ ] **Step 2: Write `fetch_inputs.sh`**

```bash
#!/usr/bin/env bash
# Download pinned inputs. First run writes SHA256SUMS; later runs verify against it.
set -e
cd "$(dirname "$0")"
PHY=20f1db053a0e6cb9f1c09d255c43bf42483041d0
PACS=fed196c2f4b46f28f67e197ddbc007acd9804d3b
mkdir -p blobs/espressif blobs/svd
for c in esp32 esp32s3 esp32c3 esp32c5 esp32c61; do
  [ -f blobs/espressif/${c}_librftest.a ] || curl -sfL -o blobs/espressif/${c}_librftest.a \
    "https://raw.githubusercontent.com/espressif/esp-phy-lib/$PHY/$c/librftest.a"
  [ -f blobs/svd/$c.svd ] || curl -sfL -o blobs/svd/$c.svd \
    "https://raw.githubusercontent.com/esp-rs/esp-pacs/$PACS/$c/svd/$c.base.svd"
done
if [ -f SHA256SUMS ]; then sha256sum -c --quiet SHA256SUMS && echo "inputs OK"
else sha256sum blobs/espressif/*.a blobs/svd/*.svd > SHA256SUMS && echo "wrote SHA256SUMS"; fi
```

- [ ] **Step 3: Run it twice**

Run: `bash fetch_inputs.sh && bash fetch_inputs.sh`
Expected: first prints `wrote SHA256SUMS`, second prints `inputs OK`. `SHA256SUMS` has 10 lines.

- [ ] **Step 4: Init git and commit**

```bash
git init && git add -A && git commit -m "chore: project skeleton, pinned inputs, facts extractor"
```
Expected: commit succeeds; `git status` clean; `blobs/` not tracked.

---

### Task 1: MMIO constants per function

**Files:**
- Modify: `chipxray/facts.py`
- Test: `tests/test_facts.py`

**Interfaces:**
- Consumes: `elf_facts(obj) -> (machine, funcs, edges)` (existing).
- Produces: each function dict gains `"mmio": list[str]` — sorted unique `"0x%08x"` addresses inside the peripheral window. Helpers `is_periph(a: int) -> bool`, `xtensa_consts(sec: bytes, entry: int) -> list[int]`, `riscv_consts(code: bytes) -> list[int]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_facts.py`, add calls in `__main__`)

```python
from chipxray.facts import riscv_consts


def _fn(chip, name):
    f = extract(f"blobs/espressif/{chip}_librftest.a")
    return next(fn for o in f["objects"] for fn in o["functions"] if fn["name"] == name)


def test_s3_adctrig_mmio():
    mmio = _fn("esp32s3", "adctrig")["mmio"]
    for a in ("0x60033d5c", "0x60033d60", "0x600c101c", "0x6001c02c"):
        assert a in mmio, (a, mmio)
    assert all(0x60000000 <= int(a, 16) < 0x60100000 for a in mmio)


def test_c3_adctrig_mmio():
    mmio = [int(a, 16) for a in _fn("esp32c3", "adctrig")["mmio"]]
    assert any(0x60033000 <= a < 0x60035000 for a in mmio), [hex(a) for a in mmio]
    assert any(0x6001c000 <= a < 0x6001d000 for a in mmio)


def test_riscv_lui_addi_and_load():
    import struct
    lui_a5 = 0x600347B7            # lui a5, 0x60034
    lw_a0 = (0xD5C << 20) | (15 << 15) | (2 << 12) | (10 << 7) | 0x03   # lw a0, -0x2a4(a5)
    code = struct.pack("<II", lui_a5, lw_a0)
    assert 0x60033D5C in riscv_consts(code)
```

- [ ] **Step 2: Run to see it fail**

Run: `PYTHONPATH=. python tests/test_facts.py`
Expected: `ImportError: cannot import name 'riscv_consts'`.

- [ ] **Step 3: Implement** (add to `chipxray/facts.py` above `elf_facts`)

```python
PERIPH = [(0x3FF00000, 0x3FF80000), (0x60000000, 0x60100000)]
# ponytail: one window list for every chip; split per chip if a target maps peripherals elsewhere


def is_periph(a):
    return any(lo <= a < hi for lo, hi in PERIPH)


def xtensa_consts(sec, entry):
    # -mtext-section-literals: the literal pool sits before the function entry in .text.<fn>
    # ponytail: ignores pools the assembler places mid-function in very long functions
    return list(struct.unpack_from(f"<{entry // 4}I", sec))


def riscv_consts(code):
    # Linear sweep: track lui bases, resolve the next addi/load/store off that base.
    # ponytail: no control flow; compressed ops other than c.lui/c.lw/c.sw don't clobber tracked regs
    reg, out, i = {}, [], 0
    sext = lambda v, bits: v - (1 << bits) if v & (1 << (bits - 1)) else v
    while i + 2 <= len(code):
        h = code[i] | code[i + 1] << 8
        if h & 3 != 3:
            i += 2
            q, f3 = h & 3, h >> 13
            if q == 1 and f3 == 3 and (h >> 7) & 0x1F not in (0, 2):  # c.lui
                imm = sext(((h >> 2) & 0x1F) | ((h >> 12) & 1) << 5, 6)
                reg[(h >> 7) & 0x1F] = (imm << 12) & 0xFFFFFFFF
                out.append(reg[(h >> 7) & 0x1F])
            elif q == 0 and f3 in (2, 6):  # c.lw / c.sw
                rs1 = ((h >> 7) & 7) + 8
                off = ((h >> 10) & 7) << 3 | ((h >> 6) & 1) << 2 | ((h >> 5) & 1) << 6
                if rs1 in reg:
                    out.append((reg[rs1] + off) & 0xFFFFFFFF)
                if f3 == 2:
                    reg.pop(((h >> 2) & 7) + 8, None)
            continue
        if i + 4 > len(code):
            break
        w = struct.unpack_from("<I", code, i)[0]
        i += 4
        op, rd, rs1, f3 = w & 0x7F, (w >> 7) & 0x1F, (w >> 15) & 0x1F, (w >> 12) & 7
        if op == 0x37:  # lui
            reg[rd] = w & 0xFFFFF000
            out.append(reg[rd])
        elif op in (0x03, 0x23) and rs1 in reg:  # load / store
            imm = (w >> 20) if op == 0x03 else ((w >> 25) << 5) | ((w >> 7) & 0x1F)
            out.append((reg[rs1] + sext(imm, 12)) & 0xFFFFFFFF)
            if op == 0x03:
                reg.pop(rd, None)
        elif op == 0x13 and f3 == 0 and rs1 in reg:  # addi
            reg[rd] = (reg[rs1] + sext(w >> 20, 12)) & 0xFFFFFFFF
            out.append(reg[rd])
        elif rd and op not in (0x23, 0x63):  # anything else that writes rd clobbers it
            reg.pop(rd, None)
    return out
```

Then in `elf_facts`, replace the final `return` with:

```python
    def mmio(f):
        s = secs[f["shndx"]]
        data = obj[s[4]:s[4] + s[5]] if s[1] != 8 else b""  # SHT_NOBITS has no bytes
        if machine == 94:  # Xtensa
            consts = xtensa_consts(data, f["value"])
        elif machine == 243:  # RISC-V
            consts = riscv_consts(data[f["value"]:f["value"] + f["size"]])
        else:
            consts = []
        return sorted({f"0x{c:08x}" for c in consts if is_periph(c)})

    return machine, [dict(name=f["name"], size=f["size"], section=secname[f["shndx"]],
                          exported=f["bind"] == 1, mmio=mmio(f)) for f in funcs], edges
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=. python tests/test_facts.py`
Expected: `ok`.

- [ ] **Step 5: Regenerate facts and commit**

```bash
for c in esp32 esp32s3 esp32c3 esp32c5 esp32c61; do python -m chipxray.facts blobs/espressif/${c}_librftest.a; done
python -m chipxray.facts blobs/espressif/esp32s3_librftest.a --strip
git add -A && git commit -m "feat: extract peripheral-window constants per function (Xtensa literals, RISC-V lui)"
```

---

### Task 2: SVD register maps

**Files:**
- Create: `chipxray/svd.py`
- Test: `tests/test_svd.py`

**Interfaces:**
- Produces: `load_svd(path: str) -> list[tuple[str, int, int, dict[int, str]]]` = (peripheral name, base, size, {offset: register name}); `classify(addr: int, periphs) -> tuple[str, str | None]` with kind in `"documented" | "undocumented_offset" | "unmapped"`.

- [ ] **Step 1: Write the failing test**

```python
from chipxray.svd import load_svd, classify

P = load_svd("blobs/svd/esp32s3.svd")


def test_documented():
    assert classify(0x600C101C, P) == ("documented", "SENSITIVE.INTERNAL_SRAM_USAGE_3")


def test_unmapped():
    assert classify(0x60033D5C, P)[0] == "unmapped"


def test_dim_registers_expanded():
    # every peripheral with registers must expose offsets; a dim array must yield >1 offset
    assert sum(len(r) for _, _, _, r in P) > 1000


def test_derived_peripheral_has_registers():
    uart = {n: r for n, _, _, r in P}
    assert uart["UART1"] and len(uart["UART1"]) == len(uart["UART0"])


if __name__ == "__main__":
    test_documented(); test_unmapped(); test_dim_registers_expanded(); test_derived_peripheral_has_registers(); print("ok")
```

- [ ] **Step 2: Run to see it fail**

Run: `PYTHONPATH=. python tests/test_svd.py`
Expected: `ModuleNotFoundError: No module named 'chipxray.svd'`.

- [ ] **Step 3: Implement `chipxray/svd.py`**

```python
"""SVD register maps: which peripheral addresses are documented."""
import xml.etree.ElementTree as ET


def _int(s):
    return int(s, 0)


def _regs(node, base_off, out):
    for r in node.findall("register"):
        off, name, dim = base_off + _int(r.findtext("addressOffset")), r.findtext("name"), r.findtext("dim")
        if dim:
            inc = _int(r.findtext("dimIncrement"))
            for k in range(_int(dim)):
                out[off + k * inc] = name.replace("[%s]", str(k)).replace("%s", str(k))
        else:
            out[off] = name
    for c in node.findall("cluster"):  # ponytail: cluster-level dim not expanded
        _regs(c, base_off + _int(c.findtext("addressOffset")), out)


def load_svd(path):
    raw = {p.findtext("name"): p for p in ET.parse(path).getroot().iter("peripheral")}
    periphs = []
    for name, p in raw.items():
        src = raw.get(p.get("derivedFrom"), p)
        regs = {}
        node = src.find("registers")
        if node is not None:
            _regs(node, 0, regs)
        blocks = p.findall("addressBlock") or src.findall("addressBlock")
        size = max((_int(b.findtext("offset")) + _int(b.findtext("size")) for b in blocks),
                   default=max(regs, default=0) + 4)
        periphs.append((name, _int(p.findtext("baseAddress")), size, regs))
    return periphs


def classify(addr, periphs):
    for name, base, size, regs in periphs:
        if base <= addr < base + size:
            off = addr - base
            if off in regs:
                return "documented", f"{name}.{regs[off]}"
            return "undocumented_offset", f"{name}+0x{off:x}"
    return "unmapped", None
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=. python tests/test_svd.py`
Expected: `ok`. If `test_derived_peripheral_has_registers` fails with KeyError, print `sorted(n for n,_,_,_ in P)[:40]` and pick two peripherals linked by `derivedFrom` in the SVD (`grep -n derivedFrom blobs/svd/esp32s3.svd`); update only the test names.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: SVD register maps and address classification"
```

---

### Task 3: Rules-only ranking

**Files:**
- Create: `chipxray/baseline.py`
- Test: `tests/test_baseline.py`

**Interfaces:**
- Consumes: facts JSON (`functions[].mmio`), `load_svd`, `classify`.
- Produces: `rank(facts: dict, periphs) -> list[dict]` with keys `name, object, score, unmapped, undoc_offset, documented, rank`; CLI writes `results/<facts-stem>_baseline.csv`.
- Rank is pessimistic: `rank = number of functions with score >= this score` (ties count against you).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to see it fail**

Run: `PYTHONPATH=. python tests/test_baseline.py`
Expected: `ModuleNotFoundError: No module named 'chipxray.baseline'`.

- [ ] **Step 3: Implement `chipxray/baseline.py`**

```python
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
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=. python tests/test_baseline.py`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: rules-only baseline ranking"
```

---

### Task 4: Run on all chips, record the result

**Files:**
- Create: `results/baseline.md`, `results/*_baseline.csv`
- Modify: `wiki/esp32-adctrig.md`, `README.md`

- [ ] **Step 1: Run the baseline on 5 chips**

```bash
for c in esp32 esp32s3 esp32c3 esp32c5 esp32c61; do python -m chipxray.baseline facts/${c}_librftest.json blobs/svd/$c.svd; done
```
Expected: 5 CSVs in `results/`.

- [ ] **Step 2: Compute the result table**

```bash
python - <<'EOF'
import csv
NEG = ["esp_phy_ble_rx","esp_phy_ble_tx","esp_phy_bt_tx_tone","esp_phy_cbw40m_en","esp_phy_get_rx_result",
       "esp_phy_rftest_config","esp_phy_rftest_init","esp_phy_tx_contin_en","esp_phy_wifi_rx","esp_phy_wifi_tx","esp_phy_wifi_tx_tone"]
print("| chip | functions | adctrig rank | adctrig score | neg. controls present | neg. controls ranked above adctrig |")
print("|---|---|---|---|---|---|")
for c in ["esp32","esp32s3","esp32c3","esp32c5","esp32c61"]:
    rows = list(csv.DictReader(open(f"results/{c}_librftest_baseline.csv")))
    by = {r["name"]: r for r in rows}
    a = by["adctrig"]; neg = [by[n] for n in NEG if n in by]
    above = sum(int(n["rank"]) < int(a["rank"]) for n in neg)
    print(f"| {c} | {len(rows)} | {a['rank']} | {a['score']} | {len(neg)} | {above} |")
EOF
```

- [ ] **Step 3: ESP32 alias check**

Run: `python -c "import csv;r=[x for x in csv.DictReader(open('results/esp32_librftest_baseline.csv'))];print(sum(int(x['unmapped']) for x in r), 'unmapped hits on esp32')"` and look at a few raw `mmio` values of top ESP32 functions in `facts/esp32_librftest.json`. If most ESP32 hits fall in `0x6000_0000–0x6003_FFFF` while the SVD bases are `0x3FFx_xxxx`, write that in `results/baseline.md` as a known limitation (address aliasing) — do not tune the scorer in this phase.

- [ ] **Step 4: Write `results/baseline.md`**

Content: one-line summary; the table from Step 2; the method in 4 numbered sentences; limitations (linear sweep, literal pools mid-function, PHY space is undocumented so many RF functions score high, ESP32 alias finding from Step 3); next step = Phase 2.

- [ ] **Step 5: Update wiki + README, run all tests, commit**

Add rows to `wiki/esp32-adctrig.md`: per-chip `adctrig` MMIO addresses (from facts JSON) and their SVD class, evidence level `observed`, source `results/*_baseline.csv`. Add to README a "Phase 1 result" line pointing to `results/baseline.md`.

```bash
PYTHONPATH=. python tests/test_facts.py && PYTHONPATH=. python tests/test_svd.py && PYTHONPATH=. python tests/test_baseline.py
git add -A && git commit -m "results: phase 1 rules-only baseline on 5 chips"
```
Expected: three `ok` lines, commit succeeds.

---

## Done when
1. `bash fetch_inputs.sh` prints `inputs OK` on a fresh clone.
2. All three test files print `ok`.
3. `results/baseline.md` has the 5-chip table, written whatever the numbers say.
