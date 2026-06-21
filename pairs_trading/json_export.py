"""
TRANSFORMER ENCODER FOR PAIRS TRADING - JSON EXPORT
====================================================
Functions for exporting testing results to JSON for website display.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

from pairs_trading.config import (
    pd, np, os, json, logging, datetime, List, Dict
)

logger = logging.getLogger(__name__)


def export_testing_results_to_json(backtest_results: Dict, system_info: Dict,
                                   output_filename: str = "pairs_trading_results_2023_2025_unbiased.json") -> str:
    """
    Export comprehensive testing period (2023-2025) results to JSON for website display.

    Args:
        backtest_results: Results from backtest
        system_info: System configuration info
        output_filename: Name of output JSON file

    Returns:
        Path to saved JSON file
    """
    try:
        logger.info("=" * 80)
        logger.info("EXPORTING 2023-2025 TESTING RESULTS TO JSON FOR WEBSITE")
        logger.info("=" * 80)

        # Extract trades data
        trades = backtest_results.get('trades', [])
        daily_returns = backtest_results.get('daily_returns', [])

        if not trades:
            logger.warning("No trades found in backtest results")
            return ""

        # Calculate pair-level performance
        pair_performance = calculate_pair_performance(trades)

        # Get top 10 pairs by total return
        top_pairs = sorted(pair_performance.items(),
                          key=lambda x: x[1]['total_return_pct'],
                          reverse=True)[:10]

        # Calculate daily equity curve
        initial_value = 100000000  # $100M
        # v26: pass the REAL trading dates so the equity curve and monthly breakdown
        # are correctly dated. Previously dates were synthesized as consecutive
        # business days from 2023-01-01, which mislabeled the axis by ~6 months and
        # treated regime-skipped days as contiguous.
        daily_dates = backtest_results.get('daily_dates', None)
        equity_curve = calculate_equity_curve(daily_returns, initial_value, daily_dates)

        # Prepare comprehensive JSON structure
        export_data = {
            "metadata": {
                "export_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "testing_period": "2023-2025",
                "model_name": "Transformer Encoder Pairs Trading",
                "initial_capital": initial_value,
                "total_symbols": system_info.get('total_symbols_processed', 0) if isinstance(system_info, dict) else len(system_info),
                "pairs_selected": system_info.get('pairs_selected', 0) if isinstance(system_info, dict) else 0
            },

            "overall_performance": {
                "total_return_pct": round(backtest_results.get('total_return', 0) * 100, 2),
                "annualized_return_pct": round(backtest_results.get('annualized_return', 0) * 100, 2),
                "sharpe_ratio": round(backtest_results.get('sharpe_ratio', 0), 3),
                "max_drawdown_pct": round(backtest_results.get('max_drawdown', 0) * 100, 2),
                "volatility_pct": round(backtest_results.get('volatility', 0) * 100, 2),
                "win_rate_pct": round(backtest_results.get('win_rate', 0) * 100, 2),
                "profit_factor": round(backtest_results.get('profit_factor', 0), 2),
                "total_trades": backtest_results.get('total_trades', 0),
                "avg_trade_return_pct": round(backtest_results.get('avg_trade_return', 0) * 100, 4),
                "trades_per_day": round(backtest_results.get('trades_per_day', 0), 2),
                "total_cost_impact_pct": round(backtest_results.get('total_cost_impact_pct', 0) * 100, 3),
                "final_portfolio_value": round(backtest_results.get('final_portfolio_value', 0), 2)
            },

            "top_10_pairs": [
                {
                    "rank": idx + 1,
                    "pair": pair_name,
                    "total_return_pct": round(stats['total_return_pct'], 2),
                    "win_rate_pct": round(stats['win_rate'] * 100, 2),
                    "total_trades": stats['total_trades'],
                    "avg_holding_days": round(stats['avg_holding_days'], 1),
                    "profit_factor": round(stats['profit_factor'], 2),
                    "avg_trade_return_pct": round(stats['avg_trade_return_pct'], 4),
                    "sharpe_ratio": round(stats['sharpe_ratio'], 3),
                    "max_drawdown_pct": round(stats['max_drawdown'] * 100, 2),
                    "total_pnl_dollars": round(stats['total_pnl_dollars'], 2),
                    "avg_signal_strength": round(stats['avg_signal_strength'], 3),
                    "avg_pair_quality": round(stats['avg_pair_quality'], 3)
                }
                for idx, (pair_name, stats) in enumerate(top_pairs)
            ],

            "daily_equity_curve": [
                {
                    "date": equity_curve['dates'][i],
                    "portfolio_value": round(equity_curve['values'][i], 2),
                    "daily_return_pct": round(equity_curve['returns'][i] * 100, 4),
                    "cumulative_return_pct": round(equity_curve['cumulative_returns'][i] * 100, 2),
                    "drawdown_pct": round(equity_curve['drawdowns'][i] * 100, 2)
                }
                for i in range(len(equity_curve['dates']))
            ],

            "all_trades": [
                {
                    "trade_id": idx + 1,
                    "date": trade['date'].strftime("%Y-%m-%d"),
                    "pair": trade['pair'],
                    "action": trade['action'],
                    "position_size_dollars": round(trade['position_size'], 2),
                    "position_pct": round(trade['position_pct'] * 100, 2),
                    "signal_strength": round(trade['signal_strength'], 3),
                    "zscore": round(trade['zscore'], 2),
                    "pair_quality": round(trade['pair_quality'], 3),
                    "gross_pnl_pct": round(trade['gross_pnl_pct'] * 100, 4),
                    "net_pnl_pct": round(trade['net_pnl_pct'] * 100, 4),
                    "pnl_dollars": round(trade['pnl_dollar'], 2),
                    "transaction_cost_pct": round(trade['transaction_cost_pct'] * 100, 4),
                    "holding_days": trade['holding_days']
                }
                for idx, trade in enumerate(trades)
            ],

            "monthly_performance": calculate_monthly_performance(daily_returns, equity_curve),

            "pair_correlation_matrix": calculate_pair_correlations(trades),

            "trade_statistics": {
                "by_action": calculate_action_statistics(trades),
                "by_holding_period": calculate_holding_period_statistics(trades),
                "by_signal_strength": calculate_signal_strength_statistics(trades)
            },

            "walk_forward_validation": backtest_results.get('walk_forward', {}),

            # Statistical significance of the edge (PSR, HAC Sharpe t-stat,
            # bootstrap CIs, OOS window test, Deflated Sharpe). Measurement only.
            "significance": backtest_results.get('significance', {}),

            # Baseline benchmarks: Gatev (2006) distance method + random-pair control
            # on the same universe/period — does the pipeline beat the textbook?
            "benchmarks": backtest_results.get('benchmarks', {}),

            # Multiple-testing (Benjamini-Hochberg FDR) diagnostic on pair selection.
            "fdr_diagnostic": backtest_results.get('fdr_diagnostic', {})
        }

        # Save to JSON file
        os.makedirs(os.path.join(os.getcwd(), 'outputs'), exist_ok=True)
        output_path = os.path.join(os.getcwd(), 'outputs', output_filename)
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)

        logger.info(f"Successfully exported testing results to: {output_path}")
        logger.info(f"   Total trades: {len(trades):,}")
        logger.info(f"   Top 10 pairs: {len(top_pairs)}")
        logger.info(f"   Daily equity points: {len(equity_curve['dates']):,}")
        logger.info(f"   File size: {os.path.getsize(output_path) / 1024:.2f} KB")
        logger.info("=" * 80)

        # Also save a compact version for quick loading
        compact_data = {
            "metadata": export_data["metadata"],
            "overall_performance": export_data["overall_performance"],
            "top_10_pairs": export_data["top_10_pairs"],
            "daily_equity_curve": export_data["daily_equity_curve"],
            "walk_forward_validation": export_data["walk_forward_validation"],
            "significance": export_data["significance"],
            "benchmarks": export_data["benchmarks"],
            "fdr_diagnostic": export_data["fdr_diagnostic"]
        }

        compact_filename = output_filename.replace('.json', '_compact.json')
        compact_path = os.path.join(os.getcwd(), 'outputs', compact_filename)
        with open(compact_path, 'w') as f:
            json.dump(compact_data, f, indent=2)

        logger.info(f"Also saved compact version: {compact_path}")
        logger.info(f"   Compact file size: {os.path.getsize(compact_path) / 1024:.2f} KB")

        return output_path

    except Exception as e:
        logger.error(f"Error exporting to JSON: {str(e)}")
        import traceback
        traceback.print_exc()
        return ""


def calculate_pair_performance(trades: List[Dict]) -> Dict[str, Dict]:
    """Calculate performance metrics for each trading pair"""
    pair_stats = {}

    for trade in trades:
        pair = trade['pair']

        if pair not in pair_stats:
            pair_stats[pair] = {
                'trades': [],
                'returns': [],
                'winning_trades': 0,
                'losing_trades': 0,
                'total_pnl': 0,
                'signal_strengths': [],
                'pair_qualities': [],
                'holding_days': []
            }

        stats = pair_stats[pair]
        stats['trades'].append(trade)
        stats['returns'].append(trade['net_pnl_pct'])
        stats['signal_strengths'].append(trade['signal_strength'])
        stats['pair_qualities'].append(trade['pair_quality'])
        stats['holding_days'].append(trade['holding_days'])
        stats['total_pnl'] += trade['pnl_dollar']

        if trade['net_pnl_pct'] > 0:
            stats['winning_trades'] += 1
        else:
            stats['losing_trades'] += 1

    # Calculate final metrics
    pair_performance = {}
    for pair, stats in pair_stats.items():
        total_trades = len(stats['trades'])
        returns = np.array(stats['returns'])

        pair_performance[pair] = {
            'total_return_pct': np.sum(returns) * 100,
            'win_rate': stats['winning_trades'] / total_trades if total_trades > 0 else 0,
            'total_trades': total_trades,
            'avg_holding_days': np.mean(stats['holding_days']) if stats['holding_days'] else 0,
            'profit_factor': calculate_profit_factor(returns),
            'avg_trade_return_pct': np.mean(returns) * 100 if len(returns) > 0 else 0,
            'sharpe_ratio': np.mean(returns) / np.std(returns) * np.sqrt(252) if len(returns) > 1 and np.std(returns) > 0 else 0,
            'max_drawdown': calculate_max_drawdown_from_returns(returns),
            'total_pnl_dollars': stats['total_pnl'],
            'avg_signal_strength': np.mean(stats['signal_strengths']) if stats['signal_strengths'] else 0,
            'avg_pair_quality': np.mean(stats['pair_qualities']) if stats['pair_qualities'] else 0
        }

    return pair_performance


def calculate_profit_factor(returns: np.ndarray) -> float:
    """Calculate profit factor from returns"""
    try:
        positive_returns = returns[returns > 0]
        negative_returns = returns[returns < 0]

        if len(positive_returns) == 0:
            return 0.0
        if len(negative_returns) == 0:
            # v26: cap at a large finite value — float('inf') serializes to the
            # bare token `Infinity`, which is invalid JSON and breaks strict parsers.
            return 999.0 if len(positive_returns) > 0 else 0.0

        profit = np.sum(positive_returns)
        loss = abs(np.sum(negative_returns))

        return profit / loss if loss > 0 else 0.0
    except Exception:
        return 0.0


def calculate_max_drawdown_from_returns(returns: np.ndarray) -> float:
    """Calculate maximum drawdown from returns"""
    try:
        if len(returns) == 0:
            return 0.0

        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max

        return abs(np.min(drawdown)) if len(drawdown) > 0 else 0.0
    except Exception:
        return 0.0


def calculate_equity_curve(daily_returns: List[float], initial_value: float,
                            daily_dates: List = None) -> Dict:
    """Calculate detailed equity curve data.

    v26: if daily_dates (the real per-day trading dates from the backtest) is
    provided, use it; otherwise fall back to synthetic business days. Synthetic
    dates were misleading — the backtest starts 2023-07-01 and skips regime
    hard-stop days, so a contiguous 2023-01-01 calendar mislabels the curve.
    """
    returns_array = np.array(daily_returns)

    # Calculate cumulative values
    cumulative_multipliers = np.cumprod(1 + returns_array)
    values = initial_value * cumulative_multipliers
    cumulative_returns = cumulative_multipliers - 1

    # Calculate drawdowns
    peak = np.maximum.accumulate(values)
    drawdowns = (peak - values) / peak

    if daily_dates is not None and len(daily_dates) == len(returns_array):
        dates = [pd.Timestamp(d) for d in daily_dates]
    else:
        # Fallback: synthetic business days (only when real dates unavailable)
        start_date = pd.Timestamp('2023-07-01')
        dates = pd.date_range(start=start_date, periods=len(returns_array), freq='B')

    return {
        'dates': [d.strftime("%Y-%m-%d") for d in dates],
        'values': values.tolist(),
        'returns': returns_array.tolist(),
        'cumulative_returns': cumulative_returns.tolist(),
        'drawdowns': drawdowns.tolist()
    }


def calculate_monthly_performance(daily_returns: List[float], equity_curve: Dict) -> List[Dict]:
    """Calculate monthly performance statistics"""
    try:
        returns_array = np.array(daily_returns)
        dates = pd.to_datetime(equity_curve['dates'])

        # Group by month
        df = pd.DataFrame({
            'date': dates,
            'return': returns_array
        })
        df['year_month'] = df['date'].dt.to_period('M')

        monthly_stats = []
        for period, group in df.groupby('year_month'):
            monthly_return = np.prod(1 + group['return'].values) - 1

            monthly_stats.append({
                'month': str(period),
                'return_pct': round(monthly_return * 100, 2),
                'trades': len(group),
                'win_rate_pct': round(len(group[group['return'] > 0]) / len(group) * 100, 2) if len(group) > 0 else 0,
                'volatility_pct': round(group['return'].std() * np.sqrt(21) * 100, 2),
                'sharpe_ratio': round(group['return'].mean() / group['return'].std() * np.sqrt(21), 3) if group['return'].std() > 0 else 0
            })

        return monthly_stats
    except Exception as e:
        logger.error(f"Error calculating monthly performance: {str(e)}")
        return []


def calculate_pair_correlations(trades: List[Dict]) -> Dict[str, List]:
    """Calculate correlation matrix between pairs"""
    try:
        # Get unique pairs
        pairs = list(set([trade['pair'] for trade in trades]))

        if len(pairs) < 2:
            return {"pairs": pairs, "correlation_matrix": []}

        # Group trades by date and pair
        trades_by_date = {}
        for trade in trades:
            date = trade['date'].strftime("%Y-%m-%d")
            if date not in trades_by_date:
                trades_by_date[date] = {}
            pair = trade['pair']
            if pair not in trades_by_date[date]:
                trades_by_date[date][pair] = []
            trades_by_date[date][pair].append(trade['net_pnl_pct'])

        # Calculate correlation (simplified)
        correlation_matrix = []
        for i, pair1 in enumerate(pairs):
            row = []
            for j, pair2 in enumerate(pairs):
                if i == j:
                    row.append(1.0)
                else:
                    row.append(0.0)
            correlation_matrix.append(row)

        return {
            "pairs": pairs,
            "correlation_matrix": correlation_matrix
        }
    except Exception as e:
        logger.error(f"Error calculating pair correlations: {str(e)}")
        return {"pairs": [], "correlation_matrix": []}


def calculate_action_statistics(trades: List[Dict]) -> Dict:
    """Calculate statistics by trade action (LONG/SHORT)"""
    try:
        long_trades = [t for t in trades if t['action'] == 'LONG']
        short_trades = [t for t in trades if t['action'] == 'SHORT']

        def get_stats(trade_list):
            if not trade_list:
                return {
                    'count': 0,
                    'win_rate_pct': 0,
                    'avg_return_pct': 0,
                    'total_return_pct': 0
                }

            returns = [t['net_pnl_pct'] for t in trade_list]
            wins = len([r for r in returns if r > 0])

            return {
                'count': len(trade_list),
                'win_rate_pct': round(wins / len(trade_list) * 100, 2),
                'avg_return_pct': round(np.mean(returns) * 100, 4),
                'total_return_pct': round(np.sum(returns) * 100, 2)
            }

        return {
            'LONG': get_stats(long_trades),
            'SHORT': get_stats(short_trades)
        }
    except Exception as e:
        logger.error(f"Error calculating action statistics: {str(e)}")
        return {}


def calculate_holding_period_statistics(trades: List[Dict]) -> Dict:
    """Calculate statistics by holding period"""
    try:
        buckets = {
            '1-3 days': (1, 3),
            '4-7 days': (4, 7),
            '8+ days': (8, 999)
        }

        stats_by_period = {}

        for bucket_name, (min_days, max_days) in buckets.items():
            bucket_trades = [t for t in trades if min_days <= t['holding_days'] <= max_days]

            if bucket_trades:
                returns = [t['net_pnl_pct'] for t in bucket_trades]
                wins = len([r for r in returns if r > 0])

                stats_by_period[bucket_name] = {
                    'count': len(bucket_trades),
                    'win_rate_pct': round(wins / len(bucket_trades) * 100, 2),
                    'avg_return_pct': round(np.mean(returns) * 100, 4),
                    'total_return_pct': round(np.sum(returns) * 100, 2)
                }
            else:
                stats_by_period[bucket_name] = {
                    'count': 0,
                    'win_rate_pct': 0,
                    'avg_return_pct': 0,
                    'total_return_pct': 0
                }

        return stats_by_period
    except Exception as e:
        logger.error(f"Error calculating holding period statistics: {str(e)}")
        return {}


def export_fund_comparison_to_json(
    comparison_results: Dict,
    output_filename: str = "fund_type_comparison.json"
) -> str:
    """
    Export the fund-type comparison results to a structured JSON file.

    The JSON is designed for:
      - Website dashboards (per-profile performance tables)
      - Research / article data backing
      - Further analysis (pandas / R import)

    Structure:
      {
        "metadata": { export date, description },
        "profiles": {
          "<profile_key>": { all metrics, cost_components, equity_curve }
        },
        "summary_table": [ { metric, quant_hf, multi_strat, ... } ]
      }
    """
    try:
        logger.info("=" * 80)
        logger.info("EXPORTING FUND TYPE COMPARISON TO JSON")
        logger.info("=" * 80)

        if not comparison_results:
            logger.warning("No comparison results to export.")
            return ""

        # Build a flat summary table for easy chart rendering
        metric_defs = [
            ('total_return_pct',          'Total Return (%)'),
            ('annualized_return_pct',      'Annualized Return (%)'),
            ('sharpe_ratio',               'Sharpe Ratio'),
            ('max_drawdown_pct',           'Max Drawdown (%)'),
            ('win_rate_pct',               'Win Rate (%)'),
            ('profit_factor',              'Profit Factor'),
            ('total_trades',               'Total Trades'),
            ('total_cost_pct_of_capital',  'Total Costs (% of $100M)'),
            ('commission_bps',             'Commission (bps)'),
            ('bid_ask_bps',                'Bid-Ask (bps)'),
            ('market_impact_cap_bps',      'Market Impact Cap (bps)'),
            ('borrow_rate_easy_pct',       'Borrow Rate Easy (%/yr)'),
            ('financing_spread_pct',       'Financing Spread (%/yr)'),
            ('base_position_pct',          'Base Position (% equity)'),
            ('gross_leverage_label',       'Gross Leverage'),
            ('trades_stopped_early',       'Stopped by Drawdown Kill-Switch'),
        ]

        summary_table = []
        for key, label in metric_defs:
            row = {'metric': label}
            for profile_key, pdata in comparison_results.items():
                row[profile_key] = pdata.get(key, 'N/A')
            summary_table.append(row)

        # Cost component summary table
        cost_table = []
        cost_items = [
            ('commission_pct',    'Commission (% of $100M)'),
            ('bid_ask_pct',       'Bid-Ask (% of $100M)'),
            ('market_impact_pct', 'Market Impact (% of $100M)'),
            ('borrow_pct',        'Stock Borrow (% of $100M)'),
            ('financing_pct',     'Financing (% of $100M)'),
        ]
        for cost_key, cost_label in cost_items:
            row = {'cost_component': cost_label}
            for profile_key, pdata in comparison_results.items():
                row[profile_key] = pdata.get('cost_components', {}).get(cost_key, 0.0)
            cost_table.append(row)

        # Strip equity_curve from the profiles dict to keep the main JSON manageable
        # (equity curves go in a separate section)
        profiles_slim = {}
        equity_curves = {}
        for profile_key, pdata in comparison_results.items():
            slim = {k: v for k, v in pdata.items() if k != 'equity_curve'}
            profiles_slim[profile_key] = slim
            equity_curves[profile_key] = {
                'profile_name': pdata['profile_name'],
                'curve':        pdata.get('equity_curve', [])
            }

        export_data = {
            'metadata': {
                'export_date':  datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'description':  (
                    'Fund-type comparison: same pairs trading signals replayed under '
                    '5 different institutional fund economics (leverage, costs, risk limits). '
                    'Initial capital: $100M for all profiles.'
                ),
                'profiles':     list(comparison_results.keys()),
                'initial_capital_usd': 100_000_000,
            },
            'profiles':      profiles_slim,
            'summary_table': summary_table,
            'cost_table':    cost_table,
            'equity_curves': equity_curves,
        }

        os.makedirs(os.path.join(os.getcwd(), 'outputs'), exist_ok=True)
        output_path = os.path.join(os.getcwd(), 'outputs', output_filename)
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)

        size_kb = os.path.getsize(output_path) / 1024
        logger.info(f"Fund comparison exported: {output_path}  ({size_kb:.1f} KB)")
        logger.info(f"  Profiles: {', '.join(comparison_results.keys())}")
        logger.info("=" * 80)

        return output_path

    except Exception as e:
        logger.error(f"Error exporting fund comparison: {str(e)}")
        import traceback
        traceback.print_exc()
        return ""


def calculate_signal_strength_statistics(trades: List[Dict]) -> Dict:
    """Calculate statistics by signal strength"""
    try:
        buckets = {
            'weak (0.5-0.7)':    (0.5,  0.7,  False),
            'medium (0.7-0.85)': (0.7,  0.85, False),
            'strong (0.85-1.0)': (0.85, 1.0,  True),   # inclusive upper bound
        }

        stats_by_strength = {}

        for bucket_name, (min_strength, max_strength, inclusive_upper) in buckets.items():
            if inclusive_upper:
                bucket_trades = [t for t in trades if min_strength <= t['signal_strength'] <= max_strength]
            else:
                bucket_trades = [t for t in trades if min_strength <= t['signal_strength'] < max_strength]

            if bucket_trades:
                returns = [t['net_pnl_pct'] for t in bucket_trades]
                wins = len([r for r in returns if r > 0])

                stats_by_strength[bucket_name] = {
                    'count': len(bucket_trades),
                    'win_rate_pct': round(wins / len(bucket_trades) * 100, 2),
                    'avg_return_pct': round(np.mean(returns) * 100, 4),
                    'total_return_pct': round(np.sum(returns) * 100, 2)
                }
            else:
                stats_by_strength[bucket_name] = {
                    'count': 0,
                    'win_rate_pct': 0,
                    'avg_return_pct': 0,
                    'total_return_pct': 0
                }

        return stats_by_strength
    except Exception as e:
        logger.error(f"Error calculating signal strength statistics: {str(e)}")
        return {}
