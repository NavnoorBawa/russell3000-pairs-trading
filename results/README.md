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
| `v33_dev/` | The v33 design (pre-registration candidate S1) on the development calendar, run of commit 7442705 (2026-10-21): `headline_metrics.json`, the full results export and its compact twin, the cost-schedule replay, `anatomy.json` (the evidence layer: shortfall, exit race, decay, persistence, capacity, cash; `scripts/anatomy_of_the_null.py`), `cost_sensitivity.json` (the declared cost and capacity scenarios, each a full re-run; `scripts/cost_sensitivity.py`), `robustness.json` (the robustness checks a reviewer asked for, on the same data: the main backtest from staggered start dates and on each half of the window, the daily returns by VIX and sector-dispersion terciles and by year, cointegration persistence on the candidate pairs S1 searches, and S2's per-trade edge with standard errors clustered by entry month; `scripts/robustness_checks.py`, which also lists it in `MANIFEST.json`; a later `publish_run.py --replace` of this directory removes it, so re-run the script after one), the run log, and `price_fetch_manifest.json`: the price cache's fetch manifest as the run left it (`data/enhanced_russell_3000_data_manifest.json` after the top-up of 2026-10-21, the run's own top-up included; every symbol's fetch outcome, from which the site splits the survivorship gap). Two labels in these exports are not the v33 design's: `version` and `package_version` 32.0.0 are the engine's package version (the design is the v33 profile, hash `d54d21314c22`), and the export's `metadata.model_name` and `strategy_description` are v32's text (re-selection every 90 trading days, a transformer ranker), which the exporter wrote for every profile until it was made to describe the recorded profile (`json_export.strategy_metadata`, after this run); the run itself has `ranker: none` and a full re-selection every 126 trading days (`run_config.effective`, `run_config.study`). |
| `residual_dev/` | The Avellaneda–Lee residual-reversion arm (S2) on the same calendar, universe rule, fills and costs (`scripts/run_residual_statarb.py`). |
| `validation/` | The known-answer checks of the engine on synthetic markets, 10 markets per scenario (`scripts/synthetic_validation.py`). |
| `v32_dev/` | The published v32 run (2026-10-18), kept as the record of what was published and as the design that runs frozen and descriptive (S3) in the holdout: headline, export, cost-schedule replay, the price-fetch manifest of the first fetch, the universe file's metadata and the run log. |
| `variant_family/` | `declaration.json`: the strategy variants for the data-snooping tests, declared before any of them was run. The run outputs (`daily_returns.csv`, `runs.json`, `snooping.json`) are added by `scripts/variant_family.py` when its run completes. |
| `trial_registry.jsonl` | One line per trial whose result was seen, append-only (`scripts/register_trial.py`). |

Prices are not redistributed (Yahoo's terms); a price-fetch manifest lists exactly which
symbols and dates a re-run fetches.
