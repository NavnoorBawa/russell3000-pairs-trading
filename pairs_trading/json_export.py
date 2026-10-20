"""
JSON exports of a completed study run.

Three files are written under outputs/ (all created atomically — see `_atomic_write_json`):

  * pairs_trading_results_2023_2025_unbiased.json (+ a `_compact` twin): the full record
    of the main backtest — equity curve, every trade, per-pair and bucketed trade
    statistics — plus the walk-forward, significance, benchmark and FDR results. The file
    name is historical and kept only so existing consumers keep working; it makes no
    claim about the period (see metadata.backtest_period) or about bias.
  * fund_type_comparison.json: the fund-cost replay of the main backtest's trades.
  * headline_metrics.json: a small, stable, rounded snapshot of the published headline
    numbers. README.md, index.html and og-image.png are checked against / generated from
    it (scripts/check_published_numbers.py, scripts/make_og_image.py), so the prose can no
    longer drift away from what the code produces.

Every file carries a `run_config` provenance block (package version, git commit, the
PAIRS_* switches, data-cache fingerprint, library versions) so a published number can be
traced to the code, data and settings that produced it.

The strategy being described is a cointegration / Kalman-filter pairs strategy
(Engle-Granger selection, beta-locked z-score signals, t+1 fills). A transformer-encoder
scorer ranks candidate entries only (its out-of-sample AUC is exported; v31.1's ablation
measured a contribution of exactly 0). The exports say so rather than naming the system
after the transformer.
"""

import dataclasses
import hashlib
import importlib.metadata
import platform
import subprocess
import uuid
from datetime import date, timedelta, timezone
from pathlib import Path

from pairs_trading.config import (
    pd, np, os, json, logging, datetime, List, Dict, Optional
)
from pairs_trading.evidence import headline_evidence
from pairs_trading.study_config import PROFILES, describe as describe_study, get_calendar, get_profile

logger = logging.getLogger(__name__)

PACKAGE_NAME = 'russell3000-pairs-trading'
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = 'outputs'          # default; PAIRS_OUTPUT_DIR redirects a run (output_root)

# Output file names. v32: the '_2023_2025_unbiased' name is kept only for backward
# compatibility with existing consumers; it is not a statement about the period or bias.
DEFAULT_RESULTS_FILENAME = 'pairs_trading_results_2023_2025_unbiased.json'
DEFAULT_FUND_FILENAME = 'fund_type_comparison.json'
DEFAULT_HEADLINE_PATH = os.path.join(OUTPUT_DIR, 'headline_metrics.json')

# The price cache data_processor reads (cwd-relative, exactly as the pipeline opens it).
DATA_CACHE_FILE = os.path.join('data', 'enhanced_russell_3000_data.pkl')

# Environment switches a run reads; recorded verbatim (None = unset). All but PAIRS_N_JOBS
# change what a run computes; PAIRS_N_JOBS only spreads the pair search over processes.
PROVENANCE_ENV_VARS = (
    'PAIRS_PROFILE', 'PAIRS_CALENDAR', 'PAIRS_SEED', 'PAIRS_FILL', 'PAIRS_USE_TRANSFORMER',
    'PAIRS_RANKER', 'PAIRS_RESELECT', 'PAIRS_DEMO_UNIVERSE', 'PAIRS_SKIP_REPROCESS',
    'PAIRS_ALLOW_PARTIAL_FETCH', 'PAIRS_N_JOBS', 'PAIRS_OUTPUT_DIR', 'PYTHONHASHSEED',
)

STRATEGY_DESCRIPTION = (
    'Cointegration / Kalman-filter pairs trading: Engle-Granger pair selection with '
    're-selection every 90 trading days, a two-state Kalman hedge ratio locked at entry, z-score '
    'mean-reversion entries and exits, t+1 fills and daily mark-to-market accounting. '
    'A transformer-encoder scorer (single feature vector, i.e. an MLP-like head) only '
    'RANKS candidate entries (its out-of-sample AUC is reported in the ranker section; the '
    'PAIRS_USE_TRANSFORMER=0 run is the ablation). This is '
    'not a transformer trading model and not reinforcement learning.'
)

# Units of the exported fields, embedded in the file so a reader does not have to guess.
FIELD_NOTES = {
    'net_pnl_pct_of_equity': 'trade P&L after all costs, as % of PORTFOLIO equity at entry',
    'gross_pnl_pct_of_equity': 'trade P&L before costs, as % of portfolio equity at entry',
    'spread_return_pct': 'gross P&L per $ of GROSS NOTIONAL of the two legs, in %',
    'position_pct_of_equity': 'gross notional of both legs as % of portfolio equity at entry',
    'holding_days_calendar': 'calendar days from the entry fill to the exit fill',
    'trading_days_held': 'trading days from the entry fill to the exit fill',
    'drawdowns': 'all drawdown fields are <= 0, relative to the running peak; the '
                 'starting capital counts as the first peak',
    'profit_factor': 'sum of winning trades / |sum of losing trades|; null when there is '
                     'no losing trade (infinite) or no trade at all',
    'dates': 'YYYY-MM-DD exchange-local trading dates; null where no real date exists',
}

MIN_TRADES_FOR_PAIR_SHARPE = 5

# |z| at the signal date. Entries require |z| >= 1.8 (trading_system.ENTRY_Z), so the
# first bucket is a sanity check that should always be empty.
ZSCORE_BUCKETS = (
    ('<1.8', 0.0, 1.8),
    ('1.8-2.0', 1.8, 2.0),
    ('2.0-2.5', 2.0, 2.5),
    ('2.5-3.0', 2.5, 3.0),
    ('>=3.0', 3.0, float('inf')),
)

# Trading days from entry fill to exit fill (inclusive bounds). The first bucket starts
# at 0 because a position can be closed on its own fill bar (end_of_data / risk_halt).
HOLDING_BUCKETS = (
    ('0-2', 0, 2),
    ('3-5', 3, 5),
    ('6-10', 6, 10),
    ('11-15', 11, 15),
    ('16-25', 16, 25),
    ('>25', 26, float('inf')),
)


# ──────────────────────────────────────────────────────────────────────────────
# Safe serialization
# ──────────────────────────────────────────────────────────────────────────────

def _json_key(key) -> str:
    """Dict key -> JSON object key (always a string).

    Tuple keys are joined with '-', the repository's 'SYM1-SYM2' pair convention;
    dates/timestamps use ISO format; numbers and booleans use their JSON spelling.
    """
    if isinstance(key, str):
        return key
    if key is None:
        return 'null'
    if isinstance(key, (bool, np.bool_)):
        return 'true' if key else 'false'
    if isinstance(key, (int, np.integer)):
        return str(int(key))
    if isinstance(key, (float, np.floating)):
        return repr(float(key))
    if isinstance(key, tuple):
        return '-'.join(_json_key(k) for k in key)
    if key is pd.NaT:
        return 'NaT'
    if isinstance(key, (pd.Timestamp, datetime, date)):
        return key.isoformat()
    if isinstance(key, np.datetime64):
        return 'NaT' if np.isnat(key) else pd.Timestamp(key).isoformat()
    return str(key)


