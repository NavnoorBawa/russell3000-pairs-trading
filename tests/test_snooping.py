"""Tests for pairs_trading.snooping — data-snooping tests over a family of variants.

Hermetic: synthetic returns, fixed seeds. Covers the stationary bootstrap (index
generator, block-sum shortcut, Politis-Romano variance kernel, block rule), Hansen's SPA
against a brute-force implementation and against arch.bootstrap.SPA on pre-scaled
differentials, the effect of studentization, the Romano-Wolf stepdown against a literal
implementation of Algorithm 4.1, the MCS wrapper's guards around arch, and a small
size / power simulation with a planted superior variant.
"""
import numpy as np
import pandas as pd
import pytest
from arch.bootstrap import SPA, RealityCheck, optimal_block_length

import arch.bootstrap
from pairs_trading.snooping import (
    _REP_CHUNK, _resampled_moments, _stationary_draws, model_confidence_set, romano_wolf,
    sharpe_losses, spa_test, stationary_block_length, stationary_bootstrap_indices,
    stationary_bootstrap_lrv,
)


def _ar1(phi, n, rng, sd=1.0, burn=200):
    e = rng.normal(0.0, sd, n + burn)
    x = np.zeros_like(e)
    for t in range(1, len(e)):
        x[t] = phi * x[t - 1] + e[t]
    return x[burn:]


def _family(rng, T=500, vol=(0.5, 1.0, 1.5, 2.0, 1.0, 1.0, 1.0),
            mu=(6e-4, 4e-4, 0.0, 0.0, -4e-4, -2.5e-3, -3e-3)):
    """Correlated variants with unequal volatility: a leader, near-zero ones, a mildly
    poor one (inside Hansen's recentring band) and two clearly poor ones."""
    common = rng.normal(0.0, 0.01, T)
    vol, mu = np.asarray(vol) * 0.01, np.asarray(mu)
    return 0.5 * common[:, None] + vol * rng.normal(0.0, 1.0, (T, len(vol))) + mu


# ── stationary bootstrap ─────────────────────────────────────────────────────

def test_indices_shape_range_and_determinism():
    idx = stationary_bootstrap_indices(200, 4, 600, seed=1)
    assert idx.shape == (600, 200) and idx.dtype == np.int64
    assert idx.min() >= 0 and idx.max() < 200
    assert np.array_equal(idx, stationary_bootstrap_indices(200, 4, 600, seed=1))
    assert not np.array_equal(idx, stationary_bootstrap_indices(200, 4, 600, seed=2))
    gen = np.random.default_rng(1)
    assert np.array_equal(idx, stationary_bootstrap_indices(200, 4, 600, seed=gen))


@pytest.mark.parametrize('block', [1, 2.5, 5, 20])
def test_indices_have_geometric_blocks_and_uniform_marginals(block):
    """A step continues the current block (idx + 1 mod n) with probability 1 - 1/B, plus
    1/(B n) for a new block that happens to start there; every index is equally likely."""
    n = 150
    idx = stationary_bootstrap_indices(n, block, 4000, seed=3)
    cont = np.mean(idx[:, 1:] == (idx[:, :-1] + 1) % n)
    assert cont == pytest.approx((1 - 1 / block) + 1 / (block * n), abs=0.006)
    counts = np.bincount(idx.ravel(), minlength=n) / idx.size
    assert np.abs(counts * n - 1).max() < 0.08


def test_block_sum_shortcut_matches_explicit_resamples():
    """_resampled_moments (prefix-sum block sums) equals the moments of d[idx] for the
    resamples stationary_bootstrap_indices draws with the same seed, and its natural
    variance equals the brute-force block formula."""
    rng = np.random.default_rng(4)
    T, B, reps = 120, 3, 2 * _REP_CHUNK + 17
    e = rng.normal(0.0, 1.0, (T, 3))
    e -= e.mean(axis=0)
    means, lrv = _resampled_moments(e, B, reps, np.random.default_rng(9), natural_variance=True)
    idx = stationary_bootstrap_indices(T, B, reps, seed=9)
    assert np.allclose(means, e[idx].mean(axis=1), atol=1e-14)
    gen = np.random.default_rng(9)
    new, start = _stationary_draws(gen, T, B, _REP_CHUNK)
    b = 0
    for s in range(5):
        pos = np.flatnonzero(new[s])
        blocks = []
        for p, q in zip(pos, np.append(pos[1:], T)):
            blocks.append(e[(start[b] + np.arange(q - p)) % T])
            b += 1
        m = np.concatenate(blocks).mean(axis=0)
        natural = sum(((blk - m).sum(axis=0)) ** 2 for blk in blocks) / T
        assert np.allclose(lrv[s], natural, rtol=1e-10)


