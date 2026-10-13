"""
Charts of a completed study run, written to deterministic file names under outputs/.

  * plot_results          -> outputs/backtest_results.png   main backtest: equity (in
                             dollars, on real dates), drawdown, per-trade net P&L
  * plot_ranker_training  -> outputs/ranker_training.png    per-epoch BCE loss of the
                             transformer entry ranker, against a constant predictor
  * plot_fund_comparison  -> outputs/fund_comparison.png    fund-cost replay by profile

v32: through v31 every call wrote a new timestamped PNG into outputs/, so charts from
different runs (and different code versions) piled up side by side. Each chart now has
one fixed name and is overwritten by the next run; when a chart has nothing to draw, a
previous file of that name is removed so outputs/ never mixes runs.

Plotting is cosmetic: a failure is logged with its traceback and the function returns
None instead of aborting a multi-hour run before the JSON exports are written.
"""

import os
import warnings
from typing import Dict, List, Optional

import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MaxNLocator

from pairs_trading.config import pd, np, plt, logging

logger = logging.getLogger(__name__)

OUTPUT_DIR = 'outputs'
BACKTEST_PLOT = 'backtest_results.png'
RANKER_PLOT = 'ranker_training.png'
FUND_PLOT = 'fund_comparison.png'
DPI = 150

# Chart chrome (light surface) and the categorical slots, in fixed order.
SURFACE = '#fcfcfb'
INK = '#0b0b0b'
INK_2 = '#52514e'
MUTED = '#898781'
GRID = '#e1e0d9'
BASELINE = '#c3c2b7'
SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948']
POS = '#2a78d6'          # diverging pair for sign: blue = gain, red = loss
NEG = '#e34948'

# Colour and short label follow the profile KEY, never its position in the dict, so a
# profile keeps its colour when others are added, removed or reordered (v32).
PROFILE_STYLE = {
    'quant_hf': ('Quant HF', SERIES[0]),
    'multi_strat': ('Multi-strat pod', SERIES[1]),
    'fundamental_ls': ('Fundamental L/S', SERIES[2]),
    'institutional': ('Buy-side inst.', SERIES[3]),
    'retail': ('Retail', SERIES[4]),
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _output_path(filename: str) -> str:
    directory = os.path.join(os.getcwd(), OUTPUT_DIR)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, filename)


def _target(output_path: Optional[str], default_name: str) -> str:
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        return output_path
    return _output_path(default_name)


def _remove_stale(path: str) -> None:
    """Delete a previous run's chart of this name, so it is not mistaken for this run's."""
    if os.path.exists(path):
        os.remove(path)
        logger.info(f"Removed stale chart {path} (nothing to plot this run)")


def _finite(x) -> Optional[float]:
    if x is None or isinstance(x, (bool, np.bool_)):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _pct(x, nd: int = 2, signed: bool = True) -> str:
    f = _finite(x)
    if f is None:
        return 'n/a'
    return f"{f:+.{nd}f}%" if signed else f"{f:.{nd}f}%"


def format_profit_factor(pf) -> str:
    """Profit factor for display: +inf (no losing trade) and missing values spelled out."""
    if pf is None:
        return 'n/a'
    try:
        f = float(pf)
    except (TypeError, ValueError):
        return 'n/a'
    if np.isnan(f):
        return 'n/a'
    if np.isinf(f):
        return 'inf (no losing trade)'
    return f"{f:.2f}"


def _naive_dates(values) -> Optional[pd.DatetimeIndex]:
    """Values -> tz-naive DatetimeIndex of wall-clock dates, or None if any is unparseable."""
    try:
        idx = pd.DatetimeIndex([pd.Timestamp(v) for v in values])
    except (TypeError, ValueError):
        return None
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    if idx.hasnans:
        return None
    return idx.normalize()


def _style(ax, grid_axis: str = 'y') -> None:
    """Recessive chrome: surface fill, hairline solid grid, no top/right spines."""
    ax.set_facecolor(SURFACE)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    for side in ('left', 'bottom'):
        ax.spines[side].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelcolor=INK_2, labelsize=8)
    ax.grid(True, axis=grid_axis, color=GRID, linewidth=0.6, linestyle='-')
    ax.set_axisbelow(True)
    ax.title.set_color(INK)
    ax.xaxis.label.set_color(INK_2)
    ax.yaxis.label.set_color(INK_2)


