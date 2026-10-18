Phase 3 plan: an evidence-driven agent that investigates ranked functions with tools and reports findings whose every claim is checked against the facts.

# Phase 3: Evidence-Driven Agent — Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** An agent that hunts undocumented hardware capabilities (first `adctrig` as the known test, then new leads such as `fft_dump_init` on ESP32-C5), plus a one-prompt comparison system, both producing the same checked report format.

**Architecture:** `query.Store` loads one chip's facts, decompiled code, register map and ranking, and exposes 5 read-only tools. `llm.LLM` talks to any OpenAI-compatible chat endpoint with tool calling; `llm.ScriptedLLM` replays fixed replies for tests. `agent.run` loops: model → tool calls → results → … → final JSON report. `evidence.check` verifies each cited fact against the `Store`. `oneshot.run` puts the top candidates in one prompt, no tools, same report.

**Tech Stack:** Python 3.10 stdlib only (`urllib`, `json`, `gzip`, `re`, `http.server` in tests). Plain `assert` tests that need no network and no API key.

## Global Constraints
- Stdlib only. Run from the repo root with `PYTHONPATH=.`. Never write to C:. Implementers never run git.
- Hard mode (`stripped=True`) loads only `*_stripped` files; tool output must never contain a real defined function name.
- Report schema (agent and one-shot identical):
  `{"ranking": [<function name>, ...up to 10], "findings": [{"function", "hypothesis", "evidence_level": "observed"|"correlated"|"inferred", "evidence": [{"kind": "mmio"|"call"|"code", "ref": str, "claim": str}], "counter_evidence": str, "alternatives": [str], "validation": str}]}`
- The model may never claim `validated`; `evidence.check` downgrades it to `inferred` and counts it as a violation.
- LLM config from env: `CHIPXRAY_LLM_BASE_URL` (e.g. `https://generativelanguage.googleapis.com/v1beta/openai`), `CHIPXRAY_LLM_API_KEY`, `CHIPXRAY_LLM_MODEL`.
- Tool results are truncated to 6000 characters before they go back to the model.
- Writing style for prompts and reports: ~80% Simplified Technical English.

## File map
| File | Responsibility |
|---|---|
| `chipxray/query.py` | `Store` + 5 tools + `TOOLS` schema + `dispatch` |
| `chipxray/llm.py` | `LLM` (HTTP), `ScriptedLLM` (tests) |
| `chipxray/evidence.py` | `check(report, store)` |
| `chipxray/agent.py` | `SYSTEM` prompt, `parse_report`, `run`, CLI |
| `chipxray/oneshot.py` | one-prompt comparison system, CLI |
| `tests/test_query.py`, `test_llm.py`, `test_evidence.py`, `test_agent.py`, `test_oneshot.py` | checks |

Waves: Tasks 1+2 → Tasks 3+7 → Tasks 4+5 → Task 8 → Task 6 (real runs).

---

### Task 1: `query.Store` and the agent's tools

**Files:** Create `chipxray/query.py`, `tests/test_query.py`

**Interfaces:**
- Consumes: `chipxray.baseline.rank`, `chipxray.svd.load_svd`, `chipxray.svd.classify`; files `facts/<chip>_librftest[_stripped].json`, `facts/decomp/<same>.json.gz`, `blobs/svd/<chip>.svd`.
- Produces: `Store(chip, stripped=False)` with attributes `chip, stripped, fn (name→facts dict + "object"), c (name→decompiled C), rows (name→ranking row), callees, callers` and methods `candidates(top=20)`, `function(name)`, `address(addr)`, `search(pattern, limit=20)`, `callers_of(name)`; module-level `TOOLS` (OpenAI tool schema list) and `dispatch(store, name, args) -> dict`.

- [ ] **Step 1: Failing test `tests/test_query.py`**

```python
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
```

- [ ] **Step 2: Run** `PYTHONPATH=. python tests/test_query.py` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `chipxray/query.py`**

