`adctrig` in Espressif `librftest.a` is the entry point ESPARGOS reverse engineered to unlock raw I/Q capture (ground truth for the benchmark).

## Facts
| Fact | Level | Source |
|---|---|---|
| ESPARGOS started from `adctrig` in `librftest`, reverse engineered "with the help of LLMs"; debug registers configure the modem's sample-dump engine | validated (external) | https://espargos.net/espsdr/ |
| `librftest.a` is public for esp32, s3, c3, c5, c61 | observed | espressif/esp-phy-lib @ 20f1db05 |
| `adctrig` is defined in `mac_common.o` on all 5 chips | observed | facts/*_librftest.json |
| No function inside librftest calls `adctrig` (external entry point, likely RF test console) | observed | facts/*_librftest.json |
| s3: `adctrig` → `tx_a_frame`, `ets_delay_us`, `phy_printf` | observed | facts/esp32s3_librftest.json |
| c5: `adctrig` → `phy_pbus_force_test`, `phy_pbus_xpd_rx_off`, `phy_disable_cca`, `trig_tx_frame`, … | observed | facts/esp32c5_librftest.json |
| s3: Ghidra decompiles `adctrig` @ 0x00010b00 (9 params). It does read-modify-write on ~4 registers via literal-pool pointers (`DAT_00010a94`, `DAT_00010a9c`, `DAT_00010aa0`) with fixed masks; packs params into one register (`p1 + p3<<20 + p2<<28 + (p5&1)<<17 + 1`); branches on `param_6` (1, 3, 4, 5) | observed | work/ghidra_run.log |
| Actual register addresses behind those `DAT_` pointers | unknown | task 02: read the literal pool values |
| Phase 1 rules-only baseline: `adctrig` ranks 30 of 289 on esp32 (score 9), 28 of 203 on esp32s3 (score 9), 29 of 218 on esp32c3 (score 15), 2 of 286 on esp32c5 (score 51), 2 of 252 on esp32c61 (score 51) | observed | results/*_librftest_baseline.csv, results/baseline.md |
| esp32 `adctrig` MMIO: 0x3ff5c02c, 0x60033d90, 0x60033d94. All three are unmapped in the esp32 SVD | observed | facts/esp32_librftest.json, blobs/svd/esp32.svd |
| esp32s3 `adctrig` MMIO: 0x6001c02c, 0x60033d5c, 0x60033d60 (unmapped); 0x600c101c (documented: SENSITIVE.INTERNAL_SRAM_USAGE_3) | observed | facts/esp32s3_librftest.json, blobs/svd/esp32s3.svd |
| esp32c3 `adctrig` MMIO: 0x6001c000, 0x6001c02c, 0x60033d5c, 0x60033d60, 0x60034000 (unmapped); 0x600c1000 (documented: SENSITIVE.ROM_TABLE_LOCK); 0x600c1020 (documented: SENSITIVE.INTERNAL_SRAM_USAGE_3) | observed | facts/esp32c3_librftest.json, blobs/svd/esp32c3.svd |
| esp32c5 `adctrig` MMIO: 19 addresses. 0x60095000 and 0x60095004 are documented (HP_SYSTEM). The other 17 are unmapped, all in 0x600a0800–0x600ae000 | observed | facts/esp32c5_librftest.json, blobs/svd/esp32c5.svd |
| esp32c61 `adctrig` MMIO: same 19 addresses as esp32c5 (2 documented, 17 unmapped) | observed | facts/esp32c61_librftest.json, blobs/svd/esp32c61.svd |
