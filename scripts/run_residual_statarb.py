#!/usr/bin/env python3
"""Run the Avellaneda-Lee (2010) sector-ETF residual strategy (S2) on a study calendar.

The strategy, its published parameters and every deviation from the paper are documented
in pairs_trading/residual_statarb.py. A run is one study_config calendar (--calendar, as
for python -m pairs_trading.main): the first signal date is the calendar's backtest_start
(that session's return is zero: its orders fill at the next close), the last entry date
its data_end, where the data end and positions still open close at the last bar. The
inputs are the caches the pairs arms read: the price cache (calendar.price_cache, with its
fetch manifest) and the sector-ETF closes of the macro cache (calendar.macro_cache).

The script fetches nothing. A missing cache, one of another period, a sector ETF without
closes through the last price date, or a point-in-time member the price cache never
attempted stops it with the step that fills the caches (the holdout runbook's data step,
python -m pairs_trading.main --profile v33 --calendar NAME --fetch-only).

Universe, S1's rule: the point-in-time Russell 3000 members of the IWV snapshot in force on
each ranking day, read from universe.reference_root(calendar) (reference/, or
data/<calendar>_reference/ for a calendar in the sealed period), the 500 most liquid by
trailing point-in-time dollar volume. Stock -> sector ETF: the committed map
reference/industry_ff49.csv (SIC -> Fama-French 49 -> SPDR). Costs: S1's cost model.

Output (--out, default outputs/residual_statarb_<calendar>.json): the daily net and gross
returns, gross exposure and open positions, every trade, cost totals, turnover, the
summary and significance battery, the universe on every ranking day and its survivorship
gap per IWV snapshot, and run_config (json_export.build_run_config: the commit and tree
state at the start of the run, PAIRS_EXPECTED_COMMIT enforced as for the pairs pipeline;
the calendar and its hash; the parameters and their hash; the cache fingerprints; the
membership index and the sector map with their sha256). 'complete' and
'non_default_switches' play the part of a pairs run's headline: other parameters, another
sector map or a partial cache make a sensitivity variant, which scripts/evaluate_holdout.py
and scripts/publish_run.py refuse.

usage: python scripts/run_residual_statarb.py [--calendar dev|rehearsal2025|holdout2026] [--out PATH]
           [--universe-size 500] [--position-frac 0.005] [--sector-map PATH|nasdaq]
Run it from the repository root, as the pairs pipeline: the calendar's cache paths are
relative to the working directory.
"""
import argparse
import dataclasses
import logging
import os
import pathlib
import sys
import time
from collections import Counter

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('TQDM_DISABLE', '1')

from pairs_trading.data_processor import EnhancedRussell3000DataProcessor  # noqa: E402
from pairs_trading.json_export import (  # noqa: E402
    MIN_UNIVERSE_COVERAGE, _atomic_write_json, build_run_config, file_fingerprint, record_start_provenance,
)
from pairs_trading.residual_statarb import (  # noqa: E402
    S1_PROFILE, ResidualStatArbParams, ff49_sector_etf_map, nasdaq_sector_etf_map, run_residual_statarb,
    s1_cost_model,
)
from pairs_trading.study_config import CALENDARS, get_calendar  # noqa: E402
from pairs_trading import universe  # noqa: E402

UNIVERSE_FILE = os.path.join('data', 'marketcap.csv')
DATA_STEP = 'python -m pairs_trading.main --profile v33 --calendar {name} --fetch-only'
# Environment switches that change what this arm computes (the pairs engine's fill,
# ranker, re-selection and seed switches do not reach it).
VARIANT_SWITCHES = ('PAIRS_SKIP_REPROCESS', 'PAIRS_ALLOW_PARTIAL_FETCH')


def _repo_path(path) -> str:
    """A path relative to the repository when inside it, else its file name: an export never
    records the author's directories."""
    path = os.path.abspath(path)
    return os.path.relpath(path, ROOT) if path.startswith(str(ROOT) + os.sep) else os.path.basename(path)


def _day(x) -> pd.Timestamp:
    ts = pd.Timestamp(x)
    return (ts.tz_localize(None) if ts.tzinfo is not None else ts).normalize()


