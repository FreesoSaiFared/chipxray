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
