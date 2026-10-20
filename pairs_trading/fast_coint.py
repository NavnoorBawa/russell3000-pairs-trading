"""
PAIRS TRADING - FAST ENGLE-GRANGER TEST
=======================================
A numpy re-implementation of statsmodels.tsa.stattools.coint(y0, y1) at the settings the
pair selector uses (trend='c', method='aeg', maxlag=None, autolag='aic'), 13-30x faster
(87 to 755 observations).

The estimator, samples, lag search, tie-break, degrees of freedom and p-value function are
statsmodels'. The cointegrating regression is computed with statsmodels' own operations,
so its residual and R^2 are bit-identical to coint's. Only the ADF regressions differ:
statsmodels fits the maxlag + 1 nested regressions one by one (pinv + model set-up each
time); here the regressors are ordered so that every candidate regression uses a leading
block of columns, and one Householder QR of the largest design yields all of their
residual sums of squares. The t-statistic then differs from statsmodels' by rounding only
(~1e-13); tests/test_fast_coint.py bounds it.
"""

from typing import Tuple

import numpy as np
from statsmodels.tools.tools import pinv_extended
from statsmodels.tsa.adfvalues import mackinnonp
from statsmodels.tsa.stattools import coint

# coint() calls the pair (almost) perfectly collinear, and returns t = -inf, p = 0, when the
# first-stage R^2 >= 1 - 100 * sqrt(eps) (statsmodels.tsa.stattools.SQRTEPS).
_COLLINEAR_R2 = 1.0 - 100.0 * np.sqrt(np.finfo(np.double).eps)
# Inputs within these margins of a statsmodels decision boundary go to statsmodels itself,
# so a rounding-level difference can never change which branch is taken. R^2 within 1e-9
# of the collinearity cut: the R^2 here is coint's to the bit, the margin covers a numpy
# or statsmodels build that rounds differently. AIC values of two lag orders within 1e-6
# of each other: the two implementations' AIC values (magnitude ~1e3-1e4) differ by a few
# units in the last place (< 1e-11) on the test series, near-collinear and high-price
# pairs included. An ADF design whose condition number exceeds 1e7: rounding grows with
# it, while statsmodels' pinv treats a design as rank-deficient only beyond ~1e15.
_R2_MARGIN = 1e-9
_AIC_MARGIN = 1e-6
_MAX_CONDITION = 1e7


def _statsmodels_coint(y0, y1) -> Tuple[float, float]:
    t_stat, p_value, _ = coint(y0, y1)
    return t_stat, p_value


def _first_stage(a0: np.ndarray, a1: np.ndarray) -> Tuple[np.ndarray, float]:
    """Residual and R^2 of OLS y0 = b y1 + a, computed exactly as coint computes them.

    coint fits OLS(y0, add_trend(y1, 'c', prepend=False)) by the pinv route
    (beta = pinv_extended(X) . y0, resid = y0 - X . beta) and compares
    R^2 = 1 - resid'resid / centered_tss, with centered_tss = sum((y0 - mean y0)^2) (OLS
    carries unit weights). The same operations in the same order give the same bits.
    """
    x = np.column_stack((a1, np.ones(a1.shape[0])))
    pinv_x, _ = pinv_extended(x)
    u = a0 - np.dot(x, np.dot(pinv_x, a0))
    return u, 1.0 - np.dot(u, u) / np.sum((a0 - a0.mean()) ** 2)


def _adf_factor(u: np.ndarray, du: np.ndarray, lags: int, level_first: bool):
    """Triangular factor of [X | y] for the ADF regression with `lags` lagged differences.

    The sample is statsmodels' (adfuller: lagmat(..., trim='both') with the level written
    into column 0): regressand du_t = u_t - u_{t-1}; regressors the lagged level u_{t-1}
    (u[-nobs - 1:-1]) and du_{t-1}, ..., du_{t-lags}; the nobs = len(du) - lags dates on
    which every lag exists. Returns (R, nobs, k): with [X | y] = Q R and k = lags + 1
    regressors, R[:k, :k] is X's factor, R[:k, k] = Q'y and R[k, k]^2 is the residual
    sum of squares of the full regression.
    """
    nobs = du.shape[0] - lags
    k = lags + 1
    xy = np.empty((nobs, k + 1), order='F')
    first_lag = 1 if level_first else 0
    xy[:, 0 if level_first else lags] = u[-nobs - 1:-1]
    for j in range(1, lags + 1):
        xy[:, first_lag + j - 1] = du[lags - j: lags - j + nobs]
    xy[:, k] = du[-nobs:]
    if nobs <= k:
        return None, nobs, k
    return np.linalg.qr(xy, mode='r'), nobs, k


def _well_conditioned(r: np.ndarray) -> bool:
    """Whether the triangular factor R of a design X (cond(R) = cond(X)) has cond <= _MAX_CONDITION."""
    s = np.linalg.svd(r, compute_uv=False)
    return bool(s[-1] > 0.0 and s[0] <= _MAX_CONDITION * s[-1])


