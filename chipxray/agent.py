"""Evidence-driven agent: investigate with tools, then report findings whose claims are checked.

Usage: python -m chipxray.agent esp32c5 [--strip] [--focus NAME] [--budget 30]
Needs CHIPXRAY_LLM_BASE_URL, CHIPXRAY_LLM_MODEL, CHIPXRAY_LLM_API_KEY.
"""
import json, re, sys, time
from pathlib import Path
from chipxray.evidence import check
from chipxray.query import TOOLS, Store, dispatch

MAX_TOOL_CHARS = 6000

HEAD = """You are a hardware reverse engineer. You study one vendor firmware library.
Your goal: find functions that drive UNDOCUMENTED hardware capabilities.
Examples: hidden operating modes, undocumented hardware engines, debug paths.
Ordinary documented features do not count.
"""

TOOLS_TEXT = """
Use the tools. They return facts from the binary:
- candidates: functions ranked by how many undocumented registers they and their callees touch.
- function: one function's registers (documented or unmapped), callers, callees, and decompiled C.
- address: the class of one hardware address and all functions that touch it.
- search: regex over all decompiled C.
- callers_of: who calls a function.
- rare_pages: register pages that only one or two functions touch.
Stay inside your tool budget. Look at the top candidates and at rare_pages first, then follow registers and calls.
"""

RULES = """
Rules:
1. Every evidence item cites ONE fact from the material you were given. Put the fact itself in "ref":
   kind "mmio": ref = one hardware address the function touches, for example "0x60033d5c".
   kind "call": ref = one function name it calls or that calls it, for example "fn_12".
   kind "code": ref = an exact snippet (12 to 80 characters) copied from its decompiled C.
   Put your explanation in "claim", never in "ref". Use several items for several facts.
2. Evidence levels: "observed" = one fact. "correlated" = two or more independent facts agree.
   "inferred" = your interpretation. Never use "validated". Only a hardware test can validate.
3. For each finding, give counter-evidence and at least one other explanation,
   for example ordinary calibration or register initialisation.
4. A function that touches many registers is not automatically interesting.
   Prefer functions that set up undocumented hardware in a deliberate sequence.
5. Function names may be hidden (fn_N). Do not rely on names. Rely on code and registers.
"""

FORMAT = """
When you finish, reply with ONLY one JSON object, no other text:
{"ranking": [up to 10 function names, most likely first],
 "findings": [up to 5 objects: {"function", "hypothesis", "evidence_level",
   "evidence": [{"kind", "ref", "claim"}], "counter_evidence", "alternatives": [..], "validation"}]}
"""

SYSTEM = HEAD + TOOLS_TEXT + RULES + FORMAT


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
    calls, report, nudged, told, t0 = 0, None, False, False, time.time()
    for _ in range(budget + 6):  # hard cap on model turns: a model that never stops cannot loop forever
        msg = llm.chat(messages, TOOLS if calls < budget else None)
        msg = {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
        messages.append(msg)
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:  # every tool_call gets a tool reply, or chat APIs reject the next request
                if calls >= budget:
                    result = json.dumps({"error": "tool budget used up"})
                else:
                    calls += 1
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    result = json.dumps(dispatch(store, tc["function"]["name"], args if isinstance(args, dict) else {}))[:MAX_TOOL_CHARS]
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            if calls >= budget and not told:
                told = True
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
