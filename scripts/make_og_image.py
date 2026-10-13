#!/usr/bin/env python3
"""Regenerate og-image.png — the 1200x630 social-share card — from the run's results.

Every number on the card is read from outputs/headline_metrics.json (written by
pairs_trading.json_export.export_headline_metrics): the per-window out-of-sample
returns and trade counts (a window with zero trades is drawn as a stub, so "traded
nothing" is visibly different from "traded and broke even"), the average window return,
the pooled OOS Sharpe, the positive / zero-trade window counts, the comparison with
the Gatev baseline (worded by its Sharpe-difference test when the run has one) and the
data years.

Usage:  python3.12 scripts/make_og_image.py [--json PATH] [--out PATH]
        python3.12 scripts/make_og_image.py --pending   # status card, no figures (no run yet)
Writes: og-image.png at the repository root by default (index.html's og:image).
Exit codes: 0 written; 1 the JSON lacks a value the card needs; 2 the JSON is missing
or unreadable.

v32: the card used to hard-code every number it drew (window returns, the zero-trade
windows, the subtitle), so it went stale the moment the results changed — the same
failure mode that left the site advertising v29 figures after v31.
"""

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / 'outputs' / 'headline_metrics.json'
DEFAULT_OUT = ROOT / 'og-image.png'

# ── Palette (matches index.html light theme) ──────────────────────────────────
BG = '#ffffff'
TEXT = '#1d1d1b'
MUTED = '#6b6b66'          # 5.3:1 on white
FAINT = '#d8d8d4'
POS = '#2e7d54'
NEG = '#b03a3a'
ZERO = '#c4c4bf'

TITLE = 'Pairs trading research,\nmeasured honestly.'


class CardDataError(ValueError):
    """The headline JSON lacks a value the card needs."""


def _signed(x, nd=2):
    """'+0.26' / '−1.23' (Unicode minus, as on the site)."""
    s = f'{x:+.{nd}f}'
    return s.replace('-', '−')


def _get(data, path):
    cur = data
    for part in path.split('.'):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _need(data, path):
    value = _get(data, path)
    if value is None:
        raise CardDataError(f'{path} is missing or null in the headline metrics')
    return value


def _years(data):
    """'2020—2025' from the data span in run_config, else from the backtest periods."""
    starts = [_get(data, 'run_config.data.data_start'), _get(data, 'oos.period_start'),
              _get(data, 'main.period_start')]
    ends = [_get(data, 'run_config.data.data_end'), _get(data, 'oos.period_end'),
            _get(data, 'main.period_end')]
    starts = [str(s)[:4] for s in starts if s]
    ends = [str(e)[:4] for e in ends if e]
    if not starts or not ends:
        return None
    return f'{min(starts)}—{max(ends)}'


def card_content(data):
    """Everything the card draws, derived from the headline metrics. Raises CardDataError."""
    if data.get('complete') is False:
        raise CardDataError('the run is marked incomplete (pipeline_errors: '
                            f"{'; '.join(data.get('pipeline_errors') or [])})")
    returns = _need(data, 'oos.window_returns_pct')
    if not isinstance(returns, list) or not returns or any(v is None for v in returns):
        raise CardDataError('oos.window_returns_pct must be a non-empty list of numbers')
    n = len(returns)
    trades = _get(data, 'oos.window_trades') or [None] * n
    ids = _get(data, 'oos.window_ids') or list(range(1, n + 1))
    if len(trades) != n or len(ids) != n:
        raise CardDataError('oos.window_trades / oos.window_ids do not match oos.window_returns_pct')
    avg = float(_need(data, 'oos.avg_window_return_pct'))
    pooled = float(_need(data, 'oos.pooled_sharpe'))
    positive = sum(1 for v in returns if v > 0)
    no_trades = sum(1 for t in trades if t == 0)
    clean = _get(data, 'oos.windows_selection_clean')

    # "%/qtr" only when the windows really are about a quarter long.
    unit = 'window'
    start, end = _get(data, 'oos.period_start'), _get(data, 'oos.period_end')
    if start and end:
        from datetime import date
        days = (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(start)[:10])).days
        if 75 <= days / n <= 105:
            unit = 'qtr'

    subtitle = f'Out-of-sample {_signed(avg)}%/{unit}, pooled Sharpe {_signed(pooled)}'
    main_sharpe, gatev_sharpe = _get(data, 'main.sharpe'), _get(data, 'benchmarks.gatev.sharpe')
    if main_sharpe is not None and gatev_sharpe is not None:
        # The Sharpe-difference test, when the run has one, decides the wording: a point
        # estimate that is not significantly different is not "beats" / "loses to".
        p = _get(data, 'benchmarks.sharpe_diff_vs_gatev.p')
        detail = f'Sharpe {_signed(main_sharpe)} vs {_signed(gatev_sharpe)}' + (f', p={p:.2f}' if p is not None else '')
        if p is not None and p >= 0.05:
            subtitle += f'\nNot distinguishable from the textbook baseline ({detail}).'
        else:
            verb = ('loses to' if main_sharpe < gatev_sharpe else
                    'beats' if main_sharpe > gatev_sharpe else 'ties with')
            subtitle += f'\nIt {verb} the textbook baseline ({detail}).'

    kind = 'SELECTION-CLEAN WINDOWS' if clean == n else 'OOS WINDOWS'
    caption = f'{n} {kind}  ·  {positive} POSITIVE'
    if no_trades:
        caption += f'  ·  {no_trades} TRADED NOTHING'
    years = _years(data)
    eyebrow = 'RUSSELL 3000     ·     EQUITY STATISTICAL ARBITRAGE' + (f'     ·     {years}' if years else '')
    return {
        'bars': [(int(i), float(v), t) for i, v, t in zip(ids, returns, trades)],
        'subtitle': subtitle,
        'caption': caption,
        'eyebrow': eyebrow,
    }