def load_sector_map(choice: str = None, reference_dir=None) -> tuple:
    """The run's {symbol: sector ETF} map and a provenance record of where it came from.

    choice: None for the committed map, industry_ff49.csv of reference_dir (default
    universe.REFERENCE_DIR, the map S1 reads its industries from), read by
    universe.sector_etf_map (the registered arm; a missing file stops the run, there is no
    fallback); a path to another industry file (ticker, sector_etf columns); or 'nasdaq'
    for the Nasdaq 'Sector' column of data/marketcap.csv. Anything but the committed map
    is a sensitivity variant ('registered': False).
    """
    reference_dir = pathlib.Path(reference_dir or universe.REFERENCE_DIR)
    committed = reference_dir / 'industry_ff49.csv'
    if choice is None:
        if not committed.exists():
            raise FileNotFoundError(f'{committed} not found: it is committed with the repository '
                                    '(scripts/build_reference_data.py builds it)')
        path, source = str(committed), 'ff49_sic (SEC SIC -> Fama-French 49 industry -> SPDR)'
        mapping = universe.sector_etf_map(reference_dir)
    elif choice == 'nasdaq':
        path, source = UNIVERSE_FILE, 'nasdaq_sector (data/marketcap.csv Sector column)'
        mapping = nasdaq_sector_etf_map(path)
    else:
        if not os.path.exists(choice):
            raise FileNotFoundError(f'{choice} not found')
        path, source = choice, 'ff49_sic (SEC SIC -> Fama-French 49 industry -> SPDR)'
        mapping = ff49_sector_etf_map(path)
    record = file_fingerprint(path)
    record['path'] = _repo_path(path)
    registered = os.path.abspath(path) == os.path.abspath(committed)
    return mapping, {'source': source, 'file': record, 'registered': registered, 'n_symbols': len(mapping),
                     'etf_counts': dict(sorted(Counter(mapping.values()).items()))}


def membership(pit: universe.PITUniverse, calendar) -> tuple:
    """(symbols, snapshots): every member of each IWV snapshot in force on some day from the
    calendar's backtest_start to its data_end, and those snapshots' index entries."""
    first, last = pit.snapshot_asof(calendar.backtest_start), _day(calendar.data_end)
    snapshots = [s for s in pit.snapshots() if first <= _day(s['period_date']) <= last]
    symbols = sorted({t for s in snapshots for t in pit.members_asof(s['period_date'])})
    return symbols, snapshots


def check_sector_closes(sectors: dict, sector_map: dict, prices: dict, calendar) -> None:
    """Every sector ETF the map names must have closes from the first signal date through the
    last price date: the hedge of a stock whose ETF stops would be marked flat."""
    last = max(_day(df.index.max()) for df in prices.values() if len(df))
    short = sorted(e for e in set(sector_map.values())
                   if sectors.get(e) is None or len(sectors[e]) == 0
                   or _day(sectors[e].index.min()) > _day(calendar.backtest_start)
                   or _day(sectors[e].index.max()) < last)
    if short:
        raise RuntimeError(f"{calendar.macro_cache} lacks closes from {calendar.backtest_start} through "
                           f"{last.date()} for {short}. This script never fetches: fill the caches with "
                           f"{DATA_STEP.format(name=calendar.name)}.")


def residual_study(calendar, params: ResidualStatArbParams) -> dict:
    """The run's design record, the residual arm's counterpart of study_config.describe."""
    return {'strategy': 'avellaneda_lee', 'profile': None,
            'params': dataclasses.asdict(params), 'params_hash': params.config_hash(),
            'calendar': dataclasses.asdict(calendar), 'calendar_hash': calendar.config_hash(),
            'shares_with_profile': {'name': S1_PROFILE,
                                    'what': 'point-in-time universe rule, t+1 close fills, cost model'}}


