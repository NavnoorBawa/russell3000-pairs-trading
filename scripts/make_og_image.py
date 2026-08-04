#!/usr/bin/env python3
"""Regenerate og-image.png — the 1200x630 social-share card for the project site.

The card carries headline numbers, so it goes stale exactly when the results change.
It was previously a hand-made asset with no generator, which is how it ended up
advertising v29's "Sharpe 0.08, p=0.83" after v31 turned the result negative.

Usage:  python3.12 scripts/make_og_image.py
Writes: og-image.png at the repository root (referenced by index.html's og:image).
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# ── Palette (matches index.html light theme) ──────────────────────────────────
BG = '#ffffff'
TEXT = '#1d1d1b'
MUTED = '#97978f'
FAINT = '#d8d8d4'
POS = '#2e7d54'
NEG = '#b03a3a'
ZERO = '#c4c4bf'

TITLE = 'Pairs trading research,\nmeasured honestly.'
EYEBROW = 'RUSSELL 3000     ·     EQUITY STATISTICAL ARBITRAGE     ·     2020—2025'
SUBTITLE = ('After a full leakage audit: out-of-sample −0.28%/qtr, Sharpe −1.23\n'
            'It loses to the textbook baseline.')

# v31 walk-forward, 10 selection-clean windows. W17-W19 traded nothing.
WINDOWS = [
    (10, -0.4634), (11, -0.4484), (12, -0.0931), (13, +0.5675), (14, -0.7372),
    (15, -0.9953), (16, -0.6481), (17, 0.0), (18, 0.0), (19, 0.0),
]


def main(out_path='og-image.png'):
    fig = plt.figure(figsize=(12, 6.3), dpi=100, facecolor=BG)

    # ── Text block ────────────────────────────────────────────────────────────
    fig.text(0.06, 0.86, TITLE, fontsize=44, fontweight='bold', color=TEXT,
             va='top', ha='left', linespacing=1.15)
    # (letter-spacing is faked with padded separators in EYEBROW — matplotlib's Text
    # has no letterspacing property)
    fig.text(0.06, 0.635, EYEBROW, fontsize=11, color=MUTED, va='top', ha='left',
             family='monospace')
    fig.text(0.06, 0.555, SUBTITLE, fontsize=16, color=TEXT, va='top', ha='left',
             linespacing=1.45)

    # ── Bar chart ─────────────────────────────────────────────────────────────
    ax = fig.add_axes([0.06, 0.09, 0.88, 0.27])
    ax.set_facecolor(BG)
    for side in ('top', 'right', 'left', 'bottom'):
        ax.spines[side].set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])

    lo = min(v for _, v in WINDOWS)
    hi = max(v for _, v in WINDOWS)
    pad = (hi - lo) * 0.22
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(-0.7, len(WINDOWS) - 0.3)

    ax.axhline(0, color=FAINT, linewidth=1.2, zorder=1)

    for i, (w, val) in enumerate(WINDOWS):
        if val == 0:
            # zero-trade window: a faint stub, so "no trades" is visibly different
            # from "traded and broke even"
            h = (hi - lo) * 0.012
            ax.add_patch(Rectangle((i - 0.36, -h / 2), 0.72, h,
                                   facecolor=ZERO, edgecolor='none', zorder=2))
        else:
            ax.bar(i, val, width=0.72, color=POS if val > 0 else NEG,
                   edgecolor='none', zorder=2)

    ax.text(0, lo - pad * 0.72, 'W10', fontsize=11, color=MUTED,
            ha='center', va='top', family='monospace')
    ax.text(len(WINDOWS) - 1, lo - pad * 0.72, 'W19', fontsize=11, color=MUTED,
            ha='center', va='top', family='monospace')
    ax.text(len(WINDOWS) / 2 - 0.5, hi + pad * 0.55,
            '10 SELECTION-CLEAN WINDOWS  ·  1 POSITIVE  ·  3 TRADED NOTHING',
            fontsize=10.5, color=MUTED, ha='center', va='center', family='monospace')

    fig.savefig(out_path, facecolor=BG, dpi=100)
    plt.close(fig)
    print(f'wrote {out_path}')


if __name__ == '__main__':
    main()
