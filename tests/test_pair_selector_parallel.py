"""The all-pairs search of FixedPrimeFundPairSelector over worker processes.

Hermetic: a 40-symbol synthetic market (pairs_trading/synthetic.py), no data files. The
selection, its order, the pair statistics and the FDR diagnostic's p-value list must be
identical, value for value and type for type, whatever the number of workers; the work
is split into a few tasks that each carry only their own symbols' data.
"""
import itertools
import os

import numpy as np
import pandas as pd
import pytest

from pairs_trading import pair_selector
from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
from pairs_trading.pair_selector import (
    PAIR_TEST_COLUMNS, FixedPrimeFundPairSelector, _test_pair_block, pair_blocks, resolve_n_jobs,
)
from pairs_trading.synthetic import make_market


@pytest.fixture(scope='module')
def market():
    proc = EnhancedRussell3000DataProcessor.__new__(EnhancedRussell3000DataProcessor)
    frames, _, planted = make_market(n_pairs=8, n_noise=24, seed=5, end='2022-12-31')
    # one late listing, so the legs of some pairs have different date sets
    frames['SN23'] = frames['SN23'].iloc[150:]
    return {s: proc._process_indicators(df) for s, df in frames.items()}, planted


def _canonical(obj):
    """Value-and-type form of a result: floats by their bits, containers in their order."""
    if isinstance(obj, dict):
        return ('dict', tuple((k, _canonical(v)) for k, v in obj.items()))
    if isinstance(obj, (list, tuple)):
        return (type(obj).__name__, tuple(_canonical(v) for v in obj))
    if isinstance(obj, (float, np.floating)):
        return (type(obj).__name__, float(obj).hex())
    return (type(obj).__name__, obj)


def _new_selector(n_jobs):
    selector = FixedPrimeFundPairSelector()
    selector.n_jobs = n_jobs
    selector.cointegration_threshold = 0.10      # non-default: workers must use the instance's
    return selector


def _reference_pair_loop(selector, data, quality_symbols):
    """The v32 serial all-pairs loop, verbatim: (selected pairs, pair statistics, FDR p-values)."""
    pca_residuals = selector.compute_pca_residuals(data, quality_symbols, n_components=5)
    valid_pairs, pvalues = [], []
    for symbol1, symbol2 in itertools.combinations(quality_symbols, 2):
        try:
            data1, data2 = data[symbol1], data[symbol2]
            if len(data1.index.intersection(data2.index)) < selector.min_common_days:
                continue
            correlation = selector.calculate_correlation(data1, data2)
            if correlation < selector.correlation_threshold:
                continue
            is_cointegrated, coint_pvalue = selector.test_cointegration(data1, data2)
            if coint_pvalue is not None and np.isfinite(coint_pvalue):
                pvalues.append(coint_pvalue)
            if not is_cointegrated:
                continue
            half_life = selector.calculate_half_life(data1, data2)
            if not (selector.min_half_life <= half_life <= selector.max_half_life):
                continue
            pca_cointegrated = False
            if symbol1 in pca_residuals and symbol2 in pca_residuals:
                try:
                    pca_ok, _ = selector.test_cointegration(pca_residuals[symbol1], pca_residuals[symbol2])
                    pca_cointegrated = pca_ok
                except Exception:
                    pass
            quality_score = selector._calculate_balanced_quality_score(
                correlation, coint_pvalue, half_life, data1, data2, pca_cointegrated=pca_cointegrated)
            if quality_score > 0.4:
                valid_pairs.append({'symbols': (symbol1, symbol2), 'score': quality_score, 'stats': {
                    'correlation': correlation, 'cointegration_pvalue': coint_pvalue,
                    'half_life': half_life, 'quality_score': quality_score,
                    'pca_cointegrated': pca_cointegrated}})
        except Exception:
            continue
    valid_pairs.sort(key=lambda x: x['score'], reverse=True)
    return ([p['symbols'] for p in valid_pairs],
            {f"{a}-{b}": p['stats'] for p in valid_pairs for a, b in [p['symbols']]}, np.asarray(pvalues))


@pytest.fixture(scope='module')
def selections(market):
    """find_quality_pairs with 1 and 4 workers (each with the p-values handed to BH-FDR and
    the joblib pools it opened), and the reference loop on the same quality symbols."""
    import statsmodels.stats.multitest as multitest
    data, _ = market
    original_fdr, original_parallel = multitest.multipletests, pair_selector.Parallel
    out = {}
    try:
        for n_jobs in (1, 4):
            seen, pools = [], []

            def recording(pvals, *args, **kwargs):
                seen.append(np.asarray(pvals, dtype=float).copy())
                return original_fdr(pvals, *args, **kwargs)

            def pool(**kwargs):
                pools.append(kwargs)
                return original_parallel(**kwargs)

            multitest.multipletests, pair_selector.Parallel = recording, pool
            selector = _new_selector(n_jobs)
            out[n_jobs] = (selector, selector.find_quality_pairs(data), seen[0], pools)
    finally:
        multitest.multipletests, pair_selector.Parallel = original_fdr, original_parallel
    out['reference'] = _reference_pair_loop(_new_selector(1), data, out[1][0].last_quality_symbols)
    return out