def residual_run_config(results: dict, system_info: dict, sector_info: dict, universe_info: dict = None) -> dict:
    """The run's provenance block: json_export.build_run_config plus the sector map and the
    membership source.

    build_run_config's 'effective' switches describe the pairs engine (PAIRS_FILL, the
    ranker, pair re-selection). This strategy always fills at the next close and has no
    ranker or pair selection, so its block records only that; a PAIRS_FILL left in the
    environment would otherwise be reported as this run's fill.
    """
    run_config = build_run_config(results, system_info)
    run_config['effective'] = {'fill': 'close', 'calendar': run_config['effective'].get('calendar')}
    run_config['sector_map'] = sector_info
    if universe_info is not None:
        run_config['universe'] = universe_info
        run_config['data']['universe_file'] = universe_info.get('index')
    return run_config


def residual_switches(run_config: dict, params: ResidualStatArbParams, sector_info: dict,
                      never_fetched=()) -> list:
    """What makes this run differ from the registered arm (empty: it is the registered arm)."""
    default = ResidualStatArbParams()
    out = [f'{k}={v}' for k, v in dataclasses.asdict(params).items() if v != getattr(default, k)]
    if not sector_info.get('registered'):
        out.append(f"sector_map={(sector_info.get('file') or {}).get('path')}")
    env = run_config.get('env') or {}
    out += [f'{key}=1' for key in VARIANT_SWITCHES if env.get(key) == '1']
    if never_fetched:
        out.append(f'never_fetched_members={len(never_fetched)}')
    coverage = (run_config.get('data') or {}).get('universe_coverage')
    if coverage is not None and coverage < MIN_UNIVERSE_COVERAGE:
        out.append(f'universe_coverage={coverage:.1%}')
    return out


def export_payload(results: dict, run_config: dict, switches=()) -> dict:
    """The JSON document: everything in `results` except the in-memory arrays."""
    payload = {k: v for k, v in results.items() if k not in ('signals', 'market')}
    payload['complete'] = True
    payload['non_default_switches'] = list(switches)
    payload['run_config'] = run_config
    return payload