```python
"""Read-only fact store for one chip, and the tools the agent may call."""
import gzip, json, re
from collections import defaultdict
from chipxray.baseline import rank
from chipxray.svd import classify, load_svd

MAX_C = 4000


class Store:
    def __init__(self, chip, stripped=False):
        self.chip, self.stripped = chip, stripped
        tag = f"{chip}_librftest" + ("_stripped" if stripped else "")
        with open(f"facts/{tag}.json", encoding="utf-8") as fh:
            self.facts = json.load(fh)
        with gzip.open(f"facts/decomp/{tag}.json.gz", "rt", encoding="utf-8") as fh:
            dec = json.load(fh)
        self.periphs = load_svd(f"blobs/svd/{chip}.svd")
        self.rows = {r["name"]: r for r in rank(self.facts, self.periphs)}
        self.fn = {f["name"]: dict(f, object=o["name"]) for o in self.facts["objects"] for f in o["functions"]}
        self.c = {f["name"]: f["c"] for o in dec["objects"] for f in o["functions"]}
        self.callees, self.callers = defaultdict(set), defaultdict(set)
        for o in self.facts["objects"]:
            for a, b in o["calls"]:
                self.callees[a].add(b)
                self.callers[b].add(a)

    def candidates(self, top=20):
        rows = sorted(self.rows.values(), key=lambda r: (-r["inclusive_score"], -r["score"], r["name"]))[:int(top)]
        return {"candidates": [{k: r[k] for k in ("name", "score", "inclusive_score", "unmapped", "undoc_offset", "documented")}
                               for r in rows]}

    def function(self, name):
        if name not in self.fn:
            return {"error": f"unknown function {name!r}"}
        f, r = self.fn[name], self.rows[name]
        mmio = [dict(zip(("kind", "detail"), classify(int(a, 16), self.periphs)), addr=a) for a in f["mmio"]]
        c = self.c.get(name, "")
        return {"name": name, "object": f["object"], "size": f["size"], "exported": f["exported"],
                "score": r["score"], "inclusive_score": r["inclusive_score"], "mmio": mmio,
                "callees": sorted(self.callees[name]), "callers": sorted(self.callers[name]),
                "c": c[:MAX_C] + ("\n/* ...truncated... */" if len(c) > MAX_C else "")}

    def address(self, addr):
        try:
            a = int(str(addr), 16)
        except ValueError:
            return {"error": f"not a hex address: {addr!r}"}
        key, page = f"0x{a:08x}", a & ~0xFF
        kind, detail = classify(a, self.periphs)
        same = sorted(n for n, f in self.fn.items() if key in f["mmio"])
        near = sorted(n for n, f in self.fn.items() if n not in same and any(int(m, 16) & ~0xFF == page for m in f["mmio"]))
        return {"addr": key, "kind": kind, "detail": detail, "functions": same, "same_page_functions": near}

    def search(self, pattern, limit=20):
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return {"error": f"bad regex: {e}"}
        hits = [n for n, c in sorted(self.c.items()) if rx.search(c)]
        return {"matches": hits[:int(limit)], "total": len(hits)}

    def callers_of(self, name):
        if name not in self.fn:
            return {"error": f"unknown function {name!r}"}
        return {"name": name, "callers": sorted(self.callers[name])}


def _tool(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


TOOLS = [
    _tool("candidates", "List functions ranked by undocumented-register score (own + called functions).",
          {"top": {"type": "integer"}}, []),
    _tool("function", "Facts for one function: registers it touches (with documented/unmapped class), callers, callees, decompiled C.",
          {"name": {"type": "string"}}, ["name"]),
    _tool("address", "Class of one hardware address and every function that touches it or its 256-byte page.",
          {"addr": {"type": "string"}}, ["addr"]),
    _tool("search", "Regex search over all decompiled C. Returns matching function names.",
          {"pattern": {"type": "string"}, "limit": {"type": "integer"}}, ["pattern"]),
    _tool("callers_of", "Functions that call the given function.", {"name": {"type": "string"}}, ["name"]),
]


def dispatch(store, name, args):
    spec = next((t["function"] for t in TOOLS if t["function"]["name"] == name), None)
    if spec is None:
        return {"error": f"unknown tool {name!r}"}
    props = spec["parameters"]["properties"]  # pass only declared parameters; models add extras
    try:
        return getattr(store, name)(**{k: v for k, v in args.items() if k in props})
    except (TypeError, ValueError) as e:
        return {"error": f"bad arguments for {name}: {e}"}
```

- [ ] **Step 4: Run** tests → `ok`.

---

### Task 2: `llm.LLM` and `llm.ScriptedLLM`

**Files:** Create `chipxray/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Produces: `LLM(base_url=None, api_key=None, model=None, timeout=180)` with `.model` and `.chat(messages, tools=None) -> dict` (the assistant message: `role`, `content`, optional `tool_calls`), plus `.usage` (running totals: `prompt_tokens`, `completion_tokens`, `calls`). `ScriptedLLM(replies)` with the same `.chat`, `.model = "scripted"`, `.usage`, and `.seen` (list of message lists it received).

- [ ] **Step 1: Failing test `tests/test_llm.py`**

```python
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from chipxray.llm import LLM, ScriptedLLM

