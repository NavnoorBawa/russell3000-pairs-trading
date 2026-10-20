"""
POWER, MINIMUM TRACK RECORD AND THE SHARPE RATIOS A SAMPLE RULES OUT
===================================================================
A null result is informative only to the extent the test had power. This module turns
"the Sharpe ratio is not significantly different from zero" into statements a reviewer
can check: which Sharpe ratios the sample could have detected (critical Sharpe, minimum
detectable Sharpe, power against stated alternatives), how long a track record each
alternative needs (minimum track record length), which Sharpe ratios the sample rules
out (one-sided upper confidence bound, tests of H0: SR >= x and equivalence tests) and
how strongly the data favour SR = SR0 over each alternative (Bayes factors).

Every quantity rests on the asymptotic variance of the per-period Sharpe ratio estimator
of López de Prado, Lipton & Zoonekynd (2025), which extends the non-normal IID variance
(Mertens 2002; Opdyke 2007) to AR(1) returns:

    Var(SR_hat) = (a - b * skew * SR + c * (kurt - 1) / 4 * SR^2) / T,
    a = 1 + 2 rho / (1 - rho),
    b = 1 + rho / (1 - rho) + rho^2 / (1 - rho^2),
    c = 1 + 2 rho^2 / (1 - rho^2),

with SR in per-period units, skew and non-excess kurtosis of the returns, rho their lag-1
autocorrelation and T the number of observations. At rho = 0 this is the variance the
PSR in significance.py uses (which divides by T - 1); at SR = 0 it is
(1 + rho) / (1 - rho) / T, the AR(1) long-run variance of a mean. sharpe_ratio_variance, critical_sharpe_ratio,
sharpe_ratio_power and minimum_track_record_length below port the functions of the same
names in the authors' code (github.com/zoonek/2025-sharpe-ratio, functions.py) for a
single test (their K = 1); tests/test_power.py reproduces that file's unit tests.

References:
  López de Prado, Lipton & Zoonekynd (2025) "Sharpe Ratio Inference: A New Standard for
    Reporting and Decision-Making", ADIA Lab (SSRN 5520741).
  Bailey & López de Prado (2012) "The Sharpe Ratio Efficient Frontier", Journal of Risk
    15(2) — minimum track record length.
  Mertens (2002) "Comments on variance of the IID estimator in Lo (2002)", working
    paper, University of Basel; Opdyke (2007) "Comparing Sharpe ratios: So where are the
    p-values?", Journal of Asset Management 8(5).
"""

from pairs_trading.config import np
from scipy import stats as _sps
from scipy.optimize import brentq

from pairs_trading.significance import _autocorrelations, _finite, _is_constant, annualized_sharpe

_NAN = float('nan')
_MIN_VARIANCE = 1e-18


def _check_rho(rho: float) -> None:
    if not -1.0 < rho < 1.0:
        raise ValueError("rho must lie in (-1, 1)")


def sharpe_ratio_variance(sr: float, n: float, skew: float = 0.0, kurtosis: float = 3.0,
                          rho: float = 0.0) -> float:
    """Asymptotic variance of the per-period Sharpe ratio estimator (module docstring).

    sr: per-period Sharpe ratio at which the variance is evaluated; n: number of
    observations (n = 1 gives the per-observation variance that the minimum track record
    length scales); kurtosis is non-excess (3 = normal); rho is the lag-1 autocorrelation
    of the returns, the dependence assumed to be AR(1).
    """
    _check_rho(rho)
    b_ = rho / (1.0 - rho)
    c_ = rho ** 2 / (1.0 - rho ** 2)
    a, b, c = 1.0 + 2.0 * b_, 1.0 + b_ + c_, 1.0 + 2.0 * c_
    return float((a - b * skew * sr + c * (kurtosis - 1.0) / 4.0 * sr ** 2) / n)


def _sd(sr, n, skew, kurtosis, rho) -> float:
    return float(np.sqrt(max(sharpe_ratio_variance(sr, n, skew, kurtosis, rho), _MIN_VARIANCE)))


def critical_sharpe_ratio(sr0: float, n: float, skew: float = 0.0, kurtosis: float = 3.0,
                          rho: float = 0.0, alpha: float = 0.05) -> float:
    """Per-period critical value of the one-sided level-alpha test H0: SR = sr0 vs SR > sr0.

    SR_c = sr0 + z_{1-alpha} * sd(SR_hat | SR = sr0): the variance is evaluated AT THE NULL.
    """
    return float(sr0 + _sps.norm.ppf(1.0 - alpha) * _sd(sr0, n, skew, kurtosis, rho))


