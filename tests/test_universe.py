"""pairs_trading/universe.py: point-in-time membership and the reference-table loaders.

Fixture: tests/fixtures/reference/ (two snapshots, listed out of order in index.json; the
first holds two Berkshire share-class CUSIPs that both map to BRK-B and one unmapped
holding). The last tests check the committed reference/ files themselves.
"""
import csv
import json
import math
import os

import pandas as pd
import pytest

from pairs_trading.universe import (REFERENCE_DIR, PITUniverse, industry_map, normalise_ticker,
                                    sector_etf_map, venue_map)

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'reference')


@pytest.fixture
def uni():
    return PITUniverse(FIX)


def test_snapshots_sorted_by_period(uni):
    assert [s['period_date'] for s in uni.snapshots()] == ['2020-03-31', '2020-06-30']


def test_members_use_latest_period_on_or_before_date(uni):
    first = ['AAA', 'BRK-B', 'CCC']
    second = ['AAA', 'DDD']
    assert uni.members_asof('2020-03-31') == first           # in force on its own period date
    assert uni.members_asof('2020-06-29') == first           # not the next one a day early
    assert uni.members_asof('2020-06-30') == second
    assert uni.members_asof(pd.Timestamp('2025-12-31')) == second
    assert uni.snapshot_asof('2020-05-15') == pd.Timestamp('2020-03-31')
    assert uni.snapshot_asof('2020-07-01') == pd.Timestamp('2020-06-30')


def test_no_snapshot_before_the_first_period(uni):
    with pytest.raises(ValueError, match='no IWV snapshot on or before 2020-03-30'):
        uni.members_asof('2020-03-30')
    with pytest.raises(ValueError):
        uni.snapshot_asof('2019-01-01')


def test_tz_aware_dates_use_their_local_calendar_date(uni):
    # the price cache indexes bars at local midnight, America/New_York
    assert uni.members_asof(pd.Timestamp('2020-06-30', tz='America/New_York')) == ['AAA', 'DDD']
    assert uni.members_asof(pd.Timestamp('2020-06-29 23:00', tz='America/New_York')) == ['AAA', 'BRK-B', 'CCC']


def test_members_sorted_unique_and_mapped_only(uni):
    w = uni.weights_asof('2020-04-01')
    assert list(w.index) == ['AAA', 'BRK-B', 'CCC']
    assert w['BRK-B'] == pytest.approx(0.3)                  # two share-class CUSIPs, one ticker
    assert w.sum() == pytest.approx(0.95)                    # the unmapped 5% is not a member
    assert len(uni.holdings_asof('2020-04-01')) == 5


def test_coverage(uni):
    cov = uni.coverage(['aaa', 'brk.b', 'ZZZ'], '2020-04-01')
    assert cov['snapshot'] == '2020-03-31'
    assert (cov['members'], cov['with_prices'], cov['missing']) == (3, 2, 1)
    assert cov['missing_symbols'] == ['CCC']
    assert cov['missing_value_weight'] == pytest.approx(0.15)
    assert cov['unmapped_value_weight'] == pytest.approx(0.05)
    assert cov['snapshot_filed'] == '2020-06-01'
    assert cov['missing_heaviest'] == [['CCC', pytest.approx(0.15)]]
    assert cov['unmapped_heaviest'] == [['ESCROW SHARES', pytest.approx(0.05)]]


def test_results_are_copies(uni):
    uni.snapshots()[0]['period_date'] = '1999-01-01'
    held = uni.holdings_asof('2020-04-01')
    held.loc[0, 'ticker'] = 'XXX'
    industry_map(FIX)['AAA'] = 'Fun'
    assert uni.snapshots()[0]['period_date'] == '2020-03-31'
    assert uni.members_asof('2020-04-01') == ['AAA', 'BRK-B', 'CCC']
    assert industry_map(FIX)['AAA'] == 'Banks'


def test_reference_maps(uni):
    assert industry_map(FIX) == {'AAA': 'Banks', 'BRK-B': 'Insur', 'CCC': 'Chips', 'EEE': 'Other'}
    assert sector_etf_map(FIX) == {'AAA': 'XLF', 'BRK-B': 'XLF', 'CCC': 'XLK'}
    assert venue_map(FIX) == {'AAA': 'NYSE', 'CCC': 'Nasdaq', 'XLK': 'NYSE Arca'}


