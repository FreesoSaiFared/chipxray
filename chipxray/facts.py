"""Extract functions + call edges from a static library (.a of ELF32 LE objects), stdlib only.

Usage: python -m chipxray.facts blobs/espressif/esp32s3_librftest.a [--strip]
Writes facts/<name>.json. --strip renames local functions to fn_N (hard-mode benchmark).
"""
import hashlib, json, struct, sys
from pathlib import Path


def ar_members(data):
    assert data[:8] == b"!<arch>\n", "not an ar archive"
    off, longnames = 8, b""
    while off + 60 <= len(data):
        hdr = data[off:off + 60]
        name, size = hdr[:16].decode().strip(), int(hdr[48:58])
        body = data[off + 60:off + 60 + size]
        off += 60 + size + (size & 1)
        if name == "//":
            longnames = body
        elif name in ("/", "/SYM64/"):
            continue  # archive symbol index
        else:
            if name.startswith("/") and name[1:].isdigit():
                i = int(name[1:])
                name = longnames[i:longnames.index(b"\n", i)].decode()
            yield name.rstrip("/"), body


PERIPH = [(0x3FF00000, 0x3FF80000), (0x60000000, 0x60100000)]
# ponytail: one window list for every chip; split per chip if a target maps peripherals elsewhere


def is_periph(a):
    return any(lo <= a < hi for lo, hi in PERIPH)


def xtensa_consts(sec, start, entry):
    # -mtext-section-literals: the literal pool sits between `start` (end of previous function) and the entry
    # ponytail: ignores pools the assembler places mid-function in very long functions
    return list(struct.unpack_from(f"<{max(0, (entry - start) // 4)}I", sec, start))


def riscv_consts(code):
    # Linear sweep: track lui bases, resolve the next addi/load/store off that base.
    # ponytail: no control flow; compressed ops other than c.lui/c.lw/c.sw don't clobber tracked regs
    reg, out, i = {}, [], 0
    sext = lambda v, bits: v - (1 << bits) if v & (1 << (bits - 1)) else v
    while i + 2 <= len(code):
        h = code[i] | code[i + 1] << 8
        if h & 3 != 3:
            i += 2
            q, f3 = h & 3, h >> 13
            rd5 = (h >> 7) & 0x1F
            if q == 1 and f3 == 3 and rd5 not in (0, 2):  # c.lui
                imm = sext(((h >> 2) & 0x1F) | ((h >> 12) & 1) << 5, 6)
                reg[rd5] = (imm << 12) & 0xFFFFFFFF
                out.append(reg[rd5])
            elif q == 1 and f3 == 0 and rd5 in reg:  # c.addi
                imm = sext(((h >> 2) & 0x1F) | ((h >> 12) & 1) << 5, 6)
                reg[rd5] = (reg[rd5] + imm) & 0xFFFFFFFF
                out.append(reg[rd5])
            elif q == 1 and f3 == 2:  # c.li
                reg.pop(rd5, None)
            elif q == 1 and f3 == 4:  # c.srli/srai/andi/sub/xor/or/and
                reg.pop(((h >> 7) & 7) + 8, None)
            elif q == 2 and f3 in (0, 2):  # c.slli, c.lwsp
                reg.pop(rd5, None)
            elif q == 2 and f3 == 4:  # c.jr/c.mv/c.add (rs2 != 0 writes rd)
                if (h >> 2) & 0x1F:
                    reg.pop(rd5, None)
            elif q == 0 and f3 == 0:  # c.addi4spn
                reg.pop(((h >> 2) & 7) + 8, None)
            elif q == 0 and f3 in (2, 6):  # c.lw / c.sw
                rs1 = ((h >> 7) & 7) + 8
                off = ((h >> 10) & 7) << 3 | ((h >> 6) & 1) << 2 | ((h >> 5) & 1) << 6
                if rs1 in reg:
                    out.append((reg[rs1] + off) & 0xFFFFFFFF)
                if f3 == 2:
                    reg.pop(((h >> 2) & 7) + 8, None)
            continue
        if i + 4 > len(code):
            break
        w = struct.unpack_from("<I", code, i)[0]
        i += 4
        op, rd, rs1, f3 = w & 0x7F, (w >> 7) & 0x1F, (w >> 15) & 0x1F, (w >> 12) & 7
        if op == 0x37:  # lui
            reg[rd] = w & 0xFFFFF000
            out.append(reg[rd])
        elif op in (0x03, 0x23) and rs1 in reg:  # load / store
            imm = (w >> 20) if op == 0x03 else ((w >> 25) << 5) | ((w >> 7) & 0x1F)
            out.append((reg[rs1] + sext(imm, 12)) & 0xFFFFFFFF)
            if op == 0x03:
                reg.pop(rd, None)
        elif op == 0x13 and f3 == 0 and rs1 in reg:  # addi
            reg[rd] = (reg[rs1] + sext(w >> 20, 12)) & 0xFFFFFFFF
            out.append(reg[rd])
        elif rd and op not in (0x23, 0x63):  # anything else that writes rd clobbers it
            reg.pop(rd, None)
    return out


