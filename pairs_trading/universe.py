"""
PAIRS TRADING - POINT-IN-TIME UNIVERSE
======================================
Russell 3000 membership as of any date, and the per-ticker industry, sector-ETF and
listing-venue maps, read from the committed reference files:

- reference/universe/index.json + iwv_<period>.csv: the iShares Russell 3000 ETF (IWV)
  holdings in each quarterly SEC N-PORT filing, CUSIP -> ticker via OpenFIGI and N-PORT's
  own reported tickers (scripts/build_pit_universe.py);
- reference/industry_ff49.csv: SIC from EDGAR -> Fama-French 49 industry -> Select
  Sector SPDR (scripts/build_reference_data.py);
- reference/listing_venue.csv: primary listing venue from Nasdaq Trader's symbol
  directory (scripts/build_reference_data.py).

Pure: no network, files are read once per path and every result is a fresh copy.
"""

import csv
import datetime
import functools
import json
import os
import pathlib
from typing import Dict, Iterable, List, Optional, Union

import pandas as pd

REFERENCE_DIR = pathlib.Path(__file__).resolve().parents[1] / 'reference'

DateLike = Union[str, pd.Timestamp, datetime.date]


def normalise_ticker(ticker: Optional[str]) -> str:
    """Upper-case Yahoo-style ticker: class separators '/' and '.' become '-' (BRK/B -> BRK-B)."""
    t = (ticker or '').strip().upper().replace(' ', '')
    return t.replace('/', '-').replace('.', '-')


def _as_date(date: DateLike) -> pd.Timestamp:
    """A tz-naive calendar date; a tz-aware stamp keeps its local wall-clock date."""
    ts = pd.Timestamp(date)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


@functools.lru_cache(maxsize=None)
def _read_index(path: str) -> tuple:
    with open(path) as f:
        index = json.load(f)
    snaps = sorted(index['snapshots'], key=lambda s: s['period_date'])
    dates = [s['period_date'] for s in snaps]
    if len(set(dates)) != len(dates):
        raise ValueError(f'{path}: more than one snapshot per period date')
    return tuple(snaps)


@functools.lru_cache(maxsize=None)
def _read_snapshot(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={'ticker': str, 'cusip': str, 'isin': str, 'name': str},
                        keep_default_na=False)
    frame['weight'] = frame['weight'].astype(float)
    return frame


@functools.lru_cache(maxsize=None)
def _read_map(path: str, column: str) -> tuple:
    with open(path, newline='') as f:
        return tuple((row['ticker'], row[column]) for row in csv.DictReader(f) if row['ticker'] and row[column])


class PITUniverse:
    """Point-in-time Russell 3000 membership from IWV's N-PORT holdings snapshots.

    A snapshot is in force from its report-period date (the date the holdings describe)
    until the next snapshot's period date: members_asof(d) uses the latest snapshot with
    period date <= d. IWV is a fund, not the index: it holds 2,580-2,900 equity positions
    per snapshot (2019-2025), not every constituent. Only N-PORT's quarter-end reports are
    public, so membership changes inside a quarter (IPO additions, M&A deletions) appear
    at the next quarter end.
    """

    def __init__(self, root: Union[str, os.PathLike, None] = None):
        self.root = pathlib.Path(root) if root is not None else REFERENCE_DIR
        self.universe_dir = self.root / 'universe'

    def _snapshots(self) -> tuple:
        path = self.universe_dir / 'index.json'
        if not path.exists():
            raise FileNotFoundError(f'{path} not found: build it with scripts/build_pit_universe.py')
        return _read_index(str(path))

    def snapshots(self) -> List[Dict]:
        """Every snapshot's index entry (period date, filing date, accession, counts), oldest first."""
        return [dict(s) for s in self._snapshots()]

    def _entry_asof(self, date: DateLike) -> Dict:
        when = _as_date(date)
        eligible = [s for s in self._snapshots() if pd.Timestamp(s['period_date']) <= when]
        if not eligible:
            first = self._snapshots()[0]['period_date'] if self._snapshots() else 'none'
            raise ValueError(f'no IWV snapshot on or before {when.date()} (first period date: {first})')
        return eligible[-1]

    def snapshot_asof(self, date: DateLike) -> pd.Timestamp:
        """Period date of the snapshot in force on `date` (raises ValueError before the first one)."""
        return pd.Timestamp(self._entry_asof(date)['period_date'])

    def holdings_asof(self, date: DateLike) -> pd.DataFrame:
        """The snapshot in force on `date`: one row per security (ticker blank when it has no usable ticker)."""
        entry = self._entry_asof(date)
        return _read_snapshot(str(self.universe_dir / entry['file'])).copy()

    def weights_asof(self, date: DateLike) -> pd.Series:
        """Value weight per mapped ticker on `date` (securities sharing a ticker are summed)."""
        frame = self.holdings_asof(date)
        frame = frame[frame['ticker'] != '']
        return frame.groupby('ticker')['weight'].sum().sort_index()

    def members_asof(self, date: DateLike) -> List[str]:
        """Sorted tickers of the index members on `date` (latest snapshot with period date <= date)."""
        return list(self.weights_asof(date).index)

    def coverage(self, symbols_with_prices: Iterable[str], date: DateLike) -> Dict:
        """How much of the membership on `date` a price universe covers.

        `missing_value_weight` is the index weight of mapped members without prices;
        `unmapped_value_weight` the weight of holdings without a usable ticker (no US listing
        found, or a last ticker that now belongs to another security).
        Together they are the survivorship gap of a study restricted to `symbols_with_prices`.
        """
        entry = self._entry_asof(date)
        frame = _read_snapshot(str(self.universe_dir / entry['file']))
        weights = frame[frame['ticker'] != ''].groupby('ticker')['weight'].sum()
        have = {normalise_ticker(s) for s in symbols_with_prices}
        missing = sorted(t for t in weights.index if t not in have)
        return {
            'snapshot': entry['period_date'],
            'members': int(len(weights)),
            'with_prices': int(len(weights) - len(missing)),
            'missing': len(missing),
            'missing_value_weight': float(weights.loc[missing].sum()),
            'unmapped_value_weight': float(frame.loc[frame['ticker'] == '', 'weight'].sum()),
            'missing_symbols': missing,
        }


def _map(root: Union[str, os.PathLike, None], filename: str, column: str) -> Dict[str, str]:
    path = (pathlib.Path(root) if root is not None else REFERENCE_DIR) / filename
    if not path.exists():
        raise FileNotFoundError(f'{path} not found: build it with scripts/build_reference_data.py')
    return dict(_read_map(str(path), column))


def industry_map(root: Union[str, os.PathLike, None] = None) -> Dict[str, str]:
    """Ticker -> Fama-French 49 industry short name (e.g. 'Banks', 'Chips'); unclassified tickers are absent."""
    return _map(root, 'industry_ff49.csv', 'ff49_name')


def sector_etf_map(root: Union[str, os.PathLike, None] = None) -> Dict[str, str]:
    """Ticker -> Select Sector SPDR (XLK, XLF, ...) from its FF49 industry and SIC; unmapped tickers are absent."""
    return _map(root, 'industry_ff49.csv', 'sector_etf')


def venue_map(root: Union[str, os.PathLike, None] = None) -> Dict[str, str]:
    """Ticker -> primary listing venue ('NYSE', 'Nasdaq', 'NYSE American', 'NYSE Arca', 'Cboe BZX', 'IEX')."""
    return _map(root, 'listing_venue.csv', 'venue')