REPLY = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
    {"id": "t1", "type": "function", "function": {"name": "candidates", "arguments": "{\"top\": 3}"}}]}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        H.last = (self.path, self.headers.get("Authorization"), body)
        out = json.dumps(REPLY).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_llm_posts_openai_format_and_parses_tool_calls():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    llm = LLM(base_url=f"http://127.0.0.1:{srv.server_port}/v1", api_key="k", model="m")
    msg = llm.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "candidates"}}])
    srv.shutdown()
    path, auth, body = H.last
    assert path == "/v1/chat/completions" and auth == "Bearer k" and body["model"] == "m" and body["tools"]
    assert msg["tool_calls"][0]["function"]["name"] == "candidates"
    assert llm.usage == {"prompt_tokens": 11, "completion_tokens": 7, "calls": 1}


def test_scripted_llm_replays_in_order():
    s = ScriptedLLM([{"role": "assistant", "content": "a"}, {"role": "assistant", "content": "b"}])
    assert s.chat([{"role": "user", "content": "1"}])["content"] == "a"
    assert s.chat([{"role": "user", "content": "2"}])["content"] == "b"
    assert len(s.seen) == 2 and s.usage["calls"] == 2


if __name__ == "__main__":
    test_llm_posts_openai_format_and_parses_tool_calls(); test_scripted_llm_replays_in_order(); print("ok")
```

- [ ] **Step 2: Run** `PYTHONPATH=. python tests/test_llm.py` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `chipxray/llm.py`**

```python
"""Minimal client for any OpenAI-compatible chat endpoint with tool calling. Stdlib only."""
import json, os, time, urllib.error, urllib.request


