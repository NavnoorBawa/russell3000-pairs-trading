"""scripts/build_reference_data.py: SIC -> Fama-French 49 -> sector ETF, listing venues.

Fixtures: tests/fixtures/reference_sources/ (an excerpt of French's Siccodes49.txt and a
Nasdaq Trader nasdaqtraded.txt sample, both in their real layout). The offline build
runs on a synthetic 49-industry definition and cached EDGAR answers. No network.
"""
import csv
import hashlib
import importlib.util
import io
import json
import os
import zipfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(REPO, 'tests', 'fixtures', 'reference_sources')
SPDRS = {'XLK', 'XLC', 'XLF', 'XLV', 'XLY', 'XLP', 'XLE', 'XLI', 'XLB', 'XLU', 'XLRE'}


def _load():
    spec = importlib.util.spec_from_file_location('_script_build_reference_data',
                                                  os.path.join(REPO, 'scripts', 'build_reference_data.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b = _load()


def _read(name):
    with open(os.path.join(FIX, name), newline='') as f:
        return f.read()


@pytest.fixture
def sic49():
    return b.parse_siccodes(_read('Siccodes_excerpt.txt'))


def test_parse_siccodes(sic49):
    ranges, names = sic49
    assert names == {1: ('Agric', 'Agriculture'), 36: ('Softw', 'Computer Software'),
                     48: ('Fin', 'Trading'), 49: ('Other', 'Almost Nothing')}
    assert (7370, 7372, 36, 'Softw') in ranges and (2048, 2048, 1, 'Agric') in ranges
    assert len(ranges) == 8


def test_ff49_assignment(sic49):
    ranges, names = sic49
    assert b.ff49_of(7372, ranges, names) == (36, 'Softw')
    assert b.ff49_of(6798, ranges, names) == (48, 'Fin')
    assert b.ff49_of(4955, ranges, names) == (49, 'Other')
    assert b.ff49_of(9999, ranges, names) == (49, 'Other')      # unlisted SIC: French's catch-all
    assert b.ff49_of(0, ranges, names) is None and b.ff49_of(None, ranges, names) is None


def test_sector_etf_table_and_overrides():
    assert len(b.FF49_SECTOR_ETF) == 49
    assert {v for v in b.FF49_SECTOR_ETF.values() if v} == SPDRS
    assert all(etf in SPDRS for _, _, etf in b.SECTOR_ETF_SIC_OVERRIDES)
    assert b.sector_etf(6211, 'Fin') == 'XLF'
    assert b.sector_etf(6798, 'Fin') == 'XLRE'                  # REITs: GICS Real Estate
    assert b.sector_etf(6324, 'Insur') == 'XLV'                 # managed care
    assert b.sector_etf(1531, 'Cnstr') == 'XLY'                 # homebuilders
    assert b.sector_etf(1623, 'Cnstr') == 'XLI'
    assert b.sector_etf(4955, 'Other') == 'XLI'
    assert b.sector_etf(9995, 'Other') is None                  # catch-all without a sector
    assert b.sector_etf(None, None) is None
    assert b.sector_etf(5122, 'Whlsl') == 'XLV'                 # drug wholesalers (McKesson, Cencora, Cardinal)
    assert b.sector_etf(5141, 'Whlsl') == 'XLP' and b.sector_etf(5065, 'Whlsl') == 'XLI'
    assert b.sector_etf(7370, 'Softw') == 'XLC'                 # Alphabet, Meta
    assert b.sector_etf(7372, 'Softw') == 'XLK'
    assert b.sector_etf(7389, 'BusSv') == 'XLF' and b.sector_etf(7374, 'BusSv') == 'XLI'
    assert b.sector_etf(8731, 'BusSv') == 'XLV'                 # contract research organisations
    spans = sorted((lo, hi) for lo, hi, _ in b.SECTOR_ETF_SIC_OVERRIDES)
    assert all(lo <= hi for lo, hi in spans)
    assert all(prev_hi < lo for (_, prev_hi), (lo, _) in zip(spans, spans[1:]))   # disjoint: order is irrelevant


def test_parse_nasdaq_traded():
    rows, as_of = b.parse_nasdaq_traded(_read('nasdaqtraded.txt'))
    assert as_of == '2026-10-20'
    by = {r['ticker']: r for r in rows}
    assert 'ZXIET' not in by and 'MTEST' not in by               # test issues
    assert by['BF-B']['venue'] == 'NYSE'                         # BF.B -> Yahoo's BF-B
    assert by['AAPL']['venue'] == 'Nasdaq' and by['SEB']['venue'] == 'NYSE American'
    assert by['XLK'] == {'ticker': 'XLK', 'venue': 'NYSE Arca', 'etf_flag': True}
    assert by['CBOE1']['venue'] == 'Cboe BZX' and by['IEXA']['venue'] == 'IEX' and by['DDS']['venue'] == 'TXSE'
    assert [r['ticker'] for r in rows] == sorted(by)


def test_industry_rows_leave_unknown_tickers_blank(sic49):
    ranges, names = sic49
    rows = b.industry_rows(['MSFT', 'GONE'], {'MSFT': 789019},
                           {'789019': {'sic': 7372, 'entityType': 'operating'}}, ranges, names)
    assert rows[0] == {'ticker': 'MSFT', 'cik': 789019, 'sic': 7372, 'ff49': 36, 'ff49_name': 'Softw',
                       'sector_etf': 'XLK', 'entity_type': 'operating'}
    assert rows[1] == {'ticker': 'GONE', 'cik': '', 'sic': '', 'ff49': '', 'ff49_name': '', 'sector_etf': '',
                       'entity_type': ''}


def _synthetic_siccodes():
    """49 industries named as FF49_SECTOR_ETF, industry k owning SIC range k*100..k*100+99."""
    lines = []
    for k, short in enumerate(b.FF49_SECTOR_ETF, start=1):
        lines += [f'{k:2d} {short:<6} Industry {k}', f'          {k * 100:04d}-{k * 100 + 99:04d} Range {k}', '']
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('Siccodes49.txt', '\r\n'.join(lines))
    return buf.getvalue()


def test_offline_build(tmp_path):
    raw, ref = tmp_path / 'raw', tmp_path / 'reference'
    (raw / 'french').mkdir(parents=True)
    (raw / 'sec').mkdir()
    (raw / 'nasdaqtrader').mkdir()
    (raw / 'french' / 'Siccodes49.zip').write_bytes(_synthetic_siccodes())
    (raw / 'sec' / 'company_tickers.json').write_text(json.dumps({
        '0': {'cik_str': 1, 'ticker': 'AAA', 'title': 'A'},
        '1': {'cik_str': 2, 'ticker': 'BRK-B', 'title': 'B'},
        '2': {'cik_str': 3, 'ticker': 'NOTUSED', 'title': 'N'}}))
    (raw / 'sec' / 'submissions_summary.json').write_text(json.dumps({
        '1': {'sic': 4501, 'entityType': 'operating'},          # industry 45 (Banks) in the synthetic file
        '2': {'sic': 4699, 'entityType': 'operating'}}))        # industry 46 (Insur)
    (raw / 'nasdaqtrader' / 'nasdaqtraded.txt').write_text(_read('nasdaqtraded.txt'))
    (ref / 'universe').mkdir(parents=True)
    (ref / 'universe' / 'iwv_2020-03-31.csv').write_text('ticker,cusip,isin,name,weight\nAAA,1,,A,0.6\n,2,,X,0.4\n')
    (tmp_path / 'marketcap.csv').write_text('Symbol,Name\nBRK.B,Berkshire\nZZZ,Delisted\n')
    assert b.main(['--offline', '--raw-dir', str(raw), '--reference-dir', str(ref),
                   '--marketcap', str(tmp_path / 'marketcap.csv')]) == 0
    with open(ref / 'industry_ff49.csv', newline='') as f:
        rows = list(csv.DictReader(f))
    assert [r['ticker'] for r in rows] == ['AAA', 'BRK-B', 'ZZZ']
    assert (rows[0]['ff49'], rows[0]['ff49_name'], rows[0]['sector_etf']) == ('45', 'Banks', 'XLF')
    assert (rows[1]['cik'], rows[1]['ff49_name']) == ('2', 'Insur')
    assert rows[2]['cik'] == '' and rows[2]['ff49'] == ''
    with open(ref / 'listing_venue.csv', newline='') as f:
        venues = list(csv.DictReader(f))
    assert venues[0] == {'ticker': 'A', 'venue': 'NYSE', 'etf_flag': 'N', 'as_of': '2026-10-20'}


def test_a_missing_marketcap_file_stops_the_build(tmp_path, capsys):
    """industry_ff49.csv also covers the v32 universe file; without it the table would
    silently lose its tickers, so the build stops unless --no-marketcap says so."""
    raw, ref = tmp_path / 'raw', tmp_path / 'reference'
    (raw / 'french').mkdir(parents=True)
    (raw / 'sec').mkdir()
    (raw / 'nasdaqtrader').mkdir()
    (raw / 'french' / 'Siccodes49.zip').write_bytes(_synthetic_siccodes())
    (raw / 'sec' / 'company_tickers.json').write_text(json.dumps({'0': {'cik_str': 1, 'ticker': 'AAA', 'title': 'A'}}))
    (raw / 'sec' / 'submissions_summary.json').write_text(json.dumps({'1': {'sic': 4501, 'entityType': 'operating'}}))
    (raw / 'nasdaqtrader' / 'nasdaqtraded.txt').write_text(_read('nasdaqtraded.txt'))
    (ref / 'universe').mkdir(parents=True)
    (ref / 'universe' / 'iwv_2020-03-31.csv').write_text('ticker,cusip,isin,name,weight,price\nAAA,1,,A,1,10\n')
    base = ['--offline', '--raw-dir', str(raw), '--reference-dir', str(ref)]
    with pytest.raises(SystemExit, match='not found'):
        b.main(base + ['--marketcap', str(tmp_path / 'missing.csv')])
    assert not (ref / 'industry_ff49.csv').exists()
    assert b.main(base + ['--no-marketcap']) == 0
    assert (ref / 'industry_ff49.csv').read_text().splitlines()[1].startswith('AAA,1,4501,')
    (tmp_path / 'marketcap.csv').write_text('Symbol,Name\nAAA,A\nZZZ,Z\n')
    capsys.readouterr()
    assert b.main(base + ['--marketcap', str(tmp_path / 'marketcap.csv')]) == 0
    digest = hashlib.sha256((tmp_path / 'marketcap.csv').read_bytes()).hexdigest()
    assert f'(sha256 {digest}, 2 tickers)' in capsys.readouterr().out


def test_offline_build_refuses_missing_cache(tmp_path):
    with pytest.raises(SystemExit, match='not cached'):
        b.main(['--offline', '--raw-dir', str(tmp_path), '--reference-dir', str(tmp_path / 'ref')])
