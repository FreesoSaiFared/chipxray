"""One-prompt comparison system: top candidates' facts in a single prompt, no tools, same report format.

Usage: python -m chipxray.oneshot esp32c5 [--strip] [--top 15]
"""
import json, re, sys, time
from pathlib import Path
from chipxray.evidence import check
from chipxray.query import MAX_C, Store


def build_prompt(store, top=15, max_c=None):
    if max_c is None:
        max_c = MAX_C
    parts = [f"Library: {store.chip} radio test library. Facts for the top {top} candidate functions follow."]
    for c in store.candidates(top=top)["candidates"]:
        f = store.function(c["name"])
        f["c"] = f["c"][:max_c]
        parts.append(json.dumps(f))
    parts.append("Rank these functions and report findings using the JSON format from the rules.")
    return "\n\n".join(parts)


def run(store, llm, top=15):
    from chipxray.agent import FORMAT, HEAD, RULES, parse_report
    system = HEAD + RULES + FORMAT
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
