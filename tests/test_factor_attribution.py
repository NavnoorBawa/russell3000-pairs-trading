"""Multi-factor attribution with Newey-West errors (significance.factor_attribution_multi).

The Bartlett HAC covariance is shared with the single-factor factor_attribution; both
are checked against statsmodels OLS(cov_type='HAC', use_correction=False).
"""
import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from pairs_trading.significance import factor_attribution, factor_attribution_multi

FACTORS = ['Mkt-RF', 'SMB', 'HML', 'Mom']


def _data(rng, T=1500):
    F = pd.DataFrame(rng.normal(0.0, 0.008, (T, len(FACTORS))), columns=FACTORS,
                     index=pd.bdate_range('2021-01-04', periods=T))
    F['SMB'] += 0.3 * F['Mkt-RF']                      # correlated factors
    F['RF'] = 1.5e-4
    e = np.convolve(rng.normal(0.0, 0.004, T + 2), [1.0, 0.5, 0.25], 'valid')   # MA(2) noise
    y = 2e-4 + F['RF'] + 0.4 * F['Mkt-RF'] - 0.25 * F['SMB'] + 0.1 * F['Mom'] + e
    return y.rename('strategy'), F


def test_matches_statsmodels_hac_without_small_sample_correction():
    y, F = _data(np.random.default_rng(0))
    res = factor_attribution_multi(y, F, max_lag=6, includes_cash_return=True)
    X = sm.add_constant(F[FACTORS])
    ref = sm.OLS(y - F['RF'], X).fit(cov_type='HAC', cov_kwds={'maxlags': 6, 'use_correction': False})
    assert res['alpha_ann'] == pytest.approx(ref.params['const'] * 252, rel=1e-10)
    assert res['alpha_tstat'] == pytest.approx(ref.tvalues['const'], rel=1e-10)
    for f in FACTORS:
        assert res['factors'][f]['beta'] == pytest.approx(ref.params[f], rel=1e-10)
        assert res['factors'][f]['tstat'] == pytest.approx(ref.tvalues[f], rel=1e-10)
    assert res['r2'] == pytest.approx(ref.rsquared, rel=1e-12)
    assert res['lags'] == 6 and res['n'] == 1500 and res['rf_subtracted']


def test_single_factor_case_reproduces_factor_attribution():
    rng = np.random.default_rng(1)
    m = rng.normal(4e-4, 0.01, 800)
    r = 1e-4 + 0.2 * m + rng.normal(0.0, 0.003, 800)
    one = factor_attribution(r, m)
    multi = factor_attribution_multi(r, pd.DataFrame({'mkt': m}))
    assert multi['alpha_ann'] == pytest.approx(one['alpha_ann'], rel=1e-12)
    assert multi['alpha_tstat'] == pytest.approx(one['alpha_tstat'], rel=1e-12)
    assert multi['factors']['mkt']['beta'] == pytest.approx(one['beta'], rel=1e-12)
    assert multi['factors']['mkt']['tstat'] == pytest.approx(one['beta_tstat'], rel=1e-12)
    assert multi['r2'] == pytest.approx(one['r2'], rel=1e-12)
    assert multi['factors']['mkt']['variance_share'] == pytest.approx(1.0)
    assert not multi['rf_subtracted']
    ref = sm.OLS(r, sm.add_constant(m)).fit(cov_type='HAC', cov_kwds={'maxlags': one['lags'],
                                                                      'use_correction': False})
    assert one['beta_tstat'] == pytest.approx(ref.tvalues[1], rel=1e-10)


def test_rf_is_subtracted_only_from_returns_that_earn_it():
    """The engine's returns earn no interest on equity: they are already excess-of-cash
    returns and the RF column must not be subtracted again (default). A funded total
    return (includes_cash_return=True) has RF taken off; RF is never a regressor."""
    y, F = _data(np.random.default_rng(5))
    engine = factor_attribution_multi(y - F['RF'], F)
    no_rf = factor_attribution_multi(y - F['RF'], F.drop(columns='RF'))
    funded = factor_attribution_multi(y, F, includes_cash_return=True)
    assert not engine['rf_subtracted'] and funded['rf_subtracted']
    assert 'RF' not in engine['factors']
    for key in ('alpha_ann', 'alpha_tstat', 'r2'):
        assert engine[key] == pytest.approx(no_rf[key], rel=1e-12)
        assert funded[key] == pytest.approx(engine[key], rel=1e-9)
    # counting cash twice would move alpha down by the average bill rate
    twice = factor_attribution_multi(y - F['RF'], F, includes_cash_return=True)
    assert twice['alpha_ann'] == pytest.approx(engine['alpha_ann'] - 1.5e-4 * 252, rel=1e-9)
    with pytest.raises(ValueError):
        factor_attribution_multi(y, F.drop(columns='RF'), includes_cash_return=True)


