# results/

Committed outputs of the study runs: the evidence behind every published number. The
pipeline writes to `outputs/` (git-ignored, overwritten by every run); a run that is
published is copied here unchanged by `scripts/publish_run.py`, with a `MANIFEST.json` of
every file's sha256 and its provenance block (`run_config`: commit, profile, calendar, data
fingerprint, library versions) inside every JSON. `scripts/build_site_data.py` builds the
site's data from these files, and `scripts/check_published_numbers.py` checks README.md and
index.html against `v33_dev/headline_metrics.json`.

| Path | What it holds |
|---|---|
| `v33_dev/` | The v33 design (pre-registration candidate S1) on the development calendar, run of commit 7442705 (2026-10-21): `headline_metrics.json`, the full results export and its compact twin, the cost-schedule replay, `anatomy.json` (the evidence layer: shortfall, exit race, decay, persistence, capacity, cash; `scripts/anatomy_of_the_null.py`), `cost_sensitivity.json` (the declared cost and capacity scenarios, each a full re-run; `scripts/cost_sensitivity.py`) and the run log. |
| `residual_dev/` | The Avellaneda–Lee residual-reversion arm (S2) on the same calendar, universe rule, fills and costs (`scripts/run_residual_statarb.py`). |
| `validation/` | The known-answer checks of the engine on synthetic markets, 10 markets per scenario (`scripts/synthetic_validation.py`). |
| `v32_dev/` | The published v32 run (2026-10-18), kept as the record of what was published and as the design that runs frozen and descriptive (S3) in the holdout: headline, export, cost-schedule replay, the price-fetch manifest of the first fetch, the universe file's metadata and the run log. |
| `variant_family/` | `declaration.json`: the strategy variants for the data-snooping tests, declared before any of them was run. The run outputs (`daily_returns.csv`, `runs.json`, `snooping.json`) are added by `scripts/variant_family.py` when its run completes. |
| `trial_registry.jsonl` | One line per trial whose result was seen, append-only (`scripts/register_trial.py`). |

Prices are not redistributed (Yahoo's terms); a price-fetch manifest lists exactly which
symbols and dates a re-run fetches.