PENDING = {
    'bars': [],
    'eyebrow': 'RUSSELL 3000     ·     EQUITY STATISTICAL ARBITRAGE     ·     v32',
    'subtitle': 'Engine rebuilt after a full audit; earlier results withdrawn.\n'
                'Validated on synthetic markets with known answers. Study re-run pending.',
    'caption': 'KNOWN-ANSWER CHECKS:  PLANTED EDGE FOUND   ·   NO EDGE IN RANDOM WALKS   ·   HEDGE RATIO RECOVERED',
}


def render_card(content, out_path):
    """Draw the card described by `content` (see card_content) to out_path."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    bars = content['bars']
    fig = plt.figure(figsize=(12, 6.3), dpi=100, facecolor=BG)
    try:
        fig.text(0.06, 0.86, TITLE, fontsize=44, fontweight='bold', color=TEXT,
                 va='top', ha='left', linespacing=1.15)
        # (letter-spacing is faked with padded separators — matplotlib Text has none)
        fig.text(0.06, 0.635, content['eyebrow'], fontsize=11, color=MUTED, va='top', ha='left',
                 family='monospace')
        fig.text(0.06, 0.555, content['subtitle'], fontsize=16, color=TEXT, va='top', ha='left',
                 linespacing=1.45)

        if not bars:                       # status card: no figures to draw
            fig.add_artist(plt.Line2D([0.06, 0.94], [0.2, 0.2], color=FAINT, linewidth=1.2))
            fig.text(0.06, 0.13, content['caption'], fontsize=11, color=MUTED, va='center', ha='left',
                     family='monospace')
            fig.savefig(out_path, facecolor=BG, dpi=100)
            return
        ax = fig.add_axes([0.06, 0.09, 0.88, 0.27])
        ax.set_facecolor(BG)
        for side in ('top', 'right', 'left', 'bottom'):
            ax.spines[side].set_visible(False)
        ax.set_xticks([])
        ax.set_yticks([])

        values = [v for _, v, _ in bars]
        lo, hi = min(min(values), 0.0), max(max(values), 0.0)
        span = (hi - lo) or 1.0
        pad = span * 0.22
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_xlim(-0.7, len(bars) - 0.3)
        ax.axhline(0, color=FAINT, linewidth=1.2, zorder=1)

        for i, (_, val, n_trades) in enumerate(bars):
            if n_trades == 0:
                # zero-trade window: a faint stub, so "no trades" differs from "broke even"
                h = span * 0.012
                ax.add_patch(Rectangle((i - 0.36, -h / 2), 0.72, h,
                                       facecolor=ZERO, edgecolor='none', zorder=2))
            else:
                ax.bar(i, val, width=0.72, color=POS if val > 0 else NEG, edgecolor='none', zorder=2)

        ax.text(0, lo - pad * 0.72, f'W{bars[0][0]}', fontsize=11, color=MUTED,
                ha='center', va='top', family='monospace')
        if len(bars) > 1:
            ax.text(len(bars) - 1, lo - pad * 0.72, f'W{bars[-1][0]}', fontsize=11, color=MUTED,
                    ha='center', va='top', family='monospace')
        ax.text(len(bars) / 2 - 0.5, hi + pad * 0.55, content['caption'],
                fontsize=10.5, color=MUTED, ha='center', va='center', family='monospace')

        fig.savefig(out_path, facecolor=BG, dpi=100)
    finally:
        plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Regenerate og-image.png from the headline metrics.')
    ap.add_argument('--json', default=None, help='headline metrics JSON '
                    '(default: outputs/headline_metrics.json in the repository)')
    ap.add_argument('--out', default=None, help='output PNG (default: og-image.png at the repository root)')
    ap.add_argument('--allow-variant', action='store_true',
                    help='draw from a sensitivity run (non-default PAIRS_* switches)')
    ap.add_argument('--pending', action='store_true',
                    help='draw the status card (no figures) used until the study has been run')
    args = ap.parse_args(argv)
    json_path = pathlib.Path(args.json) if args.json else DEFAULT_JSON
    out_path = pathlib.Path(args.out) if args.out else DEFAULT_OUT
    if args.pending:
        render_card(PENDING, out_path)
        print(f'wrote {out_path} (status card, no figures)')
        return 0

    if not json_path.exists():
        print(f'ERROR: {json_path} not found. The card is drawn from the headline metrics of a '
              f'real run: run `python -m pairs_trading.main` first.', file=sys.stderr)
        return 2
    try:
        data = json.loads(json_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        print(f'ERROR: cannot read {json_path}: {e}', file=sys.stderr)
        return 2
    variant = data.get('non_default_switches') or []
    if variant and not args.allow_variant:
        print(f'ERROR: {json_path} comes from a sensitivity run ({", ".join(variant)}); the card '
              f'shows the headline run (--allow-variant overrides).', file=sys.stderr)
        return 2
    try:
        content = card_content(data)
    except CardDataError as e:
        print(f'ERROR: {e} — not drawing a card with made-up numbers.', file=sys.stderr)
        return 1
    render_card(content, out_path)
    print(f'wrote {out_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