def sharpe_ratio_power(sr0: float, sr1: float, n: float, skew: float = 0.0, kurtosis: float = 3.0,
                       rho: float = 0.0, alpha: float = 0.05) -> float:
    """Power of the one-sided level-alpha test of H0: SR = sr0 when the true SR is sr1.

    1 - Phi((SR_c - sr1) / sd(SR_hat | SR = sr1)): the critical value is set under the null
    and the sampling distribution under the alternative uses the variance AT sr1.
    Sharpe ratios are per period.
    """
    sr_c = critical_sharpe_ratio(sr0, n, skew, kurtosis, rho, alpha)
    return float(_sps.norm.sf((sr_c - sr1) / _sd(sr1, n, skew, kurtosis, rho)))


def minimum_track_record_length(sr: float, sr0: float, skew: float = 0.0, kurtosis: float = 3.0,
                                rho: float = 0.0, alpha: float = 0.05) -> float:
    """Observations needed for a per-period Sharpe `sr` to be significantly above `sr0`.

    MinTRL = Var_1(SR_hat | SR = sr0) * (z_{1-alpha} / (sr - sr0))^2, where Var_1 is the
    per-observation variance (n = 1) evaluated AT THE NULL, as in López de Prado, Lipton &
    Zoonekynd (2025); Bailey & López de Prado (2012) evaluate it at the observed SR. A
    Sharpe ratio at or below sr0 never becomes significant: the result is then inf (the
    reference code would square a negative distance into a finite length).
    """
    if sr <= sr0:
        return float('inf')
    v1 = max(sharpe_ratio_variance(sr0, 1.0, skew, kurtosis, rho), _MIN_VARIANCE)
    return float(v1 * (_sps.norm.ppf(1.0 - alpha) / (sr - sr0)) ** 2)


def minimum_detectable_sharpe(sr0: float, n: float, skew: float = 0.0, kurtosis: float = 3.0,
                              rho: float = 0.0, alpha: float = 0.05, power: float = 0.80) -> float:
    """Smallest per-period Sharpe ratio sr1 > sr0 detected with probability `power`.

    Solves sharpe_ratio_power(sr0, sr1, ...) = power, i.e.
    sr1 - z_{power} * sd(SR_hat | SR = sr1) = SR_c, with the same variance conventions as
    sharpe_ratio_power (critical value at the null, sampling spread at sr1).
    """
    if not 0.0 < power < 1.0:
        raise ValueError("power must lie in (0, 1)")
    sr_c = critical_sharpe_ratio(sr0, n, skew, kurtosis, rho, alpha)
    z_pow = _sps.norm.ppf(power)

    def gap(s):
        return s - z_pow * _sd(s, n, skew, kurtosis, rho) - sr_c

    step = max(_sd(sr0, n, skew, kurtosis, rho), 1e-6)
    lo, hi = sr_c - step, sr_c + step
    for _ in range(60):
        if gap(lo) < 0 < gap(hi):
            return float(brentq(gap, lo, hi, xtol=1e-14, rtol=1e-12))
        step *= 2.0
        if gap(lo) >= 0:
            lo -= step
        if gap(hi) <= 0:
            hi += step
    # the sampling spread grows as fast as the Sharpe itself (a handful of observations)
    return float('inf')


