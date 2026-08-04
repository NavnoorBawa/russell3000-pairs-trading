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
| `scripts/` diagnostics | Local developer tooling, not imported by the package | Not part of the installable package |
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
executable code. To rebuild it safely, delete `data/` and let the system re-fetch from source.

### Dependency advisories

`requirements.txt` pins the exact dependency set that produced the published results, so
reproducibility and advisory-freshness are in genuine tension here. The pins are chosen so that
both hold: **`pip-audit -r requirements.txt` currently reports no known vulnerabilities**, and CI
enforces that on every push (see `.github/workflows/ci.yml`). There is no ignore-list — a newly
disclosed advisory in any pinned package turns CI red rather than being silently waived.

For the record, the pins moved to get there:

- `requests` 2.32.3 → 2.34.2, clearing `PYSEC-2026-1872` (`.netrc` credential leak) and
  `PYSEC-2026-2275`.
- `torch` 2.7.0 → 2.13.0, clearing 14 advisories.

Independently of the version pin, most `torch` advisories are also **unreachable from this
codebase**: it uses only `nn.Linear`, `nn.LayerNorm`, `nn.MultiheadAttention`, `nn.GELU`,
`nn.Dropout`, `AdamW` and `clip_grad_norm_`, and **never calls `torch.load()`,
`load_state_dict()`, or any distributed / RPC API**. Published results were re-generated on the
upgraded set, so the pins and the numbers agree.

## What is out of scope

- The strategy losing money. The repository's own conclusion is that the out-of-sample edge is
  **not statistically significant**; that is a documented research finding, not a vulnerability.
- Advisories in `torch` that require `torch.load()` or distributed APIs, unless you can show a
  reachable path in this code.
- Anything in `archive/` or `scripts/` — local diagnostics, not shipped as part of the package.
