#!/usr/bin/env python3
"""Anatomy of the null: where a run's edge goes (pairs_trading/anatomy.py).

Reads a run's exported results JSON and the price cache it traded on, and writes
anatomy.json (every section of pairs_trading.anatomy, with the inputs' fingerprints) and
anatomy.txt (a short summary) next to the results file, or where --out says:

    python scripts/anatomy_of_the_null.py
        outputs/pairs_trading_results_2023_2025_unbiased.json -> outputs/anatomy.json
    python scripts/anatomy_of_the_null.py --results A/results.json B/results.json
        -> A/anatomy.json, B/anatomy.json (the persistence table is computed once)
    python scripts/anatomy_of_the_null.py --results R.json --out /tmp/anatomy.json
    python scripts/anatomy_of_the_null.py --skip-persistence     # without the Clegg table
    python scripts/anatomy_of_the_null.py --persistence-from outputs/anatomy.json
        reuses an earlier output's Clegg table (same price cache, cutoff and table design only)

Inputs: data/enhanced_russell_3000_data.pkl (the price cache; its sha256 is compared with
the run's provenance and recorded; every trade's rebuilt gross P&L is checked against the
export whatever the hash says), data/macro_data.pkl (sector ETFs: the market proxy) and
FRED DTB3 (cached under data/external/fred/ with a fingerprint; --offline never fetches).
The cointegration-persistence table (Clegg 2014) depends on the price cache only: ~45k
pairs x 6 years of two-direction Engle-Granger tests, run over --n-jobs worker processes
(default PAIRS_N_JOBS, else min(4, CPUs)); tens of minutes with statsmodels' coint.
Output is deterministic for a given --seed.
"""
import argparse
import hashlib
import json
import logging
import os
import pathlib
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('TQDM_DISABLE', '1')

from pairs_trading import anatomy  # noqa: E402
from pairs_trading.data_processor import EnhancedRussell3000DataProcessor  # noqa: E402
from pairs_trading.json_export import _atomic_write_json, file_fingerprint  # noqa: E402

DEFAULT_RESULTS = 'outputs/pairs_trading_results_2023_2025_unbiased.json'
FRED_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id={}'
USER_AGENT = 'russell3000-pairs-trading research bot'

logger = logging.getLogger('anatomy_of_the_null')


