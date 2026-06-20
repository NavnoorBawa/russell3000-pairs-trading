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
  - Stationary/block bootstrap confidence intervals on the annualised Sharpe.
  - Small-sample t-test + bootstrap CI on the per-window OOS mean return.

References:
  Lo (2002) "The Statistics of Sharpe Ratios", Financial Analysts Journal.
  Bailey & López de Prado (2012, 2014), Journal of Risk / Journal of Portfolio Mgmt.
"""

from pairs_trading.config import np, logging
from scipy import stats as _sps

logger = logging.getLogger(__name__)

_EULER_GAMMA = 0.5772156649015329


# ──────────────────────────────────────────────────────────────────────────────
# Core Sharpe statistics
# ──────────────────────────────────────────────────────────────────────────────

def annualized_sharpe(returns: np.ndarray, periods: int = 252) -> float:
    """Annualised Sharpe of a per-period (e.g. daily) return series."""
    r = np.asarray(returns, dtype=float)
    sd = r.std(ddof=1)
    if sd <= 0 or len(r) < 2:
        return 0.0
    return float(r.mean() / sd * np.sqrt(periods))


def probabilistic_sharpe_ratio(returns: np.ndarray, sr_benchmark_ann: float = 0.0,
                               periods: int = 252) -> dict:
    """Probabilistic Sharpe Ratio: P(true SR > benchmark).

    Works in per-period (non-annualised) Sharpe units internally, incorporating the
    skewness and (non-excess) kurtosis of the return distribution — so fat tails and
    negative skew correctly *reduce* confidence in a positive Sharpe.
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    sd = r.std(ddof=1)
    if n < 3 or sd <= 0:
        return {'psr': float('nan'), 'sr_ann': 0.0, 'n': n}

    sr = r.mean() / sd                                  # per-period SR
    sr_star = sr_benchmark_ann / np.sqrt(periods)       # benchmark in per-period units
    g3 = float(_sps.skew(r, bias=False))
    g4 = float(_sps.kurtosis(r, fisher=False, bias=False))   # non-excess (3 = normal)

    denom = np.sqrt(max(1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr, 1e-12))
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
    }


def deflated_sharpe_ratio(returns: np.ndarray, n_trials: int,
                          var_sr_trials_ann: float = None, periods: int = 252) -> dict:
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
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < 3 or n_trials < 1:
        return {'dsr': float('nan'), 'sr_star_ann': float('nan'), 'n_trials': n_trials}

    if var_sr_trials_ann is None or var_sr_trials_ann <= 0:
        var_sr_trials_ann = periods / float(n)        # null estimator variance, annualised
    std_sr_ann = np.sqrt(var_sr_trials_ann)
    N = float(n_trials)
    # Expected maximum of N iid standard-normal-ish Sharpe estimates (Gumbel approx)
    z1 = _sps.norm.ppf(1.0 - 1.0 / N)
    z2 = _sps.norm.ppf(1.0 - 1.0 / (N * np.e))
    sr_star_ann = std_sr_ann * ((1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2)

    psr_vs_star = probabilistic_sharpe_ratio(r, sr_benchmark_ann=sr_star_ann, periods=periods)
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
    Testing mean = 0 is equivalent to testing Sharpe = 0.
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < 3:
        return {'tstat': 0.0, 'pvalue': 1.0, 'mean': 0.0, 'lags': 0}

    if max_lag is None:
        max_lag = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))   # Newey-West rule of thumb
        max_lag = max(1, max_lag)

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
# Bootstrap
# ──────────────────────────────────────────────────────────────────────────────

def block_bootstrap_sharpe_ci(returns: np.ndarray, block: int = 10, n_boot: int = 5000,
                              alpha: float = 0.05, periods: int = 252, seed: int = 42) -> dict:
    """Circular block-bootstrap CI on the annualised Sharpe (preserves autocorrelation)."""
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < block + 1:
        return {'lo': float('nan'), 'hi': float('nan'), 'point': annualized_sharpe(r, periods)}
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    rr = np.concatenate([r, r[:block]])               # wrap for circular blocks
    boots = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        samp = np.concatenate([rr[s:s + block] for s in starts])[:n]
        boots[i] = annualized_sharpe(samp, periods)
    return {
        'lo': float(np.percentile(boots, 100 * alpha / 2)),
        'hi': float(np.percentile(boots, 100 * (1 - alpha / 2))),
        'point': annualized_sharpe(r, periods),
        'n_boot': n_boot, 'block': block,
    }


