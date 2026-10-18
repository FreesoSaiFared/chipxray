The 5-week roadmap for ChipXray; each phase gets its own detailed plan file when it starts.

# ChipXray Roadmap

**Goal:** Show, with numbers, whether an evidence-driven agent finds an undocumented hardware capability (ESP32 raw-I/Q capture via `adctrig`) better than rules alone or a single LLM prompt.

| Phase | Plan file | Output | Status |
|---|---|---|---|
| 0. Setup | — | Ghidra + JDK on F:, 5 `librftest.a` blobs, `facts.py`, decompile script | done 2026-10-18 |
| 1. Rules-only baseline | `01-baseline.md` | MMIO constants per function, SVD register maps, ranked CSV per chip, first result table | done 2026-10-18 |
| 2. Better facts | `02-facts.md` | leak-free hard mode, call-graph-inclusive score, Ghidra C for every function | done 2026-10-18 |
| 3. Evidence-driven agent | `03-agent.md` | tools, agent loop, one-prompt system, evidence checker, external agent CLI backend (sandboxed) | done 2026-10-18 |
| 4. Benchmark + hunt | `04-benchmark.md` | pre-registered protocol (below); hunt `fft_dump_init` on ESP32-C5 | next |
| 5. Launch | `05-launch.md` | findings table, social preview, demo GIF, posts; community issues | after 4 |

## Phase 3 pilot result (2026-10-18, one run per mode, ESP32-S3)
- The agent did not rank `adctrig` in its top 10, in normal or hard mode. It stopped after 22-26 turns, mostly inside the top-ranked candidates.
- Hard mode: 14 of 14 claims supported by the facts. Normal mode: 8 of 14.
- It flagged other hidden-looking features (forced TX/RX modes, a PHY debug path, single-carrier TX). Some are documented in Espressif's RF-test API, so they are false positives.

## Phase 4 protocol (fixed BEFORE any Phase 4 run)
Only one ground truth exists, so tuning the agent until it finds `adctrig` would be overfitting. Rules:
1. Strategy changes are general and written here first. Allowed: a larger turn budget; a coverage step that asks the agent to inspect every function touching a register page used by only one or two functions. Not allowed: any wording about sampling, capture, dumps, triggers, or anything else specific to `adctrig`.
2. Conditions: systems {rules, one-prompt, agent} × modes {normal, hard} × chips {esp32s3, esp32c3, esp32c5} × 3 repeats for the model systems.
3. Metrics: `adctrig` in top 10 (yes/no) and its position; supported-claim rate; negative controls (documented RF-test API functions) in the top 10; turns, seconds, tokens.
4. Report every run, including failures. Name the model and its training cutoff.
5. Hunt runs (normal mode, `--focus fft_dump_init` on ESP32-C5) are exploration, not benchmark. They go to `wiki/` at evidence levels.

## Community track (started 2026-10-18)
Discussions on; labels `new chip`, `finding`, `hardware-verified`, `benchmark`; CONTRIBUTING.md; issue templates; starter issues for chips C2, C6, H2, H4, S2, S31.

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
