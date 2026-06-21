"""
TRANSFORMER ENCODER FOR PAIRS TRADING - PLOTTING
=================================================
Visualization functions for training and backtest results.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

import os
from pairs_trading.config import (
    pd, np, plt, sns, logging, datetime, DEFAULT_METRICS
)

logger = logging.getLogger(__name__)


def calculate_performance_metrics(returns):
    """Calculate standard performance metrics from returns series"""
    if len(returns) == 0:
        return DEFAULT_METRICS.copy()

    total_return = np.prod(1 + returns) - 1

    if np.std(returns) > 0:
        sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252)
    else:
        sharpe_ratio = 0.0

    cumulative = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - peak) / peak
    max_drawdown = np.min(drawdowns)

    return {
        'total_return': total_return,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown
    }


def plot_training_results(stats):
    """Visualize RL agent training progress"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create figure with 2x2 subplots
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle('RL Agent Training Progress', fontsize=16)

        # 1. Episode Rewards
        axes[0, 0].plot(stats['episode_rewards'], label='Episode Reward', alpha=0.6)
        # Add moving average
        if len(stats['episode_rewards']) > 20:
            ma = pd.Series(stats['episode_rewards']).rolling(window=20).mean()
            axes[0, 0].plot(ma, label='20-Episode MA', color='red', linewidth=2)
        axes[0, 0].set_title('Episode Rewards')
        axes[0, 0].set_xlabel('Episode')
        axes[0, 0].set_ylabel('Reward')
        axes[0, 0].legend()
        axes[0, 0].grid(True, alpha=0.3)

        # 2. Training Loss
        if stats['actor_losses']:
            axes[0, 1].plot(stats['actor_losses'], label='Actor Loss', color='orange', alpha=0.6)
            axes[0, 1].set_title('Actor Training Loss')
            axes[0, 1].set_xlabel('Training Step')
            axes[0, 1].set_ylabel('Loss')
            axes[0, 1].legend()
            axes[0, 1].grid(True, alpha=0.3)
        else:
            axes[0, 1].text(0.5, 0.5, 'No Loss Data Available',
                           ha='center', va='center', transform=axes[0, 1].transAxes)

        # 3. Exploration Rate
        if stats['exploration_rates']:
            axes[1, 0].plot(stats['exploration_rates'], label='Epsilon', color='green')
            axes[1, 0].set_title('Exploration Rate Decay')
            axes[1, 0].set_xlabel('Episode')
            axes[1, 0].set_ylabel('Epsilon')
            axes[1, 0].grid(True, alpha=0.3)

        # 4. Episode Lengths
        if stats['episode_lengths']:
            axes[1, 1].plot(stats['episode_lengths'], label='Steps', color='purple', alpha=0.6)
            axes[1, 1].set_title('Episode Lengths')
            axes[1, 1].set_xlabel('Episode')
            axes[1, 1].set_ylabel('Steps')
            axes[1, 1].grid(True, alpha=0.3)

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])

        os.makedirs('outputs', exist_ok=True)
        filename = f'outputs/fixed_training_progress_{timestamp}.png'
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        logger.info(f"Training plots saved to {filename}")
        plt.close()

    except Exception as e:
        logger.error(f"Error plotting training results: {str(e)}")


