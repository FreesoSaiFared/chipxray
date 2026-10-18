"""Read-only fact store for one chip, and the tools the agent may call."""
import gzip, json, os, re, sys
from collections import defaultdict
from chipxray.baseline import rank
from chipxray.svd import classify, load_svd

MAX_C = 4000


class Store:
    def __init__(self, chip, stripped=False, root=None):
        self.chip, self.stripped = chip, stripped
        root = root or os.environ.get("CHIPXRAY_ROOT", ".")
        tag = f"{chip}_librftest" + ("_stripped" if stripped else "")
        with open(f"{root}/facts/{tag}.json", encoding="utf-8") as fh:
            self.facts = json.load(fh)
        with gzip.open(f"{root}/facts/decomp/{tag}.json.gz", "rt", encoding="utf-8") as fh:
            dec = json.load(fh)
        self.periphs = load_svd(f"{root}/blobs/svd/{chip}.svd")
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
        limit = max(1, min(int(limit), 50))
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


def _value(v):
    return int(v) if v.lstrip("-").isdigit() else v


if __name__ == "__main__":
    root = os.environ.get("CHIPXRAY_ROOT", ".")
    mode_file = os.path.join(root, "mode.json")
    if os.path.exists(mode_file):  # sandboxed run: mode is fixed by the runner, env cannot override it
        with open(mode_file, encoding="utf-8") as fh:
            mode = json.load(fh)
        chip, stripped = mode["chip"], mode["stripped"]
    else:
        chip, stripped = os.environ["CHIPXRAY_CHIP"], os.environ.get("CHIPXRAY_STRIPPED") == "1"
    store = Store(chip, stripped=stripped)
    tool = sys.argv[1] if len(sys.argv) > 1 else ""
    args = dict(a.split("=", 1) for a in sys.argv[2:] if "=" in a)
    print(json.dumps(dispatch(store, tool, {k: _value(v) for k, v in args.items()})))
