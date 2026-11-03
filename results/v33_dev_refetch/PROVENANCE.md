# v33_dev_refetch: how this run was made

The published development run (`results/v33_dev/`, commit 7442705) pinned a price cache with
sha256 3a9a93cc…a7be. That cache and the macro cache were lost with the working storage by
22 October 2026, so this directory is the same design, calendar and steps run again on prices
fetched afresh, through `scripts/run_dev_studies.sh` with `RUN=v33_dev_refetch`. It registers no
trial (`results/trial_registry.jsonl`): it re-runs the published configuration and its declared
variants; it chooses nothing.

| Part | Commit | Date (UTC) | Input |
|---|---|---|---|
| Main backtest, anatomy, costs (this directory) | 10ac3bb | 2026-10-28 | price cache sha256 ca8a39e6…51b6, fetch manifest `price_fetch_manifest.json` (sha256 dde344a7…707f) |
| `residual/` (S2) | 10ac3bb | 2026-10-28 | the same cache |
| `variant_family/` | bf8daf1 | 2026-11-03 | the same cache |
| `validation/` | bf8daf1 | 2026-11-03 | synthetic markets; no prices |
| `robustness.json` | bf8daf1 | 2026-11-03 | this directory and `residual/` |

Code between the published run and this one. Between 7442705 and 10ac3bb, one change in
`pairs_trading/` touches computation: `data_processor.py` gained a second fetch pass that
retries the symbols whose fetch failed transiently. The other changes there are comments and
what the exports record (a description of the design that was run). Every computation after
the fetch is the published code.

The variant family's restarts. Two runs under 10ac3bb were killed for lack of memory, after
35 and 33 of the 38 variants. `scripts/variant_family.py` then gained checkpoints and frees
memory between selection groups (bf8daf1; `git diff 10ac3bb bf8daf1` changes nothing else).
The family then ran to the end under bf8daf1. Every variant that either killed run finished
gave the same Sharpe ratio and trade count in the complete run. The family's `MANIFEST.json`
and the known-answer report's have no commit, because neither writes a headline file of its
own. This table is their record.

Paths. `price_cache_hashes.json` names the caches by repository-relative paths, the form
`scripts/hash_cache.py` writes now. The hashes are those computed at publish time. The caches
themselves are not published. Their sha256 values above, and every symbol's fingerprint, let
a later fetch be compared with this one symbol by symbol.
