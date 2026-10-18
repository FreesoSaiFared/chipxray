`fft_dump_init` in the ESP32-C5 `librftest.a` looks like a hidden baseband capture path: it arms an undocumented engine, waits for a ready bit, and reads a 256-byte window as I/Q power values. Not verified on hardware.

# ESP32-C5 `fft_dump_init` — hidden capture candidate

## Facts
| Fact | Level | Source |
|---|---|---|
| Rules-only baseline ranks `fft_dump_init` 1st of 286 functions on ESP32-C5 (own score 75) | observed | results/esp32c5_librftest_baseline.csv |
| All 25 hardware addresses it touches are in no documented peripheral (0x600a4000–0x600ae000) | observed | `Store("esp32c5").function("fft_dump_init")`, blobs/svd/esp32c5.svd |
| The window 0x600a5c00–0x600a5d00 is touched by no other function in the library | observed | `Store("esp32c5").address("0x600a5c00")` |
| The code waits on a status bit: `while ((_DAT_ram_600a4c48 & 4) == 0)` | observed | facts/decomp/esp32c5_librftest.json.gz |
| Then it sets a 2-bit control field: `_DAT_ram_600a4c4c = _DAT_ram_600a4c4c \| 0xc;` | observed | same |
| It calls `phy_linear_to_db` and `phy_printf` on each value read from the window | observed | call edges, facts/esp32c5_librftest.json |
| Its only caller is `run_rftest_case`, the RF test-command dispatcher | observed | call edges |
| Arm → wait-for-ready → read buffer → convert to dB is a capture-and-report sequence | correlated | the five facts above |
| It is a spectrum (FFT) or raw I/Q snapshot engine in the baseband | inferred | agent run 2026-10-18 (claude-sonnet-5, normal mode, focus on this function; 6 of 8 claims supported) |

## Other explanations
1. An internal calibration helper (ADC, DC offset or RSSI) that is undocumented only because it is internal.
2. The window may be a RAM buffer the PHY fills, not a live hardware FIFO.

## How to validate (needs an ESP32-C5 board)
1. Reach `fft_dump_init` through the RF test command interface (`run_rftest_case`).
2. Feed a known tone (receive only, from a licensed or ISM-band source).
3. Check that the printed dB values change with the tone's frequency and power.

## Relation to `adctrig`
`adctrig` (the known ESPARGOS path) and `fft_dump_init` live in the same library and are both reached only from the test dispatcher. On ESP32-C5 the rules-only baseline ranks `fft_dump_init` 1st and `adctrig` 2nd.