class LLM:
    def __init__(self, base_url=None, api_key=None, model=None, timeout=180):
        self.base_url = (base_url or os.environ["CHIPXRAY_LLM_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ.get("CHIPXRAY_LLM_API_KEY", "")
        self.model = model or os.environ["CHIPXRAY_LLM_MODEL"]
        self.timeout = timeout
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    def chat(self, messages, tools=None):
        body = {"model": self.model, "messages": messages, "temperature": 0}
        if tools:
            body["tools"] = tools
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.api_key}"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503) or attempt == 3:
                    raise RuntimeError(f"LLM HTTP {e.code}: {e.read()[:500]!r}") from e
                time.sleep(2 ** attempt * 5)  # rate limits on free tiers
        u = data.get("usage") or {}
        self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += u.get("completion_tokens", 0)
        self.usage["calls"] += 1
        return data["choices"][0]["message"]


class ScriptedLLM:
    """Replays fixed assistant messages. For tests: no network, deterministic."""
    model = "scripted"

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    def chat(self, messages, tools=None):
        self.seen.append(list(messages))
        self.usage["calls"] += 1
        return self.replies.pop(0)
```

- [ ] **Step 4: Run** tests → `ok`.

---

### Task 3: `evidence.check`

**Files:** Create `chipxray/evidence.py`, `tests/test_evidence.py`

**Interfaces:**
- Consumes: `Store` (Task 1).
- Produces: `check(report, store) -> dict` = `{"claims": int, "supported": int, "unsupported": [ {function, kind, ref, why} ], "unknown_functions": [names], "level_violations": int, "unsupported_rate": float}`. It also mutates the report: any `evidence_level == "validated"` becomes `"inferred"`.

- [ ] **Step 1: Failing test `tests/test_evidence.py`**

```python
from chipxray.evidence import check
from chipxray.query import Store

S = Store("esp32s3")


def _report(evidence, level="correlated", fn="adctrig"):
    return {"ranking": [fn], "findings": [{"function": fn, "hypothesis": "h", "evidence_level": level,
            "evidence": evidence, "counter_evidence": "", "alternatives": [], "validation": ""}]}


def test_supported_claims():
    r = check(_report([{"kind": "mmio", "ref": "0x60033d5c", "claim": "x"},
                       {"kind": "call", "ref": "tx_a_frame", "claim": "x"},
                       {"kind": "code", "ref": "memw()", "claim": "x"}]), S)
    assert r["claims"] == 3 and r["supported"] == 3 and r["unsupported_rate"] == 0.0


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
    test_mmio_ref_accepts_any_hex_case(); print("ok")
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `chipxray/evidence.py`**

```python
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
```

- [ ] **Step 4: Run** tests → `ok`.

---

### Task 4: The agent loop

**Files:** Create `chipxray/agent.py`, `tests/test_agent.py`

**Interfaces:**
- Consumes: `Store`, `TOOLS`, `dispatch` (Task 1); `LLM`/`ScriptedLLM` (Task 2); `check` (Task 3).
- Produces: `SYSTEM` (str), `parse_report(text) -> dict | None`, `run(store, llm, budget=30, focus=None) -> (report, transcript)`; CLI `python -m chipxray.agent <chip> [--strip] [--focus NAME] [--budget N]` writing `results/agent/<chip>[_stripped]-<model>-<UTC stamp>.json` (report + `checked` + `meta`) and `.transcript.json`.

- [ ] **Step 1: Failing test `tests/test_agent.py`**

```python
import json
from chipxray.agent import parse_report, run
from chipxray.llm import ScriptedLLM
from chipxray.query import Store

S = Store("esp32s3")
FINAL = {"ranking": ["adctrig"], "findings": [{"function": "adctrig", "hypothesis": "sample capture trigger",
         "evidence_level": "correlated", "evidence": [{"kind": "mmio", "ref": "0x60033d5c", "claim": "writes unmapped register"}],
         "counter_evidence": "none", "alternatives": ["calibration"], "validation": "run on hardware"}]}


def _call(i, name, args):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_parse_report_accepts_fenced_json():
    assert parse_report("text\n```json\n" + json.dumps(FINAL) + "\n```")["ranking"] == ["adctrig"]
    assert parse_report("no json here") is None


def test_run_executes_tools_then_returns_checked_report():
    llm = ScriptedLLM([_call(1, "function", {"name": "adctrig"}), {"role": "assistant", "content": json.dumps(FINAL)}])
    report, transcript = run(S, llm, budget=5)
    assert report["checked"]["supported"] == 1 and report["meta"]["tool_calls"] == 1
    tool_msgs = [m for m in transcript if m["role"] == "tool"]
    assert tool_msgs and "0x60033d5c" in tool_msgs[0]["content"]


def test_budget_exhaustion_forces_final_answer():
    llm = ScriptedLLM([_call(i, "candidates", {"top": 3}) for i in range(3)] + [{"role": "assistant", "content": json.dumps(FINAL)}])
    report, transcript = run(S, llm, budget=3)
    assert report["meta"]["tool_calls"] == 3 and report["ranking"] == ["adctrig"]
    assert "budget" in transcript[-2]["content"].lower()


def test_unparseable_final_gives_empty_report():
    llm = ScriptedLLM([{"role": "assistant", "content": "I think it is adctrig."}, {"role": "assistant", "content": "still prose"}])
    report, _ = run(S, llm, budget=3)
    assert report["ranking"] == [] and report["meta"]["parse_failed"] is True


if __name__ == "__main__":
    test_parse_report_accepts_fenced_json(); test_run_executes_tools_then_returns_checked_report()
    test_budget_exhaustion_forces_final_answer(); test_unparseable_final_gives_empty_report(); print("ok")
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `chipxray/agent.py`**

```python
"""Evidence-driven agent: investigate with tools, then report findings whose claims are checked.

Usage: python -m chipxray.agent esp32c5 [--strip] [--focus NAME] [--budget 30]
Needs CHIPXRAY_LLM_BASE_URL, CHIPXRAY_LLM_MODEL, CHIPXRAY_LLM_API_KEY.
"""
import json, re, sys, time
from pathlib import Path
from chipxray.evidence import check
from chipxray.query import TOOLS, Store, dispatch

MAX_TOOL_CHARS = 6000

SYSTEM = """You are a hardware reverse engineer. You study one vendor firmware library.
Your goal: find functions that drive UNDOCUMENTED hardware capabilities.
Examples: hidden test modes, sample capture or dump engines, debug paths.
Ordinary documented features do not count.

Use the tools. They return facts from the binary:
- candidates: functions ranked by how many undocumented registers they and their callees touch.
- function: one function's registers (documented or unmapped), callers, callees, and decompiled C.
- address: the class of one hardware address and all functions that touch it.
- search: regex over all decompiled C.
- callers_of: who calls a function.

Rules:
1. Every claim must cite a fact you saw in a tool result.
   kind "mmio": a hardware address the function touches.
   kind "call": a function it calls or that calls it.
   kind "code": a short exact snippet (max 80 characters) copied from its decompiled C.
2. Evidence levels: "observed" = one fact. "correlated" = two or more independent facts agree,
   for example unmapped registers plus buffer setup plus a wait loop. "inferred" = your interpretation.
   Never use "validated". Only a hardware test can validate.
3. For each finding, give counter-evidence and at least one other explanation,
   for example ordinary calibration or register initialisation.
4. A function that touches many registers is not automatically interesting.
   Prefer functions that configure undocumented registers AND look like trigger, capture or dump sequences.
5. Function names may be hidden (fn_N). Do not rely on names. Rely on code and registers.
6. Stay inside your tool budget. Look at the top candidates first, then follow registers and calls.

When you finish, reply with ONLY one JSON object, no other text:
{"ranking": [up to 10 function names, most likely first],
 "findings": [up to 5 objects: {"function", "hypothesis", "evidence_level",
   "evidence": [{"kind", "ref", "claim"}], "counter_evidence", "alternatives": [..], "validation"}]}
"""


def parse_report(text):
    if not text:
        return None
    for chunk in [text] + re.findall(r"```(?:json)?\s*(.*?)```", text, re.S) + re.findall(r"\{.*\}", text, re.S):
        try:
            d = json.loads(chunk)
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict) and isinstance(d.get("ranking"), list):
            d.setdefault("findings", [])
            return d
    return None


