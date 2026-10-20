#!/usr/bin/env python3
"""Run the Avellaneda-Lee (2010) sector-ETF residual strategy on the study data.

The strategy, its published parameters and every deviation from the paper are documented
in pairs_trading/residual_statarb.py. This script reads the same inputs as the main
pipeline — the universe file data/marketcap.csv, the price cache
data/enhanced_russell_3000_data.pkl and the sector-ETF closes in data/macro_data.pkl — and
writes outputs/residual_statarb_<start>_<end>.json with the daily series, every trade, cost
totals, turnover, summary metrics and the run's provenance block. It never fetches prices:
if a cache is missing it stops (run `python -m pairs_trading.main` first).

Stock -> sector ETF: --sector-map PATH reads an industry file with ticker and sector_etf
columns (SIC -> Fama-French 49 -> SPDR); without it, reference/industry_ff49.csv is used
when it exists, else the Nasdaq 'Sector' column of data/marketcap.csv (forced with
--sector-map nasdaq). The provenance block records which map was used and its sha256.

usage: python scripts/run_residual_statarb.py [--start 2023-07-01] [--end 2025-12-31]
           [--universe-size 500] [--position-frac 0.005] [--sector-map PATH|nasdaq] [--out PATH]
"""
import argparse
import logging
import os
import pathlib
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('TQDM_DISABLE', '1')

from pairs_trading.data_processor import EnhancedRussell3000DataProcessor  # noqa: E402
from pairs_trading.json_export import _atomic_write_json, build_run_config, file_fingerprint  # noqa: E402
from pairs_trading.residual_statarb import (  # noqa: E402
    ResidualStatArbParams, ff49_sector_etf_map, nasdaq_sector_etf_map, run_residual_statarb,
)

UNIVERSE_FILE = os.path.join('data', 'marketcap.csv')
MACRO_FILE = os.path.join('data', 'macro_data.pkl')
INDUSTRY_FILE = os.path.join('reference', 'industry_ff49.csv')


def load_sector_map(choice: str = None) -> tuple:
    """The run's {symbol: sector ETF} map and a provenance record of where it came from.

    choice: a path to an industry file (ticker, sector_etf columns), 'nasdaq' for the
    Nasdaq 'Sector' column of the universe file, or None for INDUSTRY_FILE when it exists
    and the Nasdaq map otherwise. Relative paths resolve against the current directory.
    """
    if choice is None:
        choice = INDUSTRY_FILE if os.path.exists(INDUSTRY_FILE) else 'nasdaq'
    if choice == 'nasdaq':
        path, source = UNIVERSE_FILE, 'nasdaq_sector (data/marketcap.csv Sector column)'
        mapping = nasdaq_sector_etf_map(path)
    else:
        path, source = choice, 'ff49_sic (SEC SIC -> Fama-French 49 industry -> SPDR)'
        mapping = ff49_sector_etf_map(path)
    record = file_fingerprint(path)
    inside = os.path.abspath(path).startswith(str(ROOT) + os.sep)
    record['path'] = os.path.relpath(path, ROOT) if inside else os.path.basename(path)
    return mapping, {'source': source, 'file': record, 'n_symbols': len(mapping),
                     'etf_counts': dict(sorted(Counter(mapping.values()).items()))}


def export_payload(results: dict, run_config: dict) -> dict:
    """The JSON document: everything in `results` except the in-memory arrays."""
    payload = {k: v for k, v in results.items() if k not in ('signals', 'market')}
    payload['run_config'] = run_config
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--start', default='2023-07-01', help='first signal date (default 2023-07-01)')
    ap.add_argument('--end', default='2025-12-31', help='last date a position may be opened (default 2025-12-31)')
    ap.add_argument('--universe-size', type=int, default=500, help='N most liquid names (default 500)')
    ap.add_argument('--position-frac', type=float, default=ResidualStatArbParams.position_frac,
                    help='stock notional per position as a fraction of equity (default 0.005)')
    ap.add_argument('--sector-map', default=None,
                    help="industry file with ticker,sector_etf columns, or 'nasdaq' for the data/marketcap.csv "
                         'Sector column (default: reference/industry_ff49.csv if present, else nasdaq)')
    ap.add_argument('--out', default=None, help='output JSON (default outputs/residual_statarb_<start>_<end>.json)')
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    log = logging.getLogger('run_residual_statarb')

    out = os.path.abspath(args.out) if args.out else \
        str(ROOT / 'outputs' / f'residual_statarb_{args.start}_{args.end}.json')
    sector_choice = args.sector_map if args.sector_map in (None, 'nasdaq') else os.path.abspath(args.sector_map)
    os.chdir(ROOT)                      # the data processor resolves data/ relative to the cwd
    processor = EnhancedRussell3000DataProcessor()
    for path in (UNIVERSE_FILE, processor.data_file, MACRO_FILE):
        if not os.path.exists(path):
            log.error(f'{path} not found; this script does not fetch data. Run '
                      '`python -m pairs_trading.main` (or scripts/build_universe.py) first.')
            return 2
    if sector_choice not in (None, 'nasdaq') and not os.path.exists(sector_choice):
        log.error(f'{sector_choice} not found (build it with scripts/build_reference_data.py)')
        return 2

    t0 = time.time()
    symbols = processor.load_symbols()
    prices = processor.load_or_fetch_data(symbols)
    macro = processor.load_macro_data()
    sector_map, sector_info = load_sector_map(sector_choice)
    params = ResidualStatArbParams(universe_size=args.universe_size, position_frac=args.position_frac)
    log.info(f'Loaded {len(prices)} symbols, {len(macro["sectors"])} sector ETFs ({time.time() - t0:.0f}s)')
    log.info(f'Sector map: {sector_info["source"]}, {sector_info["file"]["path"]} '
             f'(sha256 {sector_info["file"]["sha256"][:12]}), {len(sector_map)} symbols, '
             f'{sum(s in sector_map for s in prices)} of them in the price data')

    results = run_residual_statarb(prices, macro['sectors'], sector_map, args.start, args.end, params=params)
    first = min(df.index[0] for df in prices.values() if len(df))
    last = max(df.index[-1] for df in prices.values() if len(df))
    run_config = build_run_config(results, {
        'total_symbols_processed': len(prices), 'data_start': first, 'data_end': last,
        'universe_coverage': processor.universe_coverage,
        'universe_cached_fraction': processor.universe_cached_fraction,
    })
    run_config['sector_map'] = sector_info
    _atomic_write_json(export_payload(results, run_config), out)

    s = results['summary']
    g = s['gross_bp_per_trade']
    log.info(f'{s["start"]} -> {s["end"]}: {s["trades"]} trades, total return {s["total_return"]:+.2%}, '
             f'Sharpe {s["sharpe"]:+.2f} (gross {s["gross_sharpe"]:+.2f}), max drawdown {s["max_drawdown"]:.2%}')
    if g['t'] is not None:
        log.info(f'per trade: gross {g["mean"]:+.1f} bp (t = {g["t"]:.2f}), cost {s["cost_bp_per_trade"]:.1f} bp; '
                 f'avg gross exposure {s["avg_gross_exposure"]:.2f}, avg open positions {s["avg_open_positions"]:.0f}')
    log.info(f'wrote {out} ({time.time() - t0:.0f}s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