def _json_safe(obj):
    """Recursively convert a result structure into plain, strict-JSON-compatible values.

    v31 (audit): Python's `json.dump` writes NaN/Infinity as the BARE tokens `NaN`,
    `Infinity`, `-Infinity` — valid JavaScript but invalid JSON (RFC 8259) — so strict
    parsers (`jq`, Go, Rust, Postgres, most `JSON.parse` consumers) reject the whole
    file. Non-finite floats therefore become null, and `allow_nan=False` at write time
    makes any value that slips through raise instead of producing a corrupt file.

    v32: the engine's records carry pandas/NumPy types the old sanitiser did not know
    (tz-aware Timestamps, NaT, datetime64, sets, tuple-keyed dicts). They are converted
    explicitly here: dates -> ISO strings, NaT -> null, sets -> sorted lists (so output
    is byte-reproducible), Series -> lists, DataFrames -> lists of records. Anything
    still unknown is left alone so json.dumps raises TypeError — an export must fail
    loudly rather than silently stringify an object nobody meant to publish.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            jk = _json_key(k)
            if jk in out:
                raise ValueError(f"dict keys collide after JSON conversion: {k!r} -> {jk!r}")
            out[jk] = _json_safe(v)
        return out
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if obj is pd.NaT or obj is pd.NA:
        return None
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        items = [_json_safe(v) for v in obj]
        try:
            return sorted(items)
        except TypeError:                          # mixed types: order by their JSON text
            return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(obj, pd.DataFrame):
        return _json_safe(obj.to_dict(orient='records'))
    if isinstance(obj, (pd.Series, pd.Index)):
        return [_json_safe(v) for v in obj.tolist()]
    if isinstance(obj, np.ndarray):
        if obj.dtype.kind in 'mM':                 # .tolist() would give raw int64 ticks
            return [_json_safe(v) for v in obj]
        return [_json_safe(v) for v in obj.tolist()]
    if isinstance(obj, np.datetime64):
        return None if np.isnat(obj) else pd.Timestamp(obj).isoformat()
    if isinstance(obj, np.timedelta64):
        return None if np.isnat(obj) else pd.Timedelta(obj).isoformat()
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        return pd.Timedelta(obj).isoformat()
    if isinstance(obj, pd.Period):
        return str(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        obj = float(obj)
        return obj if np.isfinite(obj) else None
    if isinstance(obj, os.PathLike):
        return os.fspath(obj)
    return obj


def _dump_json(data, fh, **kwargs):
    """json.dump with the sanitiser applied and bare NaN/Infinity tokens forbidden."""
    kwargs.setdefault('indent', 2)
    json.dump(_json_safe(data), fh, allow_nan=False, **kwargs)


def _atomic_write_json(data, path) -> str:
    """Serialise `data` and replace `path` with it atomically; return the path.

    v32: exports used to open the destination for writing and serialise into it. A
    serialisation error (or a crash) half-way left a truncated file at the published
    path, and the caller swallowed the exception and carried on. Now the whole document
    is serialised in memory first (so a TypeError/ValueError never touches the disk),
    written to a unique temporary file in the same directory, fsync'd, and moved over the
    destination with os.replace — readers see either the old file or the new one, never
    a partial one. Errors propagate to the caller.
    """
    text = json.dumps(_json_safe(data), allow_nan=False, indent=2) + '\n'
    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, f'.{os.path.basename(path)}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp')
    try:
        with open(tmp, 'x', encoding='utf-8') as fh:   # 'x': never clobber; normal umask perms
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def output_root() -> str:
    """The run's output directory (cwd-relative): PAIRS_OUTPUT_DIR, else outputs/.

    One directory per (profile, calendar) run keeps e.g. the v32 and v33 or the dev and
    holdout exports from overwriting each other.
    """
    return os.environ.get('PAIRS_OUTPUT_DIR') or OUTPUT_DIR


def _output_path(filename: str, output_dir: Optional[str] = None) -> str:
    return os.path.join(output_dir or os.path.join(os.getcwd(), output_root()), filename)


# ──────────────────────────────────────────────────────────────────────────────
# Small numeric helpers
# ──────────────────────────────────────────────────────────────────────────────

def _finite(x) -> Optional[float]:
    """float(x) if x is a finite real number, else None (bools are not numbers here)."""
    if x is None or isinstance(x, (bool, np.bool_)):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _r(x, nd: int, scale: float = 1.0) -> Optional[float]:
    """Round x * scale to nd places; None for missing / non-finite. Normalises -0.0."""
    f = _finite(x)
    if f is None:
        return None
    return round(f * scale, nd) + 0.0


def _int(x) -> Optional[int]:
    f = _finite(x)
    return int(round(f)) if f is not None else None


def _first(*values):
    """First value that is not None."""
    for v in values:
        if v is not None:
            return v
    return None


def _date_str(x) -> Optional[str]:
    """Wall-clock trading date 'YYYY-MM-DD' of a Timestamp/date/str (None for NaT/None)."""
    if x is None or x is pd.NaT:
        return None
    try:
        ts = pd.Timestamp(x)
    except (TypeError, ValueError):
        return None
    return None if ts is pd.NaT else str(ts.date())


def _as_dict(x) -> Dict:
    return x if isinstance(x, dict) else {}


# ──────────────────────────────────────────────────────────────────────────────
# Run provenance
# ──────────────────────────────────────────────────────────────────────────────

_SHA_CACHE: Dict[tuple, str] = {}


def package_version() -> Optional[str]:
    """Installed distribution version, else the version declared in pyproject.toml."""
    try:
        return importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        pass
    try:
        import tomllib
        with open(REPO_ROOT / 'pyproject.toml', 'rb') as fh:
            return tomllib.load(fh).get('project', {}).get('version')
    except (OSError, ValueError):
        return None


def _git(*args) -> Optional[str]:
    """Output of a read-only git command in the repo, or None if git/repo is unavailable."""
    try:
        out = subprocess.run(['git', *args], cwd=REPO_ROOT, capture_output=True,
                             text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _library_version(dist: str) -> Optional[str]:
    """Distribution version without importing it (torch is slow to import)."""
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return None


def file_fingerprint(path: str, chunk_size: int = 1 << 20) -> Optional[Dict]:
    """Size, mtime (UTC) and streamed sha256 of a file; None if it does not exist.

    The sha256 is cached per (path, size, mtime) so the several exports of one run hash
    the ~1 GB price cache once. The path is recorded as given (cwd-relative), never
    absolute, so a published file does not leak the author's home directory.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    digest = _SHA_CACHE.get(key)
    if digest is None:
        h = hashlib.sha256()
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(chunk_size), b''):
                h.update(chunk)
        digest = h.hexdigest()
        _SHA_CACHE[key] = digest
    return {
        'path': os.fspath(path),
        'size_bytes': int(st.st_size),
        'mtime_utc': datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(timespec='seconds'),
        'sha256': digest,
    }


def build_run_config(results: Optional[Dict] = None, system_info: Optional[Dict] = None,
                     data_file: str = DATA_CACHE_FILE) -> Dict:
    """Provenance of a run: code version, switches, data fingerprint, library versions.

    v32: exports previously carried no provenance at all, so a published number could not
    be tied to a commit, a fill convention, a seed or a data snapshot — and the README's
    figures drifted from the code for weeks unnoticed. `system_info` may carry
    'total_symbols_processed', 'pairs_selected', 'data_start', 'data_end', 'study' (the
    study_config.describe record of the run's profile and calendar) and 'price_cache'.
    """
    results = _as_dict(results)
    info = _as_dict(system_info)
    dates = results.get('daily_dates') or []
    fill = str(os.environ.get('PAIRS_FILL', 'close'))
    study = info.get('study')
    if not study:
        study = describe_study(get_profile(), get_calendar())
    profile = study['profile']
    data_file = info.get('price_cache') or data_file
    commit = _git('rev-parse', 'HEAD')
    dirty = _git('status', '--porcelain', '--untracked-files=no') if commit else None
    return {
        'package_version': package_version(),
        'git_commit': commit,
        'git_dirty': (dirty != '') if dirty is not None else None,
        'run_timestamp_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'env': {k: os.environ.get(k) for k in PROVENANCE_ENV_VARS},
        'effective': {
            'profile': profile['name'],
            'calendar': study['calendar']['name'],
            'fill': 'open' if fill.lower() == 'open' else 'close',   # trading_system.resolve_fill_column
            'ranker': profile['ranker'],
            'use_transformer_ranker': profile['ranker'] == 'transformer',
            'reselect': profile['reselect'],
            'regime_gate': profile['regime_gate'],
        },
        'study': study,
        'data': {
            'data_start': _date_str(info.get('data_start')),
            'data_end': _date_str(info.get('data_end')),
            'backtest_start': _date_str(dates[0]) if len(dates) else None,
            'backtest_end': _date_str(dates[-1]) if len(dates) else None,
            'n_symbols': _int(info.get('total_symbols_processed')),
            'n_pairs': _int(info.get('pairs_selected')),
            # fraction of the universe file the price data covers (None: pre-v32 cache, unknown)
            'universe_coverage': _r(info.get('universe_coverage'), 4),
            # fraction of the universe file present in the price cache (always measurable;
            # below coverage when symbols were deliberately excluded for short/invalid data)
            'universe_cached_fraction': _r(info.get('universe_cached_fraction'), 4),
            # universe symbols with no price history at the vendor (delisted): survivorship
            'universe_not_found_fraction': _r(info.get('universe_not_found_fraction'), 4),
            'price_cache': file_fingerprint(data_file),
        },
        'versions': {
            'python': platform.python_version(),
            'numpy': np.__version__,
            'pandas': pd.__version__,
            'torch': _library_version('torch'),
            'scipy': _library_version('scipy'),
            'statsmodels': _library_version('statsmodels'),
        },
        'platform': platform.platform(),
    }


