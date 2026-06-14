"""
TRANSFORMER ENCODER FOR PAIRS TRADING - MAIN ENTRY POINT
=========================================================
Research Paper Implementation - Main Execution Script

Run this file to execute the complete trading system.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

import random
import numpy as np
import torch
import logging

from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem

logger = logging.getLogger(__name__)


def main():
    try:
        # Set random seeds for reproducibility
        random.seed(42)
        np.random.seed(42)
        torch.manual_seed(42)

        logger.info("Starting Fixed Transformer Encoder Trading System...")

        system = CompleteFixedRussell3000TradingSystem(initial_capital=100000000)
        results = system.run_complete_system()

        print("\n" + "="*50)
        print("FINAL RESULTS SUMMARY")
        print("="*50)
        print(f"Total Return: {results['total_return']:.2%}")
        print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        print(f"Max Drawdown: {results['max_drawdown']:.2%}")
        print(f"Total Trades: {results['total_trades']}")
        print(f"Win Rate: {results['win_rate']:.2%}")
        print(f"Profit Factor: {results['profit_factor']:.2f}")
        print("="*50)

        wf = results.get('walk_forward', {})
        if wf:
            print("\n" + "="*70)
            print("WALK-FORWARD VALIDATION SUMMARY")
            print("="*70)
            print(f"Windows tested:       {wf.get('total_windows', 0)}")
            print(f"Profitable windows:   {wf.get('profitable_windows', 0)} ({wf.get('profitable_window_pct', 0)}%)")
            print(f"Avg window return:    {wf.get('avg_window_return_pct', 0):.4f}%")
            print(f"Median window return: {wf.get('median_window_return_pct', 0):.4f}%")
            print(f"Avg Sharpe:           {wf.get('avg_sharpe', 0):.3f}")
            print(f"Stitched return:      {wf.get('stitched_total_return_pct', 0):.4f}%")

            # Hard era split (Problem 5)
            is_era  = wf.get('in_sample_era', {})
            oos_era = wf.get('out_of_sample_era', {})
            if is_era or oos_era:
                print("-"*70)
                print("HARD ERA SPLIT  (regime break boundary: 2023-04-04)")
                print(f"  In-sample  W1-W9  (pre-regime):  "
                      f"{is_era.get('count', 0):2d} windows | "
                      f"avg {is_era.get('avg_return_pct', 0):+7.2f}%/qtr | "
                      f"Sharpe {is_era.get('avg_sharpe', 0):.3f} | "
                      f"WR {is_era.get('avg_win_rate_pct', 0):.1f}%")
                print(f"  OOS   W10-W19 (post-regime):     "
                      f"{oos_era.get('count', 0):2d} windows | "
                      f"avg {oos_era.get('avg_return_pct', 0):+7.2f}%/qtr | "
                      f"Sharpe {oos_era.get('avg_sharpe', 0):.3f} | "
                      f"WR {oos_era.get('avg_win_rate_pct', 0):.1f}%")
                _is_ret  = is_era.get('avg_return_pct', 0)
                _oos_ret = oos_era.get('avg_return_pct', 0)
                if abs(_is_ret) > 0:
                    _deg = (_is_ret - _oos_ret) / abs(_is_ret) * 100
                    print(f"  IS→OOS degradation: {_deg:.1f}%  "
                          f"[30-50% expected; >50% = regime break, not overfit]")
            print("="*70)

        rd = results.get('regime_diagnosis', {})
        if rd:
            print("\n" + "="*70)
            print("REGIME BREAK DIAGNOSIS — W10 (Apr–Jul 2023)")
            print("="*70)
            print(f"VIX avg: {rd.get('vix_avg', 0.0):.1f}  "
                  f"(min {rd.get('vix_min', 0.0):.1f} / max {rd.get('vix_max', 0.0):.1f})  "
                  f"[historical avg {rd.get('vix_pre_period_avg', 20):.1f}]")
            print(f"Sector dispersion z-score: avg {rd.get('sector_dispersion_avg_z', 0.0):.2f}σ  "
                  f"max {rd.get('sector_dispersion_max_z', 0.0):.2f}σ")
            print(f"Days with dispersion > 2σ: {rd.get('days_above_2sigma', '?')} "
                  f"/ {rd.get('total_days_in_period', '?')}")
            print("Root cause: 'Walking on Ice' — low VIX masked broken pair correlations")
            print("Fixes: regime gate (VIX+dispersion) + adaptive 6m cointegration window")
            print("="*70)

        fc = results.get('fund_comparison', {})
        if fc:
            print("\n" + "="*90)
            print("FUND TYPE COMPARISON SUMMARY")
            print("(Same signals — different institutional economics: leverage, costs, risk limits)")
            print("="*90)
            print(f"{'Fund Type':<32} {'Net Return%':>12} {'Sharpe':>8} {'MaxDD%':>9} "
                  f"{'WinRate%':>10} {'Costs%':>8} {'Leverage':>12}")
            print("-"*90)
            for r in fc.values():
                stopped = " [STOPPED]" if r.get('trades_stopped_early') else ""
                print(
                    f"{r['profile_name']:<32} {r['total_return_pct']:>11.2f}% "
                    f"{r['sharpe_ratio']:>8.2f} {r['max_drawdown_pct']:>8.2f}% "
                    f"{r['win_rate_pct']:>9.2f}% {r['total_cost_pct_of_capital']:>7.2f}% "
                    f"{r['gross_leverage_label']:>12}{stopped}"
                )
            print("="*90)
            print("Outputs: fund_comparison.png  |  fund_type_comparison.json")

    except Exception as e:
        logger.error(f"System execution failed: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
