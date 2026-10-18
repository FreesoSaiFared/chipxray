from chipxray.facts import extract


def test_s3_adctrig_ground_truth():
    f = extract("blobs/espressif/esp32s3_librftest.a")
    mc = next(o for o in f["objects"] if o["name"] == "mac_common.o")
    assert any(fn["name"] == "adctrig" for fn in mc["functions"])
    assert ["adctrig", "tx_a_frame"] in [list(e) for e in mc["calls"]]
    assert not any(n.startswith(".L") for e in mc["calls"] for n in e)


def test_strip_hides_names():
    f = extract("blobs/espressif/esp32s3_librftest.a", strip=True)
    names = {fn["name"] for o in f["objects"] for fn in o["functions"]}
    assert "adctrig" not in names and all(n.startswith("fn_") for n in names)


from chipxray.facts import riscv_consts


def _fn(chip, name):
    f = extract(f"blobs/espressif/{chip}_librftest.a")
    return next(fn for o in f["objects"] for fn in o["functions"] if fn["name"] == name)


def test_s3_adctrig_mmio():
    mmio = _fn("esp32s3", "adctrig")["mmio"]
    for a in ("0x60033d5c", "0x60033d60", "0x600c101c", "0x6001c02c"):
        assert a in mmio, (a, mmio)
    assert all(0x60000000 <= int(a, 16) < 0x60100000 for a in mmio)


def test_c3_adctrig_mmio():
    mmio = [int(a, 16) for a in _fn("esp32c3", "adctrig")["mmio"]]
    assert any(0x60033000 <= a < 0x60035000 for a in mmio), [hex(a) for a in mmio]
    assert any(0x6001c000 <= a < 0x6001d000 for a in mmio)


def test_riscv_lui_addi_and_load():
    import struct
    lui_a5 = 0x600347B7            # lui a5, 0x60034
    lw_a0 = (0xD5C << 20) | (15 << 15) | (2 << 12) | (10 << 7) | 0x03   # lw a0, -0x2a4(a5)
    code = struct.pack("<II", lui_a5, lw_a0)
    assert 0x60033D5C in riscv_consts(code)


def test_riscv_c_addi_updates_base():
    import struct
    # lui a5,0x60034 ; c.addi a5,8 ; c.lw a0,0(a5)
    code = struct.pack("<IHH", 0x600347B7, 0x07A1, 0x4388)
    assert 0x60034008 in riscv_consts(code)


def test_strip_leaks_no_defined_names():
    import json, re
    from chipxray.facts import alias_map
    path = "blobs/espressif/esp32s3_librftest.a"
    text = json.dumps(extract(path, strip=True))
    leaked = [n for n in alias_map(path)
              if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text)]
    assert leaked == [], leaked[:10]


if __name__ == "__main__":
    test_s3_adctrig_ground_truth(); test_strip_hides_names()
    test_s3_adctrig_mmio(); test_c3_adctrig_mmio(); test_riscv_lui_addi_and_load()
    test_riscv_c_addi_updates_base(); test_strip_leaks_no_defined_names(); print("ok")
