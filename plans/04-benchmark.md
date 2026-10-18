Phase 4 plan: run the pre-registered benchmark (see roadmap "Phase 4 protocol") and the fft_dump_init hunt.

# Phase 4: Benchmark — Implementation Plan

**Goal:** One command runs every condition and writes a result table: systems {rules, one-prompt, agent} × modes {normal, hard} × chips {esp32s3, esp32c3, esp32c5} × 3 repeats for model systems.

**Global constraints:** stdlib only; repo root; `PYTHONPATH=.`; implementers never run git; tests never call a real model (use `tests/fake_agent_cli.py`); result files must not contain account identifiers.

---

### Task 1: Rare-register tool, safe CLI logging, one-prompt over CLI

**Files:** `chipxray/query.py`, `chipxray/agent.py`, `chipxray/cli_backend.py`, `tests/test_query.py`, `tests/test_cli_backend.py`, `tests/fake_agent_cli.py`

1. `query.py`: add method and tool (pre-registered general strategy: registers touched by few functions are worth a look):
```python
    def rare_pages(self, max_users=2):
        pages = {}
        for n, f in self.fn.items():
            for m in f["mmio"]:
                pages.setdefault(int(m, 16) & ~0xFF, set()).add(n)
        rare = [{"page": f"0x{p:08x}", "kind": classify(p, self.periphs)[0], "functions": sorted(fs)}
                for p, fs in sorted(pages.items()) if len(fs) <= int(max_users)]
        return {"pages": rare[:60], "total": len(rare)}
```
   Add to `TOOLS`: `_tool("rare_pages", "Hardware register pages (256 bytes) touched by only one or two functions, with those functions.", {"max_users": {"type": "integer"}}, [])`.
   Test (append, call in `__main__`): `r = S.rare_pages(); assert r["pages"] and all(len(p["functions"]) <= 2 for p in r["pages"])`.
2. `agent.py` `TOOLS_TEXT`: add the line `- rare_pages: register pages that only one or two functions touch.` after the `callers_of` line, and change the last line to `Stay inside your tool budget. Look at the top candidates and at rare_pages first, then follow registers and calls.`
3. `cli_backend.py` `CLI_TOOLS`: add `  python -m chipxray.query rare_pages` after the `callers_of` line, and change the last line to the same wording as step 2 ("turn budget" instead of "tool budget").
4. `cli_backend.py` safe logging: replace the `cli_usage` value with `{k: raw[k] for k in ("num_turns", "duration_ms", "total_cost_usd", "stop_reason", "usage", "unparsed_stdout") if k in raw}`. In `__main__`, stop writing the `.raw.json` file.
5. `cli_backend.py` one-prompt mode: `run_cli(store, template, budget=30, focus=None, oneshot=False)`. When `oneshot` is true: `system = HEAD + RULES + FORMAT` and `task = build_prompt(store)` (import from `chipxray.oneshot`), and `meta["backend"] = "cli-oneshot"`. Always send the task on **stdin** (`subprocess.run(..., input=task)`) and replace `{task}` in argv with the short text `"Follow the instructions in the input."`; Windows limits command lines to 32 KB and one-prompt tasks are larger. Update `tests/fake_agent_cli.py` to read the task with `sys.stdin.read()` instead of `sys.argv[2]` (keep accepting the argv argument). Add test: `run_cli(Store("esp32s3", stripped=True), template, oneshot=True)` returns `meta["backend"] == "cli-oneshot"` and `checked` present (the fake still answers; fine).
6. Add test: the report's `meta["cli_usage"]` has no `session_id` key even if the fake prints one (make the fake also print `"session_id": "x"`).

Verify: all test files `ok`.

---

### Task 2: Benchmark runner

**Files:** `chipxray/bench.py`, `tests/test_bench.py`

