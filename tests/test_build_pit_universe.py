"""scripts/build_pit_universe.py: N-PORT parsing, OpenFIGI ticker choice, offline rebuild.

Fixtures: tests/fixtures/nport/filings.atom (an EDGAR Atom feed: two NPORT-P filings, an
NPORT-P/A that amends the second, an N-CEN and a 2026 filing) and primary_doc.xml (an
N-PORT document with equity, cash-sweep and futures holdings, a repeated CUSIP whose
second line alone reports a ticker, an issuer reported by ISIN only with a numeric
"ticker", an escrow line without identifiers, and a future whose reference instrument
carries identifiers of its own). No network.
"""
import argparse
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


def _resolve(result, id_type='ID_CUSIP', us_lines=None, reported='', names=()):
    return b.resolve_entry(result, id_type, us_lines or {}, '2026-10-20', reported, names)


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
    future = parsed['holdings'][-1]
    assert (future['ticker'], future['isin']) == ('RTYH0', '')     # not the reference index's identifiers
    assert parsed['holdings'][0]['ticker'] == 'AAA' and parsed['holdings'][1]['ticker'] == ''


def test_reported_ticker_keeps_only_tickers():
    assert b.reported_ticker({'ticker': 'BRK/B'}) == 'BRK/B'
    assert b.reported_ticker({'ticker': ' lin '}) == 'LIN'
    for junk in ('2258480', '2512042D', 'GFF.NY', 'SAFE-W', 'SEG-R-W', '', None):
        assert b.reported_ticker({'ticker': junk}) == ''


def test_equity_only_repeated_lines_summed_isin_fallback():
    sec = b.equity_securities(b.parse_nport(_xml())['holdings'])
    assert [s['name'] for s in sec] == ['Alpha Corp', 'Beta Inc', 'Garmin Ltd', 'ESCROW GAMMA RIGHTS']
    beta = sec[1]
    assert beta['id'] == '000000BB7' and beta['val_usd'] == 150.0           # two lines, one security
    assert [s['reported_ticker'] for s in sec] == ['AAA', 'BBB/A', '', '']   # from either line; no numerics
    assert (sec[2]['id'], sec[2]['id_type'], sec[2]['cusip']) == ('CH0114405324', 'ID_ISIN', '')
    assert sec[3]['id'] is None                                              # unmappable, still weighted
    assert [s['shares'] for s in sec] == [100.0, 15.0, 2.0, 7.0]
    lines = b.parse_nport(_xml())['holdings']
    lines[2] = dict(lines[2], units='PA')                                    # not a share count: no price
    assert b.equity_securities(lines)[1]['shares'] is None
    assert b.snapshot_rows(b.equity_securities(lines), {})[2]['price'] is None


def test_security_id():
    assert b.security_id({'cusip': '037833100', 'isin': 'US0378331005'}) == ('037833100', 'ID_CUSIP')
    assert b.security_id({'cusip': '000000000', 'isin': 'IE00B6330302'}) == ('IE00B6330302', 'ID_ISIN')
    assert b.security_id({'cusip': 'N/A', 'isin': ''}) == (None, None)
    # BlackRock's placeholders for a CVR and an escrow claim (booked under the target's ticker)
    assert b.security_id({'cusip': '457CVR017', 'isin': 'US457CVR0178'}) == (None, None)
    assert b.security_id({'cusip': '000000000', 'isin': 'US361ESC0496'}) == (None, None)
    assert b.security_id({'cusip': '12662P108', 'isin': 'US12662P1084'}) == ('12662P108', 'ID_CUSIP')   # CVR Energy


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


def test_same_security_tolerates_cut_off_names():
    def same(new, old):
        return b.same_security({'name': new, 'shareClassFIGI': 'NEW'}, [{'name': old}])
    assert same('EASTERLY GOVERNMENT PROPERTI', 'Easterly Government Properties Inc')   # Bloomberg's 28
    assert same('OFFICE PROPERTIES INCOME TRUST', 'Office Properties Income Tru')
    assert not same('EASTERLY GOVERNMENT PROPERTI', 'Easterly Government Services Inc')  # cut, other word
    assert not same('EASTERLY GOVERNMENT PROPS', 'Easterly Government Properties Inc')  # short: not cut
    assert not same('RUBICO INC', 'RUBICON PROJECT INC/THE')


