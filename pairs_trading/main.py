"""
Command-line entry point:  python -m pairs_trading.main

Runs the whole study via CompleteFixedRussell3000TradingSystem.run_complete_system —
pair selection, the main backtest, the continuous walk-forward out-of-sample
simulation, significance tests, baseline benchmarks and the fund-cost replay; that
writes the JSON exports and charts under outputs/ — then prints a summary of the
results with the headline numbers labelled for what they are.

    python -m pairs_trading.main [--profile v33|v32] [--calendar dev|holdout2026] [--output-dir DIR]

The profile (what is traded) and calendar (which period) are defined in
pairs_trading/study_config.py. PAIRS_SEED (default 42) seeds Python, NumPy and, when
installed, torch. The other PAIRS_* switches are documented in README "Reproducing";
every export records them in its run_config block. A failed run re-raises, so the
process exits non-zero.
"""

import argparse
import os
import random
import sys
import time
import logging
from typing import Dict, List, Optional

import numpy as np

from pairs_trading.config import configure_runtime
from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem
from pairs_trading import json_export, plotting
from pairs_trading.json_export import (random_control_summary, sharpe_diff_vs_gatev, vs_strategy_entry,
                                       window_test_pvalues)
from pairs_trading.plotting import format_profit_factor
from pairs_trading.study_config import CALENDARS, PROFILES

logger = logging.getLogger(__name__)

DEFAULT_SEED = 42
INITIAL_CAPITAL = 100_000_000
RULE = '=' * 90
THIN = '-' * 90


# ──────────────────────────────────────────────────────────────────────────────
# Seeding
# ──────────────────────────────────────────────────────────────────────────────

def resolve_seed() -> int:
    """PAIRS_SEED as an int (default 42); a malformed value is an error, not a fallback."""
    raw = os.environ.get('PAIRS_SEED', str(DEFAULT_SEED))
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"PAIRS_SEED must be an integer, got {raw!r}") from None


def seed_everything(seed: int) -> None:
    """Seed every RNG the pipeline touches and ask torch for deterministic kernels.

    Python's str hash seed cannot be changed inside a running interpreter; outputs whose
    order would depend on it (sets of pairs/symbols) are sorted before they are written,
    and PYTHONHASHSEED is recorded in each export's run_config. torch threading is left
    alone on purpose: set_num_threads(1) would make the ranker slow for no gain on CPU.
    torch is optional (only the v32 transformer ranker uses it).
    """
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
    except ImportError:
        torch = None
    if torch is not None:
        torch.manual_seed(seed)                           # seeds CPU and every CUDA device
        os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')   # deterministic cuBLAS
        torch.use_deterministic_algorithms(True, warn_only=True)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    # Record the seed actually used, so run_config shows it even when it was defaulted.
    os.environ['PAIRS_SEED'] = str(seed)
    if os.environ.get('PYTHONHASHSEED') is None:
        logger.info("PYTHONHASHSEED is unset (per-process str hashing); exported orderings "
                    "are sorted, set PYTHONHASHSEED=0 for bit-identical set iteration")


# ──────────────────────────────────────────────────────────────────────────────
# Summary formatting (pure: results dict -> text)
# ──────────────────────────────────────────────────────────────────────────────

def _num(x) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _fmt(x, spec: str = '+.2f', suffix: str = '', scale: float = 1.0) -> str:
    f = _num(x)
    return 'n/a' if f is None else f"{f * scale:{spec}}{suffix}"


def _reasons(d) -> str:
    return ', '.join(f"{k} {v}" for k, v in sorted((d or {}).items())) or 'none'


def _main_section(r: Dict) -> List[str]:
    dates = r.get('daily_dates') or []
    n = int(_num(r.get('total_trades')) or 0)
    period = f"{dates[0]} -> {dates[-1]}" if dates else 'no trading days'
    halted = r.get('halted_on')
    return [
        RULE,
        f"MAIN BACKTEST  {period}   (one calendar"
        + ("; the walk-forward below re-fits per window)" if r.get('walk_forward') else ")"),
        RULE,
        f"  Total return           {_fmt(r.get('total_return'), '+.2f', '%', 100)}"
        f"      Annualised {_fmt(r.get('annualized_return'), '+.2f', '%', 100)}",
        f"  Sharpe (daily, ann.)   {_fmt(r.get('sharpe_ratio'))}"
        f"       Annualised volatility {_fmt(r.get('volatility'), '.2f', '%', 100)}",
        f"  Max drawdown           {_fmt(r.get('max_drawdown'), '+.2f', '%', 100)}",
        f"  Trades                 {n}"
        + (f"          Win rate {_fmt(r.get('win_rate'), '.1f', '%', 100)}"
           f"   Profit factor {format_profit_factor(r.get('profit_factor'))}" if n else ''),
        f"  Exit reasons           {_reasons(r.get('exit_reasons'))}",
        f"  Risk halt              {f'{halted} — ' + (r.get('halt_reason') or 'no reason recorded') if halted else 'none'}",
    ]