def test_excess_of_rf_and_variance_shares():
    y, F = _data(np.random.default_rng(2))
    res = factor_attribution_multi(y, F, includes_cash_return=True)
    no_rf = factor_attribution_multi(y, F.drop(columns='RF'))
    # subtracting a constant RF moves only the intercept
    assert res['alpha_ann'] == pytest.approx(no_rf['alpha_ann'] - 1.5e-4 * 252, rel=1e-9)
    assert res['factors']['SMB']['beta'] == pytest.approx(no_rf['factors']['SMB']['beta'])
    alpha_se = res['alpha_ann'] / res['alpha_tstat']
    assert abs(res['alpha_ann'] - 2e-4 * 252) < 3 * alpha_se
    assert res['factors']['Mkt-RF']['beta'] == pytest.approx(0.4, abs=0.03)
    shares = {f: v['variance_share'] for f, v in res['factors'].items()}
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-12)
    assert 'RF' not in shares
    # covariance decomposition: beta_j Cov(f_j, fitted) / Var(fitted)
    betas = np.array([res['factors'][f]['beta'] for f in FACTORS])
    fitted = F[FACTORS].to_numpy() @ betas
    for j, f in enumerate(FACTORS):
        c = np.cov(F[f], fitted)[0, 1]
        assert shares[f] == pytest.approx(betas[j] * c / fitted.var(ddof=1), rel=1e-9)


def test_series_input_aligns_on_dates():
    y, F = _data(np.random.default_rng(3))
    full = factor_attribution_multi(y, F)
    # the strategy exports carry 'YYYY-MM-DD' strings, price caches can be tz-aware or
    # stamped at the close: all must match the factors' dates by calendar day
    as_text = y.set_axis(y.index.strftime('%Y-%m-%d'))
    as_tz = y.set_axis(y.index.tz_localize('America/New_York') + pd.Timedelta(hours=16))
    for variant in (as_text, as_tz):
        res = factor_attribution_multi(variant, F)
        assert res['n'] == full['n'] and res['alpha_tstat'] == pytest.approx(full['alpha_tstat'])
    with pytest.raises(ValueError, match='no date in common'):
        factor_attribution_multi(y.set_axis(pd.bdate_range('2031-01-01', periods=len(y))), F)
    shuffled = F.sample(frac=1.0, random_state=0)
    extra = pd.concat([shuffled, pd.DataFrame(0.001, index=pd.bdate_range('2030-01-01', periods=5),
                                              columns=F.columns)])
    assert factor_attribution_multi(y, extra)['alpha_tstat'] == pytest.approx(full['alpha_tstat'])
    holed = y.copy()
    holed.iloc[10] = np.nan
    assert factor_attribution_multi(holed, F)['n'] == 1499
    with pytest.raises(ValueError):
        factor_attribution_multi(y.to_numpy()[:-1], F)
    with pytest.raises(TypeError):
        factor_attribution_multi(y, F.to_numpy())


def test_degenerate_inputs_return_the_full_key_set():
    y, F = _data(np.random.default_rng(4), T=200)
    full = factor_attribution_multi(y, F)
    for bad in (factor_attribution_multi(y.iloc[:10], F.iloc[:10]),
                factor_attribution_multi(y, F.assign(HML=0.0)),
                factor_attribution_multi(y, F.assign(Mom=F['Mkt-RF']))):
        assert set(bad) == set(full) and set(bad['factors']) == set(FACTORS)
        assert np.isnan(bad['alpha_tstat']) and np.isnan(bad['factors']['SMB']['beta'])
