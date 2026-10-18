Phase 2 plan: close the hard-mode name leak, score functions with the functions they call, and export decompiled code for every function.

# Phase 2: Better Facts — Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give Phase 3's agent leak-free, decompiled, ranked evidence for every function on 5 chips.

**Architecture:** `facts.py` exposes one shared `alias_map()` so hard mode renames the same names everywhere (function names, call edges, section names, Ghidra output). `baseline.py` adds a call-graph-inclusive score (own score + scores of functions reachable within 3 calls). `decompile.py` runs Ghidra headless once per chip over all object files; in hard mode a Ghidra pre-script renames names *before* analysis, so derived labels (`PTR_<name>_...`) never contain real names. Output is gzipped JSON in `facts/decomp/`, committed, so CI can test it without Ghidra.

**Tech Stack:** Python 3.10 stdlib (`gzip`, `json`, `re`, `subprocess`). Ghidra 12.1.4 headless + Java GhidraScripts. Plain `assert` tests.

## Global Constraints
- Stdlib only. Run from the repo root with `PYTHONPATH=.`. Never write to C:. Never modify `blobs/`.
- Hard mode must not contain any defined function name: not in function names, call edges, section names, or decompiled code.
- One alias rule everywhere: sorted defined names → `fn_0, fn_1, ...` (`alias_map()`).
- Call-graph depth: 3. Inclusive score = sum of own scores over the function plus every library function reachable within 3 calls (each counted once).
- Ghidra launcher comes from env var `CHIPXRAY_GHIDRA` (a `.ps1` path → run via `powershell -ExecutionPolicy Bypass -File`; anything else → run directly).
- Implementers never run git. The controller commits.
- Verified before planning (2026-10-18): the stripped facts file contains `"section": ".text.adctrig"` (leak); `mac_common.o` strings are generic format strings (no leak); Ghidra takes ~33 s per object, mostly start-up.

## File map
| File | Responsibility |
|---|---|
| `chipxray/facts.py` (modify) | `alias_map(path)`; strip also renames section names |
| `chipxray/baseline.py` (modify) | inclusive score/rank; fixed CSV fields; UTF-8; name tie-break |
| `ghidra_scripts/StripNames.java` (new) | pre-analysis rename from a TSV alias file |
| `ghidra_scripts/ExportFunctions.java` (new) | write every function's decompiled C as JSON |
| `chipxray/decompile.py` (new) | orchestrate Ghidra per chip, merge to `facts/decomp/<stem>[_stripped].json.gz` |
| `tests/test_facts.py`, `tests/test_baseline.py` (modify), `tests/test_decomp.py` (new) | checks |

Parallel: Task 1 and Task 2 touch different files → run together. Task 3 needs Task 1's `alias_map`. Task 4 needs all.

---

### Task 1: Close the hard-mode leak

**Files:** Modify `chipxray/facts.py`, `tests/test_facts.py`

**Interfaces:**
- Produces: `alias_map(path) -> dict[str, str]` (defined function name → `fn_N`). `extract(path, strip=True)` uses it and also renames each dot-separated part of `section` that is a defined name.

- [ ] **Step 1: Failing test** (append to `tests/test_facts.py`, call in `__main__`)

```python
def test_strip_leaks_no_defined_names():
    import json, re
    from chipxray.facts import alias_map
    path = "blobs/espressif/esp32s3_librftest.a"
    text = json.dumps(extract(path, strip=True))
    leaked = [n for n in alias_map(path)
              if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text)]
    assert leaked == [], leaked[:10]
```

- [ ] **Step 2: Run** `PYTHONPATH=. python tests/test_facts.py` → expect `ImportError: cannot import name 'alias_map'`.

- [ ] **Step 3: Implement.** Add above `extract`:

```python
def alias_map(path):
    """Hard-mode names: every defined function -> fn_N, sorted by name. Shared by facts and decompile."""
    data = Path(path).read_bytes()
    defined = {f["name"] for _, body in ar_members(data) if body[:4] == b"\x7fELF"
               for f in elf_facts(body)[1]}
    return {n: f"fn_{i}" for i, n in enumerate(sorted(defined))}
```