def load_fred(series_id: str, cache_dir: str, offline: bool):
    """(series, fingerprint) of a FRED series, from {cache_dir}/fred/<id>.csv or fetched once.

    The cache layout is that of the study's external-data loaders: the raw CSV and,
    beside it, <id>.csv.json with the URL, sha256, size and fetch time. A cached file
    whose bytes no longer match its fingerprint is refused.
    """
    path = pathlib.Path(cache_dir) / 'fred' / f'{series_id}.csv'
    meta_path = path.with_name(path.name + '.json')
    url = FRED_URL.format(series_id)
    if path.exists():
        raw = path.read_bytes()
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        sha = hashlib.sha256(raw).hexdigest()
        if meta.get('sha256') and meta['sha256'] != sha:
            raise ValueError(f"{path} does not match its fingerprint {meta_path}")
        fingerprint = {**meta, 'url': meta.get('url', url), 'sha256': sha, 'bytes': len(raw)}
    elif offline:
        raise FileNotFoundError(f"{path} is not cached and --offline forbids fetching {url}")
    else:
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        fingerprint = {'url': url, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                       'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'vintage': None}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_bytes(raw)
        os.replace(tmp, path)
        meta_path.write_text(json.dumps(fingerprint, indent=1))
    return anatomy.parse_fred_csv(raw.decode('utf-8'), series_id), fingerprint


def _display_path(path: pathlib.Path) -> str:
    """Path relative to the repository, else parent/name (never an absolute home path)."""
    path = pathlib.Path(path).absolute()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(pathlib.Path(path.parent.name) / path.name)


def _n_jobs(value) -> int:
    if value is not None:
        return max(1, int(value))
    env = os.environ.get('PAIRS_N_JOBS')
    return max(1, int(env)) if env else min(4, os.cpu_count() or 1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--results', nargs='+', default=[DEFAULT_RESULTS], help='exported results JSON file(s)')
    ap.add_argument('--out', nargs='+', default=None, help='anatomy.json path per results file (default: beside it)')
    ap.add_argument('--prices', default='data/enhanced_russell_3000_data.pkl')
    ap.add_argument('--macro', default='data/macro_data.pkl')
    ap.add_argument('--cache-dir', default='data/external', help='FRED cache root')
    ap.add_argument('--offline', action='store_true', help='never fetch; fail if DTB3 is not cached')
    ap.add_argument('--skip-persistence', action='store_true', help='omit the year-by-year Clegg (2014) table')
    ap.add_argument('--persistence-from', default=None,
                    help="an earlier anatomy.json whose Clegg table to reuse (it must name the same price cache)")
    ap.add_argument('--n-jobs', type=int, default=None)
    ap.add_argument('--paths', type=int, default=anatomy.EXIT_RACE_PATHS, help='simulated paths per trade (exit race)')
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args(argv)
    if args.out is not None and len(args.out) != len(args.results):
        ap.error('--out needs one path per --results file')
    results_paths = [pathlib.Path(p) for p in args.results]
    out_paths = [pathlib.Path(p) for p in args.out] if args.out else [p.parent / 'anatomy.json' for p in results_paths]
    runs = [json.loads(p.read_text()) for p in results_paths]

    t0 = time.time()
    prices = EnhancedRussell3000DataProcessor._load_pickle_or_raise(args.prices)
    prices_fp = file_fingerprint(args.prices)
    macro = EnhancedRussell3000DataProcessor._load_pickle_or_raise(args.macro)
    dtb3, dtb3_fp = load_fred('DTB3', args.cache_dir, args.offline)
    logger.info(f"Loaded {len(prices)} price series, macro data and DTB3 in {time.time() - t0:.0f}s")

    persistence = {}
    if args.persistence_from:
        earlier = json.loads(pathlib.Path(args.persistence_from).read_text())
        if (earlier.get('source') or {}).get('price_cache', {}).get('sha256') != prices_fp['sha256']:
            raise SystemExit(f"{args.persistence_from} was computed on a different price cache")
        table = (earlier.get('persistence_detail') or {}).get('clegg')
        if table:
            same = (table.get('schema') == anatomy.PERSISTENCE_SCHEMA and table.get('alpha') == anatomy.PERSISTENCE_ALPHA
                    and table.get('min_common_days') == anatomy.PERSISTENCE_MIN_DAYS
                    and [r['year'] for r in table.get('years') or []] == list(anatomy.PERSISTENCE_YEARS))
            if not same:
                raise SystemExit(f"{args.persistence_from} holds a persistence table of another design; recompute it")
            persistence[table['universe_cutoff']] = table
    if not args.skip_persistence:
        for cutoff in sorted({str(anatomy.formation_schedule(r)[0][0].date()) for r in runs} - set(persistence)):
            t1 = time.time()
            symbols = anatomy.liquid_universe(prices, cutoff)
            table = anatomy.cointegration_persistence(prices, symbols, n_jobs=_n_jobs(args.n_jobs))
            persistence[cutoff] = {**table, 'universe_cutoff': cutoff}
            logger.info(f"Persistence on {len(symbols)} names screened to {cutoff}: {time.time() - t1:.0f}s")

    for res, src, dst in zip(runs, results_paths, out_paths):
        t1 = time.time()
        cutoff = str(anatomy.formation_schedule(res)[0][0].date())
        out = anatomy.build_anatomy(res, prices, macro.get('sectors'), dtb3, persistence.get(cutoff),
                                    n_paths=args.paths, seed=args.seed)
        run_cache = ((res.get('run_config') or {}).get('data') or {}).get('price_cache') or {}
        out['source'] = {
            'results': {**file_fingerprint(str(src)), 'path': _display_path(src)},
            'price_cache': prices_fp,
            'price_cache_is_the_runs': (bool(run_cache.get('sha256') == prices_fp['sha256'])
                                        if run_cache.get('sha256') else None),
            'dtb3': dtb3_fp, 'macro': file_fingerprint(args.macro),
            'builder': 'scripts/anatomy_of_the_null.py', 'seed': args.seed, 'paths_per_trade': args.paths,
        }
        text = '\n'.join(anatomy.summary_lines(out)) + '\n'
        _atomic_write_json(out, dst)
        dst.with_suffix('.txt').write_text(text)
        print(text, end='')
        logger.info(f"Wrote {dst} and {dst.with_suffix('.txt')} ({time.time() - t1:.0f}s)")
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('pairs_trading').setLevel(logging.WARNING)
    logging.getLogger('pairs_trading.anatomy').setLevel(logging.INFO)
    sys.exit(main())