def test_kernel_lrv_is_the_bootstrap_variance_of_the_mean():
    """Politis & Romano (1994), Lemma 1: omega^2 is Var*(sqrt(T) mean*); checked against
    the double-sum formula and against the bootstrap itself (Monte Carlo); the natural
    in-resample variance has about the same expectation."""
    rng = np.random.default_rng(5)
    T = 300
    x = _ar1(0.4, T, rng)
    for B in (1, 3, 8):
        w = stationary_bootstrap_lrv(x, B)[0]
        e = x - x.mean()
        q = 1.0 / B
        direct = e @ e / T + 2 * sum(((1 - i / T) * (1 - q) ** i + (i / T) * (1 - q) ** (T - i))
                                     * (e[:-i] @ e[i:]) / T for i in range(1, T))
        assert w == pytest.approx(direct, rel=1e-10)
        means, lrv = _resampled_moments(e[:, None], B, 20000, np.random.default_rng(B), True)
        assert T * means.var() == pytest.approx(w, rel=0.04)
        assert lrv.mean() == pytest.approx(w, rel=0.08)


def test_block_rule_matches_arch_optimal_block_length():
    rng = np.random.default_rng(6)
    X = np.column_stack([_ar1(phi, 630, rng) for phi in (0.0, 0.2, 0.5)])
    assert stationary_block_length(X) == int(np.ceil(optimal_block_length(X)['stationary'].max()))
    assert stationary_block_length(X[:, 2]) == stationary_block_length(X)
    assert stationary_block_length(np.zeros((100, 2))) == 1


# ── SPA and Reality Check ────────────────────────────────────────────────────

def _brute_spa(d, block, reps, seed):
    """Hansen (2005) and White (2000) written out from the index matrix."""
    T = d.shape[0]
    dbar = d.mean(axis=0)
    omega = np.sqrt(stationary_bootstrap_lrv(d, block))
    stat = max(0.0, (np.sqrt(T) * dbar / omega).max())
    star = d[stationary_bootstrap_indices(T, block, reps, seed)].mean(axis=1)
    band = -omega * np.sqrt(2 * np.log(np.log(T)) / T)
    p = {}
    for rule, g in (('lower', np.maximum(dbar, 0)), ('consistent', np.where(dbar >= band, dbar, 0)),
                    ('upper', dbar)):
        t_star = np.maximum((np.sqrt(T) * (star - g) / omega).max(axis=1), 0)
        p[rule] = np.mean(t_star >= stat)
    rc = np.mean(np.sqrt(T) * (star - dbar).max(axis=1) > np.sqrt(T) * dbar.max())
    return p, rc


def test_spa_matches_a_brute_force_implementation():
    d = _family(np.random.default_rng(7))
    out = spa_test(d, block=3, reps=3000, seed=11)
    p, rc = _brute_spa(d, 3, 3000, 11)
    assert out['pvalues'] == pytest.approx(p, abs=1e-12)
    assert out['reality_check']['pvalue'] == pytest.approx(rc, abs=1e-12)
    assert out['pvalues']['lower'] < out['pvalues']['consistent'] < out['pvalues']['upper']
    assert out['k'] == 7 and out['block'] == 3
    assert out['best_model'] == int(np.argmax(d.mean(axis=0) / np.sqrt(stationary_bootstrap_lrv(d, 3))))


