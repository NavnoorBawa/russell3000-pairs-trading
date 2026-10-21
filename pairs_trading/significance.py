"""
TRANSFORMER ENCODER FOR PAIRS TRADING - STATISTICAL SIGNIFICANCE
================================================================
Rigorous "is the edge real?" tests for the backtest results.

This module does NOT change any trading logic. It only *measures* the results that
the rest of the pipeline already produces, and answers the question a quant PM asks
first: is the Sharpe distinguishable from zero, or is it within noise?

Methods (all standard, all free, no look-ahead):
  - Probabilistic Sharpe Ratio (PSR), Bailey & López de Prado (2012): P(true SR > 0)
    given the observed SR, sample length, skew and kurtosis of returns.
  - Deflated Sharpe Ratio (DSR), Bailey & López de Prado (2014): PSR against the
    expected-maximum Sharpe under the null from N trials — a multiple-testing haircut.
  - Newey-West (HAC) t-stat that the mean return ≠ 0 — autocorrelation-robust, which
    matters because overlapping holding periods induce serial correlation.
  - Lo (2002) autocorrelation-adjusted annualisation of the Sharpe ratio, reported
    next to the IID sqrt(252) annualisation.
  - Circular block-bootstrap confidence interval on the annualised Sharpe, with the
    block length chosen automatically (Politis & White 2004; Patton, Politis & White
    2009 correction).
  - Ledoit & Wolf (2008) studentized circular-block-bootstrap test of the DIFFERENCE
    between two Sharpe ratios on date-aligned returns (strategy vs a baseline).
  - Small-sample t-test (two- and one-sided) + bootstrap CI on the per-window OOS mean.
  - Multiple testing across a family of trials: probability of backtest overfitting
    (CSCV), the effective number of trials (entropy effective rank; equicorrelation),
    the cross-sectional variance of trial Sharpes, the Deflated Sharpe as a function of
    the number of trials, and t-ratio hurdles (Harvey-Liu-Zhu, Chordia-Goyal-Saretto,
    Bonferroni) expressed as annual Sharpe ratios.
  - Factor attribution with Newey-West errors: one market factor, or several factors
    (e.g. Fama-French) with each factor's share of the explained variance.
Power, minimum track record and the Sharpe ratios a sample rules out are in power.py;
tests over a declared family of variants (SPA, Reality Check, StepM, MCS) in snooping.py.

References:
  Lo (2002) "The Statistics of Sharpe Ratios", Financial Analysts Journal.
  Bailey & López de Prado (2012, 2014), Journal of Risk / Journal of Portfolio Mgmt.
  Ledoit & Wolf (2008) "Robust performance hypothesis testing with the Sharpe ratio",
    Journal of Empirical Finance.
  Politis & White (2004) "Automatic Block-Length Selection for the Dependent
    Bootstrap", Econometric Reviews; Patton, Politis & White (2009) "Correction to ...".
  Roy & Vetterli (2007) "The effective rank: a measure of effective dimensionality",
    EUSIPCO; López de Prado, Lipton & Zoonekynd (2025) "Sharpe Ratio Inference: A New
    Standard for Reporting and Decision-Making", ADIA Lab (SSRN 5520741).
  Harvey & Liu (2015) "Backtesting", Journal of Portfolio Management 42(1); Harvey, Liu
    & Zhu (2016) "...and the Cross-Section of Expected Returns", RFS 29(1); Chordia,
    Goyal & Saretto (2020) "Anomalies and False Rejections", RFS 33(5).
  Newey & West (1987) "A Simple, Positive Semi-Definite, Heteroskedasticity and
    Autocorrelation Consistent Covariance Matrix", Econometrica 55(3).
"""

from pairs_trading.config import pd, np, logging
from scipy import stats as _sps

logger = logging.getLogger(__name__)

_EULER_GAMMA = 0.5772156649015329
_NAN = float('nan')


def _finite(returns) -> np.ndarray:
    """1-D float array with non-finite entries removed."""
    r = np.asarray(returns, dtype=float).ravel()
    return r[np.isfinite(r)]


def _is_constant(r: np.ndarray) -> bool:
    """True if `r` has no dispersion beyond floating-point rounding of its level.

    np.full(n, 0.001).std() is ~1e-19, not 0, and a Sharpe of mean / 1e-19 is noise.
    """
    if len(r) < 2:
        return True
    return bool(r.std() <= 1e-12 * max(float(np.max(np.abs(r))), 1e-300))


# ──────────────────────────────────────────────────────────────────────────────
# Core Sharpe statistics
# ──────────────────────────────────────────────────────────────────────────────

