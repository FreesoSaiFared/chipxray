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
