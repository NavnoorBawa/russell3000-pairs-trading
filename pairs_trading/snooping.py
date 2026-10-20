"""
DATA-SNOOPING TESTS OVER A DECLARED FAMILY OF STRATEGY VARIANTS
===============================================================
significance.py tests one return series. A configuration chosen from a search over many
is tested here against the search itself: the family of variants is declared before any
result is seen, and each test below accounts for every member of it.

Input: a T x K matrix R of per-period returns of K variants on the same dates, and an
optional benchmark return series (default: zero, "no variant beats cash"). Losses are
L = -r, so the performance of variant k relative to the benchmark on day t is the return
differential d_kt = r_kt - r_bench,t (Hansen 2005, Sec. 2). Rows with a non-finite entry
in any column or in the benchmark are dropped.

Methods:
  - Stationary bootstrap (Politis & Romano 1994): resamples are concatenations of blocks
    with Geometric(1/B) lengths starting at uniform positions (wrapping circularly). One
    index set per resample is shared by all columns, so cross-correlation is preserved.
    Block rule, fixed in advance: B = ceil(max over columns of the Politis-White (2004) /
    Patton-Politis-White (2009) stationary-bootstrap length of the mean).
  - Hansen (2005) test of Superior Predictive Ability, studentized by omega_k, the long-
    run standard deviation the stationary bootstrap implies (Politis & Romano 1994,
    Lemma 1), with lower, consistent and upper p-values; White (2000) Reality Check (the
    non-studentized upper p-value).
  - Romano & Wolf (2005) studentized stepdown (StepM), with the adjusted p-values of
    Romano & Wolf (2016), Algorithm 4.1: which variants, if any, beat the benchmark with
    family-wise error control.
  - Hansen, Lunde & Nason (2011) Model Confidence Set, through arch.bootstrap.MCS.

On arch: arch.bootstrap.SPA and StepM (7.2.0 and 8.0.0, the latest release as of
October 2026) accept studentize=True but compute their statistics from the raw mean
differentials — the variance they estimate only sets the consistent-recentring
threshold; the fix is on arch's main branch only. The SPA here studentizes itself; arch.bootstrap.SPA run on differentials
pre-scaled by omega_k reproduces its p-values to Monte Carlo error
(tests/test_snooping.py). arch.bootstrap.MCS is used as is, with two guards
(model_confidence_set).

Report the declared family and the block rule with any result, never select a shipped
configuration from these outputs, and never drop variants after the fact (the
consistent SPA p-value and the stepdown already discount poor ones).

References:
  Politis & Romano (1994) "The Stationary Bootstrap", JASA 89(428): 1303-1313.
  White (2000) "A Reality Check for Data Snooping", Econometrica 68(5): 1097-1126.
  Hansen (2005) "A Test for Superior Predictive Ability", JBES 23(4): 365-380; Hansen,
    Kim & Lunde (2003) "Testing for Superior Predictive Ability using Ox" (manual).
  Romano & Wolf (2005) "Stepwise Multiple Testing as Formalized Data Snooping",
    Econometrica 73(4): 1237-1282 (working paper: econ-papers.upf.edu/papers/712.pdf).
  Romano & Wolf (2016) "Efficient computation of adjusted p-values for resampling-based
    stepdown multiple testing", Statistics & Probability Letters 113: 38-40.
  Götze & Künsch (1996) "Second-order correctness of the blockwise bootstrap for
    stationary observations", Annals of Statistics 24(5).
  Hansen, Lunde & Nason (2011) "The Model Confidence Set", Econometrica 79(2): 453-497.
"""

from pairs_trading.config import pd, np
from pairs_trading.significance import politis_white_block_length

# Resamples drawn from the generator at a time. Fixed, so a seed gives the same resamples
# whatever the number of columns, and stationary_bootstrap_indices reproduces them.
_REP_CHUNK = 256
# Block sums (blocks x columns) held in memory at once.
_CELL_BUDGET = 4_000_000