def _date_axis(ax) -> None:
    loc = mdates.AutoDateLocator(minticks=4, maxticks=9)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))


def _dollar_formatter(capital: Optional[float]) -> FuncFormatter:
    if capital and capital >= 1e6:
        return FuncFormatter(lambda v, _: f"${v / 1e6:,.2f}M")
    if capital and capital >= 1e3:
        return FuncFormatter(lambda v, _: f"${v / 1e3:,.1f}k")
    return FuncFormatter(lambda v, _: f"{v:,.3f}")


def _resolve_capital(initial_capital, metrics: Dict) -> Optional[float]:
    """Explicit capital, else final equity / (1 + total return) from the engine's metrics."""
    cap = _finite(initial_capital)
    if cap and cap > 0:
        return cap
    final, tr = _finite(metrics.get('final_portfolio_value')), _finite(metrics.get('total_return'))
    if final is not None and tr is not None and tr > -1.0:
        return final / (1.0 + tr)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Main backtest
# ──────────────────────────────────────────────────────────────────────────────

def _scaled(metrics: Dict, key: str, scale: float = 100.0) -> Optional[float]:
    f = _finite(metrics.get(key))
    return f * scale if f is not None else None


def _stats_text(metrics: Dict) -> str:
    n = int(_finite(metrics.get('total_trades')) or 0)
    sharpe = _finite(metrics.get('sharpe_ratio'))
    lines = [
        f"Total return            {_pct(_scaled(metrics, 'total_return'))}",
        f"Annualised return       {_pct(_scaled(metrics, 'annualized_return'))}",
        f"Annualised volatility   {_pct(_scaled(metrics, 'volatility'), signed=False)}",
        f"Sharpe (daily, ann.)    {f'{sharpe:+.2f}' if sharpe is not None else 'n/a'}",
        f"Max drawdown            {_pct(_scaled(metrics, 'max_drawdown'))}",
        f"Trades                  {n}",
        f"Win rate                {_pct(_scaled(metrics, 'win_rate'), 1, signed=False) if n else 'n/a'}",
        f"Profit factor           {format_profit_factor(metrics.get('profit_factor')) if n else 'n/a'}",
        f"Avg trade net P&L       {_pct(_scaled(metrics, 'avg_trade_return'), 3) if n else 'n/a'}",
        "  (% of equity at entry)",
    ]
    reasons = metrics.get('exit_reasons') or {}
    if reasons:
        lines.append('Exit reasons')
        lines.extend(f"  {k:<22}{v}" for k, v in sorted(reasons.items()))
    if metrics.get('halted_on'):
        lines.append(f"Halted on {metrics['halted_on']}")
        if metrics.get('halt_reason'):
            lines.append(f"  ({metrics['halt_reason']})")
    return '\n'.join(lines)