def log_run_config(cfg: Dict) -> None:
    """One compact block in the run log, so the log alone identifies the run."""
    data = cfg.get('data', {})
    cache = data.get('price_cache') or {}
    env = {k: v for k, v in cfg.get('env', {}).items() if v is not None}
    commit = cfg.get('git_commit')
    logger.info('RUN CONFIG: version %s | commit %s%s | %s UTC',
                cfg.get('package_version'), commit[:12] if commit else 'n/a',
                ' (uncommitted changes)' if cfg.get('git_dirty') else '', cfg.get('run_timestamp_utc'))
    logger.info('  switches: %s | effective: %s', env or '{}', cfg.get('effective'))
    logger.info('  data: %s -> %s, backtest %s -> %s, %s symbols, %s pairs',
                data.get('data_start'), data.get('data_end'), data.get('backtest_start'),
                data.get('backtest_end'), data.get('n_symbols'), data.get('n_pairs'))
    if cache:
        logger.info('  price cache: %s, %.1f MB, mtime %s, sha256 %s', cache['path'],
                    cache['size_bytes'] / 1e6, cache['mtime_utc'], cache['sha256'][:16])
    else:
        logger.info('  price cache: not found')
    logger.info('  versions: %s', cfg.get('versions'))


def _run_config_for(results: Dict, system_info) -> Dict:
    """The run's provenance block, built (and logged) once per run.

    Reuses results['run_config'] when present; otherwise builds it and stores it there,
    so every export of the same run carries an identical block (one timestamp, one hash).
    """
    cfg = results.get('run_config') if isinstance(results, dict) else None
    if isinstance(cfg, dict) and cfg:
        return cfg
    cfg = build_run_config(results, _as_dict(system_info))
    log_run_config(cfg)
    if isinstance(results, dict):
        results['run_config'] = cfg
    return cfg


def _initial_capital(results: Dict, system_info) -> Optional[float]:
    """Starting capital: system_info, else final equity / (1 + total return)."""
    cap = _finite(_as_dict(system_info).get('initial_capital'))
    if cap:
        return cap
    final = _finite(results.get('final_portfolio_value'))
    tr = _finite(results.get('total_return'))
    if final is not None and tr is not None and tr > -1.0:
        return final / (1.0 + tr)
    return None


def _span_years(daily_dates) -> Optional[float]:
    """Calendar span of the backtest in years (365.25-day years), None if unknown."""
    if not daily_dates or len(daily_dates) < 2:
        return None
    try:
        days = (pd.Timestamp(daily_dates[-1]) - pd.Timestamp(daily_dates[0])).days
    except (TypeError, ValueError):
        return None
    return days / 365.25 if days > 0 else None


# ──────────────────────────────────────────────────────────────────────────────
# Main results export
# ──────────────────────────────────────────────────────────────────────────────

def _export_trade(idx: int, t: Dict) -> Dict:
    """One trade record for publication.

    v32: the export now carries what a reader needs to audit a trade — the signal and
    exit dates, the exit reason, the hedge ratio, the per-notional spread return, both
    holding measures — and labels each P&L field with its denominator (net_pnl_pct is a
    % of PORTFOLIO equity at entry; spread_return is per $ of gross notional). The bulky
    per-day `unit_path` (used only by the fund replay) is deliberately not exported.
    """
    return {
        'trade_id': idx + 1,
        'pair': t.get('pair'),
        'action': t.get('action'),
        'long_symbol': t.get('long_symbol'),
        'short_symbol': t.get('short_symbol'),
        'signal_date': _date_str(t.get('signal_date')),
        'entry_date': _date_str(t.get('date')),
        'exit_signal_date': _date_str(t.get('exit_signal_date')),
        'exit_date': _date_str(t.get('exit_date')),
        'exit_reason': t.get('exit_reason'),
        'exit_prices_real': t.get('exit_prices_real'),
        'hedge_ratio': _r(t.get('hedge_ratio'), 4),
        'zscore': _r(t.get('zscore'), 3),
        'signal_strength': _r(t.get('signal_strength'), 3),
        'pair_quality': _r(t.get('pair_quality'), 3),
        'feature_quality': _r(t.get('feature_quality'), 3),
        'position_size_dollars': _r(t.get('position_size'), 2),
        'long_notional_dollars': _r(t.get('long_notional'), 2),
        'short_notional_dollars': _r(t.get('short_notional'), 2),
        'position_pct_of_equity': _r(t.get('position_pct'), 3, 100),
        'spread_return_pct': _r(t.get('spread_return'), 4, 100),
        'gross_pnl_pct_of_equity': _r(t.get('gross_pnl_pct'), 4, 100),
        'transaction_cost_pct_of_equity': _r(t.get('transaction_cost_pct'), 4, 100),
        'transaction_costs_dollars': _r(t.get('transaction_costs'), 2),
        'net_pnl_pct_of_equity': _r(t.get('net_pnl_pct'), 4, 100),
        'net_pnl_dollars': _r(t.get('pnl_dollar'), 2),
        'holding_days_calendar': _int(t.get('holding_days')),
        'trading_days_held': _int(t.get('trading_days_held')),
        'cost_breakdown_dollars': {k: _r(v, 2) for k, v in _as_dict(t.get('cost_breakdown')).items()},
    }