def run(store, llm, budget=30, focus=None):
    task = f"Investigate the {store.chip} radio test library. Find undocumented hardware capabilities."
    if focus:
        task += f" Start with function {focus}."
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    calls, report, nudged, t0 = 0, None, False, time.time()
    while True:
        tools = TOOLS if calls < budget else None
        msg = llm.chat(messages, tools)
        msg = {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
        messages.append(msg)
        if msg.get("tool_calls") and calls < budget:
            for tc in msg["tool_calls"]:
                calls += 1
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                result = json.dumps(dispatch(store, tc["function"]["name"], args))[:MAX_TOOL_CHARS]
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            if calls >= budget:
                messages.append({"role": "user", "content": "Tool budget is used up. Reply now with ONLY the final JSON report."})
            continue
        report = parse_report(msg.get("content") or "")
        if report or nudged:
            break
        nudged = True
        messages.append({"role": "user", "content": "Reply with ONLY the final JSON report."})
    parse_failed = report is None
    report = report or {"ranking": [], "findings": []}
    report["checked"] = check(report, store)
    report["meta"] = {"chip": store.chip, "stripped": store.stripped, "model": llm.model, "budget": budget,
                      "tool_calls": calls, "focus": focus, "parse_failed": parse_failed,
                      "seconds": round(time.time() - t0, 1), "usage": dict(llm.usage)}
    return report, messages


if __name__ == "__main__":
    from chipxray.llm import LLM
    args = sys.argv[1:]
    chip, strip = args[0], "--strip" in args
    focus = args[args.index("--focus") + 1] if "--focus" in args else None
    budget = int(args[args.index("--budget") + 1]) if "--budget" in args else 30
    llm = LLM()
    report, transcript = run(Store(chip, stripped=strip), llm, budget=budget, focus=focus)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    model = re.sub(r"[^A-Za-z0-9._-]", "_", llm.model)
    base = Path("results/agent") / f"{chip}{'_stripped' if strip else ''}-{model}-{stamp}"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    Path(str(base) + ".transcript.json").write_text(json.dumps(transcript, indent=1), encoding="utf-8")
    print(base.with_suffix(".json"))
    print("ranking:", report["ranking"][:10])
    print("claims supported:", report["checked"]["supported"], "/", report["checked"]["claims"])
```

- [ ] **Step 4: Run** tests → `ok`.

---

### Task 5: The one-prompt comparison system

**Files:** Create `chipxray/oneshot.py`, `tests/test_oneshot.py`

**Interfaces:**
- Consumes: `Store` (Task 1), `check` (Task 3), `parse_report` and `SYSTEM` rules text from `chipxray.agent` (Task 4 — if Task 4 is not finished yet, copy nothing; import at call time).
- Produces: `build_prompt(store, top=15, max_c=1500) -> str`, `run(store, llm, top=15) -> (report, transcript)` with the same `checked` and `meta` keys as the agent (`tool_calls` = 0); CLI `python -m chipxray.oneshot <chip> [--strip] [--top N]` writing `results/oneshot/<chip>[_stripped]-<model>-<stamp>.json`.

- [ ] **Step 1: Failing test `tests/test_oneshot.py`**

```python
import json
from chipxray.oneshot import build_prompt, run
from chipxray.llm import ScriptedLLM
from chipxray.query import Store

S = Store("esp32s3")
FINAL = {"ranking": ["adctrig"], "findings": []}


def test_prompt_contains_top_candidates_and_code():
    p = build_prompt(S, top=5)
    top = S.candidates(top=5)["candidates"]
    assert all(c["name"] in p for c in top) and "unmapped" in p


def test_run_returns_checked_report_without_tools():
    llm = ScriptedLLM([{"role": "assistant", "content": json.dumps(FINAL)}])
    report, transcript = run(S, llm, top=5)
    assert report["ranking"] == ["adctrig"] and report["meta"]["tool_calls"] == 0
    assert "checked" in report and len(llm.seen) == 1


if __name__ == "__main__":
    test_prompt_contains_top_candidates_and_code(); test_run_returns_checked_report_without_tools(); print("ok")
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `chipxray/oneshot.py`**

```python
"""One-prompt comparison system: top candidates' facts in a single prompt, no tools, same report format.

Usage: python -m chipxray.oneshot esp32c5 [--strip] [--top 15]
"""
import json, re, sys, time
from pathlib import Path
from chipxray.evidence import check
from chipxray.query import Store


def build_prompt(store, top=15, max_c=1500):
    parts = [f"Library: {store.chip} radio test library. Facts for the top {top} candidate functions follow."]
    for c in store.candidates(top=top)["candidates"]:
        f = store.function(c["name"])
        f["c"] = f["c"][:max_c]
        parts.append(json.dumps(f))
    parts.append("Rank these functions and report findings using the JSON format from the rules.")
    return "\n\n".join(parts)


def run(store, llm, top=15):
    from chipxray.agent import SYSTEM, parse_report
    system = SYSTEM.split("Use the tools.")[0] + SYSTEM[SYSTEM.index("Rules:"):]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": build_prompt(store, top)}]
    t0 = time.time()
    msg = llm.chat(messages)
    messages.append({k: v for k, v in msg.items() if k in ("role", "content")})
    report = parse_report(msg.get("content") or "")
    parse_failed = report is None
    report = report or {"ranking": [], "findings": []}
    report["checked"] = check(report, store)
    report["meta"] = {"chip": store.chip, "stripped": store.stripped, "model": llm.model, "top": top,
                      "tool_calls": 0, "parse_failed": parse_failed, "seconds": round(time.time() - t0, 1),
                      "usage": dict(llm.usage)}
    return report, messages


if __name__ == "__main__":
    from chipxray.llm import LLM
    args = sys.argv[1:]
    chip, strip = args[0], "--strip" in args
    top = int(args[args.index("--top") + 1]) if "--top" in args else 15
    llm = LLM()
    report, transcript = run(Store(chip, stripped=strip), llm, top=top)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    model = re.sub(r"[^A-Za-z0-9._-]", "_", llm.model)
    base = Path("results/oneshot") / f"{chip}{'_stripped' if strip else ''}-{model}-{stamp}"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    Path(str(base) + ".transcript.json").write_text(json.dumps(transcript, indent=1), encoding="utf-8")
    print(base.with_suffix(".json"), "ranking:", report["ranking"][:10])
```

- [ ] **Step 4: Run** tests → `ok`.

---

### Task 6: Real runs (needs an API key; controller runs these)

- [ ] **Step 1:** Known-answer test, normal mode: `python -m chipxray.agent esp32s3 --budget 30`. Record `adctrig`'s position in `ranking` and the unsupported-claim rate.
- [ ] **Step 2:** Same in hard mode: `python -m chipxray.agent esp32s3 --strip --budget 30`. Map the alias back with `alias_map` when scoring.
- [ ] **Step 3:** Hunt: `python -m chipxray.agent esp32c5 --focus fft_dump_init --budget 40`. Read the transcript. Write `wiki/esp32c5-fft-dump.md` with every fact at its evidence level.
- [ ] **Step 4:** Add the new test files to `.github/workflows/tests.yml`.

---

### Task 7: Query tools as a command line (for external agent CLIs)

**Files:** Modify `chipxray/query.py`, `tests/test_query.py`

**Interfaces:**
- Produces: `Store(chip, stripped=False, root=None)`; `root` defaults to env `CHIPXRAY_ROOT` or `"."`, and all three file paths are joined to it. CLI: `python -m chipxray.query <tool> [key=value ...]` prints the tool's JSON result. Chip and mode come ONLY from env `CHIPXRAY_CHIP` and `CHIPXRAY_STRIPPED` (`"1"` = hard mode), so an agent cannot switch to normal mode. Integer-looking values (`top=5`) are passed as int.

- [ ] **Step 1: Failing test** (append to `tests/test_query.py`, call in `__main__`)

```python
def test_cli_uses_env_for_chip_and_mode():
    import os, subprocess, sys
    env = dict(os.environ, PYTHONPATH=".", CHIPXRAY_CHIP="esp32s3", CHIPXRAY_STRIPPED="1")
    out = subprocess.run([sys.executable, "-m", "chipxray.query", "address", "addr=0x60033d5c"],
                         capture_output=True, text=True, env=env, check=True).stdout
    d = json.loads(out)
    assert d["kind"] == "unmapped" and "adctrig" not in out and d["functions"]
    bad = subprocess.run([sys.executable, "-m", "chipxray.query", "nope"], capture_output=True, text=True, env=env).stdout
    assert "error" in json.loads(bad)
```

- [ ] **Step 2: Run** `PYTHONPATH=. python tests/test_query.py` → fails (the module prints nothing, so `json.loads` raises).

- [ ] **Step 3: Implement.** Add `import os, sys` at the top. In `Store.__init__`, add parameter `root=None`, set `root = root or os.environ.get("CHIPXRAY_ROOT", ".")`, and prefix the three file paths with `f"{root}/"`. Append at the end of the file:

```python
def _value(v):
    return int(v) if v.lstrip("-").isdigit() else v


if __name__ == "__main__":
    store = Store(os.environ["CHIPXRAY_CHIP"], stripped=os.environ.get("CHIPXRAY_STRIPPED") == "1")
    tool = sys.argv[1] if len(sys.argv) > 1 else ""
    args = dict(a.split("=", 1) for a in sys.argv[2:] if "=" in a)
    print(json.dumps(dispatch(store, tool, {k: _value(v) for k, v in args.items()})))
```

- [ ] **Step 4: Run** tests → `ok`.

---

### Task 8: External agent CLI backend

**Files:** Create `chipxray/cli_backend.py`, `tests/fake_agent_cli.py`, `tests/test_cli_backend.py`; modify `.gitignore` (add `*.local.json`).

**Interfaces:**
- Consumes: `SYSTEM`, `parse_report` (Task 4), `check` (Task 3), `Store` (Tasks 1 and 7).
- Produces: `run_cli(store, template, budget=30, focus=None) -> (report, raw)`; CLI `python -m chipxray.cli_backend <chip> [--strip] [--focus NAME] [--budget N]` that reads the template from the JSON file named by env `CHIPXRAY_AGENT_CLI` and writes `results/agent/<chip>[_stripped]-<model_label>-<stamp>.json`.
- Template JSON: `{"argv": [...], "model_label": str, "result_field": "result"}`. Placeholders in `argv`: `{task}`, `{system_file}`, `{budget}`. Real templates are local files and are never committed (`*.local.json` is git-ignored).
- The CLI runs in a fresh, empty temp directory, so the agent can read nothing but tool output. Env passed: `PYTHONPATH` and `CHIPXRAY_ROOT` = repo root (absolute), `CHIPXRAY_CHIP`, `CHIPXRAY_STRIPPED`.
- `meta` gains `backend: "cli"`, `model: model_label`, `cli_usage` (the CLI's JSON output without the result field).

- [ ] **Step 1: `tests/fake_agent_cli.py`**, a stand-in agent CLI that reads the system file, runs one tool command and answers:

```python
"""Stand-in for an agent CLI in tests: runs one query tool, then prints a JSON answer."""
import json, os, subprocess, sys

system_file, task = sys.argv[1], sys.argv[2]
assert "hardware reverse engineer" in open(system_file, encoding="utf-8").read()
assert os.listdir(".") == [os.path.basename(system_file)], "agent must start in an empty directory"
tool = subprocess.run([sys.executable, "-m", "chipxray.query", "address", "addr=0x60033d5c"],
                      capture_output=True, text=True, check=True).stdout
fn = json.loads(tool)["functions"][0]
answer = {"ranking": [fn], "findings": [{"function": fn, "hypothesis": "capture trigger", "evidence_level": "observed",
          "evidence": [{"kind": "mmio", "ref": "0x60033d5c", "claim": "touches unmapped register"}],
          "counter_evidence": "", "alternatives": [], "validation": ""}]}
print(json.dumps({"result": json.dumps(answer), "num_turns": 2, "usage": {"output_tokens": 10}}))
```

- [ ] **Step 2: Failing test `tests/test_cli_backend.py`**

```python
import os, sys
from chipxray.cli_backend import run_cli
from chipxray.facts import alias_map
from chipxray.query import Store


def test_cli_backend_runs_agent_in_empty_dir_and_checks_report():
    template = {"argv": [sys.executable, os.path.abspath("tests/fake_agent_cli.py"), "{system_file}", "{task}"],
                "model_label": "fake-cli", "result_field": "result"}
    report, raw = run_cli(Store("esp32s3", stripped=True), template, budget=5)
    alias = alias_map("blobs/espressif/esp32s3_librftest.a")["adctrig"]
    assert report["ranking"] == [alias] and report["checked"]["supported"] == 1
    assert report["meta"]["backend"] == "cli" and report["meta"]["model"] == "fake-cli"
    assert report["meta"]["cli_usage"]["num_turns"] == 2


if __name__ == "__main__":
    test_cli_backend_runs_agent_in_empty_dir_and_checks_report(); print("ok")
```

- [ ] **Step 3: Run** `PYTHONPATH=. python tests/test_cli_backend.py` → `ModuleNotFoundError: chipxray.cli_backend`.

- [ ] **Step 4: Implement `chipxray/cli_backend.py`**

```python
"""Run the investigation through an external agent CLI instead of a chat API.

The CLI gets a system prompt file, the task text, a turn budget, an EMPTY working directory,
and one tool: the shell command `python -m chipxray.query <tool> key=value ...`.
Template: JSON file named by env CHIPXRAY_AGENT_CLI (keep it local; *.local.json is git-ignored).

Usage: python -m chipxray.cli_backend esp32c5 [--strip] [--focus NAME] [--budget 30]
"""
import json, os, re, subprocess, sys, tempfile, time
from pathlib import Path
from chipxray.evidence import check
from chipxray.query import Store

CLI_TOOLS = """Use the tools by running ONE shell command per call:
  python -m chipxray.query candidates top=20
  python -m chipxray.query function name=<function>
  python -m chipxray.query address addr=0x60033d5c
  python -m chipxray.query search pattern=<regex>
  python -m chipxray.query callers_of name=<function>
Each prints JSON facts from the binary. No other command or file is available.
"""


def run_cli(store, template, budget=30, focus=None):
    from chipxray.agent import SYSTEM, parse_report
    system = SYSTEM.replace("Use the tools.", CLI_TOOLS, 1)
    task = f"Investigate the {store.chip} radio test library. Find undocumented hardware capabilities."
    if focus:
        task += f" Start with function {focus}."
    root = str(Path(".").resolve())
    env = dict(os.environ, PYTHONPATH=root, CHIPXRAY_ROOT=root, CHIPXRAY_CHIP=store.chip,
               CHIPXRAY_STRIPPED="1" if store.stripped else "0")
    field = template.get("result_field", "result")
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="chipxray_agent_") as work:
        system_file = os.path.join(work, "system.txt")
        Path(system_file).write_text(system, encoding="utf-8")
        argv = [a.format(task=task, system_file=system_file, budget=budget) for a in template["argv"]]
        proc = subprocess.run(argv, cwd=work, env=env, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"agent CLI failed ({proc.returncode}): {proc.stderr[-800:]}")
    raw = json.loads(proc.stdout)
    report = parse_report(str(raw.get(field, "")))
    parse_failed = report is None
    report = report or {"ranking": [], "findings": []}
    report["checked"] = check(report, store)
    report["meta"] = {"chip": store.chip, "stripped": store.stripped, "backend": "cli", "model": template["model_label"],
                      "budget": budget, "focus": focus, "parse_failed": parse_failed,
                      "seconds": round(time.time() - t0, 1), "cli_usage": {k: v for k, v in raw.items() if k != field}}
    return report, raw


if __name__ == "__main__":
    args = sys.argv[1:]
    chip, strip = args[0], "--strip" in args
    focus = args[args.index("--focus") + 1] if "--focus" in args else None
    budget = int(args[args.index("--budget") + 1]) if "--budget" in args else 30
    template = json.loads(Path(os.environ["CHIPXRAY_AGENT_CLI"]).read_text(encoding="utf-8"))
    report, raw = run_cli(Store(chip, stripped=strip), template, budget=budget, focus=focus)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    label = re.sub(r"[^A-Za-z0-9._-]", "_", template["model_label"])
    out = Path("results/agent") / f"{chip}{'_stripped' if strip else ''}-{label}-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(out, "ranking:", report["ranking"][:10], "supported:", report["checked"]["supported"], "/", report["checked"]["claims"])
```

- [ ] **Step 5: Run** tests → `ok`.

## Done when
1. All 9 test files print `ok` locally and in CI (no network, no key).
2. The agent and one-shot CLIs produce checked reports on a real model.
3. Every reported claim has a support verdict from `evidence.check`.