# ──────────────────────────────────────────────────────────────────────────────
# Stationary bootstrap
# ──────────────────────────────────────────────────────────────────────────────

def stationary_block_length(X) -> int:
    """Block rule B = ceil(max over columns of the Politis-White stationary length), >= 1.

    politis_white_block_length(x, 'stationary') is the expected block length that
    minimises the MSE of the stationary-bootstrap variance of the mean of x (Politis &
    White 2004 with the Patton, Politis & White 2009 correction; it equals
    arch.bootstrap.optimal_block_length). Taking the largest over the columns keeps the
    dependence of the most persistent series.
    """
    M = np.asarray(X, dtype=float)
    if M.ndim == 1:
        M = M[:, None]
    return int(np.ceil(max(politis_white_block_length(M[:, k], 'stationary')
                           for k in range(M.shape[1]))))


def _stationary_draws(rng, n: int, block: float, n_samples: int):
    """Raw draws of `n_samples` stationary-bootstrap resamples of length n.

    new[s, t] is True where resample s starts a block at position t (always at t = 0,
    else with probability 1/block); start holds each block's uniform first index, in
    row-major order of `new`.
    """
    new = rng.random((n_samples, n)) < 1.0 / block
    new[:, 0] = True
    start = rng.integers(0, n, size=int(new.sum()))
    return new, start


def _block_lengths(row: np.ndarray, pos: np.ndarray, n: int) -> np.ndarray:
    """Length of each block given its resample (row) and first position (pos)."""
    end = np.empty_like(pos)
    end[:-1] = pos[1:]
    last = np.ones(len(row), dtype=bool)
    last[:-1] = row[1:] != row[:-1]
    end[last] = n
    return end - pos


def stationary_bootstrap_indices(n: int, block: float, n_samples: int, seed=42) -> np.ndarray:
    """(n_samples, n) index matrix of stationary-bootstrap resamples (Politis & Romano 1994).

    Each resample is a concatenation of blocks of consecutive observations (wrapping from
    the last observation to the first) whose lengths are Geometric with mean `block` and
    whose starting points are uniform. seed: an int or a numpy Generator. The resamples
    are the ones spa_test and romano_wolf draw with the same seed and block.
    """
    if n < 1 or n_samples < 0:
        raise ValueError("need n >= 1 and n_samples >= 0")
    block = max(1.0, float(block))
    rng = np.random.default_rng(seed)
    out = np.empty((n_samples, n), dtype=np.int64)
    t = np.arange(n)
    for s in range(0, n_samples, _REP_CHUNK):
        m = min(_REP_CHUNK, n_samples - s)
        new, start = _stationary_draws(rng, n, block, m)
        flat = new.ravel()
        bid = (np.cumsum(flat) - 1).reshape(m, n)       # block id of every position
        first_pos = np.flatnonzero(flat) % n            # position of each block's start
        out[s:s + m] = (start[bid] + t[None, :] - first_pos[bid]) % n
    return out


def stationary_bootstrap_lrv(X, block: float) -> np.ndarray:
    """Long-run variance of each column implied by the stationary bootstrap.

    The variance of sqrt(T) times a stationary-bootstrap mean, given the data (Politis &
    Romano 1994, Lemma 1), used by Hansen (2005) as omega_k^2:
        omega^2 = g(0) + 2 sum_{i=1}^{T-1} kappa(T, i) g(i),
        kappa(T, i) = (1 - i/T) (1 - q)^i + (i/T) (1 - q)^(T - i),  q = 1 / block,
    with g(i) the sample autocovariances (divisor T). Same kernel as arch's SPA.
    """
    M = np.asarray(X, dtype=float)
    if M.ndim == 1:
        M = M[:, None]
    T = M.shape[0]
    e = M - M.mean(axis=0)
    f = np.fft.rfft(e, n=2 * T, axis=0)
    acov = np.fft.irfft(f * np.conj(f), n=2 * T, axis=0)[:T] / T
    i = np.arange(1, T)
    q = 1.0 / max(1.0, float(block))
    kappa = (1.0 - i / T) * (1.0 - q) ** i + (i / T) * (1.0 - q) ** (T - i)
    return acov[0] + 2.0 * kappa @ acov[1:]