def test_spa_matches_arch_on_prescaled_differentials():
    """arch.bootstrap.SPA does not studentize (7.2.0); on differentials divided by
    omega_k it computes Hansen's studentized SPA, and must agree with spa_test to Monte
    Carlo error (different generators). The Reality Check is arch's non-studentized upper
    p-value."""
    d = _family(np.random.default_rng(7))
    T, B, reps = d.shape[0], 3, 10_000
    ours = spa_test(d, block=B, reps=reps, seed=1)
    z = d / np.sqrt(stationary_bootstrap_lrv(d, B))
    ref = SPA(np.zeros(T), -z, block_size=B, reps=reps, bootstrap='stationary', seed=2)
    ref.compute()
    for rule in ('lower', 'consistent', 'upper'):
        assert ours['pvalues'][rule] == pytest.approx(ref.pvalues[rule], abs=0.025)
    rc = RealityCheck(np.zeros(T), -d, block_size=B, reps=reps, studentize=False, seed=2)
    rc.compute()
    assert ours['reality_check']['pvalue'] == pytest.approx(rc.pvalues['upper'], abs=0.025)


def test_studentization_changes_the_answer_on_heteroskedastic_variants():
    """A low-volatility variant with a small but very significant mean (t ~ 5) among
    volatile variants: the studentized SPA finds it; the Reality Check (max of raw means)
    is driven by the volatile variants' sampling noise and does not. (Over 20 seeds of
    this design the SPA p-value never exceeded 0.017 and the Reality Check never fell
    below 0.10.)"""
    rng = np.random.default_rng(8)
    T = 750
    d = np.column_stack([rng.normal(4e-4, 0.002, T)]
                        + [rng.normal(-1e-3, 0.03, T) for _ in range(4)])
    out = spa_test(d, reps=4000, seed=3)
    assert out['best_model'] == 0 and out['best_tstat'] > 3
    assert out['pvalues']['consistent'] < 0.02
    assert out['reality_check']['pvalue'] > 0.1


def test_spa_is_one_when_no_variant_beats_the_benchmark():
    rng = np.random.default_rng(9)
    d = rng.normal(-2e-3, 0.01, (400, 5))
    out = spa_test(d, reps=500)
    assert out['statistic'] == 0.0
    assert out['pvalues'] == {'lower': 1.0, 'consistent': 1.0, 'upper': 1.0}


def test_spa_benchmark_alignment_and_validation():
    rng = np.random.default_rng(10)
    R = pd.DataFrame(rng.normal(3e-4, 0.01, (300, 3)), columns=['a', 'b', 'c'])
    bench = rng.normal(1e-4, 0.01, 300)
    with_bench = spa_test(R, benchmark=bench, reps=800)
    as_diff = spa_test(R.to_numpy() - bench[:, None], reps=800)
    assert with_bench['pvalues'] == as_diff['pvalues']
    assert with_bench['best_model'] in ('a', 'b', 'c') and with_bench['benchmark'] == 'series'
    holed = R.copy()
    holed.iloc[5, 1] = np.nan
    assert spa_test(holed, reps=100)['n'] == 299
    with pytest.raises(ValueError):
        spa_test(R, benchmark=bench[:-1])
    with pytest.raises(ValueError):
        spa_test(R.iloc[:10])


def test_identical_and_constant_differentials():
    """A variant identical to the benchmark has t = 0; one ahead by the same amount every
    day is certain (t = inf)."""
    rng = np.random.default_rng(12)
    R = np.column_stack([np.zeros(300), rng.normal(0.0, 0.01, 300)])
    out = spa_test(R, reps=300)
    assert np.isfinite(out['best_tstat'])
    sure = np.column_stack([np.full(300, 1e-4), rng.normal(0.0, 0.01, 300)])
    out = spa_test(sure, reps=300)
    assert out['best_model'] == 0 and out['best_tstat'] == np.inf
    assert out['pvalues']['consistent'] == 0.0


# ── Romano-Wolf stepdown ─────────────────────────────────────────────────────

