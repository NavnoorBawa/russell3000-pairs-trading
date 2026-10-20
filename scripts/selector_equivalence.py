#!/usr/bin/env python3
"""Real-data equivalence of the pair selector with an earlier revision's selector.

The fast selector (pairs_trading/fast_coint.py, the all-pairs search over PAIRS_N_JOBS
processes) claims the decisions of the serial statsmodels one. This script checks the
claim on the study's own data and times both:

  selection    find_quality_pairs on the formation data, i.e. the price cache up to
               PAIR_SELECTION_CUTOFF filtered exactly as prepare_study filters it, with
               the reference revision's selector (default fa4c02b, v32: statsmodels' coint
               in one loop) and with this tree's at each --n-jobs. Required: the same
               screened universe, the same selected pairs in the same order, the same FDR
               diagnostic, the same p < 0.05 decision for every FDR p-value; the
               statistics may differ by rounding only. Runs of this tree with different
               worker counts must agree bit for bit.
  reselection  the decisions of build_rolling_pair_schedule's re-test (PAIRS_RESELECT=pool)
               for the reference selection at every 90th trading day after the cutoff:
               the 2-year Engle-Granger test and the 126-day check, with both selectors.

usage: python scripts/selector_equivalence.py [--reference fa4c02b] [--n-jobs 1 4]
                                              [--out outputs/selector_equivalence.json]
Needs data/marketcap.csv and the price cache data/enhanced_russell_3000_data.pkl (nothing
is fetched). Runtime is dominated by the reference selector on one core: ~30 min for the
44,850 pairs of the 300-symbol universe and ~9 min for the re-selection tests, against
~1 min each for this tree's (4 CPUs). Exit status 0 only if every check passes.
"""
import argparse
import json
import logging
import os
import pathlib
import subprocess
import sys
import time
import types

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('TQDM_DISABLE', '1')       # no progress bars in the log

from pairs_trading.data_processor import EnhancedRussell3000DataProcessor  # noqa: E402
from pairs_trading.pair_selector import FixedPrimeFundPairSelector  # noqa: E402
from pairs_trading.trading_system import (  # noqa: E402
    PAIR_SELECTION_CUTOFF, CompleteFixedRussell3000TradingSystem, _align_ts,
)

logger = logging.getLogger('selector_equivalence')
STAT_FIELDS = ('correlation', 'cointegration_pvalue', 'half_life', 'quality_score')


def _git(*args) -> str:
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def reference_selector_class(rev: str):
    """FixedPrimeFundPairSelector as of git revision `rev`, from an in-memory module."""
    source = _git('show', f'{rev}:pairs_trading/pair_selector.py')
    module = types.ModuleType('pair_selector_reference')
    exec(compile(source, f'{rev}:pairs_trading/pair_selector.py', 'exec'), module.__dict__)
    return module.FixedPrimeFundPairSelector


def load_processed_data() -> dict:
    """The processed price cache as the pipeline loads it (load_study_data); never fetches."""
    processor = EnhancedRussell3000DataProcessor()
    if not os.path.exists(processor.data_file):
        raise SystemExit(f'{processor.data_file} not found: this check runs on the cached prices only')
    return processor.load_or_fetch_data(processor.load_symbols())


def formation_data(processed: dict) -> dict:
    """The data prepare_study hands to find_quality_pairs: each symbol up to the cutoff, >= 100 bars."""
    out = {}
    for sym, df in processed.items():
        if len(df.index) == 0:
            continue
        filtered = df[df.index <= _align_ts(PAIR_SELECTION_CUTOFF, df.index[0])]
        if len(filtered) >= 100:
            out[sym] = filtered
    return out