```python
"""Run the Phase 4 benchmark and write results/bench/summary.md + runs.jsonl.

Usage: python -m chipxray.bench [--repeats 3] [--chips esp32s3,esp32c3,esp32c5] [--jobs 3] [--budget 40]
Needs env CHIPXRAY_AGENT_CLI (agent template) and CHIPXRAY_ONESHOT_CLI (template without tools).
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from chipxray.cli_backend import run_cli
from chipxray.facts import alias_map
from chipxray.query import Store

NEG = ["esp_phy_ble_rx", "esp_phy_ble_tx", "esp_phy_bt_tx_tone", "esp_phy_cbw40m_en", "esp_phy_get_rx_result",
       "esp_phy_rftest_config", "esp_phy_rftest_init", "esp_phy_tx_contin_en", "esp_phy_wifi_rx",
       "esp_phy_wifi_tx", "esp_phy_wifi_tx_tone"]


def score(chip, stripped, ranking):
    """Map hidden names back and measure: adctrig position (1-based or None), negative controls in top 10."""
    alias = alias_map(f"blobs/espressif/{chip}_librftest.a")
    back = {v: k for k, v in alias.items()} if stripped else {}
    real = [back.get(n, n) for n in ranking[:10]]
    pos = real.index("adctrig") + 1 if "adctrig" in real else None
    return {"adctrig_pos": pos, "neg_in_top10": sum(n in NEG for n in real), "top10": real}


def rules_run(chip, stripped):
    s = Store(chip, stripped=stripped)
    ranking = [c["name"] for c in s.candidates(top=10)["candidates"]]
    return dict(system="rules", chip=chip, stripped=stripped, repeat=0, supported=None, claims=None,
                turns=0, seconds=0.0, **score(chip, stripped, ranking))


def model_run(system, chip, stripped, repeat, templates, budget):
    s = Store(chip, stripped=stripped)
    report, _ = run_cli(s, templates[system], budget=budget, oneshot=(system == "one-prompt"))
    c, m = report["checked"], report["meta"]
    return dict(system=system, chip=chip, stripped=stripped, repeat=repeat, supported=c["supported"], claims=c["claims"],
                turns=m["cli_usage"].get("num_turns"), seconds=m["seconds"], model=m["model"],
                parse_failed=m["parse_failed"], **score(chip, stripped, report["ranking"]))


def summarize(rows):
    lines = ["| system | mode | chip | runs | adctrig in top 10 | positions | supported claims | neg. controls in top 10 (mean) |",
             "|---|---|---|---|---|---|---|---|"]
    keys = sorted({(r["system"], r["stripped"], r["chip"]) for r in rows})
    for sysname, stripped, chip in keys:
        rs = [r for r in rows if (r["system"], r["stripped"], r["chip"]) == (sysname, stripped, chip)]
        hits = sum(r["adctrig_pos"] is not None for r in rs)
        pos = ",".join(str(r["adctrig_pos"] or "-") for r in rs)
        sup = sum(r["supported"] or 0 for r in rs); cl = sum(r["claims"] or 0 for r in rs)
        neg = sum(r["neg_in_top10"] for r in rs) / len(rs)
        lines.append(f"| {sysname} | {'hard' if stripped else 'normal'} | {chip} | {len(rs)} | {hits}/{len(rs)} | {pos} | "
                     f"{f'{sup}/{cl}' if cl else 'n/a'} | {neg:.1f} |")
    return "\n".join(lines)


def main(argv):
    get = lambda k, d: argv[argv.index(k) + 1] if k in argv else d
    repeats, jobs, budget = int(get("--repeats", 3)), int(get("--jobs", 3)), int(get("--budget", 40))
    chips = get("--chips", "esp32s3,esp32c3,esp32c5").split(",")
    templates = {"agent": json.loads(Path(os.environ["CHIPXRAY_AGENT_CLI"]).read_text(encoding="utf-8")),
                 "one-prompt": json.loads(Path(os.environ["CHIPXRAY_ONESHOT_CLI"]).read_text(encoding="utf-8"))}
    out = Path("results/bench"); out.mkdir(parents=True, exist_ok=True)
    rows = [rules_run(c, st) for c in chips for st in (False, True)]
    tasks = [(sy, c, st, i) for sy in ("one-prompt", "agent") for c in chips for st in (False, True) for i in range(repeats)]
    with ThreadPoolExecutor(jobs) as ex, open(out / "runs.jsonl", "a", encoding="utf-8") as log:
        for r in rows:
            log.write(json.dumps(r) + "\n")
        futs = [ex.submit(model_run, *t, templates, budget) for t in tasks]
        for f, t in zip(futs, tasks):
            try:
                r = f.result()
            except Exception as e:  # one failed run must not lose the others
                r = dict(system=t[0], chip=t[1], stripped=t[2], repeat=t[3], error=str(e)[:300],
                         adctrig_pos=None, neg_in_top10=0, supported=None, claims=None, top10=[])
            rows.append(r); log.write(json.dumps(r) + "\n"); log.flush()
            print(r["system"], r["chip"], "hard" if r["stripped"] else "normal", r["repeat"], "adctrig_pos:", r["adctrig_pos"], flush=True)
    (out / "summary.md").write_text(f"# Benchmark summary ({time.strftime('%Y-%m-%d')})\n\n" + summarize(rows) + "\n", encoding="utf-8")
    print(out / "summary.md")


if __name__ == "__main__":
    main(sys.argv[1:])
```

Test `tests/test_bench.py` (no real model):
```python
from chipxray.bench import rules_run, score, summarize


def test_score_maps_aliases_back():
    from chipxray.facts import alias_map
    a = alias_map("blobs/espressif/esp32s3_librftest.a")
    s = score("esp32s3", True, [a["esp_phy_wifi_tx"], a["adctrig"]])
    assert s["adctrig_pos"] == 2 and s["neg_in_top10"] == 1


def test_rules_and_summary():
    rows = [rules_run("esp32s3", False), rules_run("esp32s3", True)]
    assert rows[0]["adctrig_pos"] == rows[1]["adctrig_pos"]  # rules are name-blind
    assert "| rules | normal | esp32s3 |" in summarize(rows)


if __name__ == "__main__":
    test_score_maps_aliases_back(); test_rules_and_summary(); print("ok")
```

Verify: all test files `ok`.
