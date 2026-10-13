# Security Policy

This is a **research** repository. It backtests a statistical-arbitrage strategy on historical
price data. It is not a service, it has no server, no user accounts, no database, and it accepts
no untrusted input at runtime beyond the market data you point it at. That shapes the threat
model below — please read it before filing a report.

## Reporting a vulnerability

Please report privately via
[GitHub Security Advisories](https://github.com/NavnoorBawa/russell3000-pairs-trading/security/advisories/new),
or by email to navnoorquant@gmail.com.

Please include a description, affected file/version, and a reproduction if you have one.
Expect an acknowledgement within 7 days. This is a personal research project maintained in spare
time, so please allow up to 90 days before public disclosure.

## Threat model

The realistic attack surface is small and mostly reduces to **what data you feed the system**:

| Surface | Risk | Status |
| --- | --- | --- |
| `data/*.pkl` price cache | `pickle.load()` executes arbitrary code during deserialization (CWE-502) | **Real.** See below. |
| `yfinance` / `requests` network fetch | Hostile or MITM'd upstream response | HTTPS; response is parsed as a DataFrame, never executed |
| `scripts/` tools | Publication check, social card and synthetic validation: read local JSON/HTML or generate synthetic data in memory | Not part of the installable package; no network access |
| `scripts/parameter_sensitivity.py` | On the study data it loads the same `data/*.pkl` caches as the main pipeline and fetches from Yahoo when they are absent; `--synthetic` writes and reloads its own pickles in a temporary directory | Same trust boundary as the price-cache and network rows above |
| Published site (`index.html`) | Static page, no JS input handling, no cookies, no analytics | No dynamic content |

### The pickle cache is a trust boundary

`pairs_trading/data_processor.py` caches fetched prices in `data/enhanced_russell_3000_data.pkl`
via `pickle`. Unpickling **executes code by design** — this is a property of the format, not a bug
in this repository.

The cache is normally created on your own machine by `load_or_fetch_data()`, in which case it is as
trustworthy as your machine. The danger is different:

> **Never point this system at a `.pkl` file you did not generate yourself.**
> Loading a pickle from an untrusted source is equivalent to running that source's code.

`data/` is `.gitignore`d and no `.pkl` is distributed with this repository, precisely so that no
one is ever encouraged to download one. If you obtain a cache file from anyone, treat it as
executable code. To rebuild it safely, delete the `.pkl` files in `data/` — **not**
`data/marketcap.csv`, the study universe, which is required and not redistributed — and let
the system re-fetch from source. A re-fetch is safe but will not reproduce an earlier run
bit-for-bit: vendors revise history, and adjusted prices depend on the fetch date. An
unreadable cache is reported as an error; it is never silently re-fetched over.

### Dependency advisories

`requirements.txt` pins the exact dependency set that produced the published results, so
reproducibility and advisory-freshness are in genuine tension here. The pins are chosen so that
both hold: CI runs `pip-audit` on every push in two passes (see `.github/workflows/ci.yml`) —
on the environment it actually installed, which covers every transitive dependency at the version
tested, and on each pin in `requirements.txt` by its public version. The second pass is what
covers torch: CI installs the CPU wheel (`2.13.0+cpu`), which PyPI does not know, so the
environment pass skips it. Only the torch wheel itself comes from the PyTorch index; its
dependencies come from PyPI (that index carries an old setuptools with known advisories). There is
no ignore-list — a newly disclosed advisory turns CI red rather than being silently waived.
`requirements.txt` pins the direct dependencies only; transitive versions are resolved at install
time.

For the record, the pins moved to get there:

- `requests` 2.32.3 → 2.34.2, clearing `PYSEC-2026-1872` (`.netrc` credential leak) and
  `PYSEC-2026-2275`.
- `torch` 2.7.0 → 2.13.0, clearing 14 advisories.

Independently of the version pin, most `torch` advisories are also **unreachable from this
codebase**: it uses only `nn.Linear`, `nn.LayerNorm`, `nn.MultiheadAttention`, `nn.GELU`,
`nn.Dropout`, `AdamW` and `clip_grad_norm_`, and **never calls `torch.load()`,
`load_state_dict()`, or any distributed / RPC API**. (v31.1 results were generated on this set;
they are withdrawn in v32 pending a re-run, which will use the same pins.)

## What is out of scope

- The strategy losing money, or having no statistically significant edge. That is a research
  outcome, not a vulnerability.
- Advisories in `torch` that require `torch.load()` or distributed APIs, unless you can show a
  reachable path in this code.
- Anything in `archive/` — historical material, not shipped as part of the package.