@pytest.mark.parametrize('old, new, same', [
    ('AMC ENTERTAINMENT HOLDINGS INC', 'AMC ENTERTAINMENT HLDS-CL A', True),   # abbreviated, class appended
    ('EXXON MOBIL CORP', 'EXXONMOBIL HOLDINGS CORP', True),
    ('BARNES GROUP INC', 'BARRICK MINING CORP', False),                        # ticker B reused
    ('VIACOM INC-CLASS A', 'VIA TRANSPORTATION INC', False),
    ('ALPHABET INC-CL A', 'ALPHABET INC-CL C', False),
    ('AMC', 'AMCOR PLC', False),
    ('RUBICON PROJECT INC/THE', 'RUBICO INC', False),                          # whole words only
    ('BUNGE LTD', 'BUNGE GLOBAL SA', True),                                    # re-domiciled
    ('Metals Acquisition Ltd', 'METALS ACQUISITION II-CL A', False),           # the sponsor's next SPAC
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


def test_reported_ticker_resolves_what_openfigi_cannot():
    # Cooper's pre-split CUSIP is unknown to OpenFIGI; N-PORT reported COO
    e = _resolve({'warning': 'No identifier found.'}, us_lines={'COO': [_us('COO', 'COOPER COS INC/THE', 'SC9')]},
                 reported='COO', names=('Cooper Cos Inc/The',))
    assert (e['status'], e['ticker'], e['matched_by'], e['figi']) == ('active', 'COO', 'reported ticker', 'BBG-COO')
    # without N-PORT's issuer name nothing confirms the US record
    e = _resolve({'warning': 'No identifier found.'}, us_lines={'COO': [_us('COO', 'COOPER COS INC/THE', 'SC9')]},
                 reported='COO')
    assert (e['status'], e['ticker']) == ('reused', None)
    # Lucid's pre-split CUSIP: OpenFIGI's only line is the SPAC's frozen CCIVUSD
    lucid = _figi(('CCIVUSD', 'XS'), name='LUCID GROUP INC', share_class='SC1')
    assert b.pending_tickers(lucid, 'LCID') == ['CCIV', 'LCID'] and b.pending_tickers(lucid, 'CCIV') == ['CCIV']
    e = _resolve(lucid, us_lines={'LCID': [_us('LCID', 'LUCID GROUP INC', 'SC2')]}, reported='LCID')
    assert (e['status'], e['ticker'], e['matched_by']) == ('active', 'LCID', 'reported ticker')
    assert _resolve(lucid)['ticker'] == 'CCIV'                              # what OpenFIGI alone gives
    # a reported ticker no US security uses now is kept as the last ticker
    ea = _figi(('EA*', 'MM'), ('ERTSEUR', 'X1'), name='ELECTRONIC ARTS INC')
    e = _resolve(ea, reported='EA', names=('Electronic Arts Inc',))
    assert (e['status'], e['ticker'], e['matched_by']) == ('delisted', 'EA', 'reported ticker')
    assert 'as reported in N-PORT' in e['note']
    # ... unless another security has it now
    e = _resolve(_figi(('DOCUSD', 'XS'), name='PHYSICIANS REALTY TRUST'), reported='DOCX',
                 us_lines={'DOCX': [_us('DOCX', 'HEALTHPEAK PROPERTIES INC', 'SC3')]})
    assert (e['status'], e['ticker']) == ('reused', None) and 'OpenFIGI\'s delisted line reads DOCUSD' in e['note']


def test_reported_ticker_never_overrides_an_answer_openfigi_settles():
    # an active US line wins (Madison Square Garden Entertainment is Sphere Entertainment now)
    e = _resolve(_figi(('SPHR', 'US'), name='SPHERE ENTERTAINMENT CO'), reported='MSGE',
                 us_lines={'MSGE': [_us('MSGE', 'MADISON SQUARE GARDEN ENTERT', 'SC4')]})
    assert (e['ticker'], e['matched_by']) == ('SPHR', 'cusip')
    assert b.pending_tickers(_figi(('SPHR', 'US')), 'MSGE') == []
    # a delisted line under the reported ticker, and a reused one, stay as they are
    twtr = _figi(('TWTRUSD', 'XS'), name='TWITTER INC')
    assert _resolve(twtr, reported='TWTR') == _resolve(twtr)
    barnes = _figi(('BUSD', 'XB'), name='BARNES GROUP INC', share_class='SC3')
    lines = {'B': [_us('B', 'BARRICK MINING CORP', 'SC4')], 'BGX': [_us('BGX', 'BARNES GROUP INC', 'SC3')]}
    assert _resolve(barnes, us_lines=lines, reported='BGX')['status'] == 'reused'


def test_reported_tickers_latest_valid_wins():
    snaps = [[{'id': 'X', 'reported_ticker': '', 'name': 'Old Name'}],
             [{'id': 'X', 'reported_ticker': 'AAA', 'name': 'Old Name'}, {'id': None, 'reported_ticker': 'Q', 'name': 'Q'}],
             [{'id': 'X', 'reported_ticker': 'BBB', 'name': 'New Name'}],
             [{'id': 'X', 'reported_ticker': '', 'name': 'New Name'}]]
    assert b.reported_tickers(snaps) == {'X': ('BBB', ('Old Name', 'New Name'))}


def _sec(sid, name, id_type='ID_CUSIP'):
    return {'id': sid, 'id_type': id_type, 'name': name}


def _active(ticker):
    return {'status': 'active', 'ticker': ticker}


def test_issuer_succession_links_a_new_cusip_of_the_same_issuer():
    gone = {'status': 'unmapped', 'ticker': None}
    snaps = [[_sec('369604103', 'General Electric Co'), _sec('111111AA1', 'Other Co')],
             [_sec('369604301', 'General Electric Co'), _sec('111111AA1', 'Other Co')]]
    entries = {'369604103': gone, '369604301': _active('GE'), '111111AA1': _active('OTH')}
    links = b.issuer_successions(snaps, entries)
    assert links == {'369604103': {'successor': '369604301', 'ticker': 'GE'}}
    rows = b.snapshot_rows([dict(_sec('369604103', 'General Electric Co'), cusip='369604103', isin='', val_usd=1.0)],
                           entries, links)
    assert rows[0]['ticker'] == 'GE'
    # a frozen delisted ticker gives way to the successor's
    stale = dict(entries, **{'369604103': {'status': 'delisted', 'ticker': 'GEX'}})
    assert b.issuer_successions(snaps, stale)['369604103']['ticker'] == 'GE'
    assert b.snapshot_rows([dict(_sec('369604103', 'GE'), cusip='369604103', isin='', val_usd=1.0)], stale,
                           b.issuer_successions(snaps, stale))[0]['ticker'] == 'GE'
    # chains resolve to the latest CUSIP's ticker
    chain = [[_sec('222222AA1', 'Chain Inc')], [_sec('222222AB9', 'Chain Inc')], [_sec('222222AC7', 'Chain Inc')]]
    links = b.issuer_successions(chain, {'222222AA1': gone, '222222AB9': gone, '222222AC7': _active('CHN')})
    assert {k: v['ticker'] for k, v in links.items()} == {'222222AA1': 'CHN', '222222AB9': 'CHN'}


@pytest.mark.parametrize('snaps, entries', [
    # another issuer number (a holding-company reorganisation creates a new issuer)
    ([[_sec('313747206', 'Federal Realty')], [_sec('313745101', 'Federal Realty')]], {'313745101': _active('FRT')}),
    # another issuer name under the same number
    ([[_sec('123456AA1', 'Alpha Holdings')], [_sec('123456AB9', 'Beta Holdings')]], {'123456AB9': _active('BET')}),
    # not the very next snapshot
    ([[_sec('123456AA1', 'Alpha')], [], [_sec('123456AB9', 'Alpha')]], {'123456AB9': _active('ALP')}),
    # two candidates (share classes appearing together)
    ([[_sec('123456AA1', 'Alpha')], [_sec('123456AB9', 'Alpha'), _sec('123456AC7', 'Alpha')]],
     {'123456AB9': _active('ALPA'), '123456AC7': _active('ALPC')}),
    # the old CUSIP maps by itself
    ([[_sec('123456AA1', 'Alpha')], [_sec('123456AB9', 'Alpha')]], {'123456AA1': _active('ALP'),
                                                                     '123456AB9': _active('ALP2')}),
    # the successor's ticker is another security's alongside the old CUSIP
    ([[_sec('123456AA1', 'Alpha'), _sec('999999ZZ9', 'Zeta')], [_sec('123456AB9', 'Alpha')]],
     {'123456AB9': _active('ZZZ'), '999999ZZ9': _active('ZZZ')}),
    # ISINs carry no issuer number
    ([[_sec('IE00BZ12WP82', 'Linde PLC', 'ID_ISIN')], [_sec('IE000S9YS762', 'Linde PLC', 'ID_ISIN')]],
     {'IE000S9YS762': _active('LIN')}),
])
def test_issuer_succession_refuses(snaps, entries):
    assert b.issuer_successions(snaps, entries) == {}


def test_issuer_succession_never_relinks_a_rejected_mapping():
    # Wolfspeed's 2025 reorganisation cancelled 977852102; a new CUSIP of the same issuer
    # number in the next snapshot is the new equity, which the price check rejected
    snaps = [[_sec('977852102', 'Wolfspeed Inc')], [_sec('977852201', 'Wolfspeed Inc')]]
    entries = {'977852102': {'status': 'reused', 'ticker': None}, '977852201': _active('WOLF')}
    assert '977852102' in b.REJECTED_MAPPINGS and b.issuer_successions(snaps, entries) == {}
    assert b.issuer_successions([[_sec('977852103', 'Wolfspeed Inc')], [_sec('977852201', 'Wolfspeed Inc')]],
                                dict(entries, **{'977852103': {'status': 'unmapped', 'ticker': None}})) \
        == {'977852103': {'successor': '977852201', 'ticker': 'WOLF'}}


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


def test_query_openfigi_looks_up_reported_tickers(tmp_path, monkeypatch):
    asked = []

    def fake_get(url, headers=None, data=None, **kw):
        jobs = json.loads(data)
        asked.extend(j['idValue'] for j in jobs)
        return json.dumps([{'data': [_us(j['idValue'], 'COOPER COS INC/THE', 'SC')]} if j['idType'] == 'TICKER'
                           else {'warning': 'No identifier found.'} for j in jobs]).encode()

    monkeypatch.setattr(b, 'http_get', fake_get)
    monkeypatch.setattr(b, 'RateLimiter', lambda interval: None)
    entries = {}
    b.query_openfigi([('216648402', 'ID_CUSIP'), ('000000019', 'ID_CUSIP')], entries, tmp_path / 'map.json',
                     tmp_path / 'responses.json', reported={'216648402': ('COO', ('Cooper Cos Inc/The',))})
    assert asked == ['216648402', '000000019', 'COO']
    assert (entries['216648402']['ticker'], entries['216648402']['matched_by']) == ('COO', 'reported ticker')
    assert entries['000000019']['status'] == 'unmapped'


def test_vet_mappings_takes_away_another_securitys_ticker(monkeypatch):
    # BlackRock books OmniAb's earnout shares under OABI, the common stock's ticker
    common = _resolve(_figi(('OABI', 'US'), name='OMNIAB INC'))
    earnout = _resolve({'warning': 'No identifier found.'}, us_lines={'OABI': [_us('OABI', 'OMNIAB INC')]},
                       reported='OABI', names=('OmniAb Inc',))
    assert (earnout['status'], earnout['ticker'], earnout['matched_by']) == ('active', 'OABI', 'reported ticker')
    entries = {'68218J103': common, '68218J202': earnout, '999999AA1': dict(earnout)}
    snaps = [[_sec('68218J103', 'OmniAb Inc'), _sec('68218J202', 'OmniAb Inc')], [_sec('999999AA1', 'Other Inc')]]
    assert b.vet_mappings(snaps, entries) == ['68218J202']
    assert (entries['68218J202']['status'], entries['68218J202']['ticker']) == ('reused', None)
    assert entries['68218J202']['note'] == 'OABI is the own US line of 68218J103, held alongside'
    assert entries['68218J103'] == common and entries['999999AA1'] == earnout      # not held alongside: kept
    assert b.vet_mappings(snaps, entries) == []                                    # idempotent
    # two indirect matches held together, or a direct one that is not active: no owner, kept
    entries = {'1': dict(earnout), '2': dict(earnout), '3': dict(common, status='delisted')}
    assert b.vet_mappings([[_sec('1', 'A'), _sec('2', 'B'), _sec('3', 'C')]], entries) == []
    # the price check's rejections, for the rejected ticker only
    monkeypatch.setattr(b, 'REJECTED_MAPPINGS', {'78645L100': ('SAFE', "iStar's line")})
    safe = _resolve({'warning': 'No identifier found.'}, us_lines={'SAFE': [_us('SAFE', 'SAFEHOLD INC')]},
                    reported='SAFE', names=('Safehold Inc',))
    entries = {'78645L100': safe}
    assert b.vet_mappings([], entries) == ['78645L100']
    assert (entries['78645L100']['status'], entries['78645L100']['note']) == ('reused', "SAFE is iStar's line")
    rejected = entries['78645L100']
    assert b.vet_mappings([], entries) == [] and entries['78645L100'] is rejected
    # a reason edited after the rejection reaches the entry on the next build, date kept
    monkeypatch.setattr(b, 'REJECTED_MAPPINGS', {'78645L100': ('SAFE', "iStar's line before 2023")})
    assert b.vet_mappings([], entries) == ['78645L100']
    assert entries['78645L100'] == dict(rejected, note="SAFE is iStar's line before 2023")
    other = dict(rejected, note='SAFE now trades as SAFEHOLD INC (BBG000000000)')
    entries = {'78645L100': other}                                     # reused for another reason: kept
    assert b.vet_mappings([], entries) == [] and entries['78645L100'] is other
    entries = {'78645L100': dict(safe, ticker='SAFX')}
    assert b.vet_mappings([], entries) == [] and entries['78645L100']['ticker'] == 'SAFX'


def test_rejected_mappings_name_a_ticker_and_a_reason():
    for sid, (ticker, why) in b.REJECTED_MAPPINGS.items():
        holding = {'cusip': sid, 'isin': ''} if len(sid) == 9 else {'cusip': '000000000', 'isin': sid}
        assert b.security_id(holding)[0] == sid
        assert ticker == b.normalise_ticker(ticker) and len(why) > 20


def test_accepted_mappings_name_a_ticker_and_the_evidence():
    for sid, (ticker, why) in b.ACCEPTED_MAPPINGS.items():
        holding = {'cusip': sid, 'isin': ''} if len(sid) == 9 else {'cusip': '000000000', 'isin': sid}
        assert b.security_id(holding)[0] == sid
        assert ticker == b.normalise_ticker(ticker) and "N-PORT's price" in why and 'held date' in why
        assert b.REJECTED_MAPPINGS.get(sid, ('',))[0] != ticker          # never the ticker it is denied


def test_vet_mappings_gives_an_accepted_ticker(monkeypatch):
    # Howard Hughes' CUSIP until its 2023 reorganisation: OpenFIGI's line is the dead HHC,
    # its history is served under the holding company's HHH
    monkeypatch.setattr(b, 'ACCEPTED_MAPPINGS', {'44267D107': ('HHH', "the holding company's line: N-PORT's price "
                                                                        'equals its close on all 16 held dates')})
    old = _resolve(_figi(('HHC', 'UN'), name='HOWARD HUGHES CORP'))
    old = dict(old, status='delisted')
    entries = {'44267D107': old}
    assert b.vet_mappings([], entries, {'HHH': [_us('HHH', 'HOWARD HUGHES HOLDINGS INC')]}) == ['44267D107']
    e = entries['44267D107']
    assert (e['status'], e['ticker'], e['matched_by'], e['figi_ticker']) == ('active', 'HHH', 'price check', 'HHC')
    assert e['note'].startswith("HHH: the holding company's line") and e['mapped_on'] == old['mapped_on']
    assert b.vet_mappings([], entries, {'HHH': [_us('HHH')]}) == [] and entries['44267D107'] is e   # idempotent
    assert b.vet_mappings([], entries, {}) == ['44267D107'] and entries['44267D107']['status'] == 'delisted'
    # held alongside the security whose own line it is: taken away like any indirect match
    entries = {'44267D107': old, '44267T102': _resolve(_figi(('HHH', 'US')))}
    snaps = [[_sec('44267D107', 'Howard Hughes Corp'), _sec('44267T102', 'Howard Hughes Holdings')]]
    assert b.vet_mappings(snaps, entries, {'HHH': [_us('HHH')]}) == ['44267D107', '44267D107']
    assert (entries['44267D107']['status'], entries['44267D107']['ticker']) == ('reused', None)
    # issuer_successions leaves an accepted identifier alone
    snaps = [[_sec('44267D107', 'Howard Hughes Corp')], [_sec('44267D206', 'Howard Hughes Corp')]]
    gone = {'status': 'unmapped', 'ticker': None}
    assert b.issuer_successions(snaps, {'44267D107': gone, '44267D206': _active('HHX')}) == {}


def test_accepted_lines_looks_up_only_the_held_accepted_tickers(tmp_path, monkeypatch):
    asked = []

    def fake_get(url, headers=None, data=None, **kw):
        jobs = json.loads(data)
        asked.extend(j['idValue'] for j in jobs)
        return json.dumps([{'data': [_us(j['idValue'])]} if j['idValue'] != 'TSEOQ' else {'warning': 'none'}
                           for j in jobs]).encode()

    monkeypatch.setattr(b, 'http_get', fake_get)
    monkeypatch.setattr(b, 'RateLimiter', lambda interval: None)
    monkeypatch.setattr(b, 'ACCEPTED_MAPPINGS', {'1': ('HHH', 'x'), '2': ('TSEOQ', 'y'), '3': ('BRK-B', 'z')})
    cache = tmp_path / 'responses.json'
    assert b.accepted_lines({'9'}, cache) == {} and asked == [] and not cache.exists()
    lines = b.accepted_lines({'1', '2', '3'}, cache)
    assert asked == ['BRK/B', 'HHH', 'TSEOQ']                                 # Bloomberg style
    assert [len(lines[t]) for t in ('BRK-B', 'HHH', 'TSEOQ')] == [1, 1, 0]
    assert b.accepted_lines({'1', '2', '3'}, cache) == lines and len(asked) == 3     # cached


def test_map_new_identifiers_vets_and_keeps_mapping_dates(tmp_path, monkeypatch):
    old = dict(_resolve({'warning': 'No identifier found.'}), mapped_on='2026-01-02')
    asked = []

    def query(ids, entries, map_path, response_cache, api_key=None, refresh=False, reported=None):
        asked.append((list(ids), refresh))
        for sid, id_type in ids:
            entries[sid] = _resolve({'warning': 'No identifier found.'}, id_type)    # mapped on 2026-10-20
        b.write_map(entries, map_path)

    monkeypatch.setattr(b, 'query_openfigi', query)
    parsed_all = [(None, None, [dict(_sec('000000AA1', 'Alpha Inc'), reported_ticker='')], None, None)]
    args = argparse.Namespace(openfigi_cache=str(tmp_path / 'figi.json'))
    path = tmp_path / 'map.json'
    got = b._map_new_identifiers(parsed_all, {'000000AA1': old}, path, args)
    assert asked == [] and got == {'000000AA1': old} and not path.exists()      # nothing to ask, nothing written
    got = b._map_new_identifiers(parsed_all, {'000000AA1': old}, path, args, reresolve=True)
    assert asked == [([('000000AA1', 'ID_CUSIP')], False)] and got['000000AA1'] == old   # same answer, same date
    assert b.read_map(path) == got
    got = b._map_new_identifiers(parsed_all, {'000000AA1': old}, path, args, remap=True)
    assert asked[-1][1] and got['000000AA1']['mapped_on'] == '2026-10-20'          # asked again: dated today
    stale = {'000000AA1': old, '000000ZZ9': old}
    got = b._map_new_identifiers(parsed_all, stale, path, args, prune=True)
    assert list(got) == ['000000AA1'] and list(b.read_map(path)) == ['000000AA1']
    # a price-check rejection is applied and written, the mapping date kept; a rebuild is a no-op
    path.unlink()
    monkeypatch.setattr(b, 'REJECTED_MAPPINGS', {'000000AA1': ('AAA', 'another security in a test of the map write')})
    mapped = dict(_resolve(_figi(('AAA', 'UN')), reported='AAA'), matched_by='reported ticker', mapped_on='2026-01-02')
    n = len(asked)
    got = b._map_new_identifiers(parsed_all, {'000000AA1': mapped}, path, args)
    assert len(asked) == n                                                        # no OpenFIGI query
    assert got['000000AA1'] == dict(mapped, status='reused', ticker=None,
                                    note='AAA is another security in a test of the map write')
    assert b.read_map(path) == got
    path.unlink()
    assert b._map_new_identifiers(parsed_all, dict(got), path, args) == got and not path.exists()


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
    assert rows[0] == 'ticker,cusip,isin,name,weight,price'
    assert [r.split(',')[0] for r in rows[1:]] == ['AAA', 'GRMN', 'BBB-A', '']     # by descending weight
    assert rows[1].endswith(',0.555555556,5') and rows[2].startswith('GRMN,,CH0114405324,')
    assert [r.split(',')[-1] for r in rows[2:]] == ['100', '10', f'{50 / 7:.9g}']   # value per share
    amended = (out / 'iwv_2020-06-30.csv').read_text().splitlines()
    assert amended[1].startswith('AAA,') and amended[1].endswith(f',{800 / 1200:.9g},8')


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


def test_the_online_sealed_build_maps_new_identifiers_into_its_own_map(tmp_path, monkeypatch):
    """The holdout's production path (scripts/run_holdout.sh, no --offline): the sealed
    filing's new CUSIP is mapped into DIR's copy of the map, the price check's verdicts are
    applied there, and the committed map and index stay byte for byte as they were."""
    raw, out, dest = _raw_cache(tmp_path), tmp_path / 'out', tmp_path / 'holdout' / 'universe'
    _map(out)
    b.main(['--offline', '--raw-dir', str(raw), '--out-dir', str(out)])
    _sealed_xml(raw)
    xml = raw / '0000000000-26-000004.xml'
    xml.write_bytes(xml.read_bytes().replace(b'000000AA1', b'000000ZZ5').replace(b'US000000AA11', b'US000000ZZ51'))
    committed = {p.name: p.read_bytes() for p in out.iterdir()}

    def sec_get(url):
        raise AssertionError(f'no download expected: {url}')

    asked = []

    def query(jobs, entries, map_path, response_cache, api_key=None, refresh=False, reported=None):
        asked.append(list(jobs))
        for sid, id_type in jobs:
            entries[sid] = _resolve(_figi(('ZZZ', 'US')), id_type)
        b.write_map(entries, map_path)

    monkeypatch.setattr(b, 'assert_unsealed', lambda end: None)
    monkeypatch.setattr(b, 'sec_get', sec_get)
    monkeypatch.setattr(b, 'query_openfigi', query)
    monkeypatch.setattr(b, 'REJECTED_MAPPINGS', {'000000BB7': ('BBB-A', 'another security in a test of the holdout')})
    args = ['--include-sealed', '--sealed-out', str(dest), '--raw-dir', str(raw), '--out-dir', str(out),
            '--openfigi-cache', str(tmp_path / 'figi.json')]
    assert b.main(args) == 0
    assert asked == [[('000000ZZ5', 'ID_CUSIP')]]                                # only the new identifier
    held = b.read_map(dest / 'cusip_ticker_map.json')
    assert held['000000ZZ5']['ticker'] == 'ZZZ'
    assert (held['000000BB7']['status'], held['000000BB7']['ticker']) == ('reused', None)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == committed           # reference/ untouched
    for name in ('iwv_2020-03-31.csv', 'iwv_2020-06-30.csv'):
        assert (dest / name).read_bytes() == committed[name]
    rows = (dest / 'iwv_2026-03-31.csv').read_text().splitlines()
    assert rows[1].startswith('ZZZ,000000ZZ5,') and any(r.startswith(',000000BB7,') for r in rows)
    # the guards of the sealed build
    with pytest.raises(SystemExit, match='must not be the committed reference directory'):
        b.main(['--include-sealed', '--sealed-out', str(out), '--raw-dir', str(raw), '--out-dir', str(out)])
    for bad in (['--sealed-out', str(dest)], ['--include-sealed', '--sealed-out', str(dest), '--reresolve'],
                ['--include-sealed', '--sealed-out', str(dest), '--remap-missing']):
        with pytest.raises(SystemExit, match='needs --include-sealed'):
            b.main(bad + ['--raw-dir', str(raw), '--out-dir', str(out)])
    assert {p.name: p.read_bytes() for p in out.iterdir()} == committed


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


def test_offline_build_applies_issuer_successions(tmp_path):
    # Alpha's CUSIP changes between the two snapshots (a reverse split): OpenFIGI no longer
    # knows the old one, the new one maps to AAA
    raw, out = _raw_cache(tmp_path), tmp_path / 'out'
    amended = raw / '0000000000-20-000003.xml'
    amended.write_bytes(amended.read_bytes().replace(b'000000AA1', b'000000AB9').replace(b'US000000AA11', b'US000000AB92'))
    out.mkdir()
    b.write_map({'000000AA1': _resolve({'warning': 'No identifier found.'}),
                 '000000AB9': _resolve(_figi(('AAA', 'US'))),
                 '000000BB7': _resolve(_figi(('BBB/A', 'UN'))),
                 'CH0114405324': _resolve(_figi(('GRMN', 'US')), 'ID_ISIN')}, out / 'cusip_ticker_map.json')
    b.main(['--offline', '--raw-dir', str(raw), '--out-dir', str(out)])
    with open(out / 'index.json') as f:
        index = json.load(f)
    assert index['successions'] == {'000000AA1': {'successor': '000000AB9', 'ticker': 'AAA'}}
    first = (out / 'iwv_2020-03-31.csv').read_text().splitlines()
    assert first[1].startswith('AAA,000000AA1,') and index['snapshots'][0]['n_mapped'] == 3


def test_the_sealed_build_applies_issuer_successions(tmp_path, monkeypatch):
    """A rebuilt committed snapshot takes the committed links (the successor CUSIP sits in a
    snapshot outside the window); a sealed snapshot also takes the links among the sealed ones."""
    raw, out = _raw_cache(tmp_path), tmp_path / 'out'
    amended = raw / '0000000000-20-000003.xml'
    amended.write_bytes(amended.read_bytes().replace(b'000000AA1', b'000000AB9').replace(b'US000000AA11', b'US000000AB92'))
    out.mkdir()
    gone = _resolve({'warning': 'No identifier found.'})
    b.write_map({'000000AA1': gone, '000000AB9': _resolve(_figi(('AAA', 'US'))),
                 '000000BB7': _resolve(_figi(('BBB/A', 'UN'))),
                 'CH0114405324': _resolve(_figi(('GRMN', 'US')), 'ID_ISIN'),
                 '000000AC7': gone, '000000AD5': _resolve(_figi(('DDD', 'US')))}, out / 'cusip_ticker_map.json')
    b.main(['--offline', '--raw-dir', str(raw), '--out-dir', str(out)])
    committed_link = {'000000AA1': {'successor': '000000AB9', 'ticker': 'AAA'}}
    reh = tmp_path / 'reh'
    assert b.main(['--offline', '--include-sealed', '--sealed-out', str(reh), '--sealed-from', '2020-01-01',
                   '--through', '2020-03-31', '--raw-dir', str(raw), '--out-dir', str(out)]) == 0
    assert (reh / 'iwv_2020-03-31.csv').read_bytes() == (out / 'iwv_2020-03-31.csv').read_bytes()
    assert json.loads((reh / 'index.json').read_text())['successions'] == committed_link
    # two sealed filings: Alpha's CUSIP AC7 in the first is AD5 (DDD) in the second
    index = json.loads((out / 'index.json').read_text())
    index['sealed'].append({'period_date': '2026-06-30', 'filing_date': '2026-08-25',
                            'accession': '0000000000-26-000005', 'form': 'NPORT-P'})
    (out / 'index.json').write_text(json.dumps(index, indent=1) + '\n')
    for acc, period, cusip in (('0000000000-26-000004', '2026-03-31', b'000000AC7'),
                               ('0000000000-26-000005', '2026-06-30', b'000000AD5')):
        (raw / f'{acc}.hdr').write_text(f"<SEC-HEADER>\n<PERIOD>{period.replace('-', '')}\n"
                                        f"<SERIES-ID>S000004341\n</SEC-HEADER>\n")
        (raw / f'{acc}.index.json').write_text(json.dumps({'directory': {'item': [{'name': 'primary_doc.xml'}]}}))
        (raw / f'{acc}.xml').write_bytes(_xml().replace(b'<repPdDate>2020-03-31', f'<repPdDate>{period}'.encode())
                                         .replace(b'000000AA1', cusip).replace(b'US000000AA11', b'US' + cusip + b'0'))
    monkeypatch.setattr(b, 'assert_unsealed', lambda end: None)
    dest = tmp_path / 'holdout'
    assert b.main(['--offline', '--include-sealed', '--sealed-out', str(dest), '--raw-dir', str(raw),
                   '--out-dir', str(out)]) == 0
    assert json.loads((dest / 'index.json').read_text())['successions'] == dict(
        committed_link, **{'000000AC7': {'successor': '000000AD5', 'ticker': 'DDD'}})
    assert (dest / 'iwv_2026-03-31.csv').read_text().splitlines()[1].startswith('DDD,000000AC7,')
    assert (dest / 'iwv_2020-03-31.csv').read_bytes() == (out / 'iwv_2020-03-31.csv').read_bytes()


def test_online_build_queries_only_unmapped_identifiers(tmp_path, monkeypatch):
    raw, out = _raw_cache(tmp_path), tmp_path / 'out'
    _map(out, with_all=False)
    with open(os.path.join(FIX, 'filings.atom'), 'rb') as f:
        atom = f.read()

    def sec_get(url):
        assert url == b.FILINGS_URL, url                          # everything else is cached
        return atom

    asked = []

    def query(jobs, entries, map_path, response_cache, api_key=None, refresh=False, reported=None):
        asked.append((list(jobs), refresh))
        assert reported['000000BB7'] == ('BBB/A', ('Beta Inc',))
        for sid, id_type in jobs:
            entries[sid] = _resolve({'warning': 'No identifier found.'}, id_type)
        b.write_map(entries, map_path)

    monkeypatch.setattr(b, 'sec_get', sec_get)
    monkeypatch.setattr(b, 'query_openfigi', query)
    entries = b.read_map(out / 'cusip_ticker_map.json')
    b.write_map(dict(entries, **{'457CVR017': _resolve(_figi(('INBX', 'US')))}), out / 'cusip_ticker_map.json')
    args = ['--raw-dir', str(raw), '--out-dir', str(out), '--openfigi-cache', str(tmp_path / 'figi.json')]
    b.main(args)
    assert asked == [([('000000BB7', 'ID_CUSIP'), ('CH0114405324', 'ID_ISIN')], False)]
    assert '457CVR017' not in b.read_map(out / 'cusip_ticker_map.json')   # held by no snapshot: dropped
    b.main(args)
    assert len(asked) == 1                                        # failures are cached too
    b.main(['--remap-missing'] + args)
    assert asked[-1] == ([('000000BB7', 'ID_CUSIP'), ('CH0114405324', 'ID_ISIN')], True)
    b.main(['--reresolve'] + args)                                # from the cached responses
    assert asked[-1] == ([('000000BB7', 'ID_CUSIP'), ('CH0114405324', 'ID_ISIN')], False)
    with pytest.raises(SystemExit, match='exclude each other'):
        b.main(['--reresolve', '--remap-missing'] + args)