def run_selection(selector, data: dict, max_universe=None) -> dict:
    """find_quality_pairs, the p-values it hands to the FDR diagnostic, and its wall time."""
    import statsmodels.stats.multitest as multitest
    if max_universe is not None:
        selector.max_universe = max_universe
    seen, original = [], multitest.multipletests

    def recording(pvals, *args, **kwargs):
        seen.append(np.array(pvals, dtype=float))
        return original(pvals, *args, **kwargs)

    multitest.multipletests = recording
    try:
        start = time.perf_counter()
        pairs = selector.find_quality_pairs(data)
        seconds = time.perf_counter() - start
    finally:
        multitest.multipletests = original
    return {'pairs': list(pairs), 'stats': selector.pair_statistics, 'fdr': selector.fdr_diagnostic,
            'pvalues': seen[0] if seen else np.array([]), 'universe': list(selector.last_quality_symbols),
            'seconds': seconds}


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def compare_selections(ref: dict, new: dict, label: str) -> dict:
    """Assert the decisions agree; return the largest absolute difference of each statistic."""
    _check(new['universe'] == ref['universe'], f'{label}: screened universe differs')
    _check(new['pairs'] == ref['pairs'], f'{label}: selected pairs or their order differ')
    _check(new['fdr'] == ref['fdr'], f'{label}: FDR diagnostic differs')
    _check(new['pvalues'].shape == ref['pvalues'].shape, f'{label}: number of tested pairs differs')
    _check(bool(((new['pvalues'] < 0.05) == (ref['pvalues'] < 0.05)).all()),
           f'{label}: a p < 0.05 decision differs')
    _check(list(new['stats']) == list(ref['stats']), f'{label}: pair statistics keys differ')
    diffs = {'fdr_pvalue': float(np.abs(new['pvalues'] - ref['pvalues']).max()) if ref['pvalues'].size else 0.0}
    diffs.update({field: 0.0 for field in STAT_FIELDS})
    for key, ref_stats in ref['stats'].items():
        new_stats = new['stats'][key]
        _check(new_stats.keys() == ref_stats.keys(), f'{label}: statistics fields differ for {key}')
        _check(new_stats['pca_cointegrated'] == ref_stats['pca_cointegrated'], f'{label}: PCA flag differs for {key}')
        for field in STAT_FIELDS:
            diffs[field] = max(diffs[field], abs(float(new_stats[field]) - float(ref_stats[field])))
    return diffs


def _bitwise(result: dict):
    """A selection result in a form that compares equal only if every float is bit-identical."""
    stats = [(key, [(k, float(v).hex() if isinstance(v, float) else v) for k, v in s.items()])
             for key, s in result['stats'].items()]
    return result['universe'], result['pairs'], result['fdr'], result['pvalues'].tobytes(), stats


