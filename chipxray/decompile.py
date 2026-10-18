"""Decompile every function of a static library with Ghidra headless (one run per library).

Usage: python -m chipxray.decompile blobs/espressif/esp32s3_librftest.a [--strip]
Needs env CHIPXRAY_GHIDRA: path to a .ps1 launcher (Windows) or to analyzeHeadless.
Writes facts/decomp/<stem>[_stripped].json.gz
"""
import gzip, hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path
from chipxray.facts import alias_map, ar_members

STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def launcher():
    g = os.environ["CHIPXRAY_GHIDRA"]
    return ["powershell", "-ExecutionPolicy", "Bypass", "-File", g] if g.endswith(".ps1") else [g]


def redact_strings(c, alias):
    """Inside C string literals, replace whole-word defined names with their fn_N alias."""
    if not alias:
        return c
    word = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, sorted(alias, key=len, reverse=True))) + r")(?![A-Za-z0-9_])")
    return STRING.sub(lambda m: word.sub(lambda w: alias[w.group(1)], m.group(0)), c)


def decompile(src, strip=False):
    src = Path(src).resolve()
    tag = src.stem + ("_stripped" if strip else "")
    work = (Path("work") / tag).resolve()
    shutil.rmtree(work, ignore_errors=True)
    objs, out, proj = work / "objs", work / "out", work / "proj"
    for d in (objs, out, proj):
        d.mkdir(parents=True)
    data = src.read_bytes()
    names = [n for n, body in ar_members(data) if body[:4] == b"\x7fELF"]
    for n, body in ar_members(data):
        if body[:4] == b"\x7fELF":
            (objs / n).write_bytes(body)
    cmd = launcher() + [str(proj), "p", "-import", str(objs), "-scriptPath", str(Path("ghidra_scripts").resolve()),
                        "-postScript", "ExportFunctions.java", str(out), "-deleteProject"]
    if strip:
        tsv = work / "alias.tsv"
        tsv.write_text("".join(f"{k}\t{v}\n" for k, v in alias_map(src).items()), encoding="utf-8")
        cmd += ["-preScript", "StripNames.java", str(tsv)]
    with open(work / "ghidra.log", "w", encoding="utf-8") as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    missing = [n for n in names if not (out / f"{n}.json").exists()]
    if missing:
        raise RuntimeError(f"Ghidra produced no output for {missing}; see {work / 'ghidra.log'}")
    result = dict(source=f"blobs/espressif/{src.name}", sha256=hashlib.sha256(data).hexdigest(), stripped=strip,
                  objects=[dict(name=n, functions=json.loads((out / f"{n}.json").read_text(encoding="utf-8")))
                           for n in names])
    if strip:
        alias = alias_map(src)
        for o in result["objects"]:
            for f in o["functions"]:
                f["c"] = redact_strings(f["c"], alias)
    dst = Path("facts/decomp") / f"{tag}.json.gz"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dst, "wt", encoding="utf-8") as fh:
        json.dump(result, fh)
    return dst, sum(len(o["functions"]) for o in result["objects"])


if __name__ == "__main__":
    dst, n = decompile(sys.argv[1], "--strip" in sys.argv)
    print(f"{dst}: {n} functions")
