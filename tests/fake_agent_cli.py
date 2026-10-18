"""Stand-in for an agent CLI in tests: runs one query tool, then prints a JSON answer."""
import json, os, subprocess, sys
assert "CHIPXRAY_STRIPPED" not in os.environ and "CHIPXRAY_CHIP" not in os.environ

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