def plot_results(returns, metrics, initial_capital: float = None, dates=None,
                 output_path: str = None) -> Optional[str]:
    """Main-backtest chart: dollar equity and drawdown on real dates, per-trade net P&L.

    `metrics` is the engine's results dict; its 'equity_curve' (dollars), 'daily_dates'
    and 'trades' are used when present. `initial_capital` / `dates` override them, and
    plot_results(returns, metrics) keeps working with the old two-argument call.

    v32: the old chart compounded the returns from a hard-coded $1,000,000 (for a $100M
    fund) on a trading-day index, drew drawdown on a second y-axis of the same panel,
    measured drawdown from the first day's value rather than the starting capital, and
    showed a 'Daily Return Distribution' histogram that is mostly a spike at zero for a
    strategy that is flat on most days. It is replaced by three panels on one date axis
    — equity, drawdown (seeded with the starting capital), and each trade's net P&L at
    its exit date.

    Returns the PNG path, or None when there is nothing to plot (or plotting failed).
    """
    path = _target(output_path, BACKTEST_PLOT)
    metrics = metrics or {}
    r = np.asarray(returns if returns is not None else [], dtype=float)
    if r.size == 0:
        logger.warning("No returns to plot")
        _remove_stale(path)
        return None

    fig = None
    try:
        capital = _resolve_capital(initial_capital, metrics)
        curve = metrics.get('equity_curve')
        if capital and curve is not None and len(curve) == r.size:
            equity = np.asarray(curve, dtype=float)
        else:
            equity = (capital or 1.0) * np.cumprod(1.0 + r)
        start = capital or 1.0
        peak = np.maximum.accumulate(np.concatenate([[start], equity]))[1:]
        drawdown_pct = (equity / peak - 1.0) * 100.0

        raw_dates = dates if dates is not None else metrics.get('daily_dates')
        x = _naive_dates(raw_dates) if raw_dates is not None and len(raw_dates) == r.size else None
        use_dates = x is not None
        if not use_dates:
            x = np.arange(1, r.size + 1)

        fig = plt.figure(figsize=(13, 9), facecolor=SURFACE)
        gs = fig.add_gridspec(3, 2, width_ratios=[4.2, 1.35], height_ratios=[3.0, 1.4, 1.8],
                              hspace=0.12, wspace=0.05)
        ax_eq = fig.add_subplot(gs[0, 0])
        ax_dd = fig.add_subplot(gs[1, 0], sharex=ax_eq)
        ax_tr = fig.add_subplot(gs[2, 0], sharex=ax_eq if use_dates else None)
        ax_txt = fig.add_subplot(gs[:, 1])
        ax_txt.axis('off')

        # 1) equity in dollars (or growth of 1 when the capital is unknown)
        _style(ax_eq)
        ax_eq.plot(x, equity, color=SERIES[0], linewidth=1.5)
        ax_eq.axhline(start, color=BASELINE, linewidth=0.8)
        ax_eq.yaxis.set_major_formatter(_dollar_formatter(capital))
        ax_eq.set_ylabel('Portfolio equity' if capital else 'Equity (growth of 1)', fontsize=9)
        ax_eq.tick_params(labelbottom=False)
        span = (f"{x[0].date()} to {x[-1].date()}" if use_dates else f"{r.size} trading days")
        cap_txt = f"${capital:,.0f} starting capital" if capital else "starting capital unknown"
        ax_eq.set_title(f"Main backtest, {span}  ·  {cap_txt}", fontsize=11, loc='left')

        # 2) drawdown, <= 0, relative to a running peak that starts at the capital
        _style(ax_dd)
        ax_dd.fill_between(x, drawdown_pct, 0.0, color=NEG, alpha=0.22, linewidth=0)
        ax_dd.plot(x, drawdown_pct, color=NEG, linewidth=1.0)
        ax_dd.set_ylabel('Drawdown (%)', fontsize=9)
        ax_dd.set_ylim(min(float(drawdown_pct.min()) * 1.15, -0.05), 0.0)
        ax_dd.yaxis.set_major_locator(MaxNLocator(4))
        if use_dates:
            ax_dd.tick_params(labelbottom=False)       # the trade panel below carries the dates
        else:
            ax_dd.set_xlabel('Trading day', fontsize=9)

        # 3) each trade's net P&L (% of equity at entry) at its exit fill date
        _style(ax_tr)
        trades: List[Dict] = [t for t in (metrics.get('trades') or []) if _finite(t.get('net_pnl_pct')) is not None]
        if use_dates:     # on the shared date axis only trades with a real exit/entry date can be placed
            placed = [(_naive_dates([t.get('exit_date') or t.get('date')]), t) for t in trades
                      if (t.get('exit_date') or t.get('date')) is not None]
            placed = [(d[0], t) for d, t in placed if d is not None]
            trades = [t for _, t in placed]
            tx = pd.DatetimeIndex([d for d, _ in placed])
        else:
            tx = np.arange(1, len(trades) + 1)
            ax_tr.set_xlabel('Trade number', fontsize=9)
        if trades:
            pnl = np.array([t['net_pnl_pct'] * 100.0 for t in trades])
            colors = np.where(pnl >= 0, POS, NEG)
            ax_tr.vlines(tx, 0, pnl, colors=colors, linewidth=1.5)
            ax_tr.scatter(tx, pnl, c=colors, s=24, zorder=3, edgecolors=SURFACE, linewidths=1.0)
            ax_tr.axhline(0.0, color=BASELINE, linewidth=0.8)
            ax_tr.legend(handles=[Line2D([], [], marker='o', ls='', color=POS, label='winning trade'),
                                  Line2D([], [], marker='o', ls='', color=NEG, label='losing trade')],
                         loc='upper left', fontsize=7.5, frameon=False, ncol=2)
        else:
            ax_tr.text(0.5, 0.5, 'No trades', transform=ax_tr.transAxes, ha='center', va='center',
                       color=MUTED, fontsize=10)
        ax_tr.set_ylabel('Net P&L per trade\n(% of equity at entry)', fontsize=9)
        if use_dates:
            _date_axis(ax_tr)

        ax_txt.text(0.04, 0.98, _stats_text(metrics), transform=ax_txt.transAxes, va='top', ha='left',
                    family='monospace', fontsize=8.5, color=INK, linespacing=1.55)

        fig.savefig(path, dpi=DPI, bbox_inches='tight', facecolor=SURFACE)
        logger.info(f"Backtest chart saved to {path}")
        return path
    except Exception:
        logger.exception("Plotting the backtest results failed")
        return None
    finally:
        if fig is not None:
            plt.close(fig)