def _brute_romano_wolf(d, block, reps, seed):
    """Studentized StepM written out: natural variance per resample from its blocks,
    Romano & Wolf (2016) Algorithm 4.1 step by step."""
    T, K = d.shape
    dbar = d.mean(axis=0)
    t = np.sqrt(T) * dbar / np.sqrt(stationary_bootstrap_lrv(d, block))
    rng = np.random.default_rng(seed)
    t_star = np.empty((reps, K))
    for s0 in range(0, reps, _REP_CHUNK):
        m = min(_REP_CHUNK, reps - s0)
        new, start = _stationary_draws(rng, T, block, m)
        b = 0
        for s in range(m):
            pos = np.flatnonzero(new[s])
            blocks = []
            for p, q in zip(pos, np.append(pos[1:], T)):
                blocks.append(d[(start[b] + np.arange(q - p)) % T])
                b += 1
            mean = np.concatenate(blocks).mean(axis=0)
            var = sum(((blk - mean).sum(axis=0)) ** 2 for blk in blocks) / T
            t_star[s0 + s] = np.sqrt(T) * (mean - dbar) / np.sqrt(var)
    order = np.argsort(-t)
    p_adj, previous = np.empty(K), 0.0
    for j, k in enumerate(order):
        p_init = (np.sum(t_star[:, order[j:]].max(axis=1) > t[k]) + 1) / (reps + 1)
        previous = max(previous, p_init)
        p_adj[k] = previous
    return t, p_adj


def test_romano_wolf_matches_algorithm_4_1_written_out():
    d = _family(np.random.default_rng(13), T=200)
    out = romano_wolf(d, block=3, reps=600, seed=5)
    t, p_adj = _brute_romano_wolf(d, 3, 600, 5)
    assert np.allclose(out['table']['tstat'], t, rtol=1e-12)
    assert np.allclose(out['table']['p_adjusted'], p_adj, atol=1e-12)


def test_romano_wolf_adjusted_pvalues_are_monotone_and_conservative():
    d = pd.DataFrame(_family(np.random.default_rng(14)), columns=list('abcdefg'))
    out = romano_wolf(d, reps=2000)
    tab = out['table'].sort_values('tstat', ascending=False)
    assert (np.diff(tab['p_adjusted'].to_numpy()) >= 0).all()
    assert (tab['p_adjusted'] >= tab['p_raw'] - 1e-12).all()
    assert list(out['table'].index) == list('abcdefg')
    assert out['rejected'] == list(tab.index[tab['rejected']])
    one = romano_wolf(d[['a']], reps=2000)['table'].iloc[0]
    assert one['p_adjusted'] == one['p_raw']


def test_romano_wolf_identifies_a_planted_variant():
    rng = np.random.default_rng(15)
    T = 600
    common = rng.normal(0.0, 0.01, (T, 1))
    R = 0.6 * common + 0.008 * rng.normal(0.0, 1.0, (T, 8))
    R[:, 3] += 3.5 * 0.01 / np.sqrt(252)                  # annual Sharpe ~ 3.5
    out = romano_wolf(R, reps=2000, seed=1)
    assert out['rejected'] == [3]
    assert out['table']['p_adjusted'].drop(3).min() > 0.05


# ── size and power ───────────────────────────────────────────────────────────

def test_size_and_power_with_a_planted_superior_variant():
    """150 families of 8 correlated variants (T = 400, unequal volatility), 199 bootstrap
    resamples each. Under the null (all means 0) SPA and StepM reject about 5% of the
    time; with one variant at an annual Sharpe of 4 both find it nearly always and StepM
    rarely rejects a null variant."""
    rng = np.random.default_rng(16)
    T, K, M, reps = 400, 8, 150, 199
    vols = np.linspace(0.5, 2.0, K) * 0.01

    def family(edge):
        R = 0.7 * rng.normal(0.0, 1.0, (T, 1)) * vols + 0.7 * rng.normal(0.0, 1.0, (T, K)) * vols
        R[:, 0] += edge * vols[0] / np.sqrt(252)
        return R

    null_spa = null_rw = power_spa = found = false_alarm = 0
    for m in range(M):
        R0, R1 = family(0.0), family(4.0)
        null_spa += spa_test(R0, reps=reps, seed=m)['pvalues']['consistent'] <= 0.05
        null_rw += len(romano_wolf(R0, reps=reps, seed=m)['rejected']) > 0
        power_spa += spa_test(R1, reps=reps, seed=m)['pvalues']['consistent'] <= 0.05
        rej = romano_wolf(R1, reps=reps, seed=m)['rejected']
        found += 0 in rej
        false_alarm += any(k != 0 for k in rej)
    assert null_spa / M <= 0.11 and null_rw / M <= 0.11
    assert power_spa / M >= 0.85 and found / M >= 0.85
    assert false_alarm / M <= 0.11