def annualized_sharpe(returns: np.ndarray, periods: int = 252) -> float:
    """Annualised Sharpe of a per-period (e.g. daily) return series (ddof=1).

    The single Sharpe definition of the project (the engine and the benchmarks call it).
    Non-finite values are ignored. A series without dispersion (fewer than 2 points, or
    constant up to floating-point rounding — np.full(n, 0.001) has std ~1e-19, which
    used to give a Sharpe of ~7e16) has an undefined Sharpe, reported as 0.0.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2 or _is_constant(r):
        return 0.0
    sd = r.std(ddof=1)
    if sd <= 0:
        return 0.0
    return float(r.mean() / sd * np.sqrt(periods))


def _newey_west_lags(n: int) -> int:
    """Newey-West (1994) rule-of-thumb truncation lag, floor(4 (n/100)^(2/9)), >= 1."""
    return max(1, int(np.floor(4 * (max(n, 1) / 100.0) ** (2.0 / 9.0))))


def _autocorrelations(r: np.ndarray, max_lag: int) -> np.ndarray:
    """Sample autocorrelations rho_1..rho_max_lag (biased autocovariance, divisor n)."""
    e = r - r.mean()
    n = len(e)
    c0 = float(np.dot(e, e)) / n
    if c0 <= 0 or max_lag < 1:
        return np.zeros(0)
    return np.array([np.dot(e[k:], e[:-k]) / n / c0 for k in range(1, max_lag + 1)])


def lo_annualized_sharpe(returns: np.ndarray, periods: int = 252, max_lag: int = None) -> dict:
    """Lo (2002) autocorrelation-adjusted annualisation of a per-period Sharpe ratio.

    The sqrt(q) rule (q = periods per year) is only right for IID returns. With serial
    correlation Lo (2002, eq. 21) gives the q-period Sharpe as
        SR(q) = eta(q) * SR,   eta(q) = q / sqrt( q + 2 * sum_{k=1}^{q-1} (q - k) rho_k ),
    so positive autocorrelation (P&L that trends day to day, as open positions do)
    shrinks the annual Sharpe and negative autocorrelation inflates it.

    Daily -> annual needs q - 1 = 251 autocorrelations, and summing 251 noisy sample
    autocorrelations with weights up to 251 swamps the estimate at T ~ 600 (sd of the
    weighted sum ~ q^1.5 / sqrt(3T) ~ 90, against q = 252). Autocorrelations beyond
    `max_lag` are therefore set to zero; the default is the same Newey-West rule-of-thumb
    lag the HAC t-stat uses, so both autocorrelation corrections share one horizon.

    Returns {'sharpe', 'eta', 'lags', 'iid_sharpe', 'autocorr'}; 'sharpe' is NaN when the
    implied variance ratio is non-positive (extreme negative autocorrelation).
    """
    r = _finite(returns)
    n = len(r)
    iid = annualized_sharpe(r, periods)
    if n < 4 or _is_constant(r) or r.std(ddof=1) <= 0:
        return {'sharpe': iid, 'eta': float(np.sqrt(periods)), 'lags': 0,
                'iid_sharpe': iid, 'autocorr': []}
    q = int(periods)
    if max_lag is None:
        max_lag = _newey_west_lags(n)
    lags = int(max(0, min(max_lag, q - 1, n - 2)))
    rho = _autocorrelations(r, lags)
    k = np.arange(1, lags + 1)
    inner = q + 2.0 * float(np.sum((q - k) * rho))
    sr = float(r.mean() / r.std(ddof=1))
    if inner <= 0:
        return {'sharpe': _NAN, 'eta': _NAN, 'lags': lags, 'iid_sharpe': iid,
                'autocorr': [float(x) for x in rho]}
    eta = q / np.sqrt(inner)
    return {'sharpe': float(sr * eta), 'eta': float(eta), 'lags': lags, 'iid_sharpe': iid,
            'autocorr': [float(x) for x in rho]}


def probabilistic_sharpe_ratio(returns: np.ndarray, sr_benchmark_ann: float = 0.0,
                               periods: int = 252, variance_at: str = 'estimate') -> dict:
    """Probabilistic Sharpe Ratio: P(true SR > benchmark).

    Works in per-period (non-annualised) Sharpe units internally, incorporating the
    skewness and (non-excess) kurtosis of the return distribution — so fat tails and
    negative skew correctly *reduce* confidence in a positive Sharpe.

    variance_at : where the asymptotic variance of the Sharpe estimator,
                  1 - skew*SR + (kurt-1)/4 * SR^2, is evaluated.
        'estimate' (default; Bailey & López de Prado 2012): at the observed SR — a Wald
                   form.
        'null'     : at the benchmark SR — a score-type form, whose denominator does not
                   move with the sample mean.

    v32 null calibration (true SR = benchmark = 0, T = 630, 20k Monte-Carlo paths;
    rejection rate of the one-sided 5% test, PSR > 0.95 / PSR < 0.05):
        IID normal                         estimate 4.9% / 4.8%   null 4.9% / 4.8%
        IID jump mixtures (|skew| ~0.9,
          kurtosis 7-11)                   estimate 5.0-5.5%      null 4.5-5.5%
        IID Student-t(3) (infinite kurt.)  estimate 5.8% / 5.6%   null 5.0% / 4.9%
        sparse, 92% zeros (the <=v31
          realised-only P&L series)        estimate 6.1% / 5.9%   null 5.2% / 5.0%
        IID lognormal, skew ~ -3.7         estimate 5.0% / 5.3%   null 6.7% / 3.5%
        AR(1) phi = +0.1 / +0.2 / -0.1     both ~6.7% / ~8.9% / ~3.4% (upper tail)
    Reading: the plug-in over-rejects only when the kurtosis is extreme — the sample
    skew and the sample mean then move together, so the -skew*SR term shrinks the
    denominator exactly when |SR| is large. That was the situation of the sparse
    realised-only series through v31; on the dense mark-to-market series the engine
    produces since v32 it is within Monte-Carlo error of nominal. The 'null' form fixes
    the heavy-tail case but is anti-conservative for strongly negatively skewed returns
    (6.7% false "SR > 0" calls), the usual shape of a mean-reversion book. The plug-in
    therefore stays the reported PSR; the null form is reported alongside as a
    robustness check. Both assume IID returns: positive autocorrelation inflates the
    rejection rate whichever form is used, which is what the HAC t-stat and the Lo
    (2002) annualisation are reported for.
    """
    if variance_at not in ('estimate', 'null'):
        raise ValueError("variance_at must be 'estimate' or 'null'")
    r = _finite(returns)
    n = len(r)
    sd = r.std(ddof=1) if n > 1 else 0.0
    if n < 3 or sd <= 0 or _is_constant(r):
        # v32: full key set on the degenerate path. This used to return only
        # {'psr', 'sr_ann', 'n'}, so log_significance_report raised KeyError('skew') and
        # the caller discarded the WHOLE significance report for one short series.
        return {'psr': _NAN, 'sr_ann': 0.0, 'sr_per_period': _NAN, 'skew': _NAN,
                'kurtosis': _NAN, 'n': n, 'benchmark_ann': sr_benchmark_ann,
                'variance_at': variance_at}

    sr = r.mean() / sd                                  # per-period SR
    sr_star = sr_benchmark_ann / np.sqrt(periods)       # benchmark in per-period units
    g3 = float(_sps.skew(r, bias=False))
    g4 = float(_sps.kurtosis(r, fisher=False, bias=False))   # non-excess (3 = normal)

    s = sr if variance_at == 'estimate' else sr_star
    denom = np.sqrt(max(1.0 - g3 * s + (g4 - 1.0) / 4.0 * s * s, 1e-12))
    z = (sr - sr_star) * np.sqrt(n - 1) / denom
    psr = float(_sps.norm.cdf(z))
    return {
        'psr': psr,
        'sr_ann': float(sr * np.sqrt(periods)),
        'sr_per_period': float(sr),
        'skew': g3,
        'kurtosis': g4,
        'n': n,
        'benchmark_ann': sr_benchmark_ann,
        'variance_at': variance_at,
    }


def deflated_sharpe_ratio(returns: np.ndarray, n_trials: int,
                          var_sr_trials_ann: float = None, periods: int = 252,
                          variance_at: str = 'estimate') -> dict:
    """Deflated Sharpe Ratio — PSR against the expected MAX Sharpe under the null.

    With N strategy trials, even pure-noise strategies produce a best-of-N Sharpe well
    above zero. DSR tests the observed Sharpe against that expected maximum, so it is a
    multiple-testing-aware significance measure.

    n_trials            : number of independent strategy configurations effectively tried.
    var_sr_trials_ann   : variance of the *annualised* Sharpe across those trials. If None
                          (recommended), it defaults to the null sampling variance of the
                          annualised-Sharpe estimator on a series of this length,
                          ≈ periods / T — the variance trial Sharpes would have if every
                          strategy truly had zero edge. This is assumption-light: it needs
                          only the sample length, not a guessed cross-sectional spread.
    """
    r = _finite(returns)
    n = len(r)
    if n < 3 or n_trials < 1:
        return {'dsr': _NAN, 'sr_star_ann': _NAN, 'n_trials': n_trials,
                'std_sr_trials_ann': _NAN, 'observed_sr_ann': annualized_sharpe(r, periods)}

    if var_sr_trials_ann is None or var_sr_trials_ann <= 0:
        var_sr_trials_ann = periods / float(n)        # null estimator variance, annualised
    std_sr_ann = np.sqrt(var_sr_trials_ann)
    N = float(n_trials)
    if n_trials == 1:
        # v32: with a single trial there is no selection, so E[max SR] = E[SR] = 0 under
        # the null and DSR is just PSR against zero. The Gumbel formula below evaluated
        # norm.ppf(1 - 1/1) = -inf here, i.e. a benchmark of -inf and DSR = 1.0.
        sr_star_ann = 0.0
    else:
        # Expected maximum of N iid standard-normal-ish Sharpe estimates (Gumbel approx)
        z1 = _sps.norm.ppf(1.0 - 1.0 / N)
        z2 = _sps.norm.ppf(1.0 - 1.0 / (N * np.e))
        sr_star_ann = float(std_sr_ann * ((1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2))

    psr_vs_star = probabilistic_sharpe_ratio(r, sr_benchmark_ann=sr_star_ann, periods=periods,
                                             variance_at=variance_at)
    return {
        'dsr': psr_vs_star['psr'],
        'sr_star_ann': float(sr_star_ann),
        'n_trials': int(n_trials),
        'std_sr_trials_ann': float(std_sr_ann),
        'observed_sr_ann': annualized_sharpe(r, periods),
    }


def hac_tstat_mean(returns: np.ndarray, max_lag: int = None) -> dict:
    """Newey-West (HAC) t-stat that the mean per-period return = 0.

    Robust to the serial correlation that overlapping holding periods induce.
    Testing mean = 0 is equivalent to testing Sharpe = 0. Non-finite values are ignored;
    a series without dispersion has no defined t-stat and is reported as t = 0, p = 1.
    """
    r = _finite(returns)
    n = len(r)
    if n < 3:
        return {'tstat': 0.0, 'pvalue': 1.0, 'mean': 0.0, 'lags': 0}
    if _is_constant(r):
        return {'tstat': 0.0, 'pvalue': 1.0, 'mean': float(r.mean()), 'lags': 0}

    if max_lag is None:
        max_lag = _newey_west_lags(n)

    mu = r.mean()
    e = r - mu
    gamma0 = np.dot(e, e) / n
    lrv = gamma0
    for k in range(1, max_lag + 1):
        w = 1.0 - k / (max_lag + 1.0)                 # Bartlett kernel
        cov = np.dot(e[k:], e[:-k]) / n
        lrv += 2.0 * w * cov
    se = np.sqrt(max(lrv, 1e-18) / n)
    t = mu / se if se > 0 else 0.0
    p = 2.0 * (1.0 - _sps.norm.cdf(abs(t)))
    return {'tstat': float(t), 'pvalue': float(p), 'mean': float(mu), 'lags': int(max_lag)}


# ──────────────────────────────────────────────────────────────────────────────
# Block length
# ──────────────────────────────────────────────────────────────────────────────

def _flat_top(x: np.ndarray) -> np.ndarray:
    """Politis-Romano flat-top (trapezoid) lag window."""
    x = np.abs(x)
    return np.where(x <= 0.5, 1.0, np.where(x <= 1.0, 2.0 * (1.0 - x), 0.0))


def politis_white_block_length(x, bootstrap: str = 'circular') -> float:
    """Optimal expected block length for a block bootstrap of the MEAN of `x`.

    Politis & White (2004) with the Patton, Politis & White (2009) correction, following
    the authors' reference implementation (opt_block_length_REV_dec07.m):
      * m_hat = the first lag after which K_N = max(5, sqrt(log10 T)) consecutive sample
        autocorrelations are all inside +/- 2 sqrt(log10 T / T); M = 2 m_hat;
      * G = sum_{|k|<=M} lambda(k/M) |k| R(k),  g(0) = sum_{|k|<=M} lambda(k/M) R(k), with
        the flat-top window lambda;
      * b = (2 G^2 / D)^(1/3) T^(1/3), D = (4/3) g(0)^2 for the circular (and moving)
        block bootstrap, D = 2 g(0)^2 for the stationary bootstrap (the 2009 correction);
      * capped at ceil(min(3 sqrt(T), T/3)).
    Returns a float >= 1 (callers round it up to an integer block).
    """
    if bootstrap not in ('circular', 'stationary'):
        raise ValueError("bootstrap must be 'circular' or 'stationary'")
    r = _finite(x)
    n = len(r)
    if n < 8 or _is_constant(r):          # np.std of a constant is rounding noise, not 0
        return 1.0
    # b depends on the autocovariances only through scale-free ratios, so standardising is
    # exact and keeps G^2 / g(0)^2 from underflowing for series of tiny magnitude
    e = (r - r.mean()) / r.std()
    b_max = float(np.ceil(min(3.0 * np.sqrt(n), n / 3.0)))
    k_n = int(max(5, np.ceil(np.sqrt(np.log10(n)))))
    m_max = min(int(np.ceil(np.sqrt(n))) + k_n, n - 2)
    c0 = float(np.dot(e, e)) / n
    acov = np.array([c0] + [np.dot(e[k:], e[:-k]) / n for k in range(1, m_max + 1)])
    rho = acov[1:] / c0                                # lags 1..m_max
    crit = 2.0 * np.sqrt(np.log10(n) / n)
    insignificant = np.abs(rho) < crit
    m_hat = None
    for j in range(0, m_max - k_n + 1):                 # window = lags j+1 .. j+k_n
        if insignificant[j:j + k_n].all():
            m_hat = j + 1
            break
    if m_hat is None:                                   # never settles: last significant lag
        sig = np.nonzero(~insignificant)[0]
        m_hat = int(sig[-1]) + 1 if sig.size else 1
    M = min(2 * m_hat, m_max)
    k = np.arange(1, M + 1)
    lam = _flat_top(k / M)
    G = 2.0 * float(np.sum(lam * k * acov[1:M + 1]))
    g0 = acov[0] + 2.0 * float(np.sum(lam * acov[1:M + 1]))
    if g0 <= 0:
        return 1.0
    D = (4.0 / 3.0) * g0 ** 2 if bootstrap == 'circular' else 2.0 * g0 ** 2
    b = (2.0 * G ** 2 / D) ** (1.0 / 3.0) * n ** (1.0 / 3.0)
    return float(min(max(b, 1.0), b_max))


def _auto_block(*series) -> int:
    """Integer circular-bootstrap block: the largest Politis-White length over `series`.

    Politis-White is derived for the sample MEAN. For a Sharpe ratio near zero the
    estimator's sampling variance is dominated by the mean term (the variance term is
    weighted by SR itself), so the mean's optimal block is the relevant one; taking the
    max over the series of a paired test keeps the dependence of both.
    """
    return int(np.ceil(max(politis_white_block_length(s, 'circular') for s in series)))


# ──────────────────────────────────────────────────────────────────────────────
# Bootstrap
# ──────────────────────────────────────────────────────────────────────────────

def _circular_block_indices(rng, n: int, block: int, n_samples: int, length: int = None) -> np.ndarray:
    """(n_samples, length) index matrix of circular-block-bootstrap resamples."""
    length = n if length is None else length
    n_blocks = int(np.ceil(length / block))
    starts = rng.integers(0, n, size=(n_samples, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return idx.reshape(n_samples, n_blocks * block)[:, :length]


def block_bootstrap_sharpe_ci(returns: np.ndarray, block: int = None, n_boot: int = 5000,
                              alpha: float = 0.05, periods: int = 252, seed: int = 42) -> dict:
    """Circular block-bootstrap percentile CI on the annualised Sharpe.

    block=None (default) selects the block length automatically (Politis & White 2004 /
    Patton, Politis & White 2009, circular-bootstrap constant); pass an integer to fix it.
    v32: the docstring used to promise a "stationary/block bootstrap" while the block
    was hard-coded to 10 days whatever the dependence in the data. Non-finite values are
    ignored; a series without dispersion has no CI (NaN bounds).
    """
    r = _finite(returns)
    n = len(r)
    point = annualized_sharpe(r, periods)
    method = 'fixed' if block is not None else 'politis-white'
    if block is None:
        block = _auto_block(r) if n >= 8 else 1
    block = int(max(1, block))
    if n < block + 1 or n < 3 or _is_constant(r):
        return {'lo': _NAN, 'hi': _NAN, 'point': point, 'n_boot': n_boot, 'block': block,
                'block_method': method}
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    chunk = max(1, min(n_boot, 2_000_000 // max(n, 1)))
    for s in range(0, n_boot, chunk):
        m = min(chunk, n_boot - s)
        samp = r[_circular_block_indices(rng, n, block, m)]
        sd = samp.std(axis=1, ddof=1)
        mu = samp.mean(axis=1)
        # a resample without dispersion (relative to its level) has Sharpe 0, not mean/1e-19
        ok = sd > 1e-12 * np.max(np.abs(samp), axis=1)
        boots[s:s + m] = np.where(ok, mu / np.where(ok, sd, 1.0), 0.0) * np.sqrt(periods)
    return {
        'lo': float(np.percentile(boots, 100 * alpha / 2)),
        'hi': float(np.percentile(boots, 100 * (1 - alpha / 2))),
        'point': point,
        'n_boot': n_boot, 'block': block, 'block_method': method,
    }


def bootstrap_mean_ci(values: np.ndarray, n_boot: int = 5000, alpha: float = 0.05,
                      seed: int = 42) -> dict:
    """Plain bootstrap CI on the mean of a small sample (e.g. OOS window returns)."""
    v = np.asarray(values, dtype=float)
    if len(v) < 2:
        return {'lo': _NAN, 'hi': _NAN, 'point': float(v.mean()) if len(v) else 0.0}
    rng = np.random.default_rng(seed)
    boots = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(n_boot)])
    return {
        'lo': float(np.percentile(boots, 100 * alpha / 2)),
        'hi': float(np.percentile(boots, 100 * (1 - alpha / 2))),
        'point': float(v.mean()),
    }


def oos_window_test(window_returns: np.ndarray) -> dict:
    """One-sample t-test + bootstrap CI on the per-window OOS mean return.

    Reports the two-sided p-value (mean != 0) and, v32, BOTH one-sided p-values
    (H1: mean < 0 and H1: mean > 0), so the direction of the evidence is stated rather
    than inferred: a two-sided p of 0.085 with a negative mean is one-sided p = 0.043
    for "the strategy loses money" and 0.957 for "the strategy makes money".
    """
    v = np.asarray(window_returns, dtype=float)
    n = len(v)
    if n < 2:
        return {'n': n, 'mean': float(v.mean()) if n else 0.0, 'std': _NAN, 'stderr': _NAN,
                'tstat': 0.0, 'pvalue': 1.0, 'pvalue_mean_lt0': _NAN, 'pvalue_mean_gt0': _NAN,
                'positive': int((v > 0).sum()), 'ci_lo': _NAN, 'ci_hi': _NAN, 'ci_method': 't',
                'boot_ci_lo': _NAN, 'boot_ci_hi': _NAN}
    t, p = _sps.ttest_1samp(v, 0.0)
    boot = bootstrap_mean_ci(v)

    # v31 (audit): report the interval that is COHERENT WITH THE REPORTED TEST.
    # This previously paired the t-test p-value with a percentile-bootstrap CI, and on
    # the v31 window set the two contradict each other in public: p=0.085 ("not
    # significant") next to a bootstrap CI of [-0.548%, -0.008%] that EXCLUDES zero.
    # The t-based interval is [-0.611%, +0.047%] and does include zero, agreeing with
    # its own p-value. The percentile bootstrap is the unreliable one here: n=10 with
    # three windows at exactly 0.0 means resampling cannot produce values outside the
    # observed set, so it understates the tail and shrinks the interval.
    # Primary CI is now the t interval; the bootstrap is kept alongside, clearly named.
    se = float(v.std(ddof=1) / np.sqrt(n))
    tcrit = float(_sps.t.ppf(0.975, n - 1))
    ci_lo, ci_hi = float(v.mean() - tcrit * se), float(v.mean() + tcrit * se)
    # one-sided p-values from the same t statistic (undefined for a zero-variance sample)
    p_lt0 = float(_sps.t.cdf(t, n - 1)) if se > 0 else _NAN
    p_gt0 = float(_sps.t.sf(t, n - 1)) if se > 0 else _NAN

    return {
        'n': n,
        'mean': float(v.mean()),
        'std': float(v.std(ddof=1)),
        'stderr': se,
        'tstat': float(t),
        'pvalue': float(p),
        'pvalue_mean_lt0': p_lt0,
        'pvalue_mean_gt0': p_gt0,
        'positive': int((v > 0).sum()),
        # primary: Student-t interval, consistent with `tstat`/`pvalue` above
        'ci_lo': ci_lo, 'ci_hi': ci_hi,
        'ci_method': 't',
        # secondary: percentile bootstrap, retained for comparison only
        'boot_ci_lo': boot['lo'], 'boot_ci_hi': boot['hi'],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Comparing two strategies: Ledoit & Wolf (2008)
# ──────────────────────────────────────────────────────────────────────────────

def _as_day_strings(dates) -> list:
    """Dates (strings, datetimes, tz-aware or not) -> 'YYYY-MM-DD' calendar-day strings."""
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates)))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return list(idx.normalize().strftime('%Y-%m-%d'))


def align_return_series(dates_a, returns_a, dates_b, returns_b):
    """Inner-join two daily return series on calendar date.

    Returns (dates, ra, rb): the common 'YYYY-MM-DD' dates in ascending order and the two
    return arrays on those dates. Duplicate dates keep the last value; a date where
    either series is non-finite is dropped. Pairing by DATE (not by position) is what
    makes a paired test valid: the strategy and a baseline rarely share a calendar.
    """
    if len(dates_a) != len(returns_a) or len(dates_b) != len(returns_b):
        raise ValueError("each dates list must match its returns in length")
    if len(dates_a) == 0 or len(dates_b) == 0:
        return [], np.zeros(0), np.zeros(0)
    sa = pd.Series(np.asarray(returns_a, dtype=float), index=_as_day_strings(dates_a))
    sb = pd.Series(np.asarray(returns_b, dtype=float), index=_as_day_strings(dates_b))
    sa = sa[~sa.index.duplicated(keep='last')]
    sb = sb[~sb.index.duplicated(keep='last')]
    both = pd.concat([sa.rename('a'), sb.rename('b')], axis=1, join='inner').sort_index()
    both = both[np.isfinite(both['a']) & np.isfinite(both['b'])]
    return list(both.index), both['a'].to_numpy(), both['b'].to_numpy()


def _sr_diff(mu1, mu2, g1, g2):
    """Per-period Sharpe difference from first and second raw moments (LW 2008 f(v))."""
    return mu1 / np.sqrt(g1 - mu1 ** 2) - mu2 / np.sqrt(g2 - mu2 ** 2)


def _sr_diff_gradient(mu1, mu2, g1, g2):
    """Gradient of _sr_diff w.r.t. (mu1, mu2, g1, g2); broadcasts, last axis = 4."""
    v1 = (g1 - mu1 ** 2) ** 1.5
    v2 = (g2 - mu2 ** 2) ** 1.5
    return np.stack([g1 / v1, -g2 / v2, -0.5 * mu1 / v1, 0.5 * mu2 / v2], axis=-1)


def _parzen(x: float) -> float:
    x = abs(x)
    if x <= 0.5:
        return 1.0 - 6.0 * x ** 2 + 6.0 * x ** 3
    if x <= 1.0:
        return 2.0 * (1.0 - x) ** 3
    return 0.0


def _parzen_hac(V: np.ndarray) -> np.ndarray:
    """Parzen-kernel HAC long-run covariance with Andrews (1991) automatic bandwidth."""
    T, p = V.shape
    num = den = 0.0
    for i in range(p):
        x = V[:, i] - V[:, i].mean()
        z, y = x[:-1], x[1:]
        zz = float(np.dot(z, z))
        rho = float(np.dot(z, y)) / zz if zz > 0 else 0.0
        rho = float(np.clip(rho, -0.97, 0.97))
        s2 = float(np.mean((y - rho * z) ** 2))
        num += 4.0 * rho ** 2 * s2 ** 2 / (1.0 - rho) ** 8
        den += s2 ** 2 / (1.0 - rho) ** 4
    alpha = num / den if den > 0 else 0.0
    bw = 2.6614 * (alpha * T) ** 0.2
    psi = V.T @ V / T
    j = 1
    while j < bw and j < T:
        G = V[j:].T @ V[:-j] / T
        psi = psi + _parzen(j / bw) * (G + G.T)
        j += 1
    return psi * T / (T - 4.0)


def _lw_standard_error(ra: np.ndarray, rb: np.ndarray) -> float:
    """HAC standard error of the per-period Sharpe difference (LW 2008, section 3.1).

    Delta method on the moments (mu_a, mu_b, E r_a^2, E r_b^2) with a prewhitened (VAR(1),
    singular values capped at 0.97) Parzen-kernel long-run covariance — the estimator of
    Ledoit & Wolf's own code (compute.se.Parzen.pw).
    """
    T = len(ra)
    mu1, mu2 = ra.mean(), rb.mean()
    g1, g2 = np.mean(ra * ra), np.mean(rb * rb)
    grad = _sr_diff_gradient(mu1, mu2, g1, g2)
    V = np.column_stack([ra - mu1, rb - mu2, ra * ra - g1, rb * rb - g2])
    X, Y = V[:-1], V[1:]
    if 1.0 / np.linalg.cond(X.T @ X, 1) < 1e-10:
        # collinear moments (e.g. rb a multiple of ra): the VAR(1) is not identified, so,
        # as Wolf's computeSEpw_Sharpe does when rcond(X'X) < 1e-10, skip prewhitening
        psi = _parzen_hac(V)
    else:
        B = np.linalg.lstsq(X, Y, rcond=None)[0]       # X @ B ~ Y ; VAR matrix A = B.T
        U, s, Wt = np.linalg.svd(B.T)
        A = U @ np.diag(np.minimum(s, 0.97)) @ Wt
        resid = Y - X @ A.T
        psi = _parzen_hac(resid)
        D = np.linalg.inv(np.eye(4) - A)
        psi = D @ psi @ D.T
    var = float(grad @ psi @ grad) / T
    return float(np.sqrt(var)) if var > 0 else 0.0


def sharpe_difference_test(returns_a, returns_b, block: int = None, n_boot: int = 5000,
                           seed: int = 42, alpha: float = 0.05, periods: int = 252) -> dict:
    """Test H0: Sharpe(a) = Sharpe(b) on PAIRED (date-aligned) per-period returns.

    Ledoit & Wolf (2008), section 3.2: studentized circular block bootstrap.
      * Delta = SR_a - SR_b (per period, from the four raw moments), studentized by a
        prewhitened Parzen HAC standard error (see _lw_standard_error);
      * each bootstrap resample (circular blocks of length `block`) recomputes Delta* and
        its own standard error from the block means of the centred moments — the
        "natural" block-bootstrap variance LW use in the bootstrap world;
      * p = (#{|Delta* - Delta| / se* >= |Delta| / se} + 1) / (n_boot + 1)  (two-sided);
      * CI = Delta +/- q_{1-alpha}(|Delta* - Delta| / se*) * se  (symmetric studentized).
    Unlike testing each Sharpe against zero, this accounts for the correlation between the
    two series — strategy and baseline trade the same market on the same days — which can
    make the difference much better (or worse) determined than either Sharpe alone.

    block=None selects the block length automatically (Politis-White, the larger of the
    two series' lengths). LW's own calibration of the block size is not implemented.
    Sharpe ratios here use the population (ddof=0) standard deviation, as in LW; they
    differ from annualized_sharpe by the factor sqrt((T-1)/T) (< 0.1% at T = 630).
    The difference, its standard error and CI are reported annualised (x sqrt(periods));
    'diff' = 'sharpe_a' - 'sharpe_b' exactly.

    Inputs must already be aligned on dates (see align_return_series); a row that is
    non-finite in either series is dropped.
    """
    a = np.asarray(returns_a, dtype=float).ravel()
    b = np.asarray(returns_b, dtype=float).ravel()
    if a.shape != b.shape:
        raise ValueError("returns_a and returns_b must be aligned (same length); "
                         "use align_return_series first")
    keep = np.isfinite(a) & np.isfinite(b)
    a, b = a[keep], b[keep]
    T = len(a)
    ann = np.sqrt(periods)
    out = {'diff': _NAN, 'sharpe_a': _NAN, 'sharpe_b': _NAN, 'se': _NAN, 'tstat': _NAN,
           'ci_lo': _NAN, 'ci_hi': _NAN, 'pvalue': _NAN, 'n': int(T), 'block': block,
           'block_method': 'fixed' if block is not None else 'politis-white',
           'n_boot': int(n_boot), 'alpha': alpha,
           'method': 'Ledoit-Wolf (2008) studentized circular block bootstrap'}
    if T < 20 or _is_constant(a) or _is_constant(b):
        return out

    mu1, mu2 = a.mean(), b.mean()
    g1, g2 = np.mean(a * a), np.mean(b * b)
    diff = float(_sr_diff(mu1, mu2, g1, g2))
    out['sharpe_a'] = float(mu1 / np.sqrt(g1 - mu1 ** 2) * ann)
    out['sharpe_b'] = float(mu2 / np.sqrt(g2 - mu2 ** 2) * ann)
    out['diff'] = out['sharpe_a'] - out['sharpe_b']

    if block is None:
        block = _auto_block(a, b)
    block = int(min(max(1, block), T // 2))
    out['block'] = block

    if np.array_equal(a, b):
        # identical series: the difference is exactly zero in every resample
        out.update({'diff': 0.0, 'se': 0.0, 'tstat': 0.0, 'ci_lo': 0.0, 'ci_hi': 0.0,
                    'pvalue': 1.0})
        return out

    se = _lw_standard_error(a, b)
    if se <= 1e-6 / np.sqrt(T):
        # the two Sharpe ratios move in lockstep (e.g. b is a positive multiple of a):
        # the difference has no sampling variance, so it is whatever was observed. (A
        # Sharpe ratio's own standard error is of order 1/sqrt(T); an SE a millionth of
        # that is rounding noise in the delta-method variance, not sampling variance.)
        out.update({'se': 0.0, 'tstat': _NAN, 'ci_lo': out['diff'], 'ci_hi': out['diff'],
                    'pvalue': 1.0 if abs(diff) < 1e-12 else 0.0})
        return out
    d_obs = abs(diff) / se

    n_blocks = T // block
    L = n_blocks * block
    rng = np.random.default_rng(seed)
    d_star = np.empty(n_boot)
    chunk = max(1, min(n_boot, 1_000_000 // max(L, 1)))
    for s in range(0, n_boot, chunk):
        m = min(chunk, n_boot - s)
        idx = _circular_block_indices(rng, T, block, m, length=L)
        A, B = a[idx], b[idx]
        A2, B2 = A * A, B * B
        m1, m2 = A.mean(axis=1), B.mean(axis=1)
        s1, s2 = A2.mean(axis=1), B2.mean(axis=1)
        diff_star = _sr_diff(m1, m2, s1, s2)
        zeta = np.stack([
            A.reshape(m, n_blocks, block).mean(axis=2) - m1[:, None],
            B.reshape(m, n_blocks, block).mean(axis=2) - m2[:, None],
            A2.reshape(m, n_blocks, block).mean(axis=2) - s1[:, None],
            B2.reshape(m, n_blocks, block).mean(axis=2) - s2[:, None],
        ], axis=2) * np.sqrt(block)                     # (m, n_blocks, 4)
        psi = np.einsum('mli,mlj->mij', zeta, zeta) / n_blocks
        grad = _sr_diff_gradient(m1, m2, s1, s2)
        var = np.einsum('mi,mij,mj->m', grad, psi, grad) / L
        se_star = np.sqrt(np.maximum(var, 0.0))
        num = np.abs(diff_star - diff)
        with np.errstate(divide='ignore', invalid='ignore'):
            ds = np.where(se_star > 0, num / se_star, np.where(num > 0, np.inf, 0.0))
        d_star[s:s + m] = np.nan_to_num(ds, nan=0.0)
    q = float(np.quantile(d_star, 1.0 - alpha))
    pval = (np.sum(d_star >= d_obs) + 1.0) / (n_boot + 1.0)
    out.update({
        'se': float(se * ann),
        'tstat': float(diff / se),
        'ci_lo': float((diff - q * se) * ann),
        'ci_hi': float((diff + q * se) * ann),
        'pvalue': float(pval),
    })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Multiple testing across trials
# ──────────────────────────────────────────────────────────────────────────────

def pbo_cscv(performance: np.ndarray, n_splits: int = 10, periods: int = 252) -> dict:
    """Probability of Backtest Overfitting via combinatorially symmetric cross-validation.

    Bailey, Borwein, Lopez de Prado & Zhu (2017, J. Computational Finance), "The
    probability of backtest overfitting". `performance` is a T x N matrix of daily returns
    of N strategy configurations on the same dates. Rows are cut into `n_splits` (even)
    contiguous blocks; for every choice of half the blocks as in-sample (IS) the
    configuration with the best IS Sharpe is found and its Sharpe rank among all N on the
    complementary out-of-sample (OOS) half is recorded. With relative rank w in (0, 1) and
    logit lambda = ln(w / (1 - w)), PBO is the share of splits with lambda <= 0, i.e. in
    which the IS winner ranks at or below the OOS median. PBO near 0: selection
    generalises; near or above 0.5: the chosen configuration is an artefact of search.

    Also returns the mean OOS Sharpe of the IS winner and the share of splits in which
    it has a negative OOS Sharpe (the "probability of loss").
    """
    from itertools import combinations
    M = np.asarray(performance, dtype=float)
    if M.ndim != 2 or M.shape[1] < 2:
        raise ValueError("performance must be a T x N matrix with N >= 2 configurations")
    if n_splits % 2 or n_splits < 2:
        raise ValueError("n_splits must be an even number >= 2")
    T, N = M.shape
    if T < n_splits * 2:
        raise ValueError(f"need at least {n_splits * 2} rows for {n_splits} splits")
    bounds = np.linspace(0, T, n_splits + 1).astype(int)
    blocks = [np.arange(bounds[i], bounds[i + 1]) for i in range(n_splits)]

    def _sharpes(rows):
        sub = M[rows]
        sd = sub.std(axis=0, ddof=1)
        with np.errstate(divide='ignore', invalid='ignore'):
            sr = np.where(sd > 0, sub.mean(axis=0) / sd, 0.0)
        return sr * np.sqrt(periods)

    logits, oos_best, oos_neg = [], [], 0
    for is_blocks in combinations(range(n_splits), n_splits // 2):
        is_rows = np.concatenate([blocks[b] for b in is_blocks])
        oos_rows = np.concatenate([blocks[b] for b in range(n_splits) if b not in is_blocks])
        sr_is, sr_oos = _sharpes(is_rows), _sharpes(oos_rows)
        best = int(np.argmax(sr_is))
        rank = float(_sps.rankdata(sr_oos)[best])          # 1 = worst ... N = best
        w = rank / (N + 1.0)
        logits.append(np.log(w / (1.0 - w)))
        oos_best.append(float(sr_oos[best]))
        oos_neg += int(sr_oos[best] < 0)
    logits = np.asarray(logits)
    return {
        'pbo': float(np.mean(logits <= 0)),
        'n_combinations': int(len(logits)),
        'n_configurations': int(N),
        'n_splits': int(n_splits),
        'median_logit': float(np.median(logits)),
        'mean_oos_sharpe_of_is_best': float(np.mean(oos_best)),
        'prob_oos_loss_of_is_best': float(oos_neg / len(logits)),
    }


def _trial_matrix(R):
    """(T x N float matrix of the trials with dispersion, number of constant columns).

    Rows with a non-finite entry are dropped. A column without dispersion (a variant that
    never trades) has a Sharpe of exactly 0, not a draw from the null distribution of
    trial Sharpes, so it is left out of the trial statistics below.
    """
    M = R.to_numpy(dtype=float) if isinstance(R, pd.DataFrame) else np.asarray(R, dtype=float)
    if M.ndim != 2 or M.shape[1] < 1:
        raise ValueError("R must be a T x N matrix of trial returns")
    M = M[np.isfinite(M).all(axis=1)]
    if M.shape[0] < 3:
        raise ValueError("need at least 3 finite rows")
    live = np.array([not _is_constant(M[:, k]) for k in range(M.shape[1])], dtype=bool)
    return M[:, live], int((~live).sum())


def effective_number_of_trials(R) -> dict:
    """Effective number of independent trials among the N columns of a trial-return matrix.

    Correlated trials (a threshold grid, toggles of one gate) are fewer independent draws
    than their count. Two estimates from the correlation matrix C of the trial returns:
      * 'effective_rank': the entropy effective rank of Roy & Vetterli (2007), as in
        the code of López de Prado, Lipton & Zoonekynd (2026; effective_rank): with
        p_i = lambda_i / sum(lambda) over the positive eigenvalues of C,
        N_eff = exp(-sum_i p_i ln p_i) — N for uncorrelated trials, 1 for identical ones;
      * 'n_eff_avg_corr': N / (1 + (N - 1) rho_bar), rho_bar the average off-diagonal
        correlation — the number of independent estimates with the variance of the
        average of N equicorrelated ones. Capped at N: a negative average correlation
        does not create trials.
    Either can stand in for n_trials in deflated_sharpe_ratio (with trial_sharpe_variance
    for var_sr_trials_ann). Both count only trials that left a return series; choices
    made without one (earlier versions, undocumented tries) are not in the matrix.
    Columns without dispersion are excluded and counted in 'n_constant'.
    """
    M, n_constant = _trial_matrix(R)
    N = M.shape[1]
    if N == 0:
        return {'n_trials': 0, 'n_constant': n_constant, 'effective_rank': _NAN,
                'avg_correlation': _NAN, 'n_eff_avg_corr': _NAN}
    if N == 1:
        return {'n_trials': 1, 'n_constant': n_constant, 'effective_rank': 1.0,
                'avg_correlation': _NAN, 'n_eff_avg_corr': 1.0}
    C = np.clip(np.corrcoef(M, rowvar=False), -1.0, 1.0)
    np.fill_diagonal(C, 1.0)
    rho_bar = float(C[np.triu_indices(N, 1)].mean())
    denom = 1.0 + (N - 1) * rho_bar
    return {
        'n_trials': int(N),
        'n_constant': n_constant,
        'effective_rank': _entropy_effective_rank(C),
        'avg_correlation': rho_bar,
        'n_eff_avg_corr': float(min(N, N / denom)) if denom > 0 else float(N),
    }


def _entropy_effective_rank(C: np.ndarray) -> float:
    """exp(entropy) of the normalised positive eigenvalues of a symmetric matrix C."""
    lam = np.linalg.eigvalsh(np.asarray(C, dtype=float))
    lam = lam[lam > 1e-12 * max(float(lam.max()), 1e-300)]
    p = lam / lam.sum()
    return float(np.exp(-np.sum(p * np.log(p))))


def trial_sharpe_variance(R, periods: int = 252) -> float:
    """Cross-sectional variance (ddof = 1) of the annualised Sharpe ratios of N trials.

    The empirical V[{SR_n}] of Bailey & López de Prado (2014) for the expected maximum
    Sharpe of the Deflated Sharpe Ratio: pass it as var_sr_trials_ann to
    deflated_sharpe_ratio / dsr_curve instead of the null default periods / T. Highly
    correlated trials have similar Sharpes, so this is smaller than periods / T when the
    family is redundant — the counterpart of an effective number of trials below N.
    Rows with a non-finite entry are dropped; constant columns are excluded. NaN for
    fewer than two trials.
    """
    M, _ = _trial_matrix(R)
    if M.shape[1] < 2:
        return _NAN
    sr = M.mean(axis=0) / M.std(axis=0, ddof=1) * np.sqrt(periods)
    return float(np.var(sr, ddof=1))


def dsr_curve(returns, n_values, var_sr_trials_ann: float = None, periods: int = 252,
              variance_at: str = 'estimate') -> list:
    """Deflated Sharpe Ratio as a function of the number of trials N.

    The number of trials behind a backtest is never known exactly, so the DSR is reported
    over a range of N rather than at one guessed value: for each N in n_values,
    deflated_sharpe_ratio(returns, N, var_sr_trials_ann, periods, variance_at). Returns
    [{'n_trials', 'sr_star_ann', 'dsr'}] in the order of n_values; sr_star_ann is the
    expected maximum annual Sharpe of N null trials the observed Sharpe is tested against.
    N must be a whole number: the Gumbel approximation of the expected maximum falls
    towards -inf as N approaches 1 from above, so round an effective number of trials
    (effective_number_of_trials) up, not down. var_sr_trials_ann, if given, must be
    finite (trial_sharpe_variance is NaN for fewer than two trials).
    """
    if var_sr_trials_ann is not None and not np.isfinite(var_sr_trials_ann):
        raise ValueError("var_sr_trials_ann must be finite (or None for the null default)")
    rows = []
    for N in n_values:
        if N != int(N):
            raise ValueError(f"numbers of trials must be whole numbers, got {N}")
        d = deflated_sharpe_ratio(returns, int(N), var_sr_trials_ann, periods, variance_at)
        rows.append({'n_trials': int(N), 'sr_star_ann': d['sr_star_ann'], 'dsr': d['dsr']})
    return rows


def sharpe_hurdles(T: int, n_tests: int = 1, periods: int = 252, alpha: float = 0.05,
                   rho: float = 0.0) -> dict:
    """Annual Sharpe ratio a T-period track record needs to clear common t-ratio hurdles.

    With IID returns the t-ratio of the mean is t = SR * sqrt(T), SR per period (Harvey &
    Liu 2015, eqs. 1-2), so a hurdle t_h is an annual Sharpe of t_h * sqrt(periods / T).
    With serial correlation the t-ratio uses a long-run (HAC) standard error; rho != 0
    takes it from an AR(1) with lag-1 autocorrelation rho, scaling every Sharpe hurdle by
    sqrt((1 + rho) / (1 - rho)) — the SR = 0 variance of power.sharpe_ratio_variance.
    Hurdles:
      'single_test'          z_{1-alpha}: one test, one-sided;
      'hlz'                  t = 3.0, Harvey, Liu & Zhu (2016), abstract and Sec. 3.6;
      'cgs'                  t = 3.8, Chordia, Goyal & Saretto (2020): the multiple-
                             testing threshold for time-series alphas;
      'bonferroni_one_sided' z_{1 - alpha / n_tests}: H1 SR > 0, family-wise level alpha;
      'bonferroni_two_sided' z_{1 - alpha / (2 n_tests)}: the Bonferroni line of Harvey &
                             Liu's Profit_Hurdle.m, whose p-values are two-sided (their
                             eq. 3: a long-short strategy may be traded either way).
    The haircut Sharpe of Harvey & Liu is undefined for a negative observed Sharpe, which
    is why the hurdles are reported instead. Holm / BHY hurdles are not ported: they draw
    the untested strategies from HLZ's factor-zoo model, which does not describe an in-
    house parameter grid (use snooping.romano_wolf for that). t-hurdles depend on the
    research context (Chen 2023 argues against raising them); they are reference points.
    Returns {'n_obs', 'n_tests', 'periods', 'alpha', 'rho',
    'hurdles': {name: {'t', 'sr_ann'}}}.
    """
    if T < 2 or n_tests < 1:
        raise ValueError("need T >= 2 and n_tests >= 1")
    if not -1.0 < rho < 1.0:
        raise ValueError("rho must lie in (-1, 1)")
    to_sr = np.sqrt(periods / float(T) * (1.0 + rho) / (1.0 - rho))
    t = {
        'single_test': float(_sps.norm.ppf(1.0 - alpha)),
        'hlz': 3.0,
        'cgs': 3.8,
        'bonferroni_one_sided': float(_sps.norm.ppf(1.0 - alpha / n_tests)),
        'bonferroni_two_sided': float(_sps.norm.ppf(1.0 - alpha / (2.0 * n_tests))),
    }
    return {
        'n_obs': int(T), 'n_tests': int(n_tests), 'periods': int(periods), 'alpha': float(alpha),
        'rho': float(rho),
        'hurdles': {name: {'t': v, 'sr_ann': float(v * to_sr)} for name, v in t.items()},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Factor attribution
# ──────────────────────────────────────────────────────────────────────────────

def _bartlett_hac_covariance(X: np.ndarray, e: np.ndarray, lags: int) -> np.ndarray:
    """Newey-West (1987) covariance of OLS coefficients, Bartlett weights 1 - k/(lags+1).

    (X'X)^-1 S (X'X)^-1 with S = sum_{|k|<=lags} w_k sum_t x_t e_t e_{t-k} x_{t-k}', and
    no small-sample correction (statsmodels' cov_type='HAC' with use_correction=False).
    """
    XtX_inv = np.linalg.inv(X.T @ X)
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for k in range(1, lags + 1):
        w = 1.0 - k / (lags + 1.0)
        G = Xe[k:].T @ Xe[:-k]
        S += w * (G + G.T)
    return XtX_inv @ S @ XtX_inv


def factor_attribution(strategy_returns, market_returns, periods: int = 252) -> dict:
    """Regress daily strategy returns on a market factor: r_t = alpha + beta * m_t + e_t.

    A pairs book is meant to be market-neutral, but hedge-ratio weights are not
    beta-neutral in general, so the market exposure is measured rather than assumed.
    Standard errors are Newey-West (Bartlett kernel, the same lag rule as hac_tstat_mean).
    alpha is reported annualised (x periods). Inputs must be date-aligned (see
    align_return_series).
    """
    y = np.asarray(strategy_returns, dtype=float)
    x = np.asarray(market_returns, dtype=float)
    n = min(len(y), len(x))
    y, x = y[:n], x[:n]
    ok = np.isfinite(y) & np.isfinite(x)                # drop rows missing in EITHER series
    y, x = y[ok], x[ok]
    n = len(y)
    if n < 20 or np.std(x) <= 0:
        return {'n': int(n), 'alpha_ann': float('nan'), 'beta': float('nan'),
                'alpha_tstat': float('nan'), 'beta_tstat': float('nan'), 'r2': float('nan')}
    X = np.column_stack([np.ones(n), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ coef
    lags = _newey_west_lags(n)
    V = _bartlett_hac_covariance(X, e, lags)
    se = np.sqrt(np.maximum(np.diag(V), 1e-30))
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return {
        'n': int(n),
        'alpha_ann': float(coef[0] * periods),
        'beta': float(coef[1]),
        'alpha_tstat': float(coef[0] / se[0]),
        'beta_tstat': float(coef[1] / se[1]),
        'r2': float(1.0 - (e ** 2).sum() / ss_tot) if ss_tot > 0 else float('nan'),
        'lags': int(lags),
    }


def _calendar_days(index: pd.Index) -> pd.Index:
    """A date-like index as 'YYYY-MM-DD' calendar days (time of day and time zone
    dropped, see _as_day_strings); a numeric index is returned unchanged."""
    if pd.api.types.is_numeric_dtype(index.dtype):
        return index
    return pd.Index(_as_day_strings(index))


def factor_attribution_multi(strategy_returns, factors: pd.DataFrame, periods: int = 252,
                             max_lag: int = None, includes_cash_return: bool = False) -> dict:
    """Time-series regression of excess strategy returns on several factors, Newey-West errors.

        r_t = alpha + sum_j beta_j f_jt + e_t      (OLS; r_t in excess of cash)

    factors : DataFrame of per-period factor returns in the same units as the strategy
              (decimal; Ken French's files are in percent), one column per factor, e.g.
              Mkt-RF, SMB, HML, RMW, CMA, Mom, ST_Rev, LT_Rev. A column named 'RF' is the
              risk-free rate, never a regressor.
    includes_cash_return : whether strategy_returns contain interest on the account's
              cash. The engine's do not: equity earns no interest and a long-short book
              finances itself, so its daily return is already an excess-of-cash return,
              like the zero-cost factor premia, and is used as given (False, the default).
              Subtracting RF from it would count cash twice and bias alpha down by the
              average bill rate (about 4.7%/yr over 2023-07..2025-12). For the total
              return of a funded account pass True: RF_t (the 'RF' column, required) is
              then subtracted from r_t before the regression.
    strategy_returns : a Series is aligned with `factors` by calendar day (inner join;
              string, naive, tz-aware and intraday-stamped date indexes all match by
              their day, as in align_return_series); an array must already be aligned
              row for row. Rows with a non-finite value are dropped.
    max_lag : Bartlett truncation lag; None uses the Newey-West rule of hac_tstat_mean.

    Returns 'alpha_ann' (alpha x periods) and 'alpha_tstat', 'r2', and per factor
    {'beta', 'tstat', 'variance_share'}: beta_j Cov(f_j, fitted) / Var(fitted), the
    covariance decomposition of the explained variance (shares sum to one and are
    negative for a factor that offsets the others; multiply by r2 for a share of the
    total variance). Standard errors are those of factor_attribution, without a small-
    sample correction (equal to statsmodels OLS cov_type='HAC', use_correction=False).
    """
    if not isinstance(factors, pd.DataFrame):
        raise TypeError("factors must be a DataFrame with one column per factor")
    if includes_cash_return and 'RF' not in factors.columns:
        raise ValueError("includes_cash_return=True needs an 'RF' column to subtract")
    F = factors.astype(float)
    if isinstance(strategy_returns, pd.Series):
        s = strategy_returns.astype(float)
        s.index = _calendar_days(s.index)
        F.index = _calendar_days(F.index)
        s = s[~s.index.duplicated(keep='last')]
        F = F[~F.index.duplicated(keep='last')]
        joined = pd.concat([s.rename('__strategy__'), F], axis=1, join='inner').sort_index()
        if joined.empty and len(s) and len(F):
            raise ValueError("strategy_returns and factors have no date in common")
        y = joined.pop('__strategy__').to_numpy()
        F = joined
    else:
        y = np.asarray(strategy_returns, dtype=float).ravel()
        if len(y) != len(F):
            raise ValueError("strategy_returns and factors must have the same length "
                             "(or pass a Series to align on dates)")
    names = [c for c in F.columns if c != 'RF']
    rf = F['RF'].to_numpy() if includes_cash_return else np.zeros(len(y))
    Xf = F[names].to_numpy()
    ok = np.isfinite(y) & np.isfinite(rf) & np.isfinite(Xf).all(axis=1)
    y, Xf = (y - rf)[ok], Xf[ok]
    n, k = Xf.shape
    lags = _newey_west_lags(n) if max_lag is None else int(max_lag)
    out = {'n': int(n), 'lags': int(lags), 'rf_subtracted': bool(includes_cash_return),
           'alpha_ann': _NAN, 'alpha_tstat': _NAN, 'r2': _NAN,
           'factors': {f: {'beta': _NAN, 'tstat': _NAN, 'variance_share': _NAN} for f in names}}
    if k == 0 or n < max(20, k + 2) or any(_is_constant(Xf[:, j]) for j in range(k)):
        return out
    X = np.column_stack([np.ones(n), Xf])
    if np.linalg.matrix_rank(X) < k + 1:
        return out
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ coef
    se = np.sqrt(np.maximum(np.diag(_bartlett_hac_covariance(X, e, lags)), 1e-30))
    fitted = Xf @ coef[1:]
    fc = fitted - fitted.mean()
    var_fit = float(fc @ fc)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    for j, f in enumerate(names):
        share = coef[j + 1] * float((Xf[:, j] - Xf[:, j].mean()) @ fc) / var_fit if var_fit > 0 else _NAN
        out['factors'][f] = {'beta': float(coef[j + 1]), 'tstat': float(coef[j + 1] / se[j + 1]),
                             'variance_share': float(share)}
    out.update({
        'alpha_ann': float(coef[0] * periods),
        'alpha_tstat': float(coef[0] / se[0]),
        'r2': float(1.0 - (e ** 2).sum() / ss_tot) if ss_tot > 0 else _NAN,
    })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Top-level report
# ──────────────────────────────────────────────────────────────────────────────

def significance_report(daily_returns, oos_window_returns=None,
                        oos_daily_returns=None, n_trials: int = 1,
                        var_sr_trials_ann: float = None, periods: int = 252) -> dict:
    """Assemble the full significance report from the strategy's return series.

    daily_returns      : main-backtest daily return series (the optimistic bound).
    oos_daily_returns  : stitched out-of-sample daily returns (the honest estimate),
                         if available — gets the same battery of tests.
    oos_window_returns : per-window OOS returns (for the small-sample window test).
    n_trials, var_sr_trials_ann : inputs for the Deflated Sharpe (multiple-testing).
    """
    def _battery(r):
        r = _finite(r)
        lo = lo_annualized_sharpe(r, periods)
        out = {
            'n_days': int(len(r)),
            'ann_sharpe': annualized_sharpe(r, periods),
            # v32: Lo (2002) autocorrelation-adjusted annualisation, next to the IID one
            'ann_sharpe_lo': lo['sharpe'],
            'lo_eta': lo['eta'],
            'lo_lags': lo['lags'],
            'psr_gt0': probabilistic_sharpe_ratio(r, 0.0, periods),
            # v32: robustness variant (variance evaluated under H0) — see the PSR docstring
            'psr_gt0_null_variance': probabilistic_sharpe_ratio(r, 0.0, periods,
                                                                variance_at='null'),
            'hac': hac_tstat_mean(r),
            'bootstrap_sharpe_ci': block_bootstrap_sharpe_ci(r, periods=periods),
        }
        if n_trials and n_trials > 1:
            out['deflated_sharpe'] = deflated_sharpe_ratio(r, n_trials, var_sr_trials_ann, periods)
        return out

    report = {'main_backtest': _battery(daily_returns)}
    if oos_daily_returns is not None and len(oos_daily_returns) > 2:
        report['oos_daily'] = _battery(oos_daily_returns)
    if oos_window_returns is not None and len(oos_window_returns) >= 2:
        report['oos_windows'] = oos_window_test(oos_window_returns)
    return report


def _fmt(x, spec: str, scale: float = 1.0) -> str:
    """Format a number, or 'n/a' for None/NaN/non-numeric (the log must never raise)."""
    try:
        v = float(x) * scale
    except (TypeError, ValueError):
        return 'n/a'
    return format(v, spec) if np.isfinite(v) else 'n/a'


def _below(p, level: float = 0.05) -> bool:
    try:
        return bool(np.isfinite(float(p)) and float(p) < level)
    except (TypeError, ValueError):
        return False


def ci_zero_label(lo, hi) -> str:
    """Describe where zero sits relative to an interval [lo, hi].

    v32: the log used to print '(includes 0 → within noise)' for any interval whose
    lower end was <= 0 — including one lying entirely BELOW zero, which is significant
    evidence of a negative Sharpe, not noise.
    """
    try:
        lo, hi = float(lo), float(hi)
    except (TypeError, ValueError):
        return '(n/a)'
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return '(n/a)'
    if lo > 0:
        return '(excludes 0: positive)'
    if hi < 0:
        return '(excludes 0: negative)'
    return '(includes 0 → within noise)'


def log_significance_report(report: dict):
    """Pretty-print the significance report to the log.

    v32: tolerant of missing keys and NaN values (a degenerate series used to raise
    KeyError here and take the whole report down with it).
    """
    logger.info("\n" + "=" * 78)
    logger.info(f"{'STATISTICAL SIGNIFICANCE — is the edge real?':^78}")
    logger.info("=" * 78)

    def _line_block(name, b):
        b = b or {}
        logger.info(f"\n{name}:")
        logger.info(f"  Ann. Sharpe          : {_fmt(b.get('ann_sharpe'), '.3f')}  "
                    f"({b.get('n_days', 'n/a')} days) | Lo (2002) autocorr-adjusted "
                    f"{_fmt(b.get('ann_sharpe_lo'), '.3f')} ({b.get('lo_lags', 'n/a')} lags)")
        psr = b.get('psr_gt0') or {}
        psr_null = b.get('psr_gt0_null_variance') or {}
        logger.info(f"  P(true Sharpe > 0)   : {_fmt(psr.get('psr'), '5.1f', 100)}%   "
                    f"[skew {_fmt(psr.get('skew'), '+.2f')}, kurt {_fmt(psr.get('kurtosis'), '.2f')}; "
                    f"null-variance form {_fmt(psr_null.get('psr'), '.1f', 100)}%]")
        hac = b.get('hac') or {}
        logger.info(f"  HAC t-stat (mean≠0)  : {_fmt(hac.get('tstat'), '.2f')}  "
                    f"(p={_fmt(hac.get('pvalue'), '.3f')}, {hac.get('lags', 'n/a')} lags)  "
                    f"{'SIGNIFICANT' if _below(hac.get('pvalue')) else 'not significant'} @5%")
        ci = b.get('bootstrap_sharpe_ci') or {}
        logger.info(f"  Bootstrap 95% Sharpe : [{_fmt(ci.get('lo'), '+.2f')}, {_fmt(ci.get('hi'), '+.2f')}]  "
                    f"{ci_zero_label(ci.get('lo'), ci.get('hi'))}  "
                    f"(block {ci.get('block', 'n/a')}, {ci.get('block_method', 'n/a')})")
        if 'deflated_sharpe' in b:
            d = b['deflated_sharpe'] or {}
            logger.info(f"  Deflated Sharpe (DSR): {_fmt(d.get('dsr'), '5.1f', 100)}%   "
                        f"[vs E[max] SR* {_fmt(d.get('sr_star_ann'), '.2f')} over "
                        f"{d.get('n_trials', 'n/a')} trials]")

    if 'main_backtest' in report:
        _line_block("MAIN BACKTEST (optimistic bound)", report['main_backtest'])
    if 'oos_daily' in report:
        _line_block("OUT-OF-SAMPLE, stitched daily (honest estimate)", report['oos_daily'])
    if 'oos_windows' in report:
        w = report['oos_windows'] or {}
        n = w.get('n', 'n/a')
        logger.info(f"\nOOS WINDOWS (n={n}, the binding constraint):")
        logger.info(f"  mean {_fmt(w.get('mean'), '+.3f', 100)}%/qtr | t-stat {_fmt(w.get('tstat'), '.2f')} | "
                    f"p={_fmt(w.get('pvalue'), '.3f')} (two-sided) | {w.get('positive', 'n/a')}/{n} positive | "
                    f"95% CI (t) [{_fmt(w.get('ci_lo'), '+.3f', 100)}%, {_fmt(w.get('ci_hi'), '+.3f', 100)}%]")
        logger.info(f"  one-sided p: H1 mean<0 {_fmt(w.get('pvalue_mean_lt0'), '.3f')} | "
                    f"H1 mean>0 {_fmt(w.get('pvalue_mean_gt0'), '.3f')}")
        logger.info(f"    (percentile bootstrap CI, secondary: "
                    f"[{_fmt(w.get('boot_ci_lo'), '+.3f', 100)}%, {_fmt(w.get('boot_ci_hi'), '+.3f', 100)}%] — "
                    f"unreliable at n={n} with tied zeros; the t interval above is "
                    f"the one consistent with the reported p-value)")
        logger.info(f"  {'SIGNIFICANT' if _below(w.get('pvalue')) else 'NOT significant'} @5% (two-sided)")
    logger.info("=" * 78)
