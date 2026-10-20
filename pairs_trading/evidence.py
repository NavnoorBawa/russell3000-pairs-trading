"""
PAIRS TRADING - EVIDENCE LAYER
==============================
What a run can and cannot show beyond its point estimates. Computed at the end of every
run from the run's own daily series and trades, and exported with it ('evidence' in the
results JSON; its key numbers in headline_metrics.json):

  power     power.power_report for the main backtest and the walk-forward out-of-sample
            series: the Sharpe ratio a record this long can detect, the one-sided 95% upper
            confidence bound, power against Sharpe 0.5 / 1 / 1.5 / 2, minimum track
            record lengths and Bayes factors (non-normal, AR(1) Sharpe variance).
  hurdles   the annual Sharpe needed to clear t = 3 (Harvey, Liu & Zhu 2016), t = 3.8
            (Chordia, Goyal & Saretto 2020) and a one-sided Bonferroni over the run's
            disclosed trial count, at the run's length and autocorrelation.
  gross     the pre-cost record: the daily gross series' Sharpe, HAC t and PSR, and the
            gross P&L per trade in bp of gross notional with its t-statistic — whether
            there was an edge for costs to remove at all.
  costs     the break-even cost multiple k* (total gross P&L / total costs, in dollars)
            and the net Sharpe and return with every cost scaled by k in {0, 0.5, 1, 1.5,
            2}, on the run's daily decomposition net = gross - costs. The trades are held
            fixed: in this engine costs change no decision (the ex-ante cost gate never
            binds for screened names), so this isolates the cost assumption.
  factors   Fama-French five factors + momentum + short- and long-term reversal
            attribution of daily returns in excess of the 1-month T-bill, Newey-West
            errors (significance.factor_attribution_multi; Ken French's daily files,
            cached with their CRSP vintage). Gatev, Goetzmann & Rouwenhorst (2006) and
            Chen et al. (2019) find pairs profits load on short-term reversal. Omitted,
            with the reason, when the files cannot be loaded.
  cash      the T-bill return over the main window: every return and Sharpe in this
            study is in excess of cash, because the engine's equity earns no interest.
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pairs_trading.config import logging
from pairs_trading.power import power_report
from pairs_trading.significance import (
    annualized_sharpe, factor_attribution_multi, hac_tstat_mean, probabilistic_sharpe_ratio,
    sharpe_hurdles,
)

logger = logging.getLogger(__name__)

COST_MULTIPLES = (0.0, 0.5, 1.0, 1.5, 2.0)


def _series(dates, values) -> pd.Series:
    return pd.Series(np.asarray(values, dtype=float),
                     index=pd.to_datetime([str(d)[:10] for d in dates])).sort_index()


def _sharpe_block(r: np.ndarray) -> Dict:
    h = hac_tstat_mean(r)
    return {'days': int(r.size), 'sharpe': annualized_sharpe(r), 'hac_t': h['tstat'],
            'hac_p': h['pvalue'], 'psr': probabilistic_sharpe_ratio(r)['psr'],
            'total_return_pct': float((np.prod(1.0 + r) - 1.0) * 100) if r.size else 0.0}


def gross_and_costs(results: Dict) -> Dict:
    """Pre-cost record, per-trade gross edge, break-even cost multiple, cost curve."""
    out: Dict = {}
    trades = results.get('trades') or []
    if trades:
        spread = np.array([t['spread_return'] for t in trades], dtype=float)      # per $ notional
        cost = np.array([t['transaction_costs'] / t['position_size'] for t in trades], dtype=float)
        gross_usd = float(sum(t['pnl_dollar'] + t['transaction_costs'] for t in trades))
        cost_usd = float(sum(t['transaction_costs'] for t in trades))
        sd = spread.std(ddof=1) if spread.size > 1 else float('nan')
        out['per_trade'] = {
            'trades': int(spread.size),
            'gross_bp': float(spread.mean() * 1e4),
            'gross_t': float(spread.mean() / (sd / np.sqrt(spread.size))) if spread.size > 1 and sd > 0 else None,
            'cost_bp': float(cost.mean() * 1e4),
            'gross_usd': gross_usd, 'cost_usd': cost_usd, 'net_usd': gross_usd - cost_usd,
            # gross P&L = k* x costs: every cost would have to be k* times what was modelled
            # for the trades to break even (k* < 1: they lose money even at lower costs)
            'breakeven_cost_multiple': gross_usd / cost_usd if cost_usd > 0 else None,
        }
    g = np.asarray(results.get('daily_gross_returns') or [], dtype=float)
    c = np.asarray(results.get('daily_cost_returns') or [], dtype=float)
    if g.size and g.size == c.size:
        out['gross_daily'] = _sharpe_block(g)
        out['cost_curve'] = [{'cost_multiple': k, **{key: v for key, v in _sharpe_block(g - k * c).items()
                                                      if key in ('sharpe', 'total_return_pct')}}
                             for k in COST_MULTIPLES]
    return out


def power_and_hurdles(results: Dict, n_trials: int) -> Dict:
    """Power reports (main, walk-forward OOS) and t-ratio hurdles at the main length."""
    out: Dict = {}
    main = np.asarray(results.get('daily_returns') or [], dtype=float)
    if main.size >= 30:
        out['main'] = power_report(main)
        rho = out['main'].get('rho')
        rho = float(rho) if rho is not None and np.isfinite(rho) and abs(rho) < 1 else 0.0
        out['hurdles'] = sharpe_hurdles(int(main.size), n_tests=max(1, int(n_trials)), rho=rho)
    wf = results.get('walk_forward_daily') or {}
    oos = np.asarray(wf.get('returns') or [], dtype=float)
    if oos.size >= 30:
        out['walk_forward_oos'] = power_report(oos)
    return out


def factor_block(results: Dict, factors: Optional[pd.DataFrame], fingerprint: Optional[Dict]) -> Dict:
    """Multi-factor attribution of the main and walk-forward series, and the cash return."""
    if factors is None:
        return {}
    out: Dict = {'source': fingerprint}
    series = {'main': (results.get('daily_dates'), results.get('daily_returns'))}
    wf = results.get('walk_forward_daily') or {}
    if wf.get('dates'):
        series['walk_forward_oos'] = (wf['dates'], wf['returns'])
    for name, (dates, rets) in series.items():
        if not dates:
            continue
        s = _series(dates, rets)
        covered = s.index[s.index <= factors.index[-1]]
        res = factor_attribution_multi(s.loc[covered], factors)
        res['days_after_factor_data'] = int((s.index > factors.index[-1]).sum())
        out[name] = res
    dates = results.get('daily_dates') or []
    if dates:
        idx = pd.to_datetime([str(d)[:10] for d in dates])
        rf = factors['RF'].reindex(idx).dropna()
        out['cash'] = {'tbill_return_pct': float((np.prod(1.0 + rf.to_numpy()) - 1.0) * 100),
                       'days': int(rf.size), 'source': '1-month T-bill (Ken French RF)'}
    return out


def build_evidence(results: Dict, n_trials: int, factors: Optional[pd.DataFrame] = None,
                   factor_fingerprint: Optional[Dict] = None,
                   factor_error: Optional[str] = None) -> Dict:
    """The evidence block of a run (see the module docstring)."""
    ev = {'n_trials': int(n_trials), **power_and_hurdles(results, n_trials),
          **gross_and_costs(results)}
    if factors is not None:
        ev['factors'] = factor_block(results, factors, factor_fingerprint)
    else:
        ev['factors'] = {'unavailable': factor_error or 'factor data not loaded'}
    return ev


def load_factors(cache_dir: str = 'data/external') -> tuple:
    """(factors, fingerprint, error): the French daily factors, or the reason they are missing."""
    try:
        from pairs_trading.external_data import french_daily_factors
        factors, fingerprint = french_daily_factors(cache_dir=cache_dir)
        return factors, fingerprint, None
    except Exception as e:                    # offline without a cache, or a format change
        logger.warning(f"Factor attribution skipped: {e}")
        return None, None, f"{type(e).__name__}: {e}"


def headline_evidence(ev: Dict) -> Dict:
    """The evidence numbers the published pages quote (keys for the publication checker)."""
    def g(*path):
        x = ev
        for p in path:
            if not isinstance(x, dict) or p not in x:
                return None
            x = x[p]
        return x
    curve = {row['cost_multiple']: row for row in (ev.get('cost_curve') or [])}
    fac = g('factors', 'main') or {}
    loadings = fac.get('factors') or {}
    return {
        'main_min_detectable_sharpe': g('main', 'min_detectable_sr_ann'),
        'main_upper_bound_95': g('main', 'upper_bound_ann'),
        'main_sharpe_se': g('main', 'se_ann'),
        'oos_min_detectable_sharpe': g('walk_forward_oos', 'min_detectable_sr_ann'),
        'oos_upper_bound_95': g('walk_forward_oos', 'upper_bound_ann'),
        'hurdle_hlz_sharpe': g('hurdles', 'hurdles', 'hlz', 'sr_ann'),
        'gross_bp_per_trade': g('per_trade', 'gross_bp'),
        'gross_t_per_trade': g('per_trade', 'gross_t'),
        'cost_bp_per_trade': g('per_trade', 'cost_bp'),
        'breakeven_cost_multiple': g('per_trade', 'breakeven_cost_multiple'),
        'gross_sharpe': g('gross_daily', 'sharpe'),
        'sharpe_at_zero_cost': (curve.get(0.0) or {}).get('sharpe'),
        'sharpe_at_double_cost': (curve.get(2.0) or {}).get('sharpe'),
        'factor_alpha_ann_pct': fac['alpha_ann'] * 100 if fac.get('alpha_ann') is not None else None,
        'factor_alpha_t': fac.get('alpha_tstat'),
        'factor_r2': fac.get('r2'),
        'factor_st_rev_t': (loadings.get('ST_Rev') or {}).get('tstat'),
        'tbill_return_pct': g('factors', 'cash', 'tbill_return_pct'),
    }


__all__: List[str] = ['build_evidence', 'load_factors', 'headline_evidence', 'COST_MULTIPLES']
