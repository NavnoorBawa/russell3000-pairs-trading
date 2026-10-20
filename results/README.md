# results/

Committed outputs of the study runs: the evidence behind every published number. The
pipeline writes to `outputs/` (git-ignored, overwritten by every run); a run that is
published is copied here unchanged, with its provenance block (`run_config`: commit, profile,
calendar, data fingerprint, library versions) inside every JSON.

| Directory | What it holds |
|---|---|
| `v32_dev/` | The published v32 run (2026-10-18): `headline_metrics.json` (the numbers README.md and the site are checked against), the full results export, the cost-schedule replay, the price-fetch manifest (which symbols were fetched, and how each fetch ended), the universe file's metadata, and the run log (progress bars removed, paths made relative). |
| `variant_family/` | `declaration.json`: the strategy variants for the data-snooping tests, declared before any of them was run. The run outputs (`daily_returns.csv`, `runs.json`, `snooping.json`) are added by `scripts/variant_family.py`. |

Prices are not redistributed (Yahoo's terms); `price_fetch_manifest.json` lists exactly which
symbols and dates a re-run fetches.