def _resampled_moments(e: np.ndarray, block: float, reps: int, rng, natural_variance: bool):
    """Means of the centred columns `e` over `reps` stationary-bootstrap resamples.

    Block sums come from prefix sums of the series laid twice end to end, so a resample
    costs O(blocks x columns), not O(T x columns). With natural_variance, also returns
    each resample's own long-run variance estimate, the "natural" block-bootstrap
    variance of Götze & Künsch (1996): sum over the resample's blocks of
    (block sum - block length x resample mean)^2, divided by T. Its expectation under
    the stationary bootstrap has the lag weights (1 - 1/block)^i of omega^2.
    Returns (reps x K means, reps x K variances or None).
    """
    T, K = e.shape
    prefix = np.zeros((2 * T + 1, K))
    prefix[1:] = np.cumsum(np.concatenate([e, e]), axis=0)
    means = np.empty((reps, K))
    lrv = np.empty((reps, K)) if natural_variance else None
    for s in range(0, reps, _REP_CHUNK):
        m = min(_REP_CHUNK, reps - s)
        new, start = _stationary_draws(rng, T, block, m)
        row, pos = np.nonzero(new)
        length = _block_lengths(row, pos, T)
        first = np.flatnonzero(np.r_[True, row[1:] != row[:-1]])
        width = max(1, _CELL_BUDGET // len(start))
        for c in range(0, K, width):
            cols = slice(c, c + width)
            S = prefix[start + length, cols] - prefix[start, cols]
            mu = np.add.reduceat(S, first, axis=0) / T
            means[s:s + m, cols] = mu
            if natural_variance:
                dev = S - length[:, None] * mu[row]
                lrv[s:s + m, cols] = np.add.reduceat(dev * dev, first, axis=0) / T
    return means, lrv


# ──────────────────────────────────────────────────────────────────────────────
# Inputs
# ──────────────────────────────────────────────────────────────────────────────

def _differentials(R, benchmark):
    """(model names, T x K differentials r_k - r_bench) on the rows finite everywhere."""
    if isinstance(R, pd.DataFrame):
        names = list(R.columns)
        X = R.to_numpy(dtype=float)
    else:
        X = np.asarray(R, dtype=float)
        if X.ndim == 1:
            X = X[:, None]
        names = list(range(X.shape[1]))
    if X.ndim != 2 or X.shape[1] < 1:
        raise ValueError("R must be a T x K matrix of returns")
    b = np.zeros(X.shape[0]) if benchmark is None else np.asarray(benchmark, dtype=float).ravel()
    if b.shape[0] != X.shape[0]:
        raise ValueError("benchmark must have one return per row of R (align dates first)")
    keep = np.isfinite(X).all(axis=1) & np.isfinite(b)
    d = X[keep] - b[keep, None]
    if d.shape[0] < 20:
        raise ValueError(f"need at least 20 finite rows, got {d.shape[0]}")
    return names, d


def _ratio(num: np.ndarray, den: np.ndarray, tol: float) -> np.ndarray:
    """num / den, with a zero-dispersion denominator read as no evidence (0) or certainty.

    A differential without dispersion is either identical to the benchmark (num = 0:
    statistic 0) or beats or trails it by the same amount every day (statistic +/- inf).
    """
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(den > tol, num / den,
                        np.where(np.abs(num) > tol, np.sign(num) * np.inf, 0.0))


def _tolerance(d: np.ndarray) -> float:
    return 1e-12 * max(float(np.max(np.abs(d))), 1e-300)


def _block(d: np.ndarray, block) -> int:
    return stationary_block_length(d) if block is None else int(max(1, block))


# ──────────────────────────────────────────────────────────────────────────────
# Hansen (2005) SPA and White (2000) Reality Check
# ──────────────────────────────────────────────────────────────────────────────

def spa_test(R, benchmark=None, block: int = None, reps: int = 10_000, seed: int = 42) -> dict:
    """Does ANY variant beat the benchmark, after accounting for the search over all K?

    H0: E[d_k] <= 0 for every k. Hansen (2005), Sec. 2:
      t_k = sqrt(T) dbar_k / omega_k, omega_k^2 = stationary_bootstrap_lrv(d_k, block);
      T_SPA = max(0, max_k t_k).
    Null distribution: on stationary-bootstrap resamples, Z*_k = dbar*_k - g(dbar_k) and
    T*_SPA = max(0, max_k sqrt(T) Z*_k / omega_k) (omega fixed at its sample value, as
    in Hansen), with the three recentring rules
      upper       g(x) = x                       (least favourable: every E[d_k] = 0),
      consistent  g(x) = x 1{x >= -omega_k sqrt(2 log log T / T)}  (Hansen's p-value),
      lower       g(x) = max(x, 0)               (poor variants never enter the null).
    p = #{T*_SPA >= T_SPA} / reps: no variant ahead of the benchmark in sample (T_SPA = 0)
    gives p = 1, rather than the near-zero lower and consistent values the strict '>'
    returns when every variant is far behind.

    White (2000) Reality Check: the non-studentized upper p-value,
      V = max_k sqrt(T) dbar_k,  V* = max_k sqrt(T) (dbar*_k - dbar_k),  p = #{V* > V} / reps.
    Studentization matters when the variants' volatilities differ: the Reality Check is
    driven by the most volatile variant, the SPA by the most significant one.

    block=None applies the block rule (stationary_block_length) to the differentials.
    Returns p-values, the statistics, the best variant (largest t_k) and the settings.
    """
    names, d = _differentials(R, benchmark)
    T, K = d.shape
    block = _block(d, block)
    tol = _tolerance(d)
    dbar = d.mean(axis=0)
    omega = np.sqrt(np.maximum(stationary_bootstrap_lrv(d, block), 0.0))
    t = _ratio(np.sqrt(T) * dbar, omega, tol)
    stat = float(max(0.0, t.max()))
    threshold = -omega * np.sqrt(2.0 * np.log(np.log(T)) / T)
    recentre = {
        'lower': np.maximum(dbar, 0.0),
        'consistent': np.where(dbar >= threshold, dbar, 0.0),
        'upper': dbar,
    }
    means, _ = _resampled_moments(d - dbar, block, reps, np.random.default_rng(seed),
                                  natural_variance=False)
    pvalues = {}
    for rule, g in recentre.items():
        z = _ratio(np.sqrt(T) * (means + (dbar - g)), omega, tol)
        t_star = np.maximum(z.max(axis=1), 0.0)
        pvalues[rule] = float(np.mean(t_star >= stat))
    rc_stat = float(np.sqrt(T) * dbar.max())
    rc_star = np.sqrt(T) * means.max(axis=1)
    best = int(np.argmax(t))
    return {
        'pvalues': pvalues,
        'statistic': stat,
        'reality_check': {'pvalue': float(np.mean(rc_star > rc_stat)), 'statistic': rc_stat},
        'best_model': names[best],
        'best_tstat': float(t[best]),
        'benchmark': 'zero' if benchmark is None else 'series',
        'n': int(T), 'k': int(K), 'block': int(block), 'reps': int(reps), 'seed': seed,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Romano & Wolf stepdown
# ──────────────────────────────────────────────────────────────────────────────

def romano_wolf(R, benchmark=None, block: int = None, reps: int = 10_000, seed: int = 42,
                alpha: float = 0.05) -> dict:
    """WHICH variants beat the benchmark, with family-wise error control (StepM).

    One-sided H0_k: E[d_k] <= 0 against E[d_k] > 0, for every k. Romano & Wolf (2005),
    Sec. 4 (studentized StepM): t_k = sqrt(T) dbar_k / omega_k as in spa_test; on each
    stationary-bootstrap resample the centred statistic is studentized INSIDE the
    resample,
        t*_k = sqrt(T) (dbar*_k - dbar_k) / sigma*_k,
    with sigma*_k the resample's natural block-bootstrap standard deviation (Götze &
    Künsch 1996; see _resampled_moments), whose bootstrap expectation matches omega_k.
    Adjusted p-values by Romano & Wolf (2016), Algorithm 4.1: with the variants ordered
    t_(1) >= ... >= t_(K) and max*_j = max over the remaining variants (j..K) of t*,
        p_init_(j) = (#{max*_j > t_(j)} + 1) / (reps + 1),
        p_adj_(j) = max(p_init_(j), p_adj_(j-1))    (monotonicity, their Remark 4.1).
    A variant is rejected at FWER alpha iff p_adj <= alpha. 'p_raw' is the unadjusted
    bootstrap p-value of each variant alone (their eq. 2.1).

    Returns {'table': DataFrame indexed by model (mean_diff per period, tstat, p_raw,
    p_adjusted, rejected), 'rejected': names, 'alpha', 'n', 'k', 'block', 'reps', 'seed'}.
    """
    names, d = _differentials(R, benchmark)
    T, K = d.shape
    block = _block(d, block)
    tol = _tolerance(d)
    dbar = d.mean(axis=0)
    omega = np.sqrt(np.maximum(stationary_bootstrap_lrv(d, block), 0.0))
    t = _ratio(np.sqrt(T) * dbar, omega, tol)
    means, lrv = _resampled_moments(d - dbar, block, reps, np.random.default_rng(seed),
                                    natural_variance=True)
    t_star = _ratio(np.sqrt(T) * means, np.sqrt(np.maximum(lrv, 0.0)), tol)

    order = np.argsort(-t, kind='stable')
    remaining_max = np.maximum.accumulate(t_star[:, order][:, ::-1], axis=1)[:, ::-1]
    p_init = (np.sum(remaining_max > t[order][None, :], axis=0) + 1.0) / (reps + 1.0)
    p_adj = np.empty(K)
    p_adj[order] = np.maximum.accumulate(p_init)
    p_raw = (np.sum(t_star > t[None, :], axis=0) + 1.0) / (reps + 1.0)
    table = pd.DataFrame({'mean_diff': dbar, 'tstat': t, 'p_raw': p_raw,
                          'p_adjusted': p_adj, 'rejected': p_adj <= alpha},
                         index=pd.Index(names, name='model'))
    return {
        'table': table,
        'rejected': [names[k] for k in order if p_adj[k] <= alpha],
        'alpha': float(alpha), 'benchmark': 'zero' if benchmark is None else 'series',
        'n': int(T), 'k': int(K), 'block': int(block), 'reps': int(reps), 'seed': seed,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Model Confidence Set
# ──────────────────────────────────────────────────────────────────────────────

def sharpe_losses(R):
    """Losses on a Sharpe scale: -r_k / sd(r_k), column by column (ddof = 1).

    The MCS ranks by mean loss; on raw returns that is a ranking by mean return, so a
    volatile variant is judged by its leverage. Dividing each column by its standard
    deviation makes the mean loss minus the per-period Sharpe ratio. A column without
    dispersion has a Sharpe of 0 (the convention of annualized_sharpe) and gets zero
    losses. Accepts a DataFrame (labels kept) or a T x K array.
    """
    X = R.to_numpy(dtype=float) if isinstance(R, pd.DataFrame) else np.asarray(R, dtype=float)
    sd = np.nanstd(X, axis=0, ddof=1)
    scale = np.nanmax(np.abs(X), axis=0, initial=0.0)
    ok = sd > 1e-12 * np.maximum(scale, 1e-300)
    L = np.where(ok, -X / np.where(ok, sd, 1.0), 0.0)
    L = np.where(np.isfinite(X), L, np.nan)
    if isinstance(R, pd.DataFrame):
        return pd.DataFrame(L, index=R.index, columns=R.columns)
    return L


def model_confidence_set(losses, size: float = 0.10, method: str = 'R', block: int = None,
                         reps: int = 10_000, seed: int = 42) -> dict:
    """Hansen, Lunde & Nason (2011) Model Confidence Set at level 1 - size.

    The set of models not significantly worse than the best: starting from all K, the
    equal-predictive-ability test (Sec. 3.1: T_R,M = max_ij |dbar_ij| / se, method 'R',
    or T_max,M = max_i dbar_i. / se, method 'max') eliminates the worst model until it no
    longer rejects; a model's MCS p-value is the largest test p-value up to its
    elimination (Sec. 2.3). Computed by arch.bootstrap.MCS with a stationary bootstrap.

    For strategy returns pass sharpe_losses(R) (HLN rank by mean loss; normalising each
    column's volatility makes that a Sharpe ranking). Rows with a non-finite loss are
    dropped. block=None applies stationary_block_length to the loss columns.

    Two guards around arch 7.2.0:
      * identical columns (e.g. a variant and a scaled copy, after volatility
        normalisation) make method 'R' divide 0 by 0 and fail; they are tested once and
        every copy gets the representative's p-value;
      * HLN define the MCS as {i: p_i >= size}; arch's .included uses p_i > size, so the
        set is formed here from the p-values.
    A wide MCS means "not distinguishable", not "equally good"; report the family.
    Returns {'included', 'excluded', 'pvalues' (model -> MCS p-value), 'size', 'method',
    'n', 'k', 'block', 'reps', 'seed'}, in the column order of `losses`.
    """
    from arch.bootstrap import MCS

    if method not in ('R', 'max'):
        raise ValueError("method must be 'R' or 'max'")
    if isinstance(losses, pd.DataFrame):
        names = list(losses.columns)
        L = losses.to_numpy(dtype=float)
    else:
        L = np.asarray(losses, dtype=float)
        names = list(range(L.shape[1])) if L.ndim == 2 else []
    if L.ndim != 2 or L.shape[1] < 2:
        raise ValueError("losses must be a T x K matrix with K >= 2 models")
    L = L[np.isfinite(L).all(axis=1)]
    if L.shape[0] < 20:
        raise ValueError(f"need at least 20 finite rows, got {L.shape[0]}")
    block = stationary_block_length(L) if block is None else int(max(1, block))

    representative, unique = {}, []
    for k in range(L.shape[1]):
        key = L[:, k].tobytes()
        if key not in representative:
            representative[key] = len(unique)
            unique.append(k)
    rep_of = [representative[L[:, k].tobytes()] for k in range(L.shape[1])]
    if len(unique) == 1:
        p_unique = np.ones(1)
    else:
        mcs = MCS(L[:, unique], size=size, reps=reps, block_size=block, method=method,
                  bootstrap='stationary', seed=seed)
        mcs.compute()
        pv = mcs.pvalues['Pvalue']
        p_unique = np.array([float(pv.loc[j]) for j in range(len(unique))])
    pvalues = {names[k]: float(p_unique[rep_of[k]]) for k in range(L.shape[1])}
    return {
        'included': [m for m in names if pvalues[m] >= size],
        'excluded': [m for m in names if pvalues[m] < size],
        'pvalues': pvalues,
        'size': float(size), 'method': method,
        'n': int(L.shape[0]), 'k': int(L.shape[1]), 'block': int(block), 'reps': int(reps),
        'seed': seed,
    }