def _walk_forward_section(wf: Dict) -> List[str]:
    if not wf:
        return [RULE, "WALK-FORWARD  not run / no eligible windows", RULE]
    windows = [w for w in (wf.get('windows') or []) if isinstance(w, dict)]
    n = len(windows) or int(_num(wf.get('total_windows')) or 0)
    no_trades = sum(1 for w in windows if not w.get('total_trades'))
    return [
        RULE,
        f"WALK-FORWARD  one continuous out-of-sample simulation, {wf.get('oos_start')} -> {wf.get('oos_end')}",
        RULE,
        f"  Windows                {n} evaluated, {wf.get('skipped_windows', 'n/a')} skipped (no pair universe "
        f"selected yet); {no_trades} of {n} made no trade",
        f"  Selection-clean        {wf.get('selection_clean_windows', 'n/a')}/{n}",
        f"  Profitable windows     {wf.get('profitable_windows', 'n/a')}/{n}",
        f"  Window return          avg {_fmt(wf.get('avg_window_return_pct'), '+.3f', '%')}"
        f"   median {_fmt(wf.get('median_window_return_pct'), '+.3f', '%')}",
        f"  POOLED OOS SHARPE      {_fmt(wf.get('pooled_sharpe'))}"
        f"   (daily returns of the continuous simulation: the OOS headline)",
        f"  Mean of per-window Sharpes {_fmt(wf.get('avg_sharpe'))}"
        f"   (average of {n} window Sharpes; not a portfolio Sharpe)",
        f"  Continuous OOS return  {_fmt(wf.get('stitched_total_return_pct'), '+.2f', '%')}"
        f"   max DD {_fmt(wf.get('max_drawdown_pct'), '+.2f', '%')}"
        f"   trades {wf.get('total_trades', 'n/a')}   win rate {_fmt(wf.get('win_rate_pct'), '.1f', '%')}",
        f"  Exit reasons           {_reasons(wf.get('exit_reasons'))}",
    ]


def _battery_line(label: str, b: Dict) -> str:
    if not b:
        return f"  {label:<23}not available"
    hac, psr = b.get('hac') or {}, b.get('psr_gt0') or {}
    ci, dsr = b.get('bootstrap_sharpe_ci') or {}, b.get('deflated_sharpe') or {}
    return (f"  {label:<23}Sharpe {_fmt(b.get('ann_sharpe'))} | HAC t {_fmt(hac.get('tstat'))}"
            f" p={_fmt(hac.get('pvalue'), '.3f')} | PSR {_fmt(psr.get('psr'), '.1f', '%', 100)}"
            f" | DSR {_fmt(dsr.get('dsr'), '.1f', '%', 100)}"
            f" | bootstrap 95% CI [{_fmt(ci.get('lo'))}, {_fmt(ci.get('hi'))}]")


def _significance_section(sig: Dict) -> List[str]:
    lines = [RULE, "SIGNIFICANCE  is the edge distinguishable from zero?", RULE]
    if not sig:
        return lines + ["  not available (significance analysis did not run)"]
    w = sig.get('oos_windows') or {}
    p = window_test_pvalues(w)
    if w:
        lines += [
            f"  OOS per-window t-test  n={w.get('n')}  mean {_fmt(w.get('mean'), '+.3f', '%', 100)}/window"
            f"  t={_fmt(w.get('tstat'))}  p={_fmt(p['p_two_sided'], '.3f')} (two-sided)",
            f"  {'':<23}one-sided p: H1 mean>0 {_fmt(p['p_greater'], '.3f')}"
            f" | H1 mean<0 {_fmt(p['p_less'], '.3f')}",
            f"  {'':<23}95% CI (t) [{_fmt(w.get('ci_lo'), '+.3f', '%', 100)}, {_fmt(w.get('ci_hi'), '+.3f', '%', 100)}]"
            f"   bootstrap [{_fmt(w.get('boot_ci_lo'), '+.3f', '%', 100)}, {_fmt(w.get('boot_ci_hi'), '+.3f', '%', 100)}]",
        ]
    lines.append(_battery_line('OOS daily', sig.get('oos_daily') or {}))
    lines.append(_battery_line('Main backtest daily', sig.get('main_backtest') or {}))
    if w:
        pg, pl = _num(p['p_greater']), _num(p['p_less'])
        if pg is not None and pg < 0.05:
            verdict = f"positive OOS edge, significant at 5% (one-sided p={pg:.3f})"
        else:
            verdict = f"no statistically significant positive OOS edge at 5% (one-sided p={_fmt(pg, '.3f')})"
            if pl is not None and pl < 0.05:
                verdict += f"; the OOS mean is significantly NEGATIVE (one-sided p={pl:.3f})"
        lines.append(f"  Verdict                {verdict}")
    return lines