# ──────────────────────────────────────────────────────────────────────────────
# Ranker training
# ──────────────────────────────────────────────────────────────────────────────

def constant_predictor_bce(base_rate, pos_weight=None) -> Optional[float]:
    """Mean class-weighted BCE of the best CONSTANT prediction on the same labels.

    With loss = -[w*y*log p + (1-y)*log(1-p)] averaged over samples (torch's
    binary_cross_entropy_with_logits with pos_weight=w), a constant p is optimal at
    p* = w*b / (w*b + 1 - b) for base rate b. A model whose loss does not fall below
    this has learned nothing a constant would not. With the ranker's w = n_neg/n_pos,
    p* = 0.5 and the value is 2*(1-b)*ln 2.
    """
    b, w = _finite(base_rate), _finite(pos_weight if pos_weight is not None else 1.0)
    if b is None or w is None or not (0.0 < b < 1.0) or w <= 0:
        return None
    p = w * b / (w * b + 1.0 - b)
    return float(-(w * b * np.log(p) + (1.0 - b) * np.log(1.0 - p)))


def plot_ranker_training(training_summary: dict, output_path: str = None) -> Optional[str]:
    """Per-epoch training loss of the transformer entry ranker.

    `training_summary` is FixedTransformerMultiAgentSystem.training_summary:
    {'n_samples', 'base_rate', 'epochs', 'epoch_losses', 'pos_weight'}. When the ranker
    was not trained (PAIRS_USE_TRANSFORMER=0, too few samples, degenerate labels) there
    are no epoch losses: nothing is drawn and None is returned.

    v32: replaces plot_training_results, which drew 'RL Agent Training Progress'
    (episode rewards, epsilon, actor/critic losses) for a reinforcement-learning agent
    that does not exist in this codebase; the loop that fed it had been removed.
    """
    path = _target(output_path, RANKER_PLOT)
    summary = training_summary if isinstance(training_summary, dict) else {}
    losses = [f for f in (_finite(v) for v in (summary.get('epoch_losses') or [])) if f is not None]
    if not losses:
        logger.info(f"Ranker training chart: nothing to plot (ranker not trained; "
                    f"n_samples={summary.get('n_samples', 0)})")
        _remove_stale(path)
        return None

    fig = None
    try:
        fig, ax = plt.subplots(figsize=(8, 4.6), facecolor=SURFACE)
        _style(ax)
        epochs = np.arange(1, len(losses) + 1)
        ax.plot(epochs, losses, color=SERIES[0], linewidth=1.5, marker='o', markersize=6,
                markeredgecolor=SURFACE, markeredgewidth=1.0, label='training loss (class-weighted BCE)')
        base = constant_predictor_bce(summary.get('base_rate'), summary.get('pos_weight'))
        if base is not None:
            ax.axhline(base, color=MUTED, linewidth=1.0, linestyle='--',
                       label=f'best constant prediction ({base:.3f})')
        ax.set_xticks(epochs)
        ax.set_xlabel('Epoch', fontsize=9)
        ax.set_ylabel('Mean loss on the training samples', fontsize=9)
        ax.legend(loc='upper right', fontsize=8, frameon=False)
        n = summary.get('n_samples')
        b, w = _finite(summary.get('base_rate')), _finite(summary.get('pos_weight'))
        parts = [f"{int(n):,} samples" if n is not None else None,
                 f"base rate {b:.1%}" if b is not None else None,
                 f"pos_weight {w:.2f}" if w is not None else None]
        ax.set_title('Transformer entry ranker — training loss per epoch', fontsize=11, loc='left')
        fig.text(0.01, -0.02, ' · '.join(p for p in parts if p) +
                 '  ·  in-sample loss; the ranker only orders entries (its out-of-sample AUC '
                 'is in the results export)', fontsize=7.5, color=INK_2, ha='left', va='top')
        fig.savefig(path, dpi=DPI, bbox_inches='tight', facecolor=SURFACE)
        logger.info(f"Ranker training chart saved to {path}")
        return path
    except Exception:
        logger.exception("Plotting the ranker training loss failed")
        return None
    finally:
        if fig is not None:
            plt.close(fig)


