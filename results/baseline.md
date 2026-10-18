# Phase 1 result: rules-only baseline on 5 chips

The rules-only scorer ranks `adctrig` 2nd on esp32c5 and esp32c61, but 28th to 30th on esp32, esp32s3 and esp32c3.

## Result table

| chip | functions | adctrig rank | adctrig score | neg. controls present | neg. controls ranked above adctrig |
|---|---|---|---|---|---|
| esp32 | 289 | 30 | 9 | 11 | 0 |
| esp32s3 | 203 | 28 | 9 | 11 | 0 |
| esp32c3 | 218 | 29 | 15 | 11 | 0 |
| esp32c5 | 286 | 2 | 51 | 11 | 0 |
| esp32c61 | 252 | 2 | 51 | 11 | 0 |

Rank is a competition rank: `rank = number of functions with score >= this score`. Ties share a rank.
All 11 negative controls score 0 on every chip. The "ranked above" column counts only strictly higher ranks.

## adctrig MMIO addresses and class

Class comes from `classify` in `chipxray/svd.py`. "unmapped" means no documented peripheral covers the address in that chip's SVD.

| chip | MMIO addresses (class) |
|---|---|
| esp32 | 0x3ff5c02c (unmapped), 0x60033d90 (unmapped), 0x60033d94 (unmapped) |
| esp32s3 | 0x6001c02c (unmapped), 0x60033d5c (unmapped), 0x60033d60 (unmapped), 0x600c101c (documented: SENSITIVE.INTERNAL_SRAM_USAGE_3) |
| esp32c3 | 0x6001c000 (unmapped), 0x6001c02c (unmapped), 0x60033d5c (unmapped), 0x60033d60 (unmapped), 0x60034000 (unmapped), 0x600c1000 (documented: SENSITIVE.ROM_TABLE_LOCK), 0x600c1020 (documented: SENSITIVE.INTERNAL_SRAM_USAGE_3) |
| esp32c5 | 0x60095000 (documented: HP_SYSTEM.EXTERNAL_DEVICE_ENCRYPT_DECRYPT_CONTROL), 0x60095004 (documented: HP_SYSTEM.SRAM_USAGE_CONF), and 17 unmapped addresses in 0x600a0800–0x600ae000 |
| esp32c61 | Same 19 addresses as esp32c5 (2 documented, 17 unmapped) |

## Method

1. `chipxray.facts` lists each function and the MMIO addresses it loads.
2. `classify` labels each address as documented, undocumented offset, or unmapped.
3. The scorer adds 3 points per unmapped address, 2 per undocumented offset, and 0 per documented address.
4. Functions sort by score. The rank is written to `results/<chip>_librftest_baseline.csv`.

## ESP32 address check (Step 3)

The ESP32 hits do not match the aliasing hypothesis in the brief.

- Of 554 MMIO hits in `facts/esp32_librftest.json`, 284 (51%) are unmapped.
- 207 hits (37%) fall in 0x6000_0000–0x6003_FFFF. The rest of the non-zero hits fall in the 0x3FFx_xxxx range (347 hits, 63%, counting both mapped and unmapped).
- The hypothesis needed "most" hits in 0x6000_0000–0x6003_FFFF. That is not the case.
- The low esp32 rank is therefore not explained by the 0x6000 alias alone. Many hits are in 0x3FFx_xxxx gaps that the ESP32 SVD does not cover. This is written as a known limitation. The scorer was not changed.

## Known limitations

- Linear sweep: the scorer reads instructions in order. It does not follow control flow. A call does not clear registers.
- Literal pools placed in the middle of a function are missed on Xtensa.
- `lui` bases are counted even when the code never dereferences them.
- The radio and PHY register space is undocumented in the SVD. Many radio functions score high.
- Scores add up across addresses. Large functions with many addresses rank high.
- ESP32 address check (Step 3): 51% of ESP32 hits are unmapped, and many are in 0x3FFx_xxxx gaps. Low esp32 ranks may come from SVD coverage gaps, not only from the rule weights. Not tuned in this phase.
- The esp32c5 and esp32c61 `adctrig` address lists are identical. This was not checked further.

## Next step

Phase 2, as set out in the project plans. Compare its results with this rules-only baseline on the same five chips.

# Phase 2: call-graph-inclusive score

The inclusive score adds the own score of every function reachable within 3 calls. It uses the same weights as Phase 1. The own rank is unchanged. Source: `results/<chip>_librftest_baseline.csv`.

## Result table

| chip | functions | adctrig own rank | adctrig inclusive rank | neg. controls with inclusive score > 0 | neg. controls with inclusive rank above adctrig |
|---|---|---|---|---|---|
| esp32 | 289 | 30 | 58 | 5 of 11 | 3 |
| esp32s3 | 203 | 28 | 23 | 6 of 11 | 2 |
| esp32c3 | 218 | 29 | 27 | 6 of 11 | 2 |
| esp32c5 | 286 | 2 | 19 | 3 of 11 | 1 |
| esp32c61 | 252 | 2 | 29 | 4 of 11 | 1 |

Negative controls that outrank adctrig in Phase 2: `esp_phy_rftest_init` on all five chips, `esp_phy_wifi_rx` on esp32, esp32s3 and esp32c3, and `esp_phy_wifi_tx` on esp32.

## Did inclusive scoring help?

On this data, inclusive scoring hurt adctrig on three chips and helped on two. On esp32 its rank fell from 30 to 58. On esp32c5 it fell from 2 to 19, and on esp32c61 from 2 to 29. On esp32s3 it rose from 28 to 23, and on esp32c3 from 29 to 27. Those two gains are small, and adctrig stays outside the top 20 on both chips. The negative controls now score above zero, as expected. But 1 to 3 of them per chip now rank above adctrig, where Phase 1 had none. The main cause is `esp_phy_rftest_init`, which has a high inclusive score (45 to 135). It ranks above adctrig on every chip. Why it scores high was not checked. So the inclusive score does not fix the ranking. On the two chips where adctrig already ranked 2nd, it made the result worse.