def engle_granger(y0, y1) -> Tuple[float, float]:
    """(t-statistic, p-value) of statsmodels' coint(y0, y1) with trend='c', autolag='aic'.

    Augmented Engle-Granger (1987) test of the null of no cointegration, as in statsmodels:

    1. OLS y0_t = a + b y1_t + u_t.
    2. ADF regression on the residual without deterministic terms,
       du_t = rho u_{t-1} + sum_{j=1..p} g_j du_{t-j} + e_t. maxlag is Schwert's (1989)
       ceil(12 (n/100)^(1/4)), capped at n // 2 - 1 (n = len(y0)). Every p in 0..maxlag
       is fitted on the common sample of the maxlag regression; p minimises
       AIC = -2 llf + 2 k with the concentrated Gaussian log-likelihood
       llf = -(m/2)(log 2 pi + log(SSR/m) + 1), m the number of rows and k = p + 1, and an
       exact tie goes to the smaller p (statsmodels compares (aic, lag) tuples).
    3. The p-lag regression is refitted on the longest sample it allows
       (n - 1 - p rows); the statistic is rho_hat / se(rho_hat) with
       se^2 = SSR / (n - 1 - p - k) x [(X'X)^-1]_rho. With the level as the LAST column of a
       QR factorisation X = QR this is sign(R_kk) (Q'y)_k / s (Frisch-Waugh-Lovell).
    4. p-value: MacKinnon's (1994) response surface for N = 2 I(1) variables with a
       constant, statsmodels.tsa.adfvalues.mackinnonp(t, regression='c', N=2).

    Inputs whose statsmodels result comes from special-case handling rather than from
    the regressions above go to statsmodels' coint itself, so they return (or raise)
    exactly what it does: non-finite or non-1-D input, unequal lengths, a constant leg,
    an (almost) perfectly collinear pair (t = -inf, p = 0 with a CollinearityWarning),
    a sample too short for the largest lag regression, an ill-conditioned ADF design, or
    two lag orders whose AIC values are within rounding of each other.
    """
    a0 = np.asarray(y0, dtype=float)
    a1 = np.asarray(y1, dtype=float)
    # Fewer than 4 observations leave no lag search (maxlag = n // 2 - 1 < 1).
    if (a0.ndim != 1 or a1.shape != a0.shape or a0.shape[0] < 4
            or not (np.isfinite(a0).all() and np.isfinite(a1).all())
            or np.ptp(a0) == 0.0 or np.ptp(a1) == 0.0):
        return _statsmodels_coint(y0, y1)
    n = a0.shape[0]

    # Step 1, statsmodels' arithmetic (a NaN R^2 also goes to statsmodels).
    u, r_squared = _first_stage(a0, a1)
    if not r_squared < _COLLINEAR_R2 - _R2_MARGIN:
        return _statsmodels_coint(y0, y1)

    # Step 2: lag search on the common sample. With the level first, lag order p uses the
    # leading p + 1 columns, so SSR_{p+1} = SSR_full + sum_{j > p} (Q'y)_j^2.
    maxlag = int(np.ceil(12.0 * np.power(n / 100.0, 1 / 4.0)))
    maxlag = min(n // 2 - 1, maxlag)
    du = np.diff(u)
    r, nobs, k = _adf_factor(u, du, maxlag, level_first=True)
    if r is None or not _well_conditioned(r[:k, :k]):
        return _statsmodels_coint(y0, y1)
    qy2 = r[:k, k] ** 2
    ssr = r[k, k] ** 2 + np.append(np.cumsum(qy2[::-1])[::-1][1:], 0.0)
    if not ssr[-1] > 0.0:
        return _statsmodels_coint(y0, y1)
    nobs2 = nobs / 2.0
    llf = -nobs2 * np.log(2 * np.pi) - nobs2 * np.log(ssr / nobs) - nobs2
    aic = -2 * llf + 2 * np.arange(1, k + 1, dtype=float)
    lag = int(np.argmin(aic))
    if np.partition(aic, 1)[1] - aic[lag] < _AIC_MARGIN:
        return _statsmodels_coint(y0, y1)

    # Step 3: refit with `lag` lagged differences on the longest sample, level last:
    # rho_hat = (Q'y)_k / R_kk and se(rho_hat) = s / |R_kk|.
    r, nobs, k = _adf_factor(u, du, lag, level_first=False)
    if not (_well_conditioned(r[:k, :k]) and r[k, k] != 0.0):
        return _statsmodels_coint(y0, y1)
    t_stat = np.sign(r[k - 1, k - 1]) * r[k - 1, k] / (abs(r[k, k]) / np.sqrt(nobs - k))
    return float(t_stat), mackinnonp(t_stat, regression='c', N=2)
