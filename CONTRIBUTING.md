# Contributing to ChipXray

Thank you for helping. There are three useful ways to contribute. None of them needs special hardware, except the last one.

## 1. Add a chip (good first contribution)

Espressif publishes `librftest.a` for more chips than ChipXray covers. Chips still open: **ESP32-C2, ESP32-C6, ESP32-H2, ESP32-H4, ESP32-S2, ESP32-S31.**

1. Add the chip name to the `for c in ...` list in `fetch_inputs.sh`.
2. Delete `SHA256SUMS`, then run `bash fetch_inputs.sh` twice. The second run must print `inputs OK`.
3. Extract facts in both modes:
   ```bash
   export PYTHONPATH=.
   python -m chipxray.facts blobs/espressif/<chip>_librftest.a
   python -m chipxray.facts blobs/espressif/<chip>_librftest.a --strip
   ```
4. Run the baseline: `python -m chipxray.baseline facts/<chip>_librftest.json blobs/svd/<chip>.svd`.
5. Optional, needs [Ghidra](https://ghidra-sre.org/): set `CHIPXRAY_GHIDRA` to your `analyzeHeadless` path and run `python -m chipxray.decompile blobs/espressif/<chip>_librftest.a` (and again with `--strip`).
6. Run all tests: `for t in tests/test_*.py; do python $t || break; done`.
7. Open a pull request. Say where `adctrig` ranks on the new chip, if the chip has it.

## 2. Report or challenge a finding

ChipXray reports hidden-feature candidates with an evidence level: observed, correlated or inferred. If you think a finding is wrong, or you know it is documented somewhere, open an issue with the **Finding** template. Disproving a finding is as valuable as confirming one.

## 3. Verify a finding on a real board

Only a hardware test can move a finding to **validated**. If you own the chip, open an issue with the **Hardware verification** template. Describe what you ran, what you measured, and attach logs. Verified findings credit you by name in the README.

## Rules for code

- Python 3.10+, standard library only.
- Keep changes small. Every change needs a test that fails without it.
- Hard mode must never expose a real function name. `tests/test_decomp.py` and `tests/test_facts.py` check this.
- Do not commit vendor binaries. `fetch_inputs.sh` downloads them.

## Legal

The analysed libraries are Espressif's, under Apache-2.0. Publish your own analysis, not large copies of decompiled vendor code. Receive-only experiments are fine; transmitting outside licensed bands is not.