def _benchmark_section(r: Dict) -> List[str]:
    bm = r.get('benchmarks') or {}
    lines = [RULE, "BENCHMARKS  same universe, same period as the main backtest", RULE]
    if not bm:
        return lines + ["  not available (benchmark analysis did not run)"]
    d, rc_raw = bm.get('distance_method') or {}, bm.get('random_control') or {}
    lines += [
        f"  {'This strategy':<24}return {_fmt(r.get('total_return'), '+.2f', '%', 100)}"
        f"   Sharpe {_fmt(r.get('sharpe_ratio'))}",
        f"  {'Gatev (2006) distance':<24}return {_fmt(d.get('total_return_pct'), '+.2f', '%')}"
        f"   Sharpe {_fmt(d.get('sharpe_ratio'))}",
    ]
    aligned = vs_strategy_entry(bm)
    diff = sharpe_diff_vs_gatev(bm)
    lines.append(f"  {'Sharpe diff vs Gatev':<24}" + (
        f"{_fmt(diff['diff'])} (p={_fmt(diff['p'], '.3f')}, 95% CI [{_fmt(diff['ci_lo'])}, {_fmt(diff['ci_hi'])}],"
        f" {diff['n_common_days'] or 'n/a'} common days)"
        if diff['diff'] is not None or diff['p'] is not None else 'not reported'))
    rc = random_control_summary(rc_raw, r.get('sharpe_ratio'), aligned=aligned)
    if rc['median_sharpe'] is not None:
        pct = rc['strategy_percentile']
        lines.append(f"  {'Random-pair control':<24}median Sharpe {_fmt(rc['median_sharpe'])}"
                     f" [5%-95%: {_fmt(rc['p5_sharpe'])}, {_fmt(rc['p95_sharpe'])}] over {rc['n_draws']} draws"
                     + (f"; strategy Sharpe at percentile {pct:.0f} of the draws" if pct is not None else ''))
    elif rc_raw:
        lines.append(f"  {'Random-pair control':<24}average of {rc_raw.get('n_draws', 'n/a')} draws: return "
                     f"{_fmt(rc_raw.get('total_return_pct'), '+.2f', '%')}   Sharpe {_fmt(rc_raw.get('sharpe_ratio'))}"
                     f" (no per-draw distribution reported)")
    return lines


def _fdr_line(fdr: Dict) -> List[str]:
    if not fdr:
        return []

    def n(k):
        v = _num(fdr.get(k))
        return f"{int(v):,}" if v is not None else 'n/a'
    return [RULE, f"MULTIPLE TESTING  {n('pairs_tested')} pairs tested | {n('significant_raw_p05')} at raw p<0.05"
                  f" | {n('survive_bh_fdr_q05')} survive BH-FDR q<0.05 | {n('survive_bh_fdr_q10')} at q<0.10"
                  f" | {n('final_selected_pairs')} selected"]


def _fund_section(fc: Dict) -> List[str]:
    if not fc:
        return []
    lines = [RULE, "COST-SCHEDULE REPLAY  same trades, archetypal sizing / costs / kill-switch", RULE,
             f"  {'Profile':<30}{'Return':>9}{'Sharpe':>8}{'MaxDD':>9}{'WinRate':>9}{'Costs':>8}"
             f"{'Peak gross':>11}  Kill-switch", "  " + THIN[:90]]
    for p in fc.values():
        lines.append(
            f"  {str(p.get('profile_name', '?')):<30}{_fmt(p.get('total_return_pct'), '+.2f', '%'):>9}"
            f"{_fmt(p.get('sharpe_ratio')):>8}{_fmt(p.get('max_drawdown_pct'), '+.2f', '%'):>9}"
            f"{_fmt(p.get('win_rate_pct'), '.1f', '%'):>9}{_fmt(p.get('total_cost_pct_of_capital'), '.2f', '%'):>8}"
            f"{_fmt(p.get('max_gross_leverage'), '.2f', 'x'):>11}  "
            f"{p.get('stopped_on') or '-'}")
    return lines


