# ChipXray — independent reproduction and adversarial evaluation
Date: 2026-10-28 (UTC). Host: Windows `DESKTOP-01B08BS`. Upstream: `Om7035/chipxray`, commit `54fd0f6c0ddf07d2b63ca0454dd15b7d5d2a7f7a`. Fork: `FreesoSaiFared/chipxray`.

## What was executed
- Forked upstream to the owner's GitHub account; cloned to `C:\Users\Admin\Documents\chipxray`.
- Python 3.14.0; standard-library-only software; no additional Python dependencies.
- Downloaded all five pinned Espressif `librftest.a` inputs and five pinned SVD register maps. Original `SHA256SUMS` verification passed.
- Compiled the package and test files. Executed **all 11** `tests/test_*.py` scripts successfully.
- Regenerated the five baseline CSVs. Their numerical content matched the checked-in copies.
- Ran three real model experiments with `openai/gpt-4.1-mini` through an already-configured OpenRouter API key (15 API requests in total). No keys were written to repository files.
- Saved machine receipts in ignored `work/receipts/`. The first complete receipt is `verification-20261028T004023Z.json`; the post-fix complete receipt is `verification-20261028T004807Z.json`. Both record zero failures.

## Reproduced rules baseline
| Chip | Functions | Own-register rank of `adctrig` | Call-inclusive rank |
|---|---:|---:|---:|
| ESP32 | 289 | 30 | 58 |
| ESP32-S3 | 203 | 28 | 23 |
| ESP32-C3 | 218 | 29 | 27 |
| ESP32-C5 | 286 | 2 | 19 |
| ESP32-C61 | 252 | 2 | 29 |

The inclusive heuristic harms the known-positive ranking on three chips. `Store.candidates()` sorts primarily by inclusive score, so the default `oneshot` top-15 view excludes `adctrig` even for ESP32-C5 (inclusive rank 19). This is a candidate-selection limitation *before* the language model is asked to reason.

## Real model tests (ESP32-C5)
These are **single trials**, not a replicated statistical benchmark. Model: `openai/gpt-4.1-mini`; agent tool budget: 8. One-prompt control used top 30 (default top 15 would omit `adctrig`).

| System | Function names | `adctrig` in returned ranking? | Fact references passing checker | LLM requests | Input tokens |
|---|---|---|---:|---:|---:|
| Agent | Stripped | **No** | 17/17 | 7 | 42,445 |
| Agent | Visible | **No** | 11/11 | 7 | 40,308 |
| One prompt, top 30 | Stripped | **No** | 8/25 | 1 | 33,921 |

Decoded top suggestions included `run_rftest_case`, `burnin_test_func`, `ate_rxframe_fb`, and `force_iq_set`. The one-prompt control also included `fft_dump_init`; this was already named in the project's own research plans, and its presence does not establish a novel capability.

The stripped agent produced the report before the timestamp/period filename fix; its legacy filename is `results/agent/esp32c5_stripped-openai_gpt-4.json`. The correctly timestamped matching transcript is stored locally. Other results use corrected complete filenames.

## Adversarial checks and limits
1. **Evidence support is syntactic, not semantic.** `evidence.check()` verifies that an address, call edge, or copied C snippet really appears in the cited function. It does **not** establish the accompanying natural-language claim. A controlled deliberately false claim that an ESP32 contains 128 GB HBM, paired with a real `adctrig` MMIO reference, received `supported=1/1`. See `scripts/analyze-outcomes.py` and ignored `work/receipts/outcome-analysis.json`.
2. **Candidate recall failed.** Neither agent trial nor the broader one-prompt control recovered the known `adctrig` example. Larger function counts and undocumented radio-register maps cause false-positive candidates. One prompt supplied a larger candidate window but still ranked other functions.
3. **Input and decompilation provenance is bounded.** Pinned original libraries and SVDs were verified. The repository already ships precomputed Ghidra decompilation JSON; Ghidra was not found on PATH, so this audit did not independently regenerate those decompositions.
4. **No hardware validation.** No ESP32 was flashed or physically measured. Finding a register access does not prove the corresponding circuitry works. No out-of-family transfer test was performed.
5. **The README roadmap is stale.** Agent, one-prompt, benchmark, and CLI-backend implementations exist and their deterministic tests pass; that is distinct from a validated autonomous discovery benchmark.

## Verified repairs in the fork
- `chipxray/agent.py` and `chipxray/oneshot.py`: append `.json` rather than `Path.with_suffix('.json')` on names containing `gpt-4.1-mini`. Previous code silently truncated model names and run timestamps, making output collisions possible. `tests/test_agent.py` now covers the extension rule; a post-fix live run demonstrated a full timestamped filename.
- `chipxray/baseline.py`: force LF terminators for generated CSV on Windows. Rerunning all five baselines thereafter produced no tracked baseline diffs.
- `.gitignore`: exclude raw agent/one-shot reports and transcripts from routine public commits.
- `scripts/verify-local.ps1`: deterministic setup, checks, baselines, and local machine-readable receipt.
- `scripts/run-live.ps1`: real OpenRouter-backed model trials, loads an existing key from the environment; no credential is saved.
- `scripts/analyze-outcomes.py`: decodes blinded function identifiers, records run metrics, reproduces the semantic evidence-checker weakness.

## What would justify a stronger discovery claim?
1. Make high-ranking *direct* register users visible alongside high-scoring call-chain parents, independently of function names. Compare recall/precision before adopting a new heuristic.
2. Run 3+ repeats per configuration across all five chips, including blind mode and documented negative controls; report hit@10, supported-reference rate, total input tokens, actual model spend, and number of hypotheses physically validated.
3. Ensure final claims have distinct machine-checkable categories: directly observed opcode/address, semantic inference, independent source, and measured hardware effect. A copied address cannot validate the proposed effect.
4. Regenerate Ghidra outputs independently, compare extracted call/address edges, and investigate linear-sweep false positives.
5. Transfer unchanged extraction/ranking algorithms to a **different, held-out chip family**, then validate one surprising claim using physical hardware or an independent measurement.

## Repeat locally
From the repository root on Windows PowerShell:

```powershell
& .\scripts\verify-local.ps1             # fetch SHA-256-pinned inputs, compile, test, baseline
& .\scripts\verify-local.ps1 -SkipFetch  # rerun entirely offline
python .\scripts\analyze-outcomes.py
# Optional paid model runs; requires OPENROUTER_API_KEY set privately in host environment:
& .\scripts\run-live.ps1 -Chip esp32c5 -Strip -Budget 8
& .\scripts\run-live.ps1 -Chip esp32c5 -Strip -Mode oneshot -Top 30
```

Conclusion: **the repository builds and analyzes reproducibly. It does not yet meet a discovery-quality acceptance threshold.** This is a negative empirical finding, not a judgment that new hardware capabilities cannot be discovered by improved methods.