def power_report(returns, periods: int = 252, alpha: float = 0.05, power: float = 0.80,
                 alternatives=(0.5, 1.0, 1.5, 2.0), sr0: float = 0.0) -> dict:
    """Power, detectable and excluded Sharpe ratios of a per-period return series.

    Sample moments: the Sharpe ratio is annualized_sharpe (ddof = 1); skew and non-excess
    kurtosis are the bias-corrected estimates the PSR uses; rho is the lag-1 sample
    autocorrelation. All Sharpe ratios in and out are annualised by sqrt(periods) (the
    IID annualisation of the headline Sharpe; autocorrelation enters through the
    variance, not the annualisation). alternatives and sr0 are annual Sharpe ratios.

    Variance convention of each quantity ("null": Var evaluated at the hypothesised SR;
    "estimate": at the observed SR; both are listed under 'variance_at' in the output):
      se_ann                    estimate (Wald standard error of the observed Sharpe).
      critical_sr_ann           null (sr0): observed annual SR above which the one-sided
                                level-alpha test rejects SR = sr0.
      min_detectable_sr_ann     null for the critical value, the alternative itself for
                                the sampling spread: the SR detected with probability
                                `power`.
      upper_bound_ann           estimate: SR_hat + z_{1-alpha} se, the one-sided
                                (1 - alpha) upper confidence bound.
      per alternative x (annual, in 'alternatives'):
        power                   as min_detectable_sr_ann, evaluated at SR = x.
        min_trl_years           null (sr0): years of data a strategy whose SR is x needs
                                for its observed SR to be significant at alpha (inf if
                                x <= sr0).
        p_sr_at_least           estimate: one-sided p-value of H0: SR >= x,
                                Phi((SR_hat - x) / se). It is below alpha exactly when x
                                exceeds upper_bound_ann (test-interval duality).
        p_equivalence           estimate: TOST p-value of H0: |SR| >= x,
                                max(p(SR >= x), p(SR <= -x)); small values support
                                -x < SR < x.
        bayes_factor_null_vs_alt  each hypothesis at its own SR: the likelihood ratio
                                N(SR_hat; sr0, Var(sr0)) / N(SR_hat; x, Var(x)) of the
                                normal approximation. > 1 favours SR = sr0, e.g. 3.5 means
                                the data are 3.5 times as likely under SR = sr0 as under
                                SR = x.
    The approximation is asymptotic and the dependence correction assumes AR(1) only.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie in (0, 1)")
    r = _finite(returns)
    n = len(r)
    ann = float(np.sqrt(periods))
    alternatives = [float(x) for x in alternatives]
    out = {
        'n': n, 'periods': int(periods), 'alpha': float(alpha), 'power': float(power),
        'sr0_ann': float(sr0), 'sr_ann': annualized_sharpe(r, periods), 'se_ann': _NAN,
        'skew': _NAN, 'kurtosis': _NAN, 'rho': _NAN, 'critical_sr_ann': _NAN,
        'min_detectable_sr_ann': _NAN, 'upper_bound_ann': _NAN,
        'alternatives': [{'sr_ann': x, 'power': _NAN, 'min_trl_years': _NAN,
                          'p_sr_at_least': _NAN, 'p_equivalence': _NAN,
                          'bayes_factor_null_vs_alt': _NAN} for x in alternatives],
        'variance_at': {'se_ann': 'estimate', 'critical_sr_ann': 'null',
                        'min_detectable_sr_ann': 'null and alternative',
                        'upper_bound_ann': 'estimate', 'power': 'null and alternative',
                        'min_trl_years': 'null', 'p_sr_at_least': 'estimate',
                        'p_equivalence': 'estimate', 'bayes_factor_null_vs_alt': 'each hypothesis'},
    }
    if n < 4 or _is_constant(r):
        return out

    sr = float(r.mean() / r.std(ddof=1))
    g3 = float(_sps.skew(r, bias=False))
    g4 = float(_sps.kurtosis(r, fisher=False, bias=False))
    rho = float(_autocorrelations(r, 1)[0])
    s0 = sr0 / ann
    se = _sd(sr, n, g3, g4, rho)
    z = float(_sps.norm.ppf(1.0 - alpha))
    sd0 = _sd(s0, n, g3, g4, rho)
    out.update({
        'se_ann': se * ann, 'skew': g3, 'kurtosis': g4, 'rho': rho,
        'critical_sr_ann': critical_sharpe_ratio(s0, n, g3, g4, rho, alpha) * ann,
        'min_detectable_sr_ann': minimum_detectable_sharpe(s0, n, g3, g4, rho, alpha, power) * ann,
        'upper_bound_ann': (sr + z * se) * ann,
    })
    for row, x_ann in zip(out['alternatives'], alternatives):
        x = x_ann / ann
        p_ge = float(_sps.norm.cdf((sr - x) / se))
        p_le = float(_sps.norm.sf((sr + x) / se))
        sd_x = _sd(x, n, g3, g4, rho)
        log_bf = (_sps.norm.logpdf(sr, loc=s0, scale=sd0)
                  - _sps.norm.logpdf(sr, loc=x, scale=sd_x))
        row.update({
            'power': sharpe_ratio_power(s0, x, n, g3, g4, rho, alpha),
            'min_trl_years': minimum_track_record_length(x, s0, g3, g4, rho, alpha) / periods,
            'p_sr_at_least': p_ge,
            'p_equivalence': max(p_ge, p_le) if x > 0 else _NAN,
            'bayes_factor_null_vs_alt': float(np.exp(log_bf)),
        })
    return out
