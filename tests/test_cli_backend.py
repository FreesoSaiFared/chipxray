import os, sys
from pathlib import Path
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


def test_sandbox_blocks_mode_override():
    import json, subprocess, tempfile
    from chipxray.cli_backend import make_sandbox
    with tempfile.TemporaryDirectory() as d:
        make_sandbox(Store("esp32s3", stripped=True), d)
        env = dict(os.environ, PYTHONPATH=os.path.abspath("."), CHIPXRAY_ROOT=d,
                   CHIPXRAY_CHIP="esp32s3", CHIPXRAY_STRIPPED="0")  # agent tries to switch hard mode off
        out = subprocess.run([sys.executable, "-m", "chipxray.query", "function", "name=adctrig"],
                             capture_output=True, text=True, env=env, cwd=d).stdout
        assert "error" in json.loads(out)
        assert not any("stripped" not in p.name and p.suffix in (".json", ".gz")
                       for p in Path(d, "facts").rglob("*"))


if __name__ == "__main__":
    test_cli_backend_runs_agent_in_empty_dir_and_checks_report(); test_sandbox_blocks_mode_override(); print("ok")
