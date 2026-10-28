import json
from pathlib import Path
from chipxray.agent import output_paths, parse_report, run
from chipxray.llm import ScriptedLLM
from chipxray.query import Store

S = Store("esp32s3")
FINAL = {"ranking": ["adctrig"], "findings": [{"function": "adctrig", "hypothesis": "sample capture trigger",
         "evidence_level": "correlated", "evidence": [{"kind": "mmio", "ref": "0x60033d5c", "claim": "writes unmapped register"}],
         "counter_evidence": "none", "alternatives": ["calibration"], "validation": "run on hardware"}]}


def _call(i, name, args):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_report_paths_preserve_model_dots_and_timestamp():
    base = Path('results/agent/esp32c5-openai_gpt-4.1-mini-20261028T004437Z')
    report, transcript = output_paths(base)
    assert report.name == base.name + '.json'
    assert transcript.name == base.name + '.transcript.json'


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


def test_tool_calls_after_budget_get_error_replies_and_loop_ends():
    llm = ScriptedLLM([_call(i, "candidates", {"top": 3}) for i in range(12)])
    report, transcript = run(S, llm, budget=2)
    assert report["meta"]["tool_calls"] == 2 and report["meta"]["parse_failed"] is True
    ids = [tc["id"] for m in transcript if m.get("tool_calls") for tc in m["tool_calls"]]
    answered = [m["tool_call_id"] for m in transcript if m["role"] == "tool"]
    assert ids == answered and any("budget used up" in m["content"] for m in transcript if m["role"] == "tool")


if __name__ == "__main__":
    test_report_paths_preserve_model_dots_and_timestamp()
    test_parse_report_accepts_fenced_json(); test_run_executes_tools_then_returns_checked_report()
    test_budget_exhaustion_forces_final_answer(); test_unparseable_final_gives_empty_report()
    test_tool_calls_after_budget_get_error_replies_and_loop_ends(); print("ok")
