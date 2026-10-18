"""SVD register maps: which peripheral addresses are documented."""
import xml.etree.ElementTree as ET


def _int(s):
    return int(s, 0)


def _regs(node, base_off, out):
    for r in node.findall("register"):
        off, name, dim = base_off + _int(r.findtext("addressOffset")), r.findtext("name"), r.findtext("dim")
        if dim:
            inc = _int(r.findtext("dimIncrement"))
            for k in range(_int(dim)):
                out[off + k * inc] = name.replace("[%s]", str(k)).replace("%s", str(k))
        else:
            out[off] = name
    for c in node.findall("cluster"):  # ponytail: cluster-level dim not expanded
        _regs(c, base_off + _int(c.findtext("addressOffset")), out)


def load_svd(path):
    raw = {p.findtext("name"): p for p in ET.parse(path).getroot().iter("peripheral")}
    periphs = []
    for name, p in raw.items():
        src = raw.get(p.get("derivedFrom"), p)
        regs = {}
        node = src.find("registers")
        if node is not None:
            _regs(node, 0, regs)
        blocks = p.findall("addressBlock") or src.findall("addressBlock")
        ext = max((_int(b.findtext("offset")) + _int(b.findtext("size")) for b in blocks), default=0)
        size = max(ext, max(regs, default=-4) + 4)  # addressBlock can be smaller than its registers
        periphs.append((name, _int(p.findtext("baseAddress")), size, regs))
    return periphs


def classify(addr, periphs):
    hits = [(name, base, regs) for name, base, size, regs in periphs if base <= addr < base + size]
    for name, base, regs in hits:
        off = (addr - base) & ~3  # registers are <= 32 bits in these SVDs
        if off in regs:
            return "documented", f"{name}.{regs[off]}"
    if hits:
        name, base, _ = hits[0]
        return "undocumented_offset", f"{name}+0x{addr - base:x}"
    return "unmapped", None