def test_selection_is_identical_for_any_number_of_workers(market, selections):
    _, planted = market
    serial, pairs1, pvals1, pools1 = selections[1]
    parallel, pairs4, pvals4, pools4 = selections[4]
    assert len(serial.last_quality_symbols) == 40
    assert pools1 == [] and [p['n_jobs'] for p in pools4] == [4]       # in-process vs 4 workers

    assert set(planted) <= set(pairs1) and len(pairs1) > len(planted)
    assert pairs4 == pairs1
    assert _canonical(parallel.pair_statistics) == _canonical(serial.pair_statistics)
    assert _canonical(parallel.fdr_diagnostic) == _canonical(serial.fdr_diagnostic)
    assert parallel.last_quality_symbols == serial.last_quality_symbols
    assert pvals1.size == serial.fdr_diagnostic['pairs_tested'] > 100
    assert pvals4.tobytes() == pvals1.tobytes()


def test_blocked_search_reproduces_the_serial_pair_loop(selections):
    """Same pairs in the same order, same statistics, same FDR p-values in the same order
    as the single loop over itertools.combinations that the blocks replaced."""
    parallel, pairs4, pvals4, _ = selections[4]
    ref_pairs, ref_stats, ref_pvals = selections['reference']
    assert pairs4 == ref_pairs
    assert _canonical(parallel.pair_statistics) == _canonical(ref_stats)
    assert pvals4.tobytes() == ref_pvals.tobytes()


def test_pair_tests_run_with_one_blas_thread(market):
    from threadpoolctl import threadpool_info, threadpool_limits
    data, _ = market
    seen = []

    class Recording(FixedPrimeFundPairSelector):
        def _test_pair(self, *args):
            seen.extend(pool['num_threads'] for pool in threadpool_info())
            return None, None

    with threadpool_limits(limits=2):
        _test_pair_block(Recording(), data, {}, [('SA00', 'SB00'), ('SA01', 'SB01')])
    assert seen and set(seen) == {1}


def test_pair_blocks_partition_the_pairs_in_combinations_order():
    for n_symbols in (2, 3, 7, 50, 120, 300):
        for n_jobs in (1, 2, 4, 16):
            blocks = pair_blocks(n_symbols, n_jobs)
            flat = [pair for block in blocks for pair in block]
            assert sorted(flat) == list(itertools.combinations(range(n_symbols), 2))
            assert all(block == sorted(block) for block in blocks)
            if len(blocks) > 1:
                assert len(flat) >= 250 * len(blocks)
                assert len(blocks) < 8 * n_jobs + 4 * np.sqrt(n_jobs) + 1
    assert len(pair_blocks(300, 4)) == 36          # 8 groups of ~37 symbols
    assert len(pair_blocks(300, 1)) == 10
    assert len(pair_blocks(24, 4)) == 1             # 276 pairs: one task, run in-process


def test_each_task_carries_only_its_symbols_test_columns():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range('2020-01-01', periods=60, tz='America/New_York')
    symbols = [f'S{k:03d}' for k in range(120)]
    data = {s: pd.DataFrame({'Open': 1.0, 'Close': rng.uniform(10, 20, 60), 'Volume': 1e6,
                             'Returns': rng.normal(0, 0.01, 60), 'MA_50': 15.0}, index=idx)
            for s in symbols}
    pca = {s: data[s][['Close', 'Returns']] * 0.5 for s in symbols[::3]}
    selector = FixedPrimeFundPairSelector()
    selector.n_jobs = 4
    tasks = selector._pair_tasks(data, symbols, pca)
    assert len(tasks) == len(pair_blocks(120, 4)) == 28              # 7 groups of 17-18 symbols
    assert sorted(p for _, _, pairs in tasks for p in pairs) == list(itertools.combinations(symbols, 2))
    for frames, pca_frames, pairs in tasks:
        names = {s for pair in pairs for s in pair}
        assert set(frames) == names and len(names) <= 36             # two groups, never the universe
        assert set(pca_frames) == names & set(pca)
        for sym, frame in frames.items():
            pd.testing.assert_frame_equal(frame, data[sym][list(PAIR_TEST_COLUMNS)])
        for sym, frame in pca_frames.items():
            assert frame is pca[sym]


def test_a_failing_later_test_keeps_the_pairs_p_value(market):
    """As in the serial loop through v32: a pair whose half-life step raises still counts in
    the FDR diagnostic with the p-value it obtained, and is not selected."""
    data, planted = market
    a, b = sorted(planted)[0]
    selector = FixedPrimeFundPairSelector()
    p_ok, stats_ok = selector._test_pair(data[a], data[b])
    assert p_ok is not None and stats_ok is not None

    def broken(*args):
        raise RuntimeError('half-life failed')

    selector.calculate_half_life = broken
    assert selector._test_pair(data[a], data[b]) == (p_ok, None)


def test_n_jobs_switch(monkeypatch):
    monkeypatch.delenv('PAIRS_N_JOBS', raising=False)
    assert resolve_n_jobs() == min(4, os.cpu_count() or 1)
    monkeypatch.setenv('PAIRS_N_JOBS', '3')
    assert resolve_n_jobs() == 3
    assert FixedPrimeFundPairSelector().n_jobs == 3
    for bad in ('0', '-2', 'four', '2.5'):
        monkeypatch.setenv('PAIRS_N_JOBS', bad)
        with pytest.raises(ValueError, match='PAIRS_N_JOBS'):
            resolve_n_jobs()


def test_worker_count_is_recorded_but_does_not_make_a_variant(monkeypatch, tmp_path):
    """PAIRS_N_JOBS is in the provenance block, and a run with any value is a headline run."""
    from pairs_trading import json_export
    for value in ('1', '2', '16'):
        monkeypatch.setenv('PAIRS_N_JOBS', value)
        run_config = json_export.build_run_config(data_file=str(tmp_path / 'no_cache.pkl'))
        assert run_config['env']['PAIRS_N_JOBS'] == value
        assert json_export.non_default_switches(run_config) == []