def export_testing_results_to_json(backtest_results: Dict, system_info: Dict,
                                   output_filename: str = DEFAULT_RESULTS_FILENAME,
                                   output_dir: Optional[str] = None) -> str:
    """Export the main backtest (and the attached validation results) to JSON.

    Writes `output_filename` and a `_compact` twin (no trade list / statistics) under
    outputs/ and returns the path of the full file.

    v32: the export is written even when the main backtest made no trade — through v31
    it returned early, so a zero-trade run silently published NO walk-forward,
    significance or benchmark results. Serialisation errors now propagate instead of
    being logged and turned into a bogus empty path.
    """
    results = _as_dict(backtest_results)
    info = _as_dict(system_info)
    run_config = _run_config_for(results, info)
    trades = results.get('trades') or []
    daily_returns = results.get('daily_returns') or []
    daily_dates = results.get('daily_dates') or []
    period_start = _date_str(daily_dates[0]) if len(daily_dates) else None
    period_end = _date_str(daily_dates[-1]) if len(daily_dates) else None

    logger.info('=' * 80)
    logger.info(f'EXPORTING BACKTEST RESULTS ({period_start} -> {period_end}) TO JSON')
    logger.info('=' * 80)
    if not trades:
        logger.warning('The main backtest made no trades; exporting the (empty) record and '
                       'the walk-forward / significance / benchmark results anyway.')

    initial_capital = _initial_capital(results, info)
    equity_curve = calculate_equity_curve(daily_returns, initial_capital or 1.0, daily_dates,
                                          equity=results.get('equity_curve') if initial_capital else None)
    span_years = _span_years(daily_dates)
    pair_performance = calculate_pair_performance(trades, span_years=span_years)
    ranked_pairs = sorted(pair_performance.items(),
                          key=lambda kv: (-kv[1]['total_return_pct'], kv[0]))
    pair_rows = [_export_pair(rank, name, stats) for rank, (name, stats) in enumerate(ranked_pairs)]
    n_trades = int(results.get('total_trades', len(trades)) or 0)

    wf = {k: v for k, v in _as_dict(results.get('walk_forward')).items()
          if k not in ('oos_daily_returns', 'all_window_daily_returns', 'oos_daily_dates',
                       'oos_daily_detail')}   # bulky daily series (exported below)
    wf_daily = _as_dict(results.get('walk_forward_daily'))

    def _day(source: Dict, series: str, i: int, nd: int, scale: float = 1.0):
        values = source.get(series) or []
        return _r(values[i], nd, scale) if i < len(values) else None

    export_data = {
        'metadata': {
            'export_date_utc': run_config.get('run_timestamp_utc'),
            'backtest_period': {'start': period_start, 'end': period_end},
            # kept for older consumers; now derived from the data rather than hard-coded
            'testing_period': f'{period_start} to {period_end}' if period_start else None,
            'model_name': 'Cointegration / Kalman-filter pairs strategy (transformer used only as an entry ranker)',
            'strategy_description': STRATEGY_DESCRIPTION,
            'initial_capital': _r(initial_capital, 2),
            'total_symbols': _int(info.get('total_symbols_processed')),
            'pairs_selected': _int(info.get('pairs_selected')),
            'file_name_note': 'The file name is historical and kept for backward compatibility; '
                              'see backtest_period for the actual period.',
            'field_notes': FIELD_NOTES,
            # Stages that failed in this run (empty = complete). A run with failures still
            # exports, for debugging, but main() exits non-zero and the headline is flagged.
            'pipeline_errors': list(results.get('pipeline_errors') or []),
        },
        'run_config': run_config,
        'overall_performance': {
            'total_return_pct': _r(results.get('total_return'), 4, 100),
            'annualized_return_pct': _r(results.get('annualized_return'), 4, 100),
            'sharpe_ratio': _r(results.get('sharpe_ratio'), 3),
            'max_drawdown_pct': _r(results.get('max_drawdown'), 4, 100),
            'annualized_volatility_pct': _r(results.get('volatility'), 4, 100),
            'win_rate_pct': _r(results.get('win_rate'), 2, 100) if n_trades else None,
            'profit_factor': _r(results.get('profit_factor'), 3) if n_trades else None,
            'total_trades': n_trades,
            'avg_trade_net_pnl_pct_of_equity': _r(results.get('avg_trade_return'), 4, 100) if n_trades else None,
            'trades_per_day': _r(results.get('trades_per_day'), 4),
            'total_cost_impact_pct': _r(results.get('total_cost_impact_pct'), 4, 100),
            'final_portfolio_value': _r(results.get('final_portfolio_value'), 2),
            'exit_reasons': dict(sorted(_as_dict(results.get('exit_reasons')).items())),
            'signal_rejections': dict(sorted(_as_dict(results.get('signal_rejections')).items())),
            'halted_on': _date_str(results.get('halted_on')),
            'halt_reason': results.get('halt_reason') or None,
            # Capital utilisation: a return on committed capital means little without
            # how much capital was actually deployed and how often it turned over.
            'avg_gross_exposure_pct_of_equity': _r(results.get('avg_gross_exposure'), 2, 100),
            'max_gross_exposure_pct_of_equity': _r(results.get('max_gross_exposure'), 2, 100),
            'annual_turnover_x_equity': _r(results.get('annual_turnover'), 2),
            'return_on_avg_gross_exposure_pct': _r(results.get('return_on_gross_exposure'), 2, 100),
            'avg_trading_days_held': _r(results.get('avg_trading_days_held'), 1),
            # per trade, the larger of (leg notional / that leg's dollar ADV); then averaged
            'avg_max_leg_adv_participation_pct': _r(results.get('avg_max_leg_adv_participation'), 4, 100),
        },
        'pair_performance': pair_rows,
        'top_10_pairs': pair_rows[:10],
        'daily_equity_curve': [
            {
                'date': equity_curve['dates'][i],
                'portfolio_value': _r(equity_curve['values'][i], 2),
                'daily_return_pct': _r(equity_curve['returns'][i], 6, 100),
                'cumulative_return_pct': _r(equity_curve['cumulative_returns'][i], 4, 100),
                'drawdown_pct': _r(equity_curve['drawdowns'][i], 4, 100),
                # net = gross - costs (each per previous-day equity)
                'gross_return_pct': _day(results, 'daily_gross_returns', i, 6, 100),
                'cost_pct': _day(results, 'daily_cost_returns', i, 6, 100),
                'gross_exposure_pct': _day(results, 'daily_gross_exposure', i, 3, 100),
                'open_positions': _int(_day(results, 'daily_open_positions', i, 0)),
            }
            for i in range(len(equity_curve['values']))
        ],
        # The continuous walk-forward out-of-sample series (one simulation, per-window refits).
        'walk_forward_daily': [
            {'date': d, 'daily_return_pct': _r(r, 6, 100),
             'gross_return_pct': _day(wf_daily, 'daily_gross_returns', i, 6, 100),
             'cost_pct': _day(wf_daily, 'daily_cost_returns', i, 6, 100),
             'gross_exposure_pct': _day(wf_daily, 'daily_gross_exposure', i, 3, 100),
             'open_positions': _int(_day(wf_daily, 'daily_open_positions', i, 0))}
            for i, (d, r) in enumerate(zip(wf_daily.get('dates') or [], wf_daily.get('returns') or []))
        ],
        'all_trades': [_export_trade(i, t) for i, t in enumerate(trades)],
        'monthly_performance': calculate_monthly_performance(daily_returns, equity_curve),
        'pair_correlation_matrix': calculate_pair_correlations(trades),
        'trade_statistics': {
            'by_action': calculate_action_statistics(trades),
            'by_exit_reason': calculate_exit_reason_statistics(trades),
            'by_holding_period_trading_days': calculate_holding_period_statistics(trades),
            'by_abs_zscore': calculate_zscore_bucket_statistics(trades),
        },
        'walk_forward_validation': wf,
        'significance': _as_dict(results.get('significance')),
        'benchmarks': _as_dict(results.get('benchmarks')),
        'fdr_diagnostic': _as_dict(results.get('fdr_diagnostic')),
        # point-in-time universe at each formation date: members, and those without free
        # price history (count and index weight) — the survivorship gap, measured
        'universe_by_formation': list(results.get('universe_by_formation') or []),
        'factor_attribution': _as_dict(results.get('factor_attribution')),
        # power, hurdles, gross-vs-net, cost curve, multi-factor attribution, cash (evidence.py)
        'evidence': _as_dict(results.get('evidence')),
        # The learned ranker: how it was trained, and its out-of-sample skill (AUC 0.5 =
        # no information) on signals after its training window; walk-forward per-window
        # figures are in walk_forward_validation.windows[*].ranker_oos.
        'ranker': {
            'training': {k: v for k, v in _as_dict(results.get('ranker_training')).items()},
            'out_of_sample': _as_dict(results.get('ranker_oos')) or None,
            'walk_forward_pooled_out_of_sample': _as_dict(wf.get('ranker_oos_pooled')) or None,
            'walk_forward_windows_with_trained_ranker': _int(wf.get('windows_with_trained_ranker')),
        },
        'regime_diagnosis': _as_dict(results.get('regime_diagnosis')),
    }

    output_path = _atomic_write_json(export_data, _output_path(output_filename, output_dir))
    logger.info(f'Exported results: {output_path} ({os.path.getsize(output_path) / 1024:.1f} KB) — '
                f'{len(trades)} trades, {len(pair_rows)} pairs, {len(equity_curve["values"])} daily points')

    compact_keys = ('metadata', 'run_config', 'overall_performance', 'top_10_pairs',
                    'daily_equity_curve', 'walk_forward_validation', 'significance',
                    'benchmarks', 'fdr_diagnostic', 'factor_attribution', 'ranker')
    compact_name = output_filename[:-5] + '_compact.json' if output_filename.endswith('.json') \
        else output_filename + '_compact.json'
    compact_path = _atomic_write_json({k: export_data[k] for k in compact_keys},
                                      _output_path(compact_name, output_dir))
    logger.info(f'Exported compact results: {compact_path} ({os.path.getsize(compact_path) / 1024:.1f} KB)')
    logger.info('=' * 80)
    return output_path


