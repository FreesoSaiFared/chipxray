from chipxray.svd import load_svd, classify

P = load_svd("blobs/svd/esp32s3.svd")


def test_documented():
    assert classify(0x600C101C, P) == ("documented", "SENSITIVE.INTERNAL_SRAM_USAGE_3")


def test_unmapped():
    assert classify(0x60033D5C, P)[0] == "unmapped"


def test_dim_registers_expanded():
    # every peripheral with registers must expose offsets; a dim array must yield >1 offset
    assert sum(len(r) for _, _, _, r in P) > 1000


def test_derived_peripheral_has_registers():
    uart = {n: r for n, _, _, r in P}
    assert uart["UART1"] and len(uart["UART1"]) == len(uart["UART0"])


def test_overlap_prefers_documented():
    p3 = load_svd("blobs/svd/esp32c3.svd")
    name, base, size, regs = next(p for p in p3 if p[0] == "HMAC")
    off = min(regs)
    assert classify(base + off, p3) == ("documented", f"HMAC.{regs[off]}")


def test_register_beyond_address_block():
    name, base, size, regs = next(p for p in P if p[0] == "APB_CTRL")
    assert 0x3FC in regs
    assert classify(base + 0x3FC, P)[0] == "documented"


def test_unaligned_byte_inside_register():
    assert classify(0x600C101D, P) == ("documented", "SENSITIVE.INTERNAL_SRAM_USAGE_3")


if __name__ == "__main__":
    test_documented(); test_unmapped(); test_dim_registers_expanded(); test_derived_peripheral_has_registers()
    test_overlap_prefers_documented(); test_register_beyond_address_block(); test_unaligned_byte_inside_register(); print("ok")