Replace the `if strip:` block in `extract` with:

```python
    if strip:
        alias = alias_map(path)
        for o in out["objects"]:
            for f in o["functions"]:
                f["name"] = alias[f["name"]]
                f["section"] = ".".join(alias.get(p, p) for p in f["section"].split("."))
            o["calls"] = [[alias.get(a, a), alias.get(b, b)] for a, b in o["calls"]]
```

Keep the existing `ponytail:` comment about renaming exported symbols.

- [ ] **Step 4: Run** tests → `ok`. Regenerate: `python -m chipxray.facts blobs/espressif/esp32s3_librftest.a --strip`.

---

### Task 2: Call-graph-inclusive score + Phase 1 minor fixes

**Files:** Modify `chipxray/baseline.py`, `tests/test_baseline.py`

**Interfaces:**
- Consumes: facts JSON (`functions[].mmio`, `objects[].calls`), `load_svd`, `classify`.
- Produces: `rank(facts, periphs, depth=3)` rows gain `inclusive_score`, `inclusive_rank`. CSV columns fixed by `FIELDS`. Rows sorted by `(-score, name)`.

- [ ] **Step 1: Failing tests** (append; call in `__main__`)

```python
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
```

Also add `"calls": []` to the object in the existing `test_scoring_mechanics` facts.

- [ ] **Step 2: Run** `PYTHONPATH=. python tests/test_baseline.py` → expect `KeyError: 'inclusive_score'`.

- [ ] **Step 3: Implement.** Replace `rank` and the CLI in `chipxray/baseline.py` with:

```python
FIELDS = ["name", "object", "score", "unmapped", "undoc_offset", "documented", "rank",
          "inclusive_score", "inclusive_rank"]
DEPTH = 3  # ponytail: fixed call depth; tune only if Phase 3 shows it matters


def _competition_rank(rows, key, out):
    for r in rows:
        r[out] = sum(x[key] >= r[key] for x in rows)


def rank(facts, periphs, depth=DEPTH):
    rows, calls = [], {}
    for o in facts["objects"]:
        for a, b in o.get("calls", []):
            calls.setdefault(a, set()).add(b)
        for f in o["functions"]:
            kinds = [classify(int(a, 16), periphs)[0] for a in f["mmio"]]
            rows.append(dict(name=f["name"], object=o["name"], score=sum(WEIGHT[k] for k in kinds),
                             unmapped=kinds.count("unmapped"), undoc_offset=kinds.count("undocumented_offset"),
                             documented=kinds.count("documented")))
    own = {r["name"]: r["score"] for r in rows}  # ponytail: assumes unique names per library (true for librftest)
    for r in rows:
        seen = frontier = {r["name"]}
        for _ in range(depth):
            frontier = {c for f in frontier for c in calls.get(f, ()) if c in own and c not in seen}
            seen = seen | frontier
        r["inclusive_score"] = sum(own[n] for n in seen)
    _competition_rank(rows, "score", "rank")
    _competition_rank(rows, "inclusive_score", "inclusive_rank")
    rows.sort(key=lambda r: (-r["score"], r["name"]))
    return rows


if __name__ == "__main__":
    facts_path, svd_path = sys.argv[1], sys.argv[2]
    with open(facts_path, encoding="utf-8") as fh:
        rows = rank(json.load(fh), load_svd(svd_path))
    out = Path("results") / (Path(facts_path).stem + "_baseline.csv")
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(out)
    for r in sorted(rows, key=lambda r: (-r["inclusive_score"], r["name"]))[:10]:
        print(f"{r['inclusive_rank']:>4} {r['inclusive_score']:>4} (own {r['score']:>3}) {r['name']}")
```

- [ ] **Step 4: Run** tests → `ok`.

---

### Task 3: Ghidra export, normal and hard mode

**Files:** Create `ghidra_scripts/StripNames.java`, `ghidra_scripts/ExportFunctions.java`, `chipxray/decompile.py`, `tests/test_decomp.py`

