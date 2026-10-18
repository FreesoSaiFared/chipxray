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