def elf_facts(obj):
    assert obj[:4] == b"\x7fELF" and obj[4] == 1 and obj[5] == 1, "need ELF32 little-endian"
    machine = struct.unpack_from("<H", obj, 18)[0]
    shoff, = struct.unpack_from("<I", obj, 32)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", obj, 46)
    secs = [struct.unpack_from("<IIIIIIIIII", obj, shoff + i * shentsize) for i in range(shnum)]
    # (name, type, flags, addr, offset, size, link, info, align, entsize)
    cstr = lambda tab, i: obj[tab + i:obj.index(b"\0", tab + i)].decode()
    secname = [cstr(secs[shstrndx][4], s[0]) for s in secs]

    symtab_i = next((i for i, s in enumerate(secs) if s[1] == 2), None)  # SHT_SYMTAB
    if symtab_i is None:
        return machine, [], set()  # empty/data-only object
    st = secs[symtab_i]
    syms = []
    for k in range(st[5] // 16):
        name, value, size, info, _, shndx = struct.unpack_from("<IIIBBH", obj, st[4] + k * 16)
        syms.append(dict(name=cstr(secs[st[6]][4], name), value=value, size=size,
                         type=info & 0xF, bind=info >> 4, shndx=shndx))

    funcs = [s for s in syms if s["type"] == 2 and s["shndx"] not in (0, 0xFFF1)]  # STT_FUNC, defined

    def owner(shndx, off):
        best = None
        for f in funcs:
            if f["shndx"] == shndx and f["value"] <= off < f["value"] + max(f["size"], 1):
                best = f
        return best

    edges = set()
    for s in secs:
        if s[1] != 4 or s[6] != symtab_i:  # SHT_RELA against our symtab
            continue
        target = s[7]
        if not secs[target][2] & 4:  # SHF_EXECINSTR: only references made from code
            continue
        for k in range(s[5] // 12):
            r_off, r_info, _ = struct.unpack_from("<IIi", obj, s[4] + k * 12)
            ref = syms[r_info >> 8]
            src = owner(target, r_off)
            if not src or not ref["name"] or ref["name"] == src["name"]:
                continue
            if ref["type"] == 3 or ref["name"].startswith(".L"):  # section syms, compiler-local labels
                continue
            edges.add((src["name"], ref["name"]))

    def mmio(f):
        s = secs[f["shndx"]]
        if s[1] == 8:  # SHT_NOBITS has no bytes
            return []
        data = obj[s[4]:s[4] + s[5]]
        if machine == 94:  # Xtensa
            prev = [g["value"] + g["size"] for g in funcs
                    if g["shndx"] == f["shndx"] and g["value"] < f["value"]]
            start = (max(prev, default=0) + 3) // 4 * 4
            consts = xtensa_consts(data, start, f["value"])
        elif machine == 243:  # RISC-V
            consts = riscv_consts(data[f["value"]:f["value"] + f["size"]])
        else:
            consts = []
        return sorted({f"0x{c:08x}" for c in consts if is_periph(c)})

    return machine, [dict(name=f["name"], size=f["size"], section=secname[f["shndx"]],
                          exported=f["bind"] == 1, mmio=mmio(f)) for f in funcs], edges


def alias_map(path):
    """Hard-mode names: every defined function -> fn_N, sorted by name. Shared by facts and decompile."""
    data = Path(path).read_bytes()
    defined = {f["name"] for _, body in ar_members(data) if body[:4] == b"\x7fELF"
               for f in elf_facts(body)[1]}
    return {n: f"fn_{i}" for i, n in enumerate(sorted(defined))}


def extract(path, strip=False):
    data = Path(path).read_bytes()
    out = dict(source=str(path), sha256=hashlib.sha256(data).hexdigest(), objects=[])
    for name, body in ar_members(data):
        if body[:4] != b"\x7fELF":
            continue
        machine, funcs, edges = elf_facts(body)
        out["objects"].append(dict(name=name, machine=machine, functions=funcs,
                                   calls=sorted(edges)))
    if strip:
        alias = alias_map(path)
        # ponytail: renames every defined symbol, incl. exported ones; real stripping keeps exports. Revisit for hard-mode fairness.
        for o in out["objects"]:
            for f in o["functions"]:
                f["name"] = alias[f["name"]]
                f["section"] = ".".join(alias.get(p, p) for p in f["section"].split("."))
            o["calls"] = [[alias.get(a, a), alias.get(b, b)] for a, b in o["calls"]]
    return out


if __name__ == "__main__":
    src = Path(sys.argv[1])
    strip = "--strip" in sys.argv
    facts = extract(src, strip)
    dst = Path("facts") / (src.stem + ("_stripped" if strip else "") + ".json")
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(json.dumps(facts, indent=1))
    n_f = sum(len(o["functions"]) for o in facts["objects"])
    n_e = sum(len(o["calls"]) for o in facts["objects"])
    print(f"{dst}: {len(facts['objects'])} objects, {n_f} functions, {n_e} call/ref edges")