def plot_results(returns, metrics):
    """Visualize backtest performance matching the specific design"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if len(returns) == 0:
            logger.warning("No returns data to plot")
            return

        # Create figure with 1 row, 2 columns
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 6))

        # ==========================================
        # Plot 1: Portfolio Equity Curve & Drawdown
        # ==========================================

        # Calculate Cumulative Returns / Portfolio Value
        # Assuming initial capital of $1,000,000 for visualization scale if not provided
        initial_capital = 1_000_000
        cumulative_returns = np.cumprod(1 + np.array(returns))
        portfolio_value = initial_capital * cumulative_returns

        # Calculate Drawdown (%)
        peak = np.maximum.accumulate(portfolio_value)
        drawdown = (portfolio_value - peak) / peak
        drawdown_pct = np.abs(drawdown) * 100  # Convert to positive percentage for plotting

        # Plot Portfolio Value (Left Axis)
        ax1.plot(portfolio_value, label='Portfolio Value ($)', color='blue', linewidth=1.5)
        ax1.set_title('Portfolio Equity Curve Over Time', fontsize=12)
        ax1.set_xlabel('Trading Days')
        ax1.set_ylabel('Portfolio Value ($)')
        ax1.grid(True, alpha=0.3)

        # Plot Drawdown (Right Axis)
        ax1_twin = ax1.twinx()
        ax1_twin.fill_between(range(len(drawdown_pct)), 0, drawdown_pct, color='red', alpha=0.3, label='Drawdown %')
        ax1_twin.set_ylabel('Drawdown %')
        ax1_twin.set_ylim(0, max(drawdown_pct.max() * 1.2, 1.0))  # Ensure some headroom

        # Legend for Drawdown
        ax1_twin.legend(loc='upper left')

        # Text Box with Metrics
        ann_return = metrics.get('annualized_return', 0) * 100
        volatility = metrics.get('volatility', 0) * 100
        sharpe = metrics.get('sharpe_ratio', 0)
        max_dd = metrics.get('max_drawdown', 0) * 100
        max_dd_abs = abs(max_dd)

        win_rate = metrics.get('win_rate', 0) * 100
        total_trades = metrics.get('total_trades', 0)
        profit_factor = metrics.get('profit_factor', 0)
        avg_trade_ret = metrics.get('avg_trade_return', 0) * 100

        textstr = '\n'.join((
            f"Annualized Return: {ann_return:.4f}%",
            f"Daily Volatility (Annualized): {volatility:.4f}%",
            f"Sharpe Ratio (Annualized): {sharpe:.4f}",
            f"Maximum Drawdown: {max_dd_abs:.4f}%",
            f"Win Rate (% of profitable trades): {win_rate:.2f}%",
            f"Total Trades Executed: {total_trades}",
            f"Profit Factor (Gains/Losses): {profit_factor:.4f}",
            f"Average Trade Return: {avg_trade_ret:.4f}%"
        ))

        props = dict(boxstyle='square', facecolor='white', alpha=0.8, edgecolor='black')
        ax1.text(0.02, 0.02, textstr, transform=ax1.transAxes, fontsize=9,
                verticalalignment='bottom', bbox=props)

        # ==========================================
        # Plot 2: Daily Return Distribution
        # ==========================================

        daily_returns_pct = np.array(returns) * 100

        sns.histplot(daily_returns_pct, kde=True, ax=ax2, stat='density', alpha=0.5)
        ax2.set_title('Daily Return Distribution', fontsize=12)
        ax2.set_xlabel('Daily Returns (%)')
        ax2.set_ylabel('Density')
        ax2.grid(True, alpha=0.3)

        # Vertical Lines
        mean_ret = np.mean(daily_returns_pct)
        std_dev = np.std(daily_returns_pct)

        ax2.axvline(mean_ret, color='red', linestyle='--', linewidth=1.5, label=f'Mean Return: {mean_ret:.4f}%')
        ax2.axvline(mean_ret + std_dev, color='green', linestyle=':', linewidth=1.5, label=f'+1 Std Dev: {(mean_ret + std_dev):.4f}%')
        ax2.axvline(mean_ret - std_dev, color='green', linestyle=':', linewidth=1.5, label=f'-1 Std Dev: {(mean_ret - std_dev):.4f}%')

        ax2.legend(loc='upper right', fontsize=8)

        plt.tight_layout()

        os.makedirs('outputs', exist_ok=True)
        filename = f'outputs/fixed_results_{timestamp}.png'
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        logger.info(f"Backtest results plot saved to {filename}")
        plt.close()

    except Exception as e:
        logger.error(f"Error plotting results: {str(e)}")


def plot_fund_comparison(comparison_results: dict):
    """
    Generate a 6-panel figure comparing strategy performance across fund types.

    Panels:
      1. Equity curves (all 5 profiles overlaid)
      2. Gross return vs Net return (bar, showing cost drag)
      3. Cost breakdown stacked bar (commission, bid-ask, market impact, borrow, financing)
      4. Key metrics heatmap (return, sharpe, drawdown, win-rate, costs)
      5. Sharpe ratio bar chart by fund type
      6. Scatter: total cost % vs net return % (fund labels)
    """
    try:
        if not comparison_results:
            logger.warning("No comparison results to plot.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        profiles   = list(comparison_results.values())
        short_names = ['Quant HF', 'Multi-Strat', 'Fundamental L/S', 'Institutional', 'Retail']
        colors     = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']

        fig = plt.figure(figsize=(22, 18))
        fig.suptitle(
            'Pairs Trading Strategy Performance by Institutional Fund Type\n'
            '(Same trade signals — different economics: leverage, costs, risk limits)',
            fontsize=14, fontweight='bold', y=0.98
        )

        # ──────────────────────────────────────────────────────────────────────
        # Panel 1 — Equity curves
        # ──────────────────────────────────────────────────────────────────────
        ax1 = fig.add_subplot(3, 2, 1)
        for idx, (pdata, color) in enumerate(zip(profiles, colors)):
            curve = pdata.get('equity_curve', [])
            if not curve:
                continue
            values = [pt['value'] / 1e6 for pt in curve]   # convert to $M
            ax1.plot(range(len(values)), values,
                     color=color, linewidth=1.5,
                     label=f"{short_names[idx]} ({pdata['total_return_pct']:.1f}%)",
                     alpha=0.85)

        ax1.axhline(y=100, color='black', linestyle='--', linewidth=0.8, alpha=0.5,
                    label='Initial ($100M)')
        ax1.set_title('Portfolio Equity Curve by Fund Type', fontsize=11, fontweight='bold')
        ax1.set_xlabel('Days (exit dates)')
        ax1.set_ylabel('Portfolio Value ($M)')
        ax1.legend(fontsize=7, loc='upper left')
        ax1.grid(True, alpha=0.3)
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'${x:.0f}M'))

        # ──────────────────────────────────────────────────────────────────────
        # Panel 2 — Gross vs Net total return (bar chart)
        # ──────────────────────────────────────────────────────────────────────
        ax2 = fig.add_subplot(3, 2, 2)
        x = np.arange(len(profiles))
        bar_width = 0.35

        # Gross return = net return + total cost as % of capital
        net_returns   = [p['total_return_pct'] for p in profiles]
        cost_drags    = [p['total_cost_pct_of_capital'] for p in profiles]
        gross_returns = [n + c for n, c in zip(net_returns, cost_drags)]

        ax2.bar(x - bar_width/2, gross_returns, bar_width,
                label='Gross Return (before costs)', color=[c+'aa' for c in colors],
                edgecolor=colors, linewidth=1.5)
        bars_net   = ax2.bar(x + bar_width/2, net_returns, bar_width,
                             label='Net Return (after all costs)', color=colors, alpha=0.9)

        ax2.set_title('Gross vs Net Return by Fund Type\n(Cost drag visible in gap)',
                      fontsize=11, fontweight='bold')
        ax2.set_xticks(x)
        ax2.set_xticklabels(short_names, rotation=20, ha='right', fontsize=8)
        ax2.set_ylabel('Total Return (%)')
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3, axis='y')

        for bar, val in zip(bars_net, net_returns):
            ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height(),
                     f'{val:.1f}%', ha='center', va='bottom', fontsize=7, fontweight='bold')

        # ──────────────────────────────────────────────────────────────────────
        # Panel 3 — Cost breakdown stacked bar
        # ──────────────────────────────────────────────────────────────────────
        ax3 = fig.add_subplot(3, 2, 3)
        cost_labels   = ['Commission', 'Bid-Ask Spread', 'Market Impact', 'Stock Borrow', 'Financing']
        cost_keys     = ['commission_pct', 'bid_ask_pct', 'market_impact_pct', 'borrow_pct', 'financing_pct']
        cost_colors_s = ['#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f']

        bottom = np.zeros(len(profiles))
        for ck, cl, cc in zip(cost_keys, cost_labels, cost_colors_s):
            vals = [p['cost_components'].get(ck, 0.0) for p in profiles]
            ax3.bar(x, vals, 0.5, bottom=bottom, label=cl, color=cc, alpha=0.85)
            bottom += np.array(vals)

        ax3.set_title('Transaction Cost Breakdown by Fund Type\n(% of initial $100M capital)',
                      fontsize=11, fontweight='bold')
        ax3.set_xticks(x)
        ax3.set_xticklabels(short_names, rotation=20, ha='right', fontsize=8)
        ax3.set_ylabel('Cost (% of initial capital)')
        ax3.legend(fontsize=8, loc='upper right')
        ax3.grid(True, alpha=0.3, axis='y')

        # ──────────────────────────────────────────────────────────────────────
        # Panel 4 — Key metrics heatmap table
        # ──────────────────────────────────────────────────────────────────────
        ax4 = fig.add_subplot(3, 2, 4)
        ax4.axis('off')

        metric_rows = [
            ('Net Return %',         [f"{p['total_return_pct']:.2f}%"         for p in profiles]),
            ('Ann. Return %',        [f"{p['annualized_return_pct']:.2f}%"    for p in profiles]),
            ('Sharpe Ratio',         [f"{p['sharpe_ratio']:.2f}"              for p in profiles]),
            ('Max Drawdown',         [f"{p['max_drawdown_pct']:.2f}%"         for p in profiles]),
            ('Win Rate',             [f"{p['win_rate_pct']:.1f}%"             for p in profiles]),
            ('Profit Factor',        [f"{p['profit_factor']:.2f}"             for p in profiles]),
            ('Total Trades',         [f"{p['total_trades']:,}"                for p in profiles]),
            ('Total Costs %',        [f"{p['total_cost_pct_of_capital']:.2f}%"for p in profiles]),
            ('Commission bps',       [f"{p['commission_bps']:.1f}"            for p in profiles]),
            ('Bid-Ask bps',          [f"{p['bid_ask_bps']:.1f}"               for p in profiles]),
            ('Leverage',             [p['gross_leverage_label']               for p in profiles]),
            ('Stopped Early',        [str(p['trades_stopped_early'])          for p in profiles]),
        ]

        col_labels = ['Metric'] + short_names
        table_data = [[row[0]] + row[1] for row in metric_rows]

        table = ax4.table(
            cellText=table_data,
            colLabels=col_labels,
            loc='center',
            cellLoc='center'
        )
        table.auto_set_font_size(False)
        table.set_fontsize(7.5)
        table.scale(1.0, 1.4)

        # Color header row
        for j in range(len(col_labels)):
            table[0, j].set_facecolor('#2c3e50')
            table[0, j].set_text_props(color='white', fontweight='bold')

        # Alternating row shading
        for i in range(1, len(metric_rows) + 1):
            for j in range(len(col_labels)):
                if i % 2 == 0:
                    table[i, j].set_facecolor('#f8f9fa')

        ax4.set_title('Key Metrics Summary — All Fund Types', fontsize=11, fontweight='bold', pad=12)

        # ──────────────────────────────────────────────────────────────────────
        # Panel 5 — Sharpe ratio bar chart
        # ──────────────────────────────────────────────────────────────────────
        ax5 = fig.add_subplot(3, 2, 5)
        sharpes = [p['sharpe_ratio'] for p in profiles]
        bars = ax5.bar(x, sharpes, 0.5, color=colors, alpha=0.85, edgecolor='white', linewidth=0.5)
        ax5.axhline(y=1.0, color='green', linestyle='--', linewidth=1, label='Sharpe = 1 (good)')
        ax5.axhline(y=2.0, color='orange', linestyle='--', linewidth=1, label='Sharpe = 2 (excellent)')
        ax5.set_title('Risk-Adjusted Return (Sharpe Ratio) by Fund Type', fontsize=11, fontweight='bold')
        ax5.set_xticks(x)
        ax5.set_xticklabels(short_names, rotation=20, ha='right', fontsize=8)
        ax5.set_ylabel('Sharpe Ratio (annualised)')
        ax5.legend(fontsize=8)
        ax5.grid(True, alpha=0.3, axis='y')
        for bar, val in zip(bars, sharpes):
            ax5.text(bar.get_x() + bar.get_width()/2., max(bar.get_height(), 0),
                     f'{val:.2f}', ha='center', va='bottom', fontsize=8, fontweight='bold')

        # ──────────────────────────────────────────────────────────────────────
        # Panel 6 — Scatter: cost drag vs net return (insight chart)
        # ──────────────────────────────────────────────────────────────────────
        ax6 = fig.add_subplot(3, 2, 6)
        for idx, (pdata, color, sname) in enumerate(zip(profiles, colors, short_names)):
            ax6.scatter(pdata['total_cost_pct_of_capital'], pdata['total_return_pct'],
                        s=200, color=color, zorder=5, label=sname, edgecolors='white', linewidth=1.5)
            ax6.annotate(
                sname,
                (pdata['total_cost_pct_of_capital'], pdata['total_return_pct']),
                textcoords='offset points', xytext=(6, 4), fontsize=8
            )

        ax6.set_title('Cost Drag vs Net Return\n(Lower cost + higher return = upper left)',
                      fontsize=11, fontweight='bold')
        ax6.set_xlabel('Total Transaction Costs (% of initial $100M capital)')
        ax6.set_ylabel('Net Total Return (%)')
        ax6.legend(fontsize=7, loc='upper right')
        ax6.grid(True, alpha=0.3)

        plt.tight_layout(rect=[0, 0, 1, 0.96])

        os.makedirs('outputs', exist_ok=True)
        filename = f'outputs/fund_comparison_{timestamp}.png'
        plt.savefig(filename, dpi=200, bbox_inches='tight')
        logger.info(f"Fund comparison plot saved: {filename}")
        plt.close()

    except Exception as e:
        logger.error(f"Error plotting fund comparison: {str(e)}")
        import traceback
        traceback.print_exc()