def test_missing_reference_files_fail_clearly(tmp_path):
    with pytest.raises(FileNotFoundError, match='build_pit_universe.py'):
        PITUniverse(tmp_path).members_asof('2021-01-01')
    with pytest.raises(FileNotFoundError, match='build_reference_data.py'):
        industry_map(tmp_path)


def test_normalise_ticker():
    assert normalise_ticker(' brk/b ') == 'BRK-B'
    assert normalise_ticker('BF.B') == 'BF-B'
    assert normalise_ticker(None) == ''


def test_traded_prices_one_per_ticker_and_snapshot(tmp_path):
    (tmp_path / 'universe').mkdir()
    snaps = {'2020-03-31': 'ticker,cusip,isin,name,weight,price\n'
                           'AAA,000000AA1,,Alpha,0.5,10.5\nBRK-B,084670702,,B,0.2,200\nBRK-B,084670108,,B,0.1,300000\n'
                           'CCC,000000CC9,,Gamma,0.15,\n,,,ESCROW,0.05,1\n',
             '2020-06-30': 'ticker,cusip,isin,name,weight\nAAA,000000AA1,,Alpha,1\n',     # written without prices
             '2020-09-30': 'ticker,cusip,isin,name,weight,price\nAAA,000000AA1,,Alpha,1,12\n'}
    for period, text in snaps.items():
        (tmp_path / 'universe' / f'iwv_{period}.csv').write_text(text)
    (tmp_path / 'universe' / 'index.json').write_text(json.dumps({'snapshots': [
        {'period_date': p, 'file': f'iwv_{p}.csv'} for p in snaps]}))
    traded = PITUniverse(tmp_path).traded_prices()
    assert traded.values.tolist() == [[pd.Timestamp('2020-03-31'), 'AAA', 10.5], [pd.Timestamp('2020-09-30'), 'AAA', 12.0]]


# --- the committed reference data ------------------------------------------------------

committed = pytest.mark.skipif(not (REFERENCE_DIR / 'universe' / 'index.json').exists(),
                               reason='reference/universe not built')


@committed
def test_committed_snapshots_are_consistent_and_none_is_sealed():
    with open(REFERENCE_DIR / 'universe' / 'index.json') as f:
        index = json.load(f)
    with open(REFERENCE_DIR / 'universe' / 'cusip_ticker_map.json') as f:
        entries = json.load(f)['entries']
    assert not [k for k, e in entries.items() if e['status'] in ('reused', 'unmapped') and e['ticker']]
    successions = index['successions']
    for old, link in successions.items():                   # same issuer number, successor's own ticker
        assert old[:6] == link['successor'][:6] and entries.get(old, {}).get('status') != 'active'
        assert link['ticker'] == (successions.get(link['successor']) or entries[link['successor']])['ticker']
    snaps = index['snapshots']
    assert snaps and [s['period_date'] for s in snaps] == sorted(s['period_date'] for s in snaps)
    for s in snaps:
        # 2026 is the pre-registered holdout: a 2026 snapshot carries 2026 market values
        assert s['period_date'] < index['sealed_from'] == '2026-01-01'
        with open(REFERENCE_DIR / 'universe' / s['file'], newline='') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == s['n_equity']
        assert math.isclose(sum(float(r['weight']) for r in rows), 1.0, abs_tol=1e-6)
        mapped = sum(float(r['weight']) for r in rows if r['ticker'])
        assert mapped == pytest.approx(s['mapped_value_share'], abs=1e-5)
        assert sum(1 for r in rows if r['ticker']) == s['n_mapped']
        assert all(r['ticker'] == normalise_ticker(r['ticker']) for r in rows)
        for r in rows:                                       # every ticker comes from the map or a succession
            sid = r['cusip'] or r['isin']
            want = successions[sid]['ticker'] if sid in successions else (entries.get(sid) or {}).get('ticker')
            assert r['ticker'] == (want or ''), (s['file'], sid)