**Interfaces:**
- Consumes: `alias_map(path)`, `ar_members(data)` from `chipxray.facts`.
- Produces: `facts/decomp/<stem>[_stripped].json.gz` = `{"source", "sha256", "stripped": bool, "objects": [{"name": "<obj>.o", "functions": [{"name", "entry", "c"}]}]}`.

- [ ] **Step 1: `ghidra_scripts/StripNames.java`**

```java
// Pre-analysis: rename defined symbols and memory blocks using a TSV alias file (name<TAB>alias).
// @category ChipXray
import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class StripNames extends GhidraScript {
    @Override
    protected void run() throws Exception {
        Map<String, String> alias = new HashMap<>();
        for (String line : Files.readAllLines(Paths.get(getScriptArgs()[0]))) {
            String[] p = line.split("\t");
            if (p.length == 2) alias.put(p[0], p[1]);
        }
        List<Symbol> all = new ArrayList<>();
        currentProgram.getSymbolTable().getAllSymbols(true).forEach(all::add);
        for (Symbol s : all) {
            String a = alias.get(s.getName());
            if (a != null) s.setName(a, SourceType.USER_DEFINED);
        }
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            String[] parts = b.getName().split("\\.", -1);
            for (int i = 0; i < parts.length; i++) parts[i] = alias.getOrDefault(parts[i], parts[i]);
            String n = String.join(".", parts);
            if (!n.equals(b.getName())) b.setName(n);
        }
    }
}
```

- [ ] **Step 2: `ghidra_scripts/ExportFunctions.java`**

```java
// Post-analysis: write every non-external function's decompiled C to <outdir>/<program>.json.
// @category ChipXray
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

public class ExportFunctions extends GhidraScript {
    private static String esc(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c);
            }
        }
        return b.append('"').toString();
    }

    @Override
    protected void run() throws Exception {
        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        StringBuilder out = new StringBuilder("[");
        boolean first = true;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (f.isExternal() || f.isThunk()) continue;
            DecompileResults r = ifc.decompileFunction(f, 60, monitor);
            String c = r.getDecompiledFunction() == null ? "" : r.getDecompiledFunction().getC();
            out.append(first ? "" : ",").append("{\"name\":").append(esc(f.getName()))
               .append(",\"entry\":").append(esc(f.getEntryPoint().toString()))
               .append(",\"c\":").append(esc(c)).append("}");
            first = false;
        }
        out.append("]");
        Files.write(Paths.get(getScriptArgs()[0], currentProgram.getName() + ".json"),
                    out.toString().getBytes(StandardCharsets.UTF_8));
    }
}
```

- [ ] **Step 3: `chipxray/decompile.py`**