def universe_record(pit: universe.PITUniverse, calendar, snapshots: list, results: dict, prices: dict) -> tuple:
    """(membership provenance, survivorship gap per snapshot) of a point-in-time run.

    Each ranking row gets the period date of the snapshot in force; each snapshot's gap
    is measured on the first ranking day it governs (universe.PITUniverse.coverage, the
    record S1 keeps per formation, under the same 'formation_date' key).
    """
    first_day = {}
    for row in results['universe']['rankings']:
        row['snapshot'] = str(pit.snapshot_asof(row['date']).date())
        first_day.setdefault(row['snapshot'], row['date'])
    gaps = [{'formation_date': day, **{k: v for k, v in pit.coverage(prices.keys(), day).items()
                                        if k != 'missing_symbols'}}
            for day in first_day.values()]
    index = pit.universe_dir / 'index.json'
    fingerprint = file_fingerprint(str(index))
    fingerprint['path'] = _repo_path(index)
    info = {'source': 'point-in-time Russell 3000 membership, IWV N-PORT holdings (universe.PITUniverse)',
            'reference_root': _repo_path(universe.reference_root(calendar)), 'index': fingerprint,
            'snapshots': [{k: s.get(k) for k in ('period_date', 'filing_date', 'accession', 'file')}
                          for s in snapshots]}
    return info, gaps


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--calendar', choices=sorted(CALENDARS),
                    help='study calendar (default: PAIRS_CALENDAR, else dev)')
    ap.add_argument('--out', default=None, help='output JSON (default outputs/residual_statarb_<calendar>.json)')
    ap.add_argument('--universe-size', type=int, default=ResidualStatArbParams.universe_size,
                    help='N most liquid point-in-time members (default 500, as S1); another value is a variant')
    ap.add_argument('--position-frac', type=float, default=ResidualStatArbParams.position_frac,
                    help='stock notional per position as a fraction of equity (default 0.005); another value '
                         'is a variant')
    ap.add_argument('--sector-map', default=None,
                    help="another industry file with ticker,sector_etf columns, or 'nasdaq' for the "
                         'data/marketcap.csv Sector column (default: the committed reference/industry_ff49.csv); '
                         'a variant')
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    log = logging.getLogger('run_residual_statarb')

    t0 = time.time()
    try:
        record_start_provenance()           # PAIRS_EXPECTED_COMMIT: stops before any data is read
        calendar = get_calendar(args.calendar)
        out = args.out or os.path.join('outputs', f'residual_statarb_{calendar.name}.json')
        step = DATA_STEP.format(name=calendar.name)
        for path in (calendar.price_cache, calendar.macro_cache):
            if not os.path.exists(path):
                raise FileNotFoundError(f'{path} not found; this script never fetches. Fill the caches with {step}.')
        pit = universe.PITUniverse(universe.reference_root(calendar))
        symbols, snapshots = membership(pit, calendar)
        sector_map, sector_info = load_sector_map(args.sector_map)
        processor = EnhancedRussell3000DataProcessor(
            start_date=calendar.data_start, end_date=calendar.data_end,
            data_file=calendar.price_cache, macro_file=calendar.macro_cache)
        prices = processor.load_cached_data(symbols)
        macro = processor.load_macro_data(fetch=False)
        check_sector_closes(macro.get('sectors') or {}, sector_map, prices, calendar)
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        log.error(str(e))
        return 2
    params = ResidualStatArbParams(universe_size=args.universe_size, position_frac=args.position_frac)
    log.info(f'Calendar {calendar.name}: signals {calendar.backtest_start} -> {calendar.data_end}; '
             f'{len(snapshots)} IWV snapshots ({snapshots[0]["period_date"]} -> {snapshots[-1]["period_date"]}), '
             f'{len(symbols)} distinct members, {len(prices)} with prices ({time.time() - t0:.0f}s)')
    log.info(f'Sector map: {sector_info["source"]}, {sector_info["file"]["path"]} '
             f'(sha256 {sector_info["file"]["sha256"][:12]}), {len(sector_map)} symbols, '
             f'{sum(s in sector_map for s in prices)} of them with prices')

    results = run_residual_statarb(prices, macro['sectors'], sector_map, calendar.backtest_start,
                                   calendar.data_end, params=params, cost_model=s1_cost_model(),
                                   members=pit.members_asof)
    universe_info, gaps = universe_record(pit, calendar, snapshots, results, prices)
    results['universe_by_formation'] = gaps
    first = min(df.index[0] for df in prices.values() if len(df))
    last = max(df.index[-1] for df in prices.values() if len(df))
    run_config = residual_run_config(results, {
        'study': residual_study(calendar, params),
        'total_symbols_processed': len(prices), 'data_start': first, 'data_end': last,
        'price_cache': calendar.price_cache, 'macro_cache': calendar.macro_cache,
        'universe_coverage': processor.universe_coverage,
        'universe_cached_fraction': processor.universe_cached_fraction,
        'universe_not_found_fraction': processor.universe_not_found_fraction,
    }, sector_info, universe_info)
    if processor.never_fetched:
        run_config['data']['never_fetched_members'] = list(processor.never_fetched)
    switches = residual_switches(run_config, params, sector_info, processor.never_fetched)
    _atomic_write_json(export_payload(results, run_config, switches), out)

    s = results['summary']
    g = s['gross_bp_per_trade']
    log.info(f'{s["start"]} -> {s["end"]} ({s["days"]} days): {s["trades"]} trades, total return '
             f'{s["total_return"]:+.2%}, net Sharpe {s["sharpe"]:+.2f} (gross {s["gross_sharpe"]:+.2f}), '
             f'max drawdown {s["max_drawdown"]:.2%}')
    if g['t'] is not None:
        log.info(f'per trade: gross {g["mean"]:+.1f} bp (t = {g["t"]:.2f}), cost {s["cost_bp_per_trade"]:.1f} bp; '
                 f'avg gross exposure {s["avg_gross_exposure"]:.2f}, avg open positions {s["avg_open_positions"]:.0f}')
    if switches:
        log.warning(f'non-default switches (a sensitivity variant, not the registered arm): {switches}')
    log.info(f'commit {run_config["git_commit"]}{" (uncommitted changes)" if run_config["git_dirty"] else ""}; '
             f'wrote {out} ({time.time() - t0:.0f}s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
