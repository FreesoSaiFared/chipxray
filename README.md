# ChipXray

Evidence-driven discovery of undocumented hardware capabilities in vendor firmware blobs.

Ground-truth case: the ESP32 raw-I/Q capture path found via `adctrig` in Espressif's `librftest`
([ESPARGOS write-up](https://espargos.net/espsdr/)).

## Inputs (pinned)
`blobs/espressif/<chip>_librftest.a` from [espressif/esp-phy-lib](https://github.com/espressif/esp-phy-lib)
@ `20f1db053a0e6cb9f1c09d255c43bf42483041d0`. SHA-256 of each blob is recorded in `facts/*.json`.

Phase 1 result: [results/baseline.md](results/baseline.md). The rules-only scorer ranks `adctrig` 2nd on esp32c5 and esp32c61, but 28th to 30th on esp32, esp32s3 and esp32c3.

## Run
```
bash fetch_inputs.sh                                                        # fetch pinned blobs
python -m chipxray.facts blobs/espressif/esp32s3_librftest.a           # normal mode
python -m chipxray.facts blobs/espressif/esp32s3_librftest.a --strip   # hard mode (names hidden)
python tests/test_facts.py
```

## Benchmark protocol
- Systems: rules-only / single-shot LLM / evidence-driven agent.
- Conditions: symbols intact vs stripped; log model name + training cutoff (contamination check).
- Negative controls: documented calibration routines must not be reported as hidden.
- Evidence levels: observed → correlated → inferred → validated.

Tools (Ghidra, JDK) live in `../tools/`, not on C:.