def _export_pair(rank: int, name: str, stats: Dict) -> Dict:
    return {
        'rank': rank + 1,
        'pair': name,
        'total_trades': stats['total_trades'],
        # sum of the pair's per-trade net P&L, each a % of portfolio equity at entry
        'net_pnl_sum_pct_of_equity': _r(stats['total_return_pct'], 4),
        'total_pnl_dollars': _r(stats['total_pnl_dollars'], 2),
        'win_rate_pct': _r(stats['win_rate'], 2, 100),
        'profit_factor': _r(stats['profit_factor'], 3),
        'avg_trade_net_pnl_pct_of_equity': _r(stats['avg_trade_return_pct'], 4),
        'avg_holding_days_calendar': _r(stats['avg_holding_days'], 1),
        'avg_trading_days_held': _r(stats['avg_trading_days_held'], 1),
        'sharpe_per_trade': _r(stats['sharpe_per_trade'], 3),
        'sharpe_ratio_annualized': _r(stats['sharpe_ratio_annualized'], 3),
        'trades_per_year': _r(stats['trades_per_year'], 2),
        'max_drawdown_pct': _r(-stats['max_drawdown'], 4, 100),
        'avg_signal_strength': _r(stats['avg_signal_strength'], 3),
        'avg_pair_quality': _r(stats['avg_pair_quality'], 3),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Analytics helpers
# ──────────────────────────────────────────────────────────────────────────────

def calculate_pair_performance(trades: List[Dict], span_years: Optional[float] = None) -> Dict[str, Dict]:
    """Per-pair statistics from the trade list.

    v32: the annualised per-pair Sharpe used sqrt(252 / average calendar hold), i.e. it
    assumed the pair traded back-to-back all year. A pair that traded twice in two years
    was annualised as if it traded ~15 times a year. It is now annualised with the pair's
    ACTUAL trade frequency over the backtest span (trades per year = n / span_years,
    span passed in by the caller), uses the sample std (ddof=1), and is null below
    MIN_TRADES_FOR_PAIR_SHARPE trades, where it would be noise. Without a span it is null.
    """
    by_pair: Dict[str, List[Dict]] = {}
    for trade in trades:
        by_pair.setdefault(trade['pair'], []).append(trade)

    out = {}
    for pair in sorted(by_pair):
        tl = by_pair[pair]
        n = len(tl)
        returns = np.array([t['net_pnl_pct'] for t in tl], dtype=float)
        hold_cal = [t['holding_days'] for t in tl if t.get('holding_days') is not None]
        hold_td = [t['trading_days_held'] for t in tl if t.get('trading_days_held') is not None]
        sd = float(returns.std(ddof=1)) if n > 1 else 0.0
        sharpe_per_trade = (float(returns.mean() / sd)
                            if n >= MIN_TRADES_FOR_PAIR_SHARPE and sd > 0 else None)
        trades_per_year = n / span_years if span_years else None
        out[pair] = {
            'total_return_pct': float(returns.sum() * 100),
            'win_rate': float((returns > 0).sum() / n) if n else 0.0,
            'total_trades': n,
            'avg_holding_days': float(np.mean(hold_cal)) if hold_cal else None,
            'avg_trading_days_held': float(np.mean(hold_td)) if hold_td else None,
            'profit_factor': calculate_profit_factor(returns),
            'avg_trade_return_pct': float(returns.mean() * 100) if n else 0.0,
            'sharpe_per_trade': sharpe_per_trade,
            'trades_per_year': trades_per_year,
            'sharpe_ratio_annualized': (sharpe_per_trade * np.sqrt(trades_per_year)
                                        if sharpe_per_trade is not None and trades_per_year else None),
            'max_drawdown': calculate_max_drawdown_from_returns(returns),
            'total_pnl_dollars': float(sum(t['pnl_dollar'] for t in tl)),
            'avg_signal_strength': float(np.mean([t['signal_strength'] for t in tl])),
            'avg_pair_quality': float(np.mean([t['pair_quality'] for t in tl])),
        }
    return out


def calculate_profit_factor(returns) -> float:
    """Sum of wins / |sum of losses|.

    v32: one convention, the engine's (_summarise_backtest): +inf when there is no
    losing trade, 0.0 when there are losses but no wins, NaN when there are no trades.
    v26 capped the no-loss case at a 999.0 sentinel that then got published as a real
    number; infinity is now kept in memory and serialised as null by `_json_safe`.
    """
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return float('nan')
    losses = r[r < 0]
    if losses.size == 0:
        return float('inf')
    return float(r[r > 0].sum() / np.abs(losses).sum())


def calculate_max_drawdown_from_returns(returns) -> float:
    """Largest peak-to-trough loss of the compounded series, as a POSITIVE magnitude.

    v32: the starting value (1.0) counts as the first peak. Through v31 the running
    peak started at the first compounded value, so a loss on the first period was not a
    drawdown at all and a series that only fell from the start was understated.
    """
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    return float(np.max(1.0 - equity / peak))


def calculate_equity_curve(daily_returns: List[float], initial_value: float,
                           daily_dates: List = None, equity: List[float] = None) -> Dict:
    """Daily equity, cumulative return and drawdown series.

    `equity` (the engine's marked-to-market dollar curve) is used as-is when it matches
    the return series; otherwise the curve is compounded from `initial_value`.

    v32: drawdowns are <= 0 (the engine's and overall_performance's convention; through
    v31 this series was positive while max_drawdown_pct was negative) and are measured
    against a running peak seeded with the initial value, so a first-day loss counts.
    Without real dates the dates are None: v26 replaced a synthetic calendar starting in
    January with real dates, but kept a hard-coded synthetic fallback — no fabricated
    calendar is emitted any more.
    """
    r = np.asarray(daily_returns, dtype=float)
    initial_value = float(initial_value)
    if equity is not None and len(equity) == len(r):
        values = np.asarray(equity, dtype=float)
    else:
        values = initial_value * np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(np.concatenate([[initial_value], values]))[1:]
    if daily_dates is not None and len(daily_dates) == len(r):
        dates = [_date_str(d) for d in daily_dates]
    else:
        dates = [None] * len(r)
    return {
        'dates': dates,
        'values': values.tolist(),
        'returns': r.tolist(),
        'cumulative_returns': (values / initial_value - 1.0).tolist(),
        'drawdowns': (values / peak - 1.0).tolist(),
    }


def calculate_monthly_performance(daily_returns: List[float], equity_curve: Dict) -> List[Dict]:
    """Calendar-month statistics of the DAILY return series (not of trades).

    Empty when the curve has no real dates.
    """
    dates = equity_curve.get('dates') or []
    if not len(daily_returns) or any(d is None for d in dates) or len(dates) != len(daily_returns):
        return []
    df = pd.DataFrame({'date': pd.to_datetime(dates), 'ret': np.asarray(daily_returns, dtype=float)})
    monthly = []
    for period, group in df.groupby(df['date'].dt.to_period('M')):
        rets = group['ret']
        # v31 (audit): a one-day month has std()==NaN (ddof=1); emit null, not a fake 0.0.
        sd = rets.std()
        sd_ok = bool(np.isfinite(sd)) and sd > 0
        monthly.append({
            'month': str(period),
            'return_pct': _r(np.prod(1.0 + rets.to_numpy()) - 1.0, 4, 100),
            # v31 (audit): these count DAYS, not trades.
            'trading_days': int(len(group)),
            'positive_day_pct': _r((rets > 0).mean(), 2, 100),
            'volatility_pct_monthly': _r(sd * np.sqrt(21), 4, 100) if np.isfinite(sd) else None,
            'sharpe_ratio_monthly': _r(rets.mean() / sd * np.sqrt(21), 3) if sd_ok else None,
        })
    return monthly


def calculate_pair_correlations(trades: List[Dict]) -> Dict:
    """Pairs traded and their trade counts; correlations are deliberately not computed.

    v31 (audit): this used to return a hard-coded identity matrix labelled
    `correlation_matrix` — fabricated data implying perfect diversification. A genuine
    correlation needs per-pair daily mark-to-market series; the trade list does not give
    enough overlapping observations, so nothing is emitted.
    v32: pairs are sorted — built from an unordered set, the list order depended on the
    interpreter's hash seed and the file was not byte-reproducible.
    """
    counts: Dict[str, int] = {}
    for trade in trades:
        counts[trade['pair']] = counts.get(trade['pair'], 0) + 1
    pairs = sorted(counts)
    return {
        'pairs': pairs,
        'correlation_matrix': None,
        'note': ('Not computed. Correlations between pair return streams require per-pair '
                 'daily mark-to-market series; the trade-level record gives too few '
                 'overlapping observations per pair to estimate them.'),
        'trades_per_pair': {p: counts[p] for p in pairs},
    }


def _bucket_stats(trade_list: List[Dict]) -> Dict:
    """Count, win rate and net P&L (% of equity at entry) of a group of trades."""
    if not trade_list:
        return {'count': 0, 'win_rate_pct': None, 'avg_net_pnl_pct_of_equity': None,
                'total_net_pnl_pct_of_equity': 0.0}
    r = np.array([t['net_pnl_pct'] for t in trade_list], dtype=float)
    return {
        'count': len(trade_list),
        'win_rate_pct': _r((r > 0).mean(), 2, 100),
        'avg_net_pnl_pct_of_equity': _r(r.mean(), 4, 100),
        'total_net_pnl_pct_of_equity': _r(r.sum(), 4, 100),
    }


def calculate_action_statistics(trades: List[Dict]) -> Dict:
    """Statistics by trade direction (LONG / SHORT the spread)."""
    return {action: _bucket_stats([t for t in trades if t['action'] == action])
            for action in ('LONG', 'SHORT')}


def calculate_exit_reason_statistics(trades: List[Dict]) -> Dict:
    """Statistics by exit reason (target / stop / time / end_of_data / risk_halt)."""
    reasons = sorted({t.get('exit_reason') or 'unknown' for t in trades})
    return {r: _bucket_stats([t for t in trades if (t.get('exit_reason') or 'unknown') == r])
            for r in reasons}


def calculate_holding_period_statistics(trades: List[Dict]) -> Dict:
    """Statistics by TRADING days held (entry fill to exit fill).

    v32: through v31 the buckets were '1-3 / 4-7 / 8+' CALENDAR days. With a 10-25
    trading-day time stop almost every trade fell in '8+', so the table said nothing.
    Trades without a trading-day count are left out.
    """
    held = [(t, t.get('trading_days_held')) for t in trades]
    return {label: _bucket_stats([t for t, d in held if d is not None and lo <= d <= hi])
            for label, lo, hi in HOLDING_BUCKETS}


def calculate_zscore_bucket_statistics(trades: List[Dict]) -> Dict:
    """Statistics by |z| of the entry signal (lower bound inclusive, upper exclusive).

    v32: replaces buckets on signal_strength. signal_strength = min(|z| / 2.5, 1) and
    entries require |z| >= 1.8, so strength is always >= 0.72: the old 'weak (0.5-0.7)'
    bucket could never be populated and 'medium'/'strong' just re-cut |z| at 1.75/2.125
    with a cap. Bucketing |z| directly says what it means.
    """
    zs = [(t, abs(float(t['zscore']))) for t in trades if _finite(t.get('zscore')) is not None]
    return {label: _bucket_stats([t for t, z in zs if lo <= z < hi])
            for label, lo, hi in ZSCORE_BUCKETS}


# ──────────────────────────────────────────────────────────────────────────────
# Cost-schedule replay export
# ──────────────────────────────────────────────────────────────────────────────

def export_fund_comparison_to_json(comparison_results: Dict,
                                   output_filename: str = DEFAULT_FUND_FILENAME,
                                   run_config: Optional[Dict] = None,
                                   output_dir: Optional[str] = None) -> str:
    """Export the cost-schedule replay (per-schedule metrics, cost tables, equity curves).

    Returns the written path, or '' when there is nothing to export (no profiles).
    Serialisation errors propagate (v32; they used to be logged and swallowed).
    """
    if not comparison_results:
        logger.warning('No fund comparison results to export.')
        return ''
    logger.info('=' * 80)
    logger.info('EXPORTING FUND TYPE COMPARISON TO JSON')
    logger.info('=' * 80)
    if not run_config:
        run_config = build_run_config()
        log_run_config(run_config)

    metric_defs = [
        ('total_return_pct', 'Total Return (%)'),
        ('annualized_return_pct', 'Annualized Return (%)'),
        ('sharpe_ratio', 'Sharpe Ratio'),
        ('max_drawdown_pct', 'Max Drawdown (%)'),
        ('win_rate_pct', 'Win Rate (%)'),
        ('profit_factor', 'Profit Factor (null = no losing trade)'),
        ('total_trades', 'Total Trades'),
        ('total_cost_pct_of_capital', 'Total Costs (% of initial capital)'),
        ('commission_bps', 'Commission (bps)'),
        ('bid_ask_bps', 'Bid-Ask (bps)'),
        ('market_impact_cap_bps', 'Market Impact Cap (bps)'),
        ('borrow_rate_gc_pct', 'Borrow Rate, GC, short leg (%/yr)'),
        ('financing_spread_pct', 'Financing Spread (%/yr)'),
        ('base_position_pct', 'Base Position (% equity)'),
        ('max_gross_leverage', 'Peak Gross Leverage (realised)'),
        ('trades_stopped_early', 'Stopped by Drawdown Kill-Switch'),
        ('stopped_on', 'Kill-Switch Date'),
    ]
    summary_table = [{'metric': label, **{pk: pdata.get(key) for pk, pdata in comparison_results.items()}}
                     for key, label in metric_defs]
    cost_items = [
        ('commission_pct', 'Commission (% of initial capital)'),
        ('bid_ask_pct', 'Bid-Ask (% of initial capital)'),
        ('market_impact_pct', 'Market Impact (% of initial capital)'),
        ('borrow_pct', 'Stock Borrow (% of initial capital)'),
        ('financing_pct', 'Financing (% of initial capital)'),
    ]
    cost_table = [{'cost_component': label,
                   **{pk: _as_dict(pdata.get('cost_components')).get(key, 0.0)
                      for pk, pdata in comparison_results.items()}}
                  for key, label in cost_items]

    profiles_slim, equity_curves, capital = {}, {}, {}
    for pk, pdata in comparison_results.items():
        profiles_slim[pk] = {k: v for k, v in pdata.items() if k != 'equity_curve'}
        equity_curves[pk] = {'profile_name': pdata.get('profile_name', pk),
                             'curve': pdata.get('equity_curve', [])}
        final, tr = _finite(pdata.get('final_equity')), _finite(pdata.get('total_return_pct'))
        capital[pk] = _r(final / (1.0 + tr / 100.0), 2) if final is not None and tr is not None and tr > -100 else None

    export_data = {
        'metadata': {
            'export_date_utc': run_config.get('run_timestamp_utc'),
            'description': (
                'Cost-schedule replay: the main backtest\'s trades (same signals, entry/exit '
                'dates and daily mark-to-market paths) re-sized and re-costed under five '
                'archetypal cost schedules (pairs_trading/fund_profiles.py). The schedules are '
                'illustrative parameter sets, not any firm\'s terms; the replay does not model '
                'margin, and max_gross_leverage reports the peak gross exposure actually run.'),
            'profiles': list(comparison_results),
            'initial_capital_usd': capital,
            'field_notes': {k: FIELD_NOTES[k] for k in ('drawdowns', 'profit_factor')},
        },
        'run_config': run_config,
        'profiles': profiles_slim,
        'summary_table': summary_table,
        'cost_table': cost_table,
        'equity_curves': equity_curves,
    }
    output_path = _atomic_write_json(export_data, _output_path(output_filename, output_dir))
    logger.info(f'Fund comparison exported: {output_path} ({os.path.getsize(output_path) / 1024:.1f} KB) — '
                f'profiles: {", ".join(comparison_results)}')
    logger.info('=' * 80)
    return output_path


# ──────────────────────────────────────────────────────────────────────────────
# Headline metrics snapshot
# ──────────────────────────────────────────────────────────────────────────────

HEADLINE_SCHEMA_VERSION = 1


def window_test_pvalues(w: Dict) -> Dict:
    """Two-sided and both one-sided p-values of the per-window OOS t-test.

    significance.oos_window_test reports the one-sided values ('pvalue_mean_lt0',
    'pvalue_mean_gt0'); for an older report without them they are derived from the
    reported t-stat with n-1 degrees of freedom — the same Student-t test.
    """
    w = _as_dict(w)
    p_less, p_greater = _finite(w.get('pvalue_mean_lt0')), _finite(w.get('pvalue_mean_gt0'))
    t, n = _finite(w.get('tstat')), _int(w.get('n'))
    if (p_less is None or p_greater is None) and t is not None and n is not None and n >= 2:
        from scipy import stats as _sps
        p_less = _first(p_less, float(_sps.t.cdf(t, n - 1)))
        p_greater = _first(p_greater, float(_sps.t.sf(t, n - 1)))
    return {'p_two_sided': _finite(w.get('pvalue')), 'p_less': p_less, 'p_greater': p_greater}


def vs_strategy_entry(benchmarks: Dict, label: Optional[str] = None) -> Dict:
    """The benchmark's date-aligned comparison block for one strategy series.

    run_benchmarks(..., strategy_series={label: (dates, returns)}) reports each series
    under benchmarks['vs_strategy'][label]; the FIRST series is the headline one, and is
    what this returns when no label is given.
    """
    vs = _as_dict(_as_dict(benchmarks).get('vs_strategy'))
    if label is not None:
        return _as_dict(vs.get(label))
    return _as_dict(next(iter(vs.values()), None))


def random_control_summary(rc: Dict, strategy_sharpe=None, aligned: Optional[Dict] = None) -> Dict:
    """Median / 5th / 95th percentile Sharpe of the random-pair control draws.

    Read from the benchmark's 'sharpe_distribution' (its own calendar, the one its
    headline return and Sharpe use), else computed from the per-draw 'draw_sharpes'.
    The average-of-draws 'sharpe_ratio' is NOT relabelled as a median: without a
    distribution the fields are null. `strategy_percentile` is where the strategy's
    Sharpe falls among the draws (ties count half): the benchmark's own date-aligned
    value ('strategy_percentile', or the vs_strategy block passed as `aligned`) when
    available, else computed against the draws on the benchmark calendar.
    """
    rc = _as_dict(rc)
    dist = _as_dict(rc.get('sharpe_distribution'))
    draws = [f for f in (_finite(v) for v in (rc.get('draw_sharpes') or [])) if f is not None]
    arr = np.asarray(draws, dtype=float)
    have = arr.size > 0
    s = _finite(strategy_sharpe)
    percentile = _finite(_first(rc.get('strategy_percentile'),
                                _as_dict(aligned).get('strategy_percentile_in_random')))
    if percentile is None and have and s is not None:
        percentile = float(100.0 * ((arr < s).mean() + 0.5 * (arr == s).mean()))
    return {
        'median_sharpe': _finite(_first(dist.get('median'), float(np.median(arr)) if have else None)),
        'p5_sharpe': _finite(_first(dist.get('p5'), float(np.percentile(arr, 5)) if have else None)),
        'p95_sharpe': _finite(_first(dist.get('p95'), float(np.percentile(arr, 95)) if have else None)),
        'n_draws': _int(_first(rc.get('n_draws'), arr.size if have else None)),
        'strategy_percentile': percentile,
    }


def sharpe_diff_vs_gatev(benchmarks: Dict, label: Optional[str] = None) -> Dict:
    """Strategy-minus-distance-method Sharpe difference and its Ledoit-Wolf test.

    The benchmark publishes the headline series' test as benchmarks['sharpe_diff_vs_gatev']
    (date-aligned, from vs_strategy); a specific `label` reads that series' block instead.
    Null when the benchmark was run without the strategy's return series.
    """
    bm = _as_dict(benchmarks)
    d = _as_dict(bm.get('sharpe_diff_vs_gatev')) if label is None else {}
    if not d:
        d = _as_dict(vs_strategy_entry(bm, label).get('sharpe_difference_vs_distance'))
    return {'diff': _finite(d.get('diff')), 'p': _finite(_first(d.get('pvalue'), d.get('p'))),
            'ci_lo': _finite(d.get('ci_lo')), 'ci_hi': _finite(d.get('ci_hi')),
            'n_common_days': _int(d.get('n_common_days'))}


def _sig_battery(b: Dict) -> Dict:
    b = _as_dict(b)
    hac, psr = _as_dict(b.get('hac')), _as_dict(b.get('psr_gt0'))
    ci, dsr = _as_dict(b.get('bootstrap_sharpe_ci')), _as_dict(b.get('deflated_sharpe'))
    return {
        'ann_sharpe': _r(b.get('ann_sharpe'), 2),
        'hac_t': _r(hac.get('tstat'), 2),
        'hac_p': _r(hac.get('pvalue'), 3),
        'psr': _r(psr.get('psr'), 4),                 # probability in [0, 1]
        'psr_pct': _r(psr.get('psr'), 1, 100),        # the same, in % for display
        'boot_lo': _r(ci.get('lo'), 2),
        'boot_hi': _r(ci.get('hi'), 2),
        'dsr': _r(dsr.get('dsr'), 4),
        'dsr_pct': _r(dsr.get('dsr'), 1, 100),
    }


# The headline configuration: every PAIRS_* switch at its default. A run with any other
# value is a sensitivity variant (non_default_switches), which the publishing scripts refuse.
HEADLINE_SEED = 42                                  # pairs_trading.main.DEFAULT_SEED
FLAG_SWITCHES = ('PAIRS_DEMO_UNIVERSE', 'PAIRS_SKIP_REPROCESS', 'PAIRS_ALLOW_PARTIAL_FETCH')
MIN_UNIVERSE_COVERAGE = 0.90                        # data_processor.MIN_FETCH_COVERAGE


def non_default_switches(run_config: Optional[Dict]) -> List[str]:
    """Run switches that make a run differ from its named profile (empty = a clean run).

    A clean run executes a study_config profile exactly as defined (any calendar). An
    override of a profile field (PAIRS_RESELECT, PAIRS_USE_TRANSFORMER=0, PAIRS_RANKER),
    another fill convention, another seed, a debugging flag or a partial price cache
    makes it a variant, and the publication checker refuses its numbers by default.
    """
    rc = run_config or {}
    eff, env = rc.get('effective') or {}, rc.get('env') or {}
    out = []
    if eff.get('fill', 'close') != 'close':
        out.append(f"PAIRS_FILL={eff.get('fill')}")
    profile = ((rc.get('study') or {}).get('profile')) or {}
    if profile:
        defined = PROFILES.get(profile.get('name'))
        if defined is None:
            out.append(f"profile={profile.get('name')} (not a defined profile)")
        else:
            for key, value in dataclasses.asdict(defined).items():
                if profile.get(key) != value:
                    out.append(f"{key}={profile.get(key)}")
    else:                                    # an export from before study profiles
        if eff.get('use_transformer_ranker', True) is not True:
            out.append('PAIRS_USE_TRANSFORMER=0')
        if eff.get('reselect', 'pool') != 'pool':
            out.append(f"PAIRS_RESELECT={eff.get('reselect')}")
    seed = env.get('PAIRS_SEED')
    if seed is not None:
        try:
            other_seed = int(str(seed).strip()) != HEADLINE_SEED
        except ValueError:
            other_seed = True
        if other_seed:
            out.append(f'PAIRS_SEED={seed}')
    for key in FLAG_SWITCHES:
        if env.get(key) == '1':
            out.append(f'{key}=1')
    coverage = (rc.get('data') or {}).get('universe_coverage')
    if coverage is not None and coverage < MIN_UNIVERSE_COVERAGE:
        out.append(f'universe_coverage={coverage:.1%}')   # a partial cache, whatever the switches
    return out


def build_headline_metrics(results: Dict, system_info: Dict = None,
                           run_config: Optional[Dict] = None) -> Dict:
    """The headline snapshot as a dict (see `export_headline_metrics`)."""
    results = _as_dict(results)
    wf = _as_dict(results.get('walk_forward'))
    sig = _as_dict(results.get('significance'))
    bm = _as_dict(results.get('benchmarks'))
    fdr = _as_dict(results.get('fdr_diagnostic'))
    funds = _as_dict(results.get('fund_comparison'))
    dates = results.get('daily_dates') or []
    windows = [w for w in (wf.get('windows') or []) if isinstance(w, dict)]
    n_trades = _int(results.get('total_trades'))
    ow = _as_dict(sig.get('oos_windows'))
    ow_p = window_test_pvalues(ow)
    gatev = _as_dict(bm.get('distance_method'))
    rc = random_control_summary(bm.get('random_control'), results.get('sharpe_ratio'),
                                aligned=vs_strategy_entry(bm))
    diff = sharpe_diff_vs_gatev(bm)
    ranker_oos = _as_dict(results.get('ranker_oos'))

    return {
        'schema': HEADLINE_SCHEMA_VERSION,
        'version': package_version(),
        'complete': not results.get('pipeline_errors'),
        # switches that make this a sensitivity variant rather than the headline run; the
        # publishing scripts refuse a non-empty list unless explicitly overridden
        'non_default_switches': non_default_switches(run_config if run_config is not None
                                                     else _run_config_for(results, system_info)),
        'pipeline_errors': list(results.get('pipeline_errors') or []),
        'run_config': run_config if run_config is not None else _run_config_for(results, system_info),
        'main': {
            'period_start': _date_str(dates[0]) if len(dates) else None,
            'period_end': _date_str(dates[-1]) if len(dates) else None,
            'total_return_pct': _r(results.get('total_return'), 2, 100),
            'sharpe': _r(results.get('sharpe_ratio'), 2),
            'trades': n_trades,
            'win_rate_pct': _r(results.get('win_rate'), 1, 100) if n_trades else None,
            'max_drawdown_pct': _r(results.get('max_drawdown'), 2, 100),
            'exit_reasons': dict(sorted(_as_dict(results.get('exit_reasons')).items())),
            'avg_gross_exposure_pct': _r(results.get('avg_gross_exposure'), 1, 100),
            'annual_turnover_x': _r(results.get('annual_turnover'), 1),
        },
        'ranker': {
            'trained': bool(_as_dict(results.get('ranker_training')).get('epochs')),
            'train_samples': _int(_as_dict(results.get('ranker_training')).get('n_samples')),
            'oos_signals': _int(ranker_oos.get('n')),
            'oos_auc': _r(ranker_oos.get('auc'), 3),
            'wf_pooled_auc': _r(_as_dict(wf.get('ranker_oos_pooled')).get('auc'), 3),
            'wf_windows_trained': _int(wf.get('windows_with_trained_ranker')),
        },
        'oos': {
            'period_start': _date_str(wf.get('oos_start')),
            'period_end': _date_str(wf.get('oos_end')),
            'windows': _int(_first(wf.get('total_windows'), len(windows) if windows else None)),
            'windows_positive': _int(wf.get('profitable_windows')),
            'windows_no_trades': sum(1 for w in windows if _int(w.get('total_trades')) == 0) if windows else None,
            'windows_selection_clean': _int(wf.get('selection_clean_windows')),
            'windows_skipped': _int(wf.get('skipped_windows')),
            'avg_window_return_pct': _r(wf.get('avg_window_return_pct'), 3),
            'median_window_return_pct': _r(wf.get('median_window_return_pct'), 3),
            'pooled_sharpe': _r(wf.get('pooled_sharpe'), 2),
            'total_return_pct': _r(wf.get('stitched_total_return_pct'), 2),
            'trades': _int(wf.get('total_trades')),
            'max_drawdown_pct': _r(wf.get('max_drawdown_pct'), 2),
            'window_ids': [_int(w.get('window')) for w in windows],
            'window_returns_pct': [_r(w.get('total_return_pct'), 3) for w in windows],
            'window_trades': [_int(w.get('total_trades')) for w in windows],
        },
        'significance': {
            'main': _sig_battery(sig.get('main_backtest')),
            'oos_daily': _sig_battery(sig.get('oos_daily')),
            'oos_windows': {
                'n': _int(ow.get('n')),
                'mean_pct': _r(ow.get('mean'), 3, 100),
                't': _r(ow.get('tstat'), 2),
                'p': _r(ow_p['p_two_sided'], 3),
                'p_one_sided_negative': _r(ow_p['p_less'], 3),
                'ci_lo_pct': _r(ow.get('ci_lo'), 3, 100),
                'ci_hi_pct': _r(ow.get('ci_hi'), 3, 100),
                'boot_ci_lo_pct': _r(ow.get('boot_ci_lo'), 3, 100),
                'boot_ci_hi_pct': _r(ow.get('boot_ci_hi'), 3, 100),
                'positive': _int(ow.get('positive')),
            },
        },
        'benchmarks': {
            'gatev': {'total_return_pct': _r(gatev.get('total_return_pct'), 2),
                      'sharpe': _r(gatev.get('sharpe_ratio'), 2)},
            'random_control': {'median_sharpe': _r(rc['median_sharpe'], 2),
                               'p5_sharpe': _r(rc['p5_sharpe'], 2),
                               'p95_sharpe': _r(rc['p95_sharpe'], 2),
                               'n_draws': rc['n_draws'],
                               'strategy_percentile': _r(rc['strategy_percentile'], 1)},
            'sharpe_diff_vs_gatev': {'diff': _r(diff['diff'], 2), 'p': _r(diff['p'], 3),
                                     'ci_lo': _r(diff['ci_lo'], 2), 'ci_hi': _r(diff['ci_hi'], 2)},
        },
        'fdr': {k: _int(fdr.get(k)) for k in ('pairs_tested', 'significant_raw_p05', 'survive_bh_fdr_q05',
                                               'survive_bh_fdr_q10', 'final_selected_pairs')},
        'fund_profiles': {
            key: {'name': _as_dict(p).get('profile_name'),
                  'total_return_pct': _r(_as_dict(p).get('total_return_pct'), 2),
                  'sharpe': _r(_as_dict(p).get('sharpe_ratio'), 2),
                  'max_drawdown_pct': _r(_as_dict(p).get('max_drawdown_pct'), 2),
                  'max_gross_leverage': _r(_as_dict(p).get('max_gross_leverage'), 2)}
            for key, p in funds.items()
        },
        # what the run can and cannot show (pairs_trading/evidence.py)
        'evidence': {k: _r(v, 4) for k, v in headline_evidence(_as_dict(results.get('evidence'))).items()},
        # survivorship, measured: the point-in-time universe at the first formation date
        'universe': _first_formation(results.get('universe_by_formation')),
    }


def _first_formation(log) -> Dict:
    """Members, members with prices and the missing index weight at the first formation."""
    first = (log or [{}])[0] or {}
    return {'formation_date': first.get('formation_date'), 'members': _int(first.get('members')),
            'with_prices': _int(first.get('with_prices')),
            'missing_value_weight_pct': _r(first.get('missing_value_weight'), 3, 100),
            'unmapped_value_weight_pct': _r(first.get('unmapped_value_weight'), 3, 100)}


def export_headline_metrics(results: dict, system_info: dict, path: str = None) -> str:
    """Write the small, stable, machine-readable headline snapshot; return its path.

    v32 (new): README.md and index.html mark every headline number with its key in this
    file, scripts/check_published_numbers.py fails when any marked number disagrees with
    it, and scripts/make_og_image.py draws the social card from it. Schema (schema=1):

      schema, version, run_config,
      main:  period_start, period_end, total_return_pct, sharpe, trades, win_rate_pct,
             max_drawdown_pct, exit_reasons
      oos:   period_start, period_end, windows, windows_positive, windows_no_trades,
             windows_selection_clean, windows_skipped, avg_window_return_pct,
             median_window_return_pct, pooled_sharpe, total_return_pct, trades,
             max_drawdown_pct, window_ids[], window_returns_pct[], window_trades[]
      significance.main / .oos_daily: ann_sharpe, hac_t, hac_p, psr, psr_pct, boot_lo,
             boot_hi, dsr, dsr_pct
      significance.oos_windows: n, mean_pct, t, p, p_one_sided_negative, ci_lo_pct,
             ci_hi_pct, boot_ci_lo_pct, boot_ci_hi_pct, positive
      benchmarks: gatev{total_return_pct, sharpe}, random_control{median_sharpe,
             p5_sharpe, p95_sharpe, n_draws, strategy_percentile},
             sharpe_diff_vs_gatev{diff, p, ci_lo, ci_hi}
      fdr:   pairs_tested, significant_raw_p05, survive_bh_fdr_q05, survive_bh_fdr_q10,
             final_selected_pairs
      fund_profiles.<key>: name, total_return_pct, sharpe, max_drawdown_pct,
             max_gross_leverage

    Percentages are in percent (-0.28 means -0.28%); drawdowns are <= 0; psr/dsr are
    probabilities (psr_pct/dsr_pct the same in %). Any value that is unavailable — a
    section that did not run, a key another module does not report — is null, never a
    crash and never a placeholder number. Call it after the fund comparison has run so
    fund_profiles is populated.
    """
    doc = build_headline_metrics(results, system_info)
    out = _atomic_write_json(doc, path or _output_path('headline_metrics.json'))
    m, o = doc['main'], doc['oos']
    logger.info(f'Headline metrics: {out} — main {m["total_return_pct"]}% / Sharpe {m["sharpe"]} / '
                f'{m["trades"]} trades; OOS {o["avg_window_return_pct"]}%/window, pooled Sharpe '
                f'{o["pooled_sharpe"]}, {o["windows_positive"]}/{o["windows"]} windows positive')
    return out