def plot_training_results(stats) -> Optional[str]:
    """Deprecated alias kept for import compatibility; use plot_ranker_training.

    The reinforcement-learning training loop this used to plot no longer exists. A
    ranker training summary is forwarded to plot_ranker_training; anything else is a
    no-op.
    """
    warnings.warn("plot_training_results is deprecated: the RL agent it plotted does not exist. "
                  "Use plot_ranker_training(training_summary).", DeprecationWarning, stacklevel=2)
    if isinstance(stats, dict) and stats.get('epoch_losses'):
        return plot_ranker_training(stats)
    logger.info("plot_training_results: no ranker training summary given — nothing plotted")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Fund-type comparison
# ──────────────────────────────────────────────────────────────────────────────

def _profile_styles(keys) -> Dict[str, tuple]:
    """(short label, colour) per profile key; unknown keys take the unused slots in order."""
    spare = [c for c in SERIES if c not in {c for _, c in PROFILE_STYLE.values()}]
    out = {}
    for key in keys:
        if key in PROFILE_STYLE:
            out[key] = PROFILE_STYLE[key]
        else:
            out[key] = (str(key), spare.pop(0) if spare else MUTED)
    return out


def _profile_capital(pdata: Dict, default: Optional[float]) -> Optional[float]:
    if default:
        return float(default)
    final, tr = _finite(pdata.get('final_equity')), _finite(pdata.get('total_return_pct'))
    if final is not None and tr is not None and tr > -100.0:
        return final / (1.0 + tr / 100.0)
    return None


