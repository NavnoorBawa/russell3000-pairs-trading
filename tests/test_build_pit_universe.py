"""scripts/build_pit_universe.py: N-PORT parsing, OpenFIGI ticker choice, offline rebuild.

Fixtures: tests/fixtures/nport/filings.atom (an EDGAR Atom feed: two NPORT-P filings, an
NPORT-P/A that amends the second, an N-CEN and a 2026 filing) and primary_doc.xml (an
N-PORT document with equity, cash-sweep and futures holdings, a repeated CUSIP, an
issuer reported by ISIN only and an escrow line without identifiers). No network.
"""
import hashlib
import importlib.util
import json
import os
import shutil

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(REPO, 'tests', 'fixtures', 'nport')


def _load():
    spec = importlib.util.spec_from_file_location('_script_build_pit_universe',
                                                  os.path.join(REPO, 'scripts', 'build_pit_universe.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b = _load()

FILINGS = {
    '0000000000-20-000001': '2020-03-31',
    '0000000000-20-000002': '2020-06-30',
    '0000000000-20-000003': '2020-06-30',   # NPORT-P/A: replaces -000002
    '0000000000-26-000004': '2026-03-31',   # sealed holdout: its XML is never cached
}


def _xml():
    with open(os.path.join(FIX, 'primary_doc.xml'), 'rb') as f:
        return f.read()


def _figi(*records, name='NAME', share_class=None):
    return {'data': [dict(zip(('ticker', 'exchCode'), r), figi=f'BBG{i:09d}', name=name, shareClassFIGI=share_class,
                          securityType='Common Stock') for i, r in enumerate(records)]}


def _resolve(result, id_type='ID_CUSIP', us_lines=None):
    return b.resolve_entry(result, id_type, us_lines or {}, '2026-10-20')


def _raw_cache(tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    shutil.copy(os.path.join(FIX, 'filings.atom'), raw / 'filings.atom')
    for acc, period in FILINGS.items():
        (raw / f'{acc}.hdr').write_text(f"<SEC-HEADER>\n<PERIOD>{period.replace('-', '')}\n"
                                        f"<SERIES-ID>S000004341\n</SEC-HEADER>\n")
        if period >= b.SEALED_FROM:
            continue
        (raw / f'{acc}.index.json').write_text(json.dumps(
            {'directory': {'item': [{'name': f'{acc}-index.html'}, {'name': 'primary_doc.xml'}]}}))
        body = _xml().replace(b'<repPdDate>2020-03-31', f'<repPdDate>{period}'.encode())
        if acc.endswith('3'):
            body = body.replace(b'<valUSD>500.00000000', b'<valUSD>800.00000000')
        (raw / f'{acc}.xml').write_bytes(body)
    return raw


def _map(out, with_all=True):
    out.mkdir(parents=True, exist_ok=True)
    entries = {'000000AA1': _resolve(_figi(('AAA', 'US'), ('AAA', 'UN')))}
    if with_all:
        entries['000000BB7'] = _resolve(_figi(('BBB/A', 'UN')))
        entries['CH0114405324'] = _resolve(_figi(('GRMN', 'US')), 'ID_ISIN')
    b.write_map(entries, out / 'cusip_ticker_map.json')


# --- parsing -----------------------------------------------------------------------------

def test_parse_nport_reads_period_series_and_every_holding():
    parsed = b.parse_nport(_xml())
    assert parsed['period_date'] == '2020-03-31' and parsed['series_id'] == 'S000004341'
    assert len(parsed['holdings']) == 7
    garmin = next(h for h in parsed['holdings'] if h['name'] == 'Garmin Ltd')
    assert garmin['cusip'] == '000000000' and garmin['isin'] == 'CH0114405324' and garmin['val_usd'] == 200.0


def test_equity_only_repeated_lines_summed_isin_fallback():
    sec = b.equity_securities(b.parse_nport(_xml())['holdings'])
    assert [s['name'] for s in sec] == ['Alpha Corp', 'Beta Inc', 'Garmin Ltd', 'ESCROW GAMMA RIGHTS']
    beta = sec[1]
    assert beta['id'] == '000000BB7' and beta['val_usd'] == 150.0           # two lines, one security
    assert (sec[2]['id'], sec[2]['id_type'], sec[2]['cusip']) == ('CH0114405324', 'ID_ISIN', '')
    assert sec[3]['id'] is None                                              # unmappable, still weighted


def test_security_id():
    assert b.security_id({'cusip': '037833100', 'isin': 'US0378331005'}) == ('037833100', 'ID_CUSIP')
    assert b.security_id({'cusip': '000000000', 'isin': 'IE00B6330302'}) == ('IE00B6330302', 'ID_ISIN')
    assert b.security_id({'cusip': 'N/A', 'isin': ''}) == (None, None)


def test_filing_list_and_header():
    with open(os.path.join(FIX, 'filings.atom'), 'rb') as f:
        filings = b.parse_filing_list(f.read())
    assert [f['accession'] for f in filings] == list(FILINGS)                          # by filing date
    assert {f['form'] for f in filings} == {'NPORT-P', 'NPORT-P/A'}                    # N-CEN dropped
    assert b.parse_header('<PERIOD>20251231\n<SERIES-ID>S000004341\n<SERIES-ID>S000004310\n') == \
        {'period_date': '2025-12-31', 'series': ['S000004310', 'S000004341']}
    assert b.primary_doc_name(json.dumps({'directory': {'item': [{'name': 'x.htm'}, {'name': 'primary_doc.xml'}]}})) \
        == 'primary_doc.xml'


def test_amendment_replaces_original_for_its_period():
    filings = [{'accession': a, 'period_date': p, 'filing_date': f'2020-0{i + 1}-01', 'form': 'NPORT-P'}
               for i, (a, p) in enumerate(FILINGS.items())]
    kept = b.latest_per_period(filings)
    assert [f['accession'] for f in kept] == ['0000000000-20-000001', '0000000000-20-000003', '0000000000-26-000004']
    assert kept[1]['supersedes'] == ['0000000000-20-000002']


# --- OpenFIGI ticker choice ------------------------------------------------------------------

@pytest.mark.parametrize('records, ticker', [
    ([('X1', 'UN'), ('X2', 'US')], 'X2'),                       # the US composite first
    ([('X1', 'UW'), ('X2', 'UN')], 'X2'),                       # then NYSE before Nasdaq GS
    ([('X1', 'UV'), ('X2', 'UR')], 'X2'),
    ([('ABCD', 'LN'), ('ABC', 'UF')], 'ABC'),                   # any other US venue
    ([('TWTRUSD', 'XS'), ('TWTR', 'SW'), ('TWTREUR', 'XS')], 'TWTR'),   # delisted: XS line less USD
    ([(None, 'US'), ('ABC', 'UN')], 'ABC'),
    ([('0QZB', 'LN'), ('TWTREUR', 'XS')], None),                # no US line at all
    ([('9990302D', 'UW'), ('APAUSD', 'XB')], 'APA'),            # Bloomberg placeholder skipped
    ([('CPE3USD', 'XB')], 'CPE'),                               # retired symbol, numbered
])
def test_choose_listing(records, ticker):
    pick = b.choose_listing(_figi(*records)['data'])
    assert (pick[1] if pick else None) == ticker


def test_resolve_active_line_normalises():
    e = _resolve(_figi(('BRK/B', 'US')))
    assert (e['status'], e['ticker'], e['figi_ticker'], e['exchCode']) == ('active', 'BRK-B', 'BRK/B', 'US')
    assert (e['figi'], e['matched_by'], e['mapped_on']) == ('BBG000000000', 'cusip', '2026-10-20')
    miss = _resolve({'warning': 'No identifier found.'}, 'ID_ISIN')
    assert (miss['status'], miss['ticker'], miss['note']) == ('unmapped', None, 'No identifier found.')


def _us(ticker, name='NAME', share_class=None):
    return {'ticker': ticker, 'exchCode': 'US', 'figi': f'BBG-{ticker}', 'name': name, 'shareClassFIGI': share_class}


def test_live_security_with_foreign_lines_only_is_recovered_by_share_class():
    # Exxon Mobil's CUSIP query returns no US line (observed 2026-10-20)
    xom = _figi(('EXMOC', 'CP'), ('XOMCHF', 'X1'), ('XOM', 'UZ'), name='EXXON MOBIL CORP', share_class='SC1')
    assert b.pending_tickers(xom) == ['EXMOC', 'XOM']
    e = _resolve(xom, us_lines={'XOM': [_us('XOM', 'EXXON MOBIL CORP', 'SC1')]})
    assert (e['status'], e['ticker'], e['figi'], e['matched_by']) == ('active', 'XOM', 'BBG-XOM', 'share class')
    hon = _figi(('HONGBP', 'X1'), ('HONEUR', 'X1'), name='HONEYWELL INTERNATIONAL INC')
    e = _resolve(hon, us_lines={'HON': [_us('HON', 'HONEYWELL INTERNATIONAL INC')]})
    assert (e['ticker'], e['matched_by']) == ('HON', 'name')
    # a candidate ticker that is another security is not accepted
    e = _resolve(hon, us_lines={'HON': [_us('HON', 'HONDA MOTOR CO', 'SC9')]})
    assert (e['status'], e['ticker']) == ('unmapped', None)
    # after a holding-company reorganisation the US line is a new share class of a renamed issuer
    e = _resolve(xom, us_lines={'XOM': [_us('XOM', 'EXXONMOBIL HOLDINGS CORP', 'SC7')]})
    assert (e['status'], e['ticker'], e['matched_by']) == ('active', 'XOM', 'name')


def test_issuer_key_drops_legal_form_but_keeps_share_class():
    assert b.issuer_key('EXXON MOBIL CORP') == b.issuer_key('EXXONMOBIL HOLDINGS CORP') == 'EXXONMOBIL'
    assert b.issuer_key('LINDE PLC/OLD') == b.issuer_key('Linde plc') == 'LINDE'
    assert b.issuer_key('ALPHABET INC-CL A') != b.issuer_key('ALPHABET INC-CL C')
    assert b.issuer_key('BARNES GROUP INC') != b.issuer_key('BARRICK MINING CORP')
    assert b.issuer_key(None) == ''


@pytest.mark.parametrize('old, new, same', [
    ('AMC ENTERTAINMENT HOLDINGS INC', 'AMC ENTERTAINMENT HLDS-CL A', True),   # abbreviated, class appended
    ('EXXON MOBIL CORP', 'EXXONMOBIL HOLDINGS CORP', True),
    ('BARNES GROUP INC', 'BARRICK MINING CORP', False),                        # ticker B reused
    ('VIACOM INC-CLASS A', 'VIA TRANSPORTATION INC', False),
    ('ALPHABET INC-CL A', 'ALPHABET INC-CL C', False),
    ('AMC', 'AMCOR PLC', False),
    ('RUBICON PROJECT INC/THE', 'RUBICO INC', False),                          # whole words only
    ('BUNGE LTD', 'BUNGE GLOBAL SA', True),                                    # re-domiciled
])
def test_same_security_by_name(old, new, same):
    assert b.same_security({'name': new, 'shareClassFIGI': 'NEW'}, _figi(('X', 'X1'), name=old)['data']) is same
    assert b.same_security({'name': 'Z', 'shareClassFIGI': 'SC'}, _figi(('X', 'X1'), name=old, share_class='SC')['data'])


def test_delisted_line_kept_continued_or_marked_reused():
    twtr = _figi(('TWTRUSD', 'XS'), ('TWTR', 'SW'), name='TWITTER INC', share_class='SC2')
    assert b.pending_tickers(twtr) == ['TWTR']
    e = _resolve(twtr)
    assert (e['status'], e['ticker']) == ('delisted', 'TWTR')              # no US security uses TWTR now
    barnes = _figi(('BUSD', 'XB'), name='BARNES GROUP INC', share_class='SC3')
    e = _resolve(barnes, us_lines={'B': [_us('B', 'BARRICK MINING CORP', 'SC4')]})
    assert (e['status'], e['ticker'], e['figi_ticker']) == ('reused', None, 'BUSD')
    assert 'B now trades as BARRICK MINING CORP' in e['note']
    blk = _figi(('BLKUSD', 'XB'), name='BLACKROCK INC', share_class='SC5')   # same issuer, new CUSIP
    e = _resolve(blk, us_lines={'BLK': [_us('BLK', 'BLACKROCK INC', 'SC6')]})
    assert (e['status'], e['ticker'], e['matched_by']) == ('active', 'BLK', 'name')
    assert b.pending_tickers(_figi(('AAPL', 'US'))) == []


def test_ticker_candidates():
    data = _figi(('XOMCHF', 'X1'), ('1XOMM', 'L1'), ('XOM', 'UZ'), ('BRK/B', 'EU'), ('BRK/BEUR', 'X1'))['data']
    assert b.ticker_candidates(data) == ['XOM', 'BRK/B']


def test_a_retired_numbered_currency_line_is_recovered():
    """Carnival's CUSIP after its 2026 reorganisation: OpenFIGI lists only the numbered
    currency lines CCL1USD / CCL1GBX on X1 (cached response); the US record of 'CCL' is the
    successor issuer. Through v33 the digit kept the line from being a candidate: unmapped."""
    ccl = _figi(('CCL1USD', 'X1'), ('CCL1GBX', 'X1'), name='CARNIVAL CORP')
    assert b.choose_listing(ccl['data']) is None
    assert b.ticker_candidates(ccl['data']) == ['CCL'] and b.pending_tickers(ccl) == ['CCL']
    e = _resolve(ccl, us_lines={'CCL': [_us('CCL', 'CARNIVAL CORP LTD', 'BBG001S5PL01')]})
    assert (e['status'], e['ticker'], e['matched_by']) == ('active', 'CCL', 'name')
    e = _resolve(ccl, us_lines={'CCL': [_us('CCL', 'CENTURY CASINOS', 'SC9')]})     # not the same issuer
    assert (e['status'], e['ticker']) == ('unmapped', None)


def test_query_openfigi_two_passes_cached_and_resumable(tmp_path, monkeypatch):
    bodies = []

    def fake_get(url, headers=None, data=None, **kw):
        jobs = json.loads(data)
        bodies.append((headers, jobs))
        out = []
        for j in jobs:
            letters = ''.join(chr(65 + int(c)) for c in j['idValue'][-3:]) if j['idType'] != 'TICKER' else None
            if j['idType'] == 'TICKER':
                out.append({'data': [_us(j['idValue'], 'NAME', 'SC')]})
            elif j['idValue'].endswith('10'):                               # foreign lines only
                out.append(_figi((letters + 'GBP', 'X1'), share_class='SC'))
            else:
                out.append(_figi((letters, 'US')))
        return json.dumps(out).encode()

    monkeypatch.setattr(b, 'http_get', fake_get)
    monkeypatch.setattr(b, 'RateLimiter', lambda interval: None)
    ids = [(f'{n:08d}0', 'ID_CUSIP') for n in range(23)]
    cache = tmp_path / 'responses.json'
    entries = {}
    b.query_openfigi(ids, entries, tmp_path / 'map.json', cache)
    assert [len(j) for _, j in bodies] == [10, 10, 3, 3]                   # no key: 10 jobs a request
    assert [j['idValue'] for j in bodies[-1][1]] == ['ABA', 'BBA', 'CBA']  # pass 2: exchCode-US lookups
    assert 'X-OPENFIGI-APIKEY' not in bodies[0][0]
    assert entries['000000220']['ticker'] == 'CCA'
    assert (entries['000000110']['ticker'], entries['000000110']['matched_by']) == ('BBA', 'share class')
    assert b.read_map(tmp_path / 'map.json') == entries
    bodies.clear()
    b.query_openfigi(ids, {}, tmp_path / 'map2.json', cache)
    assert bodies == []                                                     # everything cached
    b.query_openfigi(ids[:2], {}, tmp_path / 'map3.json', cache, api_key='k', refresh=True)
    assert [len(j) for _, j in bodies] == [2, 1] and bodies[0][0]['X-OPENFIGI-APIKEY'] == 'k'   # lookups refreshed too


# --- the whole build, offline ----------------------------------------------------------------

def test_offline_build_snapshots_index_and_sealed(tmp_path):
    raw, out = _raw_cache(tmp_path), tmp_path / 'out'
    _map(out)
    assert b.main(['--offline', '--raw-dir', str(raw), '--out-dir', str(out)]) == 0
    with open(out / 'index.json') as f:
        index = json.load(f)
    assert [s['period_date'] for s in index['snapshots']] == ['2020-03-31', '2020-06-30']
    assert [s['period_date'] for s in index['sealed']] == ['2026-03-31']
    assert not (out / 'iwv_2026-03-31.csv').exists()
    first, second = index['snapshots']
    assert (first['n_holdings'], first['n_equity'], first['n_mapped'], first['n_tickers']) == (7, 4, 3, 3)
    assert first['mapped_value_share'] == pytest.approx(850 / 900, abs=1e-6)
    assert first['source_url'] == ('https://www.sec.gov/Archives/edgar/data/1100663/000000000020000001/'
                                   'primary_doc.xml')
    assert first['sha256'] == hashlib.sha256((raw / '0000000000-20-000001.xml').read_bytes()).hexdigest()
    assert second['accession'] == '0000000000-20-000003' and second['supersedes'] == ['0000000000-20-000002']
    rows = (out / 'iwv_2020-03-31.csv').read_text().splitlines()
    assert rows[0] == 'ticker,cusip,isin,name,weight'
    assert [r.split(',')[0] for r in rows[1:]] == ['AAA', 'GRMN', 'BBB-A', '']     # by descending weight
    assert rows[1].endswith(',0.555555556') and rows[2].startswith('GRMN,,CH0114405324,')
    amended = (out / 'iwv_2020-06-30.csv').read_text().splitlines()
    assert amended[1].startswith('AAA,') and amended[1].endswith(f',{800 / 1200:.9g}')


def test_offline_build_is_deterministic_and_never_reads_sealed(tmp_path, monkeypatch):
    from pairs_trading.study_config import SealedError
    raw, out = _raw_cache(tmp_path), tmp_path / 'out'
    _map(out)
    b.main(['--offline', '--raw-dir', str(raw), '--out-dir', str(out)])
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    b.main(['--offline', '--raw-dir', str(raw), '--out-dir', str(out)])
    assert {p.name: p.read_bytes() for p in out.iterdir()} == first
    with pytest.raises(SealedError):                               # not before the pre-registration
        b.main(['--offline', '--include-sealed', '--raw-dir', str(raw), '--out-dir', str(out)])
    monkeypatch.setattr(b, 'assert_unsealed', lambda end: None)
    with pytest.raises(SystemExit, match='not cached'):           # the 2026 XML would be required
        b.main(['--offline', '--include-sealed', '--raw-dir', str(raw), '--out-dir', str(out)])


def _sealed_xml(raw):
    acc = '0000000000-26-000004'
    (raw / f'{acc}.index.json').write_text(json.dumps({'directory': {'item': [{'name': 'primary_doc.xml'}]}}))
    (raw / f'{acc}.xml').write_bytes(_xml().replace(b'<repPdDate>2020-03-31', b'<repPdDate>2026-03-31'))


def test_the_sealed_build_writes_outside_the_committed_tree(tmp_path, monkeypatch):
    """--sealed-out: committed snapshots copied unchanged, the sealed filing built from the
    accession listed at the freeze, reference/ untouched; refused while sealed."""
    from pairs_trading.study_config import SealedError
    raw, out, dest = _raw_cache(tmp_path), tmp_path / 'out', tmp_path / 'holdout' / 'universe'
    _map(out)
    b.main(['--offline', '--raw-dir', str(raw), '--out-dir', str(out)])
    _sealed_xml(raw)
    committed = {p.name: p.read_bytes() for p in out.iterdir()}
    args = ['--offline', '--include-sealed', '--sealed-out', str(dest), '--raw-dir', str(raw), '--out-dir', str(out)]
    with pytest.raises(SealedError):
        b.main(args)
    monkeypatch.setattr(b, 'assert_unsealed', lambda end: None)
    assert b.main(args) == 0
    assert {p.name: p.read_bytes() for p in out.iterdir()} == committed
    index = json.loads((dest / 'index.json').read_text())
    assert [s['period_date'] for s in index['snapshots']] == ['2020-03-31', '2020-06-30', '2026-03-31']
    assert index['sealed'] == [] and index['snapshots'][-1]['accession'] == '0000000000-26-000004'
    for name in ('iwv_2020-03-31.csv', 'iwv_2020-06-30.csv', 'cusip_ticker_map.json'):
        assert (dest / name).read_bytes() == committed[name]
    assert (dest / 'iwv_2026-03-31.csv').read_text().splitlines()[1].startswith('AAA,')
    from pairs_trading.universe import PITUniverse
    assert str(PITUniverse(dest.parent).snapshot_asof('2026-07-07').date()) == '2026-03-31'


def test_the_rehearsal_rebuilds_committed_snapshots_byte_for_byte(tmp_path):
    """--sealed-from/--through inside the development period: the committed snapshots in that
    window are rebuilt from their accessions and must equal the committed files."""
    raw, out, dest = _raw_cache(tmp_path), tmp_path / 'out', tmp_path / 'reh'
    _map(out)
    b.main(['--offline', '--raw-dir', str(raw), '--out-dir', str(out)])
    args = ['--offline', '--include-sealed', '--sealed-out', str(dest), '--sealed-from', '2020-06-01',
            '--through', '2020-12-31', '--raw-dir', str(raw), '--out-dir', str(out)]
    assert b.main(args) == 0
    assert (dest / 'iwv_2020-06-30.csv').read_bytes() == (out / 'iwv_2020-06-30.csv').read_bytes()
    assert not (dest / 'iwv_2026-03-31.csv').exists()
    rows = (out / 'iwv_2020-06-30.csv').read_text().replace('AAA,', 'AAB,')
    (out / 'iwv_2020-06-30.csv').write_text(rows)
    with pytest.raises(SystemExit, match='differ'):
        b.main(args)


def test_online_build_queries_only_unmapped_identifiers(tmp_path, monkeypatch):
    raw, out = _raw_cache(tmp_path), tmp_path / 'out'
    _map(out, with_all=False)
    with open(os.path.join(FIX, 'filings.atom'), 'rb') as f:
        atom = f.read()

    def sec_get(url):
        assert url == b.FILINGS_URL, url                          # everything else is cached
        return atom

    asked = []

    def query(jobs, entries, map_path, response_cache, api_key=None, refresh=False):
        asked.append((list(jobs), refresh))
        for sid, id_type in jobs:
            entries[sid] = _resolve({'warning': 'No identifier found.'}, id_type)
        b.write_map(entries, map_path)

    monkeypatch.setattr(b, 'sec_get', sec_get)
    monkeypatch.setattr(b, 'query_openfigi', query)
    args = ['--raw-dir', str(raw), '--out-dir', str(out), '--openfigi-cache', str(tmp_path / 'figi.json')]
    b.main(args)
    assert asked == [([('000000BB7', 'ID_CUSIP'), ('CH0114405324', 'ID_ISIN')], False)]
    b.main(args)
    assert len(asked) == 1                                        # failures are cached too
    b.main(['--remap-missing'] + args)
    assert asked[-1] == ([('000000BB7', 'ID_CUSIP'), ('CH0114405324', 'ID_ISIN')], True)