# ── Model Confidence Set ─────────────────────────────────────────────────────

def _losses(rng, T=600, means=(0.0, 0.02, 0.3, 0.6)):
    return pd.DataFrame(rng.normal(0.0, 1.0, (T, len(means))) + np.asarray(means),
                        columns=[f'm{i}' for i in range(len(means))])


@pytest.mark.parametrize('method', ['R', 'max'])
def test_mcs_excludes_clearly_worse_models(method):
    L = _losses(np.random.default_rng(17))
    out = model_confidence_set(L, size=0.10, method=method, reps=2000, seed=1)
    assert {'m2', 'm3'} <= set(out['excluded'])
    assert 'm0' in out['included']
    assert max(out['pvalues'].values()) == 1.0
    assert out == model_confidence_set(L, size=0.10, method=method, reps=2000, seed=1)
    assert out['included'] + out['excluded'] != [] and out['k'] == 4


def test_mcs_survives_duplicate_models():
    """arch 7.2.0's method 'R' divides 0 by 0 on identical columns and fails; each copy
    must get its original's p-value."""
    L = _losses(np.random.default_rng(18))
    L['m0_copy'] = L['m0']
    out = model_confidence_set(L, method='R', reps=1000)
    assert out['pvalues']['m0_copy'] == out['pvalues']['m0']
    assert ('m0_copy' in out['included']) == ('m0' in out['included'])
    single = model_confidence_set(pd.DataFrame({'a': L['m1'], 'b': L['m1']}), reps=100)
    assert single['pvalues'] == {'a': 1.0, 'b': 1.0}


def test_mcs_includes_a_model_whose_pvalue_equals_the_size(monkeypatch):
    """Hansen, Lunde & Nason: the MCS is {i: p_i >= size}; arch's .included uses '>'."""
    class FakeMCS:
        def __init__(self, losses, **kwargs):
            self.k = losses.shape[1]

        def compute(self):
            self.pvalues = pd.DataFrame({'Pvalue': [0.05, 0.10, 1.0][:self.k]})

    monkeypatch.setattr(arch.bootstrap, 'MCS', FakeMCS)
    out = model_confidence_set(_losses(np.random.default_rng(19), means=(0, 0, 0)), size=0.10)
    assert out['included'] == ['m1', 'm2'] and out['excluded'] == ['m0']


def test_mcs_validation():
    L = _losses(np.random.default_rng(20))
    with pytest.raises(ValueError):
        model_confidence_set(L, method='T')
    with pytest.raises(ValueError):
        model_confidence_set(L[['m0']])
    with pytest.raises(ValueError):
        model_confidence_set(L.iloc[:10])


def test_sharpe_losses_put_variants_on_a_sharpe_scale():
    rng = np.random.default_rng(21)
    R = pd.DataFrame({'lo': rng.normal(5e-4, 0.005, 500), 'hi': rng.normal(5e-4, 0.05, 500),
                      'flat': np.zeros(500)})
    R.iloc[3, 0] = np.nan
    L = sharpe_losses(R)
    assert list(L.columns) == ['lo', 'hi', 'flat'] and np.isnan(L.iloc[3, 0])
    for c in ('lo', 'hi'):
        assert L[c].mean() == pytest.approx(-R[c].mean() / R[c].std(ddof=1))
        assert L[c].std(ddof=1) == pytest.approx(1.0)
    assert (L['flat'] == 0).all()
    assert np.allclose(sharpe_losses(R.to_numpy()), L.to_numpy(), equal_nan=True)