def _display_path(path: str) -> str:
    """Paths under the working directory are shown relative to it (outputs/...)."""
    try:
        rel = os.path.relpath(path)
    except ValueError:
        return str(path)
    return rel if not rel.startswith('..') else str(path)


def format_summary(results: Dict, output_files: Optional[List[str]] = None) -> str:
    """The end-of-run summary as text. Every field is optional: a missing section is
    reported as unavailable instead of raising, so a partial run still prints."""
    r = results or {}
    lines: List[str] = ['']
    lines += _main_section(r)
    lines += _walk_forward_section(r.get('walk_forward') or {})
    lines += _significance_section(r.get('significance') or {})
    lines += _benchmark_section(r)
    lines += _fdr_line(r.get('fdr_diagnostic') or {})
    lines += _fund_section(r.get('fund_comparison') or {})
    lines += [RULE, "OUTPUTS"]
    lines += [f"  {_display_path(p)}" for p in (output_files or [])] or ["  (none found)"]
    lines.append(RULE)
    return '\n'.join(lines)


def known_output_files(since: Optional[float] = None, directory: str = None) -> List[str]:
    """The pipeline's deterministic output files that exist (modified at/after `since`)."""
    results_name = json_export.DEFAULT_RESULTS_FILENAME
    names = [results_name, results_name[:-5] + '_compact.json', json_export.DEFAULT_FUND_FILENAME,
             os.path.basename(json_export.DEFAULT_HEADLINE_PATH), plotting.BACKTEST_PLOT,
             plotting.RANKER_PLOT, plotting.FUND_PLOT]
    directory = directory or json_export.output_root()
    out = []
    for name in names:
        path = os.path.join(directory, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if since is None or mtime >= since - 1.0:
            out.append(path)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main():
    # v31 (audit): the CLI owns the process, so it — not module import — installs the
    # log format and warning filters. See pairs_trading/config.configure_runtime.
    configure_runtime()
    started = time.time()
    try:
        seed = resolve_seed()
        seed_everything(seed)
        logger.info(f"Random seed: {seed}")
        logger.info("Starting the Russell 3000 pairs-trading study")

        system = CompleteFixedRussell3000TradingSystem(initial_capital=INITIAL_CAPITAL)
        results = system.run_complete_system()
        files = results.get('output_files')
        if isinstance(files, dict):
            files = [p for p in files.values() if p]
        print(format_summary(results, files or known_output_files(since=started)))
        if results.get('pipeline_errors'):
            logger.error("Run INCOMPLETE — exports were written but these stages failed: "
                         + "; ".join(results['pipeline_errors']))
        return results

    except Exception as e:
        logger.error(f"System execution failed: {str(e)}")
        import traceback
        traceback.print_exc()
        # v31 (audit): signal failure to the caller. Previously this swallowed every
        # exception and returned normally, so a run that died partway through still
        # exited 0 — `python -m pairs_trading.main && publish` would happily publish
        # nothing, and CI/cron could not distinguish a completed run from a crashed one.
        raise


def cli(argv: Optional[List[str]] = None) -> int:
    """Console entry point: exit status 0 only for a complete run.

    The flags set the corresponding PAIRS_* variables, so the run's provenance block
    records them exactly like environment switches.
    """
    ap = argparse.ArgumentParser(prog='python -m pairs_trading.main',
                                 description='Run the pairs-trading study.')
    ap.add_argument('--profile', choices=sorted(PROFILES), help='study design (default v33)')
    ap.add_argument('--calendar', choices=sorted(CALENDARS), help='study period (default dev)')
    ap.add_argument('--output-dir', help='where exports and charts go (default outputs/)')
    args = ap.parse_args(argv)
    for flag, var in (('profile', 'PAIRS_PROFILE'), ('calendar', 'PAIRS_CALENDAR'),
                      ('output_dir', 'PAIRS_OUTPUT_DIR')):
        if getattr(args, flag):
            os.environ[var] = getattr(args, flag)
    results = main()
    return 1 if results.get('pipeline_errors') else 0


if __name__ == "__main__":
    sys.exit(cli())