def bootstrap_mean_ci(values: np.ndarray, n_boot: int = 5000, alpha: float = 0.05,
                      seed: int = 42) -> dict:
    """Plain bootstrap CI on the mean of a small sample (e.g. OOS window returns)."""
    v = np.asarray(values, dtype=float)
    if len(v) < 2:
        return {'lo': float('nan'), 'hi': float('nan'), 'point': float(v.mean()) if len(v) else 0.0}
    rng = np.random.default_rng(seed)
    boots = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(n_boot)])
    return {
        'lo': float(np.percentile(boots, 100 * alpha / 2)),
        'hi': float(np.percentile(boots, 100 * (1 - alpha / 2))),
        'point': float(v.mean()),
    }


def oos_window_test(window_returns: np.ndarray) -> dict:
    """One-sample t-test + bootstrap CI that the per-window OOS mean return > 0."""
    v = np.asarray(window_returns, dtype=float)
    n = len(v)
    if n < 2:
        return {'n': n, 'mean': float(v.mean()) if n else 0.0, 'tstat': 0.0, 'pvalue': 1.0}
    t, p = _sps.ttest_1samp(v, 0.0)
    ci = bootstrap_mean_ci(v)
    return {
        'n': n,
        'mean': float(v.mean()),
        'std': float(v.std(ddof=1)),
        'tstat': float(t),
        'pvalue': float(p),
        'positive': int((v > 0).sum()),
        'ci_lo': ci['lo'], 'ci_hi': ci['hi'],
    }


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
        r = np.asarray(r, dtype=float)
        out = {
            'n_days': int(len(r)),
            'ann_sharpe': annualized_sharpe(r, periods),
            'psr_gt0': probabilistic_sharpe_ratio(r, 0.0, periods),
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


def log_significance_report(report: dict):
    """Pretty-print the significance report to the log."""
    logger.info("\n" + "=" * 78)
    logger.info(f"{'STATISTICAL SIGNIFICANCE — is the edge real?':^78}")
    logger.info("=" * 78)

    def _line_block(name, b):
        logger.info(f"\n{name}:")
        logger.info(f"  Ann. Sharpe          : {b['ann_sharpe']:.3f}  ({b['n_days']} days)")
        psr = b['psr_gt0']
        logger.info(f"  P(true Sharpe > 0)   : {psr['psr']*100:5.1f}%   "
                    f"[skew {psr['skew']:+.2f}, kurt {psr['kurtosis']:.2f}]")
        hac = b['hac']
        logger.info(f"  HAC t-stat (mean≠0)  : {hac['tstat']:.2f}  (p={hac['pvalue']:.3f}, "
                    f"{hac['lags']} lags)  {'SIGNIFICANT' if hac['pvalue']<0.05 else 'not significant'} @5%")
        ci = b['bootstrap_sharpe_ci']
        logger.info(f"  Bootstrap 95% Sharpe : [{ci['lo']:+.2f}, {ci['hi']:+.2f}]  "
                    f"{'(excludes 0)' if ci['lo']>0 else '(includes 0 → within noise)'}")
        if 'deflated_sharpe' in b:
            d = b['deflated_sharpe']
            logger.info(f"  Deflated Sharpe (DSR): {d['dsr']*100:5.1f}%   "
                        f"[vs E[max] SR* {d['sr_star_ann']:.2f} over {d['n_trials']} trials]")

    if 'main_backtest' in report:
        _line_block("MAIN BACKTEST (optimistic bound)", report['main_backtest'])
    if 'oos_daily' in report:
        _line_block("OUT-OF-SAMPLE, stitched daily (honest estimate)", report['oos_daily'])
    if 'oos_windows' in report:
        w = report['oos_windows']
        logger.info(f"\nOOS WINDOWS (n={w['n']}, the binding constraint):")
        logger.info(f"  mean {w['mean']*100:+.3f}%/qtr | t-stat {w['tstat']:.2f} | "
                    f"p={w['pvalue']:.3f} | {w['positive']}/{w['n']} positive | "
                    f"95% CI [{w['ci_lo']*100:+.3f}%, {w['ci_hi']*100:+.3f}%]")
        logger.info(f"  {'SIGNIFICANT' if w['pvalue']<0.05 else 'NOT significant'} @5%")
    logger.info("=" * 78)