@committed
def test_committed_universe_loads():
    uni = PITUniverse()
    last = uni.snapshots()[-1]['period_date']
    members = uni.members_asof(last)
    assert len(members) > 2000 and members == sorted(set(members))
    assert {'AAPL', 'MSFT', 'JPM'} <= set(members)


@committed
def test_committed_universe_keeps_members_whose_cusip_changed():
    # OpenFIGI no longer resolves these identifiers (re-domiciliation, reverse split,
    # holding-company reorganisation); N-PORT's reported ticker or the issuer's successor
    # CUSIP recovers them, so the formation universe is not missing them
    uni = PITUniverse()
    assert {'LIN', 'COO', 'CCL', 'AMC', 'LCID'} <= set(uni.members_asof('2022-12-31'))
    assert 'GE' in uni.members_asof('2020-12-31')


@committed
def test_committed_map_respects_the_price_check():
    # Every mapping the 2026-10-20 rebuild changed was checked against N-PORT's own value
    # per share (reference/README.md). The rejected ones carry no ticker, and no snapshot
    # joins a security to a ticker that another holding is the own US line of.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'build_pit_universe', REFERENCE_DIR.parent / 'scripts' / 'build_pit_universe.py')
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    with open(REFERENCE_DIR / 'universe' / 'cusip_ticker_map.json') as f:
        entries = json.load(f)['entries']
    for sid, (ticker, _) in b.REJECTED_MAPPINGS.items():
        if sid in b.ACCEPTED_MAPPINGS:                      # denied one ticker, given another
            assert entries[sid]['ticker'] == b.ACCEPTED_MAPPINGS[sid][0] != ticker, sid
            continue
        assert (entries[sid]['status'], entries[sid]['ticker']) == ('reused', None), sid
        assert entries[sid]['note'].startswith(f'{ticker} is '), sid
    for sid, (ticker, _) in b.ACCEPTED_MAPPINGS.items():    # none taken away by the shared-ticker rule
        assert (entries[sid]['ticker'], entries[sid]['matched_by']) == (ticker, 'price check'), sid
        assert entries[sid]['note'].startswith(f'{ticker}: '), sid
    with open(REFERENCE_DIR / 'universe' / 'index.json') as f:
        index = json.load(f)
    for s in index['snapshots']:
        with open(REFERENCE_DIR / 'universe' / s['file'], newline='') as f:
            rows = [r for r in csv.DictReader(f) if r['ticker'] in s.get('shared_tickers', ())]
        for t in {r['ticker'] for r in rows}:
            own = [r for r in rows if r['ticker'] == t
                   and (entries.get(r['cusip'] or r['isin']) or {}).get('matched_by') in ('cusip', 'isin')
                   and entries[r['cusip'] or r['isin']]['status'] == 'active']
            assert not own or len(own) == sum(r['ticker'] == t for r in rows), (s['file'], t)
    uni = PITUniverse()
    held = uni.holdings_asof('2020-12-31').set_index('cusip')['ticker']
    assert (held['78645L100'], held['45031U101']) == ('', 'SAFE')    # SAFE's history before 2023 is iStar's
    assert 'OABI' in uni.members_asof('2022-12-31')           # the common stock, not its earnout shares
    # the price check's accepted mappings: securities whose history sits under a later line
    assert {'RTX', 'AON', 'TFC', 'TT'} <= set(uni.members_asof('2019-09-30'))
    assert {'LH', 'CPAY', 'HHH'} <= set(uni.members_asof('2022-12-31'))


@committed
def test_committed_snapshots_carry_the_traded_price():
    """N-PORT's value per share on the period date, which anchors Close_PIT
    (data_processor.anchor_point_in_time)."""
    uni = PITUniverse()
    for s in uni.snapshots():
        frame = uni.holdings_asof(s['period_date'])
        price = pd.to_numeric(frame['price'], errors='coerce')
        mapped = frame['ticker'] != ''
        assert (price[mapped].notna() * frame.loc[mapped, 'weight']).sum() > 0.999 * frame.loc[mapped, 'weight'].sum()
    traded = uni.traded_prices()
    apple = traded[traded['ticker'] == 'AAPL'].set_index('period_date')['price']
    assert len(apple) == len(uni.snapshots()) and 200 < apple[pd.Timestamp('2025-12-31')] < 300