```python
"""Decompile every function of a static library with Ghidra headless (one run per library).

Usage: python -m chipxray.decompile blobs/espressif/esp32s3_librftest.a [--strip]
Needs env CHIPXRAY_GHIDRA: path to a .ps1 launcher (Windows) or to analyzeHeadless.
Writes facts/decomp/<stem>[_stripped].json.gz
"""
import gzip, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
from chipxray.facts import alias_map, ar_members


def launcher():
    g = os.environ["CHIPXRAY_GHIDRA"]
    return ["powershell", "-ExecutionPolicy", "Bypass", "-File", g] if g.endswith(".ps1") else [g]


def decompile(src, strip=False):
    src = Path(src).resolve()
    tag = src.stem + ("_stripped" if strip else "")
    work = (Path("work") / tag).resolve()
    shutil.rmtree(work, ignore_errors=True)
    objs, out, proj = work / "objs", work / "out", work / "proj"
    for d in (objs, out, proj):
        d.mkdir(parents=True)
    data = src.read_bytes()
    names = [n for n, body in ar_members(data) if body[:4] == b"\x7fELF"]
    for n, body in ar_members(data):
        if body[:4] == b"\x7fELF":
            (objs / n).write_bytes(body)
    cmd = launcher() + [str(proj), "p", "-import", str(objs), "-scriptPath", str(Path("ghidra_scripts").resolve()),
                        "-postScript", "ExportFunctions.java", str(out), "-deleteProject"]
    if strip:
        tsv = work / "alias.tsv"
        tsv.write_text("".join(f"{k}\t{v}\n" for k, v in alias_map(src).items()), encoding="utf-8")
        cmd += ["-preScript", "StripNames.java", str(tsv)]
    with open(work / "ghidra.log", "w", encoding="utf-8") as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    missing = [n for n in names if not (out / f"{n}.json").exists()]
    if missing:
        raise RuntimeError(f"Ghidra produced no output for {missing}; see {work / 'ghidra.log'}")
    result = dict(source=f"blobs/espressif/{src.name}", sha256=hashlib.sha256(data).hexdigest(), stripped=strip,
                  objects=[dict(name=n, functions=json.loads((out / f"{n}.json").read_text(encoding="utf-8")))
                           for n in names])
    dst = Path("facts/decomp") / f"{tag}.json.gz"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dst, "wt", encoding="utf-8") as fh:
        json.dump(result, fh)
    return dst, sum(len(o["functions"]) for o in result["objects"])


if __name__ == "__main__":
    dst, n = decompile(sys.argv[1], "--strip" in sys.argv)
    print(f"{dst}: {n} functions")
```

- [ ] **Step 4: Run on the S3, both modes** (Windows):

```bash
export CHIPXRAY_GHIDRA="/path/to/ghidra-headless.ps1"  # or <ghidra>/support/analyzeHeadless
python -m chipxray.decompile blobs/espressif/esp32s3_librftest.a
python -m chipxray.decompile blobs/espressif/esp32s3_librftest.a --strip
```
Expected: two lines, each `facts/decomp/...json.gz: N functions` with N ≥ 200.

- [ ] **Step 5: `tests/test_decomp.py`** (runs in CI from the committed `.json.gz`; Ghidra not needed)

```python
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
```

Note: external names (ROM/libphy functions) legitimately keep their names, and some contain a defined name as a substring (`tx_a_frame_trig`), so the test matches whole identifiers only, plus the explicit `PTR_<name>_` pattern.

- [ ] **Step 6: Run** `PYTHONPATH=. python tests/test_decomp.py` → `ok`. If `test_stripped_leaks_no_defined_names` fails, print the first leaked name and 80 characters around it, and report BLOCKED with that context. Do not weaken the test.

---

### Task 4: Run everything, record the result

**Files:** `facts/`, `facts/decomp/`, `results/*.csv`, `results/baseline.md`, `wiki/esp32-adctrig.md`, `README.md` (Phase 1 table → add inclusive rank column)

- [ ] **Step 1:** Regenerate facts (5 chips + `--strip` for all 5): `for c in esp32 esp32s3 esp32c3 esp32c5 esp32c61; do python -m chipxray.facts blobs/espressif/${c}_librftest.a; python -m chipxray.facts blobs/espressif/${c}_librftest.a --strip; done`
- [ ] **Step 2:** Decompile 5 chips × 2 modes with `chipxray.decompile` (10 runs). Record each function count.
- [ ] **Step 3:** Baseline for 5 chips: `python -m chipxray.baseline facts/${c}_librftest.json blobs/svd/$c.svd`.
- [ ] **Step 4:** Result table per chip: functions, `adctrig` own rank, `adctrig` inclusive rank, negative controls (same 11 names as Phase 1) with inclusive score > 0, negative controls with inclusive rank better than `adctrig`'s.
- [ ] **Step 5:** Update `results/baseline.md` (new table + one paragraph: did inclusive scoring change the picture?), add wiki rows (level `observed`), update the README result table with an "inclusive rank" column. Run all four test files → four `ok`.

## Done when
1. All four test files print `ok`, locally and in CI.
2. No hard-mode output contains a defined function name.
3. `results/baseline.md` reports own and inclusive ranks for 5 chips, whatever they show.
