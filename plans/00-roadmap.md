The 5-week roadmap for ChipXray; each phase gets its own detailed plan file when it starts.

# ChipXray Roadmap

**Goal:** Show, with numbers, whether an evidence-driven agent finds an undocumented hardware capability (ESP32 raw-I/Q capture via `adctrig`) better than rules alone or a single LLM prompt.

| Phase | Plan file | Output | Status |
|---|---|---|---|
| 0. Setup | — | Ghidra + JDK on F:, 5 `librftest.a` blobs, `facts.py`, decompile script | done 2026-10-18 |
| 1. Rules-only baseline | `01-baseline.md` | MMIO constants per function, SVD register maps, ranked CSV per chip, first result table | next |
| 2. Decompiled-code facts | `02-decompile-facts.md` | Ghidra export (C + MMIO accesses) for top-N functions into `facts/` | after 1 |
| 3. Evidence-driven agent | `03-agent.md` | Agent that queries facts, writes findings at 4 evidence levels with counter-evidence | after 2 |
| 4. Benchmark | `04-benchmark.md` | rules vs single-shot LLM vs agent × names intact vs stripped; negative controls; contamination log | after 3 |
| 5. Transfer + write-up | `05-writeup.md` | Run on a sibling chip, README with results, demo, limitations | after 4 |

## Fixed decisions
- Ground truth: `adctrig` in Espressif `librftest.a`, validated by https://espargos.net/espsdr/.
- Negative controls: the documented RF-test API in ESP-IDF `esp_phy_cert_test.h` (`esp_phy_wifi_tx`, `esp_phy_ble_rx`, ...).
- Evidence levels: observed → correlated → inferred → validated.
- Hard mode: no names, no `wiki/`, no write-ups reach the system under test.
- Writing style: ~80% ASD-STE100.

## Exit criteria for the whole project
1. One command reproduces every number in `results/`.
2. The README states what the system cannot prove.
3. At least one honest negative result is published.