def reselection_tests(selector, processed: dict, pool: list, dates: list, recent_max_p: float) -> list:
    """build_rolling_pair_schedule's per-pair tests (PAIRS_RESELECT=pool) on every date.

    One row per (date, pair): (decision, 2-year p, 126-day p). The windows and the order
    of the tests are the engine's; the spreads it then builds do not involve the selector.
    """
    rows = []
    for resel_date in dates:
        for sym1, sym2 in pool:
            d1, d2 = processed.get(sym1), processed.get(sym2)
            if d1 is None or d2 is None:
                rows.append(('missing', None, None))
                continue
            cut = _align_ts(resel_date, d1.index[0])
            w1 = d1[(d1.index > cut - pd.Timedelta(days=730)) & (d1.index <= cut)]
            w2 = d2[(d2.index > cut - pd.Timedelta(days=730)) & (d2.index <= cut)]
            if len(w1) < 100 or len(w2) < 100:
                rows.append(('short', None, None))
                continue
            is_coint, p_long = selector.test_cointegration(w1, w2)
            if not is_coint:
                rows.append(('not_cointegrated', p_long, None))
                continue
            recent_start = cut - pd.Timedelta(days=126)
            lp1, lp2 = selector._aligned_log_prices(w1.loc[w1.index >= recent_start],
                                                    w2.loc[w2.index >= recent_start])
            p_recent = selector.cointegration_pvalue(lp1, lp2) if len(lp1) >= 60 else None
            kept = p_recent is None or p_recent <= recent_max_p
            rows.append(('kept' if kept else 'dropped_recent', p_long, p_recent))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--reference', default='fa4c02b', help='git revision of the reference selector')
    ap.add_argument('--n-jobs', type=int, nargs='+', default=[1, 4],
                    help='worker counts to run this tree\'s selector with')
    ap.add_argument('--max-universe', type=int, default=None,
                    help='screened universe size (default: the selector\'s, 300); smaller for a quick run')
    ap.add_argument('--out', default=str(ROOT / 'outputs' / 'selector_equivalence.json'))
    args = ap.parse_args(argv)
    out_path = pathlib.Path(args.out).resolve()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    os.chdir(ROOT)                    # the data paths are relative to the repository root
    load_start = os.getloadavg()

    processed = load_processed_data()
    data = formation_data(processed)
    logger.info(f'Formation data: {len(data)} symbols up to {PAIR_SELECTION_CUTOFF}')

    reference_cls = reference_selector_class(args.reference)
    logger.info(f'Reference selector ({args.reference}), one process')
    reference = run_selection(reference_cls(), data, args.max_universe)
    logger.info(f"Reference: {len(reference['pairs'])} pairs in {reference['seconds']:.0f} s")
    runs = {}
    for n_jobs in args.n_jobs:
        selector = FixedPrimeFundPairSelector()
        selector.n_jobs = n_jobs
        runs[n_jobs] = run_selection(selector, data, args.max_universe)
        logger.info(f"This tree, n_jobs={n_jobs}: {len(runs[n_jobs]['pairs'])} pairs in "
                    f"{runs[n_jobs]['seconds']:.0f} s")

    diffs = {n_jobs: compare_selections(reference, result, f'n_jobs={n_jobs}') for n_jobs, result in runs.items()}
    first = _bitwise(runs[args.n_jobs[0]])
    for n_jobs, result in runs.items():
        _check(_bitwise(result) == first, f'n_jobs={n_jobs} is not bit-identical to n_jobs={args.n_jobs[0]}')

    pool = reference['pairs']
    calendar = sorted({d for s in {s for p in pool for s in p} for d in processed[s].index
                       if d > _align_ts(PAIR_SELECTION_CUTOFF, d)})
    dates = calendar[::90]
    max_p = CompleteFixedRussell3000TradingSystem.RESEL_RECENT_MAX_P
    start = time.perf_counter()
    ref_rows = reselection_tests(reference_cls(), processed, pool, dates, max_p)
    ref_seconds = time.perf_counter() - start
    start = time.perf_counter()
    new_rows = reselection_tests(FixedPrimeFundPairSelector(), processed, pool, dates, max_p)
    new_seconds = time.perf_counter() - start
    _check([r[0] for r in new_rows] == [r[0] for r in ref_rows], 're-selection: a decision differs')
    resel_diff = {
        name: max([abs(a[i] - b[i]) for a, b in zip(ref_rows, new_rows) if a[i] is not None] or [0.0])
        for i, name in ((1, 'two_year_pvalue'), (2, 'recent_pvalue'))}
    decisions = pd.Series([r[0] for r in new_rows]).value_counts().to_dict()

    report = {
        'reference_revision': _git('rev-parse', args.reference),
        'tree_commit': _git('rev-parse', 'HEAD'),
        'tree_dirty': _git('status', '--porcelain', '--untracked-files=no') != '',
        'formation_cutoff': PAIR_SELECTION_CUTOFF,
        'formation_symbols': len(data),
        'screened_universe': len(reference['universe']),
        'pairs_searched': len(reference['universe']) * (len(reference['universe']) - 1) // 2,
        'selected_pairs': len(reference['pairs']),
        'fdr_diagnostic': reference['fdr'],
        'selection': {
            'identical_decisions': True,
            'bit_identical_across_n_jobs': args.n_jobs,
            'max_abs_diff_vs_reference': {f'n_jobs={k}': v for k, v in diffs.items()},
        },
        'reselection': {
            'dates': [str(pd.Timestamp(d).date()) for d in dates],
            'tests': len(new_rows),
            'decisions': {str(k): int(v) for k, v in decisions.items()},
            'identical_decisions': True,
            'max_abs_diff_vs_reference': resel_diff,
            'seconds': {'reference': round(ref_seconds, 1), 'this_tree': round(new_seconds, 1)},
        },
        'selection_seconds': {'reference': round(reference['seconds'], 1),
                              **{f'n_jobs={k}': round(r['seconds'], 1) for k, r in runs.items()}},
        'speedup': {f'n_jobs={k}': round(reference['seconds'] / r['seconds'], 1) for k, r in runs.items()},
        'machine': {'cpu_count': os.cpu_count(), 'load_average_start': [round(x, 2) for x in load_start],
                    'load_average_end': [round(x, 2) for x in os.getloadavg()]},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps({k: report[k] for k in ('selected_pairs', 'selection', 'selection_seconds', 'speedup')},
                     indent=2))
    print(f'ALL CHECKS PASS -> {out_path}')


if __name__ == '__main__':
    main()