def plot_fund_comparison(comparison_results: dict, output_path: str = None,
                         initial_capital: float = None) -> Optional[str]:
    """Fund-cost replay by profile: return paths, gross vs net, Sharpe, leverage, table.

    v32: colours and labels are keyed by profile key (they were assigned by list
    position, so a reordered or missing profile silently took another's colour and
    name); equity paths are drawn against their real dates as % return on the starting
    capital (the ordinal 'exit dates' axis and '$100M' ticks on every gridline were
    unreadable); the 'Sharpe = 1 (good) / 2 (excellent)' reference lines are gone —
    decorations tuned for a winning strategy, drawn over all-negative data. The realised
    peak gross leverage is plotted against return, and the cost components moved into
    the table.
    """
    path = _target(output_path, FUND_PLOT)
    if not comparison_results:
        logger.warning("No fund comparison results to plot.")
        _remove_stale(path)
        return None

    fig = None
    try:
        keys = list(comparison_results)
        profiles = [comparison_results[k] for k in keys]
        style = _profile_styles(keys)
        short = [style[k][0] for k in keys]
        x = np.arange(len(keys))

        fig = plt.figure(figsize=(15, 13), facecolor=SURFACE)
        gs = fig.add_gridspec(3, 2, height_ratios=[1.25, 1.0, 1.15], hspace=0.5, wspace=0.22, top=0.9)
        fig.suptitle("Fund-cost replay of the main backtest's trades",
                     fontsize=14, color=INK, x=0.06, ha='left', y=0.965)
        fig.text(0.06, 0.94, 'Same signals, dates and daily paths; position sizing, costs and '
                 'kill-switch per profile. Leverage labels are descriptive: the realised peak '
                 'gross leverage is shown.', fontsize=9, color=INK_2, ha='left')

        # 1) return paths on real dates
        ax1 = fig.add_subplot(gs[0, :])
        _style(ax1)
        stop_handle = False
        for key, p in zip(keys, profiles):
            curve = p.get('equity_curve') or []
            cap = _profile_capital(p, initial_capital)
            dts = _naive_dates([pt.get('date') for pt in curve]) if curve else None
            if not curve or cap is None or dts is None:
                continue
            ret = (np.array([float(pt['value']) for pt in curve]) / cap - 1.0) * 100.0
            label, color = style[key]
            ax1.plot(dts, ret, color=color, linewidth=1.5,
                     label=f"{label}  {_pct(p.get('total_return_pct'))}")
            stop = p.get('stopped_on')
            if stop:
                sd = _naive_dates([stop])
                hit = np.where(dts == sd[0])[0] if sd is not None else []
                if len(hit):
                    ax1.plot(dts[hit[0]], ret[hit[0]], marker='X', markersize=9, color=color,
                             markeredgecolor=SURFACE, zorder=4)
                    stop_handle = True
        ax1.axhline(0.0, color=BASELINE, linewidth=0.8)
        ax1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+.1f}%"))
        ax1.set_ylabel('Return on starting capital', fontsize=9)
        _date_axis(ax1)
        handles, labels = ax1.get_legend_handles_labels()
        if stop_handle:
            handles.append(Line2D([], [], marker='X', ls='', color=INK_2, markersize=8))
            labels.append('drawdown kill-switch hit')
        if handles:      # below the axis, so it never covers a path
            ax1.legend(handles, labels, loc='upper left', bbox_to_anchor=(0.0, -0.1), fontsize=8,
                       frameon=False, ncol=min(len(handles), 6))
        ax1.set_title('Daily marked-to-market return by fund profile', fontsize=11, loc='left')

        # 2) gross vs net total return (neutral tones: colour here is the measure, not the profile)
        ax2 = fig.add_subplot(gs[1, 0])
        _style(ax2)
        net = np.array([_finite(p.get('total_return_pct')) or 0.0 for p in profiles])
        cost = np.array([_finite(p.get('total_cost_pct_of_capital')) or 0.0 for p in profiles])
        gross = net + cost
        w = 0.36
        ax2.bar(x - w / 2 - 0.01, gross, w, color=BASELINE, label='before costs')
        bars = ax2.bar(x + w / 2 + 0.01, net, w, color=INK_2, label='after all costs')
        for b, v in zip(bars, net):
            ax2.annotate(f"{v:+.2f}%", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3 if v >= 0 else -3),
                         textcoords='offset points', ha='center', va='bottom' if v >= 0 else 'top',
                         fontsize=7.5, color=INK)
        ax2.axhline(0.0, color=BASELINE, linewidth=0.8)
        ax2.set_xticks(x)
        ax2.set_xticklabels(short, rotation=15, ha='right')
        ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+.1f}%"))
        ax2.set_title('Total return before and after costs', fontsize=11, loc='left')
        ax2.legend(fontsize=8, frameon=False)

        # 3) Sharpe by profile — zero is the only reference line that means anything here
        ax3 = fig.add_subplot(gs[1, 1])
        _style(ax3)
        sharpes = np.array([_finite(p.get('sharpe_ratio')) or 0.0 for p in profiles])
        bars = ax3.bar(x, sharpes, 0.55, color=INK_2)
        for b, v in zip(bars, sharpes):
            ax3.annotate(f"{v:+.2f}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3 if v >= 0 else -3),
                         textcoords='offset points', ha='center', va='bottom' if v >= 0 else 'top',
                         fontsize=7.5, color=INK)
        ax3.axhline(0.0, color=BASELINE, linewidth=0.8)
        ax3.set_xticks(x)
        ax3.set_xticklabels(short, rotation=15, ha='right')
        ax3.set_title('Sharpe ratio (daily, annualised)', fontsize=11, loc='left')
        lo, hi = min(0.0, float(sharpes.min())), max(0.0, float(sharpes.max()))
        pad = max(0.15 * (hi - lo), 0.1)
        ax3.set_ylim(lo - pad, hi + pad)

        # 4) realised peak gross leverage vs net return, direct-labelled
        ax4 = fig.add_subplot(gs[2, 0])
        _style(ax4, grid_axis='both')
        for key, p in zip(keys, profiles):
            lev, ret = _finite(p.get('max_gross_leverage')), _finite(p.get('total_return_pct'))
            if lev is None or ret is None:
                continue
            label, color = style[key]
            ax4.scatter(lev, ret, s=70, color=color, edgecolors=SURFACE, linewidths=1.5, zorder=3)
            ax4.annotate(label, (lev, ret), xytext=(7, 4), textcoords='offset points', fontsize=8, color=INK)
        ax4.axhline(0.0, color=BASELINE, linewidth=0.8)
        ax4.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.2f}x"))
        ax4.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+.1f}%"))
        ax4.set_xlabel('Peak gross exposure / equity (realised)', fontsize=9)
        ax4.set_ylabel('Net total return', fontsize=9)
        ax4.set_title('Leverage actually run vs net return', fontsize=11, loc='left')

        # 5) table view: every number behind the charts, plus the cost components
        ax5 = fig.add_subplot(gs[2, 1])
        ax5.axis('off')

        def comp(p, k):
            return _pct((p.get('cost_components') or {}).get(k), 3, signed=False)

        rows = [
            ('Net return', [_pct(p.get('total_return_pct')) for p in profiles]),
            ('Ann. return', [_pct(p.get('annualized_return_pct')) for p in profiles]),
            ('Sharpe', [f"{_finite(p.get('sharpe_ratio')) or 0.0:+.2f}" for p in profiles]),
            ('Max drawdown', [_pct(p.get('max_drawdown_pct')) for p in profiles]),
            ('Win rate', [_pct(p.get('win_rate_pct'), 1, signed=False) for p in profiles]),
            ('Profit factor', [format_profit_factor(p.get('profit_factor')).replace(' (no losing trade)', '')
                               for p in profiles]),
            ('Trades', [str(p.get('total_trades', 'n/a')) for p in profiles]),
            ('Costs (% of capital)', [_pct(p.get('total_cost_pct_of_capital'), 3, signed=False) for p in profiles]),
            ('  commission', [comp(p, 'commission_pct') for p in profiles]),
            ('  bid-ask', [comp(p, 'bid_ask_pct') for p in profiles]),
            ('  market impact', [comp(p, 'market_impact_pct') for p in profiles]),
            ('  borrow', [comp(p, 'borrow_pct') for p in profiles]),
            ('  financing', [comp(p, 'financing_pct') for p in profiles]),
            ('Leverage (label)', [str(p.get('gross_leverage_label', 'n/a')).split(' (')[0] for p in profiles]),
            ('Peak gross (realised)', [f"{_finite(p.get('max_gross_leverage')):.2f}x"
                                       if _finite(p.get('max_gross_leverage')) is not None else 'n/a'
                                       for p in profiles]),
            ('Kill-switch', [str(p.get('stopped_on') or '—') for p in profiles]),
        ]
        header = [''] + [s.replace(' ', '\n', 1) if len(s) > 10 else s for s in short]
        table = ax5.table(cellText=[[name] + vals for name, vals in rows], colLabels=header,
                          cellLoc='center', bbox=[0.0, 0.0, 1.0, 1.0],
                          colWidths=[0.25] + [0.75 / len(keys)] * len(keys))
        table.auto_set_font_size(False)
        table.set_fontsize(7)
        for (i, j), cell in table.get_celld().items():
            cell.set_edgecolor(GRID)
            cell.set_linewidth(0.5)
            cell.get_text().set_color(INK if i else INK_2)
            if j == 0:
                cell.get_text().set_ha('left')
                cell.PAD = 0.03
            if i == 0:                     # two-line headers: bbox scaling keeps relative heights
                cell.set_height(cell.get_height() * 2.0)
                cell.set_facecolor(SURFACE)
                cell.get_text().set_fontweight('bold')
            else:
                cell.set_facecolor('#f4f3f0' if i % 2 == 0 else SURFACE)
        ax5.set_title('All profiles', fontsize=11, loc='left', color=INK)

        fig.savefig(path, dpi=DPI, bbox_inches='tight', facecolor=SURFACE)
        logger.info(f"Fund comparison chart saved to {path}")
        return path
    except Exception:
        logger.exception("Plotting the fund comparison failed")
        return None
    finally:
        if fig is not None:
            plt.close(fig)
