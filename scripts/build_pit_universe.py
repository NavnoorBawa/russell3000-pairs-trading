#!/usr/bin/env python3
"""Build the point-in-time Russell 3000 universe from IWV's quarterly SEC N-PORT filings.

The iShares Russell 3000 ETF (IWV; iShares Trust CIK 1100663, series S000004341) holds
nearly every index constituent, and each N-PORT-P filing lists its holdings with CUSIP,
ISIN and market value on the report-period date. Only the third month of each fiscal
quarter is made public, so the snapshots are quarterly; N-PORT starts in 2019Q3.

For every filing the script
  1. reads the period date and series from the filing header and downloads
     primary_doc.xml (located through the filing's index.json), cached under
     data/raw/nport/;
  2. keeps the equity-common holdings (assetCat EC; cash sweeps, money-market funds and
     index futures are dropped) and weights each by its share of their total value
     (contingent value rights and escrow claims stay in the weights without a ticker);
  3. maps each CUSIP (or, where N-PORT gives none, the ISIN) to a US ticker with OpenFIGI,
     cached in reference/universe/cusip_ticker_map.json;
  4. writes reference/universe/iwv_<period>.csv (ticker, cusip, isin, name, weight) and
     reference/universe/index.json (dates, accession, source URL, XML SHA-256, counts).

Sealed holdout. A snapshot dated 2026 or later carries every holding's market value, that
is a 2026 price for every member, and 2026 is the pre-registered holdout. Such filings are
listed in index.json under 'sealed' but not downloaded unless --include-sealed is given
(after the pre-registration is committed).

Ticker choice from an OpenFIGI response: exchCode US (the US composite), then UN, UW, UQ,
UA, UR, UP, UV; then any other US venue; then, for a security OpenFIGI only lists on
non-US lines (delisted names such as TWTR, listed as TWTRUSD on XS), the XS/XB ticker with
its 'USD' suffix stripped (and Bloomberg's numbering of a retired symbol, CPE3 -> CPE).
Two checks follow, both on OpenFIGI's own identity data (a share-class FIGI is shared by
every listing of a share class):
  - a CUSIP whose US line OpenFIGI has retired (Exxon Mobil's, after its 2026 holding-
    company reorganisation) comes back with foreign lines only (XOMCHF on X1, XOM on UZ);
    their tickers are looked up on exchCode US and accepted when the US record has the
    same share-class FIGI or a matching issuer name (same_security);
  - a delisted line's ticker may since have been taken by another issuer (Barnes Group's
    B is Barrick's today), so a price history under it would belong to someone else;
    such a mapping is kept as status 'reused' with no ticker.
Two more sources cover the CUSIPs OpenFIGI no longer resolves, which are mostly not
delisted at all but replaced by a new CUSIP (a reverse split, a holding-company
reorganisation, a re-domiciliation: Linde's ISIN until 2023, Cooper's CUSIP until its 2024
split):
  - from the 2022-09-30 filing on, N-PORT reports each holding's ticker on the period date.
    For an identifier OpenFIGI leaves unmapped, or maps only to a delisted XS/XB line
    (whose ticker Bloomberg froze at an earlier name: CCIVUSD for Lucid, PJCUSD for Piper
    Sandler), the latest reported ticker goes through the same exchCode-US lookup and
    same_security test (issuer names include N-PORT's), giving 'active', 'reused' or
    'delisted' with the reported ticker (matched_by 'reported ticker');
  - an identifier that is still without a ticker and whose CUSIP is succeeded, in the very
    next snapshot, by exactly one new CUSIP with the same six-character issuer number and
    the same issuer name inherits that CUSIP's ticker (issuer_successions; General
    Electric's CUSIP before its 2021 reverse split). The links are listed in index.json.
Tickers are normalised to Yahoo style (BRK/B -> BRK-B). The mapping is as of the mapping
date: a CUSIP maps to the security's latest ticker, the key under which Yahoo serves its
whole history.

OpenFIGI allows 25 requests/min of 10 jobs without a key; OPENFIGI_API_KEY raises this to
25 requests/6 s of 100 jobs. EDGAR requests carry SEC_USER_AGENT and stay under 10/s.
The outputs are deterministic given the caches: --offline rebuilds them byte for byte.

usage: python scripts/build_pit_universe.py [--offline] [--include-sealed] [--remap-missing]
"""
import argparse
import csv
import hashlib
import json
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pairs_trading.external_data import RateLimiter, http_get, sec_get, write_atomic  # noqa: E402
from pairs_trading.universe import normalise_ticker  # noqa: E402

TRUST_CIK = 1100663
SERIES_ID = 'S000004341'
FILINGS_URL = (f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={SERIES_ID}'
               '&type=NPORT-P&count=100&output=atom')
ARCHIVE_URL = f'https://www.sec.gov/Archives/edgar/data/{TRUST_CIK}/{{folder}}/'
OPENFIGI_URL = 'https://api.openfigi.com/v3/mapping'
SEALED_FROM = '2026-01-01'

US_EXCH_PRIORITY = ('US', 'UN', 'UW', 'UQ', 'UA', 'UR', 'UP', 'UV')
# Bloomberg codes of the US venues under the US composite, as OpenFIGI returns them
# (exchanges, alternative venues, FINRA ADF, OTC).
US_VENUES = frozenset({'UA', 'UB', 'UC', 'UD', 'UF', 'UM', 'UN', 'UP', 'UQ', 'UR', 'UT', 'UV', 'UW', 'UX',
                       'VJ', 'VK', 'VY'})
USD_LINE_EXCH = frozenset({'XS', 'XB'})
ACTIVE_EXCH = frozenset(US_EXCH_PRIORITY) | US_VENUES
_USD_LINE = re.compile(r'([A-Z][A-Z0-9/.]{0,5})USD')
# Bloomberg's tickers for retired securities: a placeholder, or the old symbol numbered.
_PLACEHOLDER = re.compile(r'\d+D')
_NUMBERED = re.compile(r'([A-Z][A-Z/.]*?)\d+')
# Bloomberg's currency lines append the trading currency to the ticker (XOMCHF, HONGBP).
_CCY_LINE = re.compile(r'([A-Z][A-Z/]{0,5}?)(USD|EUR|GBP|GBX|CHF|CAD|RUB|JPY|SEK|NOK|DKK|PLN|MXN|BRL|AUD|HKD|SGD|ZAR)')

# Series numerals that tell a sponsor's next vehicle from its first (SPACs, funds).
_SERIES = frozenset({'II', 'III', 'IV', 'VI', 'VII', 'VIII', 'IX'})
# Length at which an issuer name may have been cut off (Bloomberg: 28 characters).
NAME_CUT = 28
_LEGAL_FORM = frozenset({'INC', 'CORP', 'CORPORATION', 'CO', 'COMPANY', 'LTD', 'LIMITED', 'PLC', 'HOLDINGS',
                         'HOLDING', 'HLDGS', 'GROUP', 'THE', 'NEW', 'OLD', 'NV', 'SA', 'AG', 'SE', 'LP', 'LLC',
                         'CL', 'CLASS'})
# BlackRock's placeholder CUSIPs for contingent value rights and escrow claims.
_PLACEHOLDER_CUSIP = re.compile(r'[0-9]{3}(CVR|ESC)[0-9A-Z]{3}')
# A ticker as N-PORT reports it (Bloomberg style, BRK/B); numeric codes, exchange suffixes
# (GFF.NY) and when-issued lines (SAFE-W) are not tickers to look up.
_REPORTED_TICKER = re.compile(r'[A-Z]{1,5}(/[A-Z])?')

ATOM_NS = '{http://www.w3.org/2005/Atom}'


# ---------------------------------------------------------------------------------------
# EDGAR: filing list, headers, holdings
# ---------------------------------------------------------------------------------------

def parse_filing_list(atom):
    """Filings in an EDGAR browse-edgar Atom feed: accession, filing date, form (NPORT-P[/A])."""
    root = ET.fromstring(atom)
    filings = []
    for entry in root.iter(f'{ATOM_NS}entry'):
        content = entry.find(f'{ATOM_NS}content')
        if content is None:
            continue
        form = (content.findtext(f'{ATOM_NS}filing-type') or '').strip()
        if not form.startswith('NPORT-P'):
            continue
        filings.append({'accession': content.findtext(f'{ATOM_NS}accession-number').strip(),
                        'filing_date': content.findtext(f'{ATOM_NS}filing-date').strip(),
                        'form': form})
    return sorted(filings, key=lambda f: (f['filing_date'], f['accession']))


def parse_header(text):
    """Period of report (ISO date) and series ids from an EDGAR SGML submission header."""
    period = re.search(r'<PERIOD>\s*(\d{8})', text)
    if not period:
        raise ValueError('no <PERIOD> in the filing header')
    p = period.group(1)
    return {'period_date': f'{p[:4]}-{p[4:6]}-{p[6:]}',
            'series': sorted(set(re.findall(r'<SERIES-ID>\s*(S\d{9})', text)))}


def folder_url(accession):
    return ARCHIVE_URL.format(folder=accession.replace('-', ''))


def primary_doc_name(index_json):
    """The holdings document named in a filing's index.json (primary_doc.xml)."""
    items = [i['name'] for i in json.loads(index_json)['directory']['item']]
    if 'primary_doc.xml' in items:
        return 'primary_doc.xml'
    xml = [n for n in items if n.lower().endswith('.xml')]
    if len(xml) != 1:
        raise ValueError(f'cannot identify the N-PORT XML among {items}')
    return xml[0]


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def parse_nport(blob):
    """Report-period date, series id and every <invstOrSec> of an N-PORT primary_doc.xml.

    A holding's ISIN and ticker are the holding's own <identifiers> (a derivative's
    reference instrument carries identifiers too, one level down); filings before
    2022-09-30 report no ticker.
    """
    root = ET.fromstring(blob)
    gen = next((e for e in root.iter() if _local(e.tag) == 'genInfo'), None)
    if gen is None:
        raise ValueError('no genInfo in N-PORT document')
    info = {_local(c.tag): (c.text or '').strip() for c in gen}
    holdings = []
    for sec in root.iter():
        if _local(sec.tag) != 'invstOrSec':
            continue
        fields = {_local(c.tag): (c.text or '').strip() for c in sec}
        ids = next((c for c in sec if _local(c.tag) == 'identifiers'), ())
        id_values = {_local(e.tag): (e.get('value') or '').strip() for e in ids}
        holdings.append({'name': fields.get('name', ''), 'title': fields.get('title', ''),
                         'cusip': fields.get('cusip', ''), 'isin': id_values.get('isin', ''),
                         'ticker': id_values.get('ticker', ''),
                         'balance': float(fields.get('balance') or 0.0),
                         'val_usd': float(fields.get('valUSD') or 0.0),
                         'asset_cat': fields.get('assetCat', ''), 'inv_country': fields.get('invCountry', '')})
    return {'period_date': info.get('repPdDate'), 'series_id': info.get('seriesId'), 'holdings': holdings}


def security_id(holding):
    """(identifier, OpenFIGI idType): the CUSIP, else the ISIN (N-PORT writes 000000000
    for some foreign-domiciled issuers), else (None, None).

    BlackRock books contingent value rights and escrow claims left by an acquisition under
    placeholder CUSIPs ('457CVR017', '361ESC049', with ISINs built on them) and the target's
    old ticker: they are not listed shares, so they get no identifier to map.
    """
    cusip = holding['cusip'].upper()
    isin = holding['isin'].upper()
    if _PLACEHOLDER_CUSIP.fullmatch(cusip) or _PLACEHOLDER_CUSIP.fullmatch(isin[2:11]):
        return None, None
    if re.fullmatch(r'[0-9A-Z]{8}[0-9]', cusip) and cusip != '000000000':
        return cusip, 'ID_CUSIP'
    if re.fullmatch(r'[A-Z]{2}[0-9A-Z]{9}[0-9]', isin):
        return isin, 'ID_ISIN'
    return None, None


def reported_ticker(holding):
    """The holding's N-PORT ticker in Bloomberg style ('BRK/B'), or '' when it reports none
    or something that is not a ticker (a numeric code, 'GFF.NY', 'SAFE-W')."""
    t = (holding.get('ticker') or '').strip().upper()
    return t if _REPORTED_TICKER.fullmatch(t) else ''


def equity_securities(holdings):
    """Equity-common holdings, one entry per security (repeated lines summed), in file order."""
    out = OrderedDict()
    equity = [h for h in holdings if h['asset_cat'] == 'EC']
    for n, h in enumerate(equity):
        sid, id_type = security_id(h)
        key = sid or f'#{n}'
        if key in out:
            out[key]['val_usd'] += h['val_usd']
            out[key]['reported_ticker'] = out[key]['reported_ticker'] or reported_ticker(h)
            continue
        out[key] = {'id': sid, 'id_type': id_type, 'cusip': sid if id_type == 'ID_CUSIP' else '',
                    'isin': h['isin'].upper(), 'name': h['name'], 'val_usd': h['val_usd'],
                    'reported_ticker': reported_ticker(h)}
    return list(out.values())


# ---------------------------------------------------------------------------------------
# OpenFIGI
# ---------------------------------------------------------------------------------------

def choose_listing(data):
    """(record, raw ticker) of the US listing in an OpenFIGI result list, or None.

    Bloomberg renames a retired security's ticker when the symbol is reassigned: lines
    with a placeholder ('9990302D') are skipped, and a delisted line's numbered ticker
    ('CPE3USD') gives back the symbol it traded under ('CPE').
    """
    listed = [d for d in data if d.get('ticker') and not _PLACEHOLDER.fullmatch(d['ticker'])]
    for code in US_EXCH_PRIORITY:
        hit = next((d for d in listed if d.get('exchCode') == code), None)
        if hit:
            return hit, hit['ticker']
    hit = next((d for d in listed if d.get('exchCode') in US_VENUES), None)
    if hit:
        return hit, hit['ticker']
    for d in listed:
        m = _USD_LINE.fullmatch(d['ticker']) if d.get('exchCode') in USD_LINE_EXCH else None
        if m:
            numbered = _NUMBERED.fullmatch(m.group(1))
            return d, (numbered.group(1) if numbered else m.group(1)).rstrip('/.')
    return None


def ticker_candidates(data):
    """Possible US tickers of a security OpenFIGI lists only on non-US lines: each line's
    ticker less a currency suffix (XOMCHF -> XOM, HONGBP -> HON), in result order."""
    out = []
    for d in data:
        t = (d.get('ticker') or '').strip()
        m = _CCY_LINE.fullmatch(t)
        base = m.group(1) if m else t
        if re.fullmatch(r'[A-Z]{1,5}(/[A-Z]{1,2})?', base) and base not in out:
            out.append(base)
    return out


def issuer_tokens(name):
    """An issuer name's words without punctuation and legal-form words (share-class letters
    are kept): 'EXXONMOBIL HOLDINGS CORP' -> ['EXXONMOBIL']."""
    return [t for t in re.findall(r'[A-Z0-9]+', (name or '').upper()) if t not in _LEGAL_FORM]


def issuer_key(name):
    """issuer_tokens joined, for comparing names across a re-domiciliation or holding-company
    reorganisation ('EXXON MOBIL CORP' and 'EXXONMOBIL HOLDINGS CORP' -> 'EXXONMOBIL')."""
    return ''.join(issuer_tokens(name))


def _cut_word(words, other):
    """Whether `words` is `other` cut off inside its last word ('EASTERLY GOVERNMENT
    PROPERTI' for 'EASTERLY GOVERNMENT PROPERTIES')."""
    n = len(words)
    return n >= 2 and len(other) >= n and other[:n - 1] == words[:-1] and other[n - 1].startswith(words[-1])


def same_security(record, data):
    """Whether an OpenFIGI record is the security that `data` (one job's results) describes,
    or its successor: the same share-class FIGI, which every listing of a share class
    carries; the same issuer_key; or issuer names of which one opens with all the words of
    the other (Bloomberg abbreviates and appends classes: 'AMC ENTERTAINMENT HOLDINGS INC'
    vs 'AMC ENTERTAINMENT HLDS-CL A'; but 'RUBICON PROJECT' is not 'RUBICO', and a sponsor's
    next vehicle, 'METALS ACQUISITION II', is not 'METALS ACQUISITION'). A name of
    NAME_CUT characters or more may end inside a word (Bloomberg cuts names at 28, older
    N-PORT filings at 30). The record always comes from looking up one of the security's
    own tickers, so the name test only has to tell a successor from an unrelated issuer
    that has taken the ticker since."""
    if record.get('shareClassFIGI') in {d.get('shareClassFIGI') for d in data} - {None}:
        return True
    name = record.get('name') or ''
    words = issuer_tokens(name)
    for other_name in {d.get('name') or '' for d in data}:
        other = issuer_tokens(other_name)
        short, long_ = sorted((words, other), key=len)
        if short and (''.join(short) == ''.join(long_)
                      or (len(''.join(short)) >= 4 and long_[:len(short)] == short
                          and not _SERIES.intersection(long_[len(short):]))):
            return True
        if ((len(name) >= NAME_CUT and _cut_word(words, other))
                or (len(other_name) >= NAME_CUT and _cut_word(other, words))):
            return True
    return False


def pending_tickers(result, reported=''):
    """Tickers resolve_entry needs looked up on exchCode US for one job result: none when
    OpenFIGI already gives an active US line, the delisted line's ticker when that is all
    it gives, else the candidates from the security's foreign lines; plus the ticker
    N-PORT reported for the security, if any."""
    data = result.get('data') or []
    pick = choose_listing(data)
    if pick and pick[0].get('exchCode') in ACTIVE_EXCH:
        return []
    out = [pick[1]] if pick else ticker_candidates(data)
    return out + [reported] if reported and reported not in out else out


def _entry(record, ticker, id_type, status, matched_by, mapped_on):
    return {'id_type': id_type, 'status': status, 'ticker': normalise_ticker(ticker), 'figi_ticker': record['ticker'],
            'figi': record.get('figi'), 'composite_figi': record.get('compositeFIGI'), 'name': record.get('name'),
            'exchCode': record.get('exchCode'), 'security_type': record.get('securityType'),
            'matched_by': matched_by, 'mapped_on': mapped_on}


def resolve_entry(result, id_type, us_lines, mapped_on, reported='', names=()):
    """The cusip_ticker_map.json entry for one OpenFIGI job result.

    `us_lines[t]` are the records OpenFIGI returns for ticker t on exchCode US (see
    pending_tickers). Status: 'active' (an active US line: the job's own, or one found
    through a candidate ticker and confirmed by same_security); 'delisted' (only a
    delisted XS/XB line, whose ticker no US security uses now: the last ticker is kept);
    'reused' (that ticker now belongs to a different security, so its price history is
    not this one's: no ticker); 'unmapped'.

    `reported` is the latest ticker N-PORT gave for the security and `names` its N-PORT
    issuer names. When OpenFIGI's answer is 'unmapped', or 'delisted' under another
    ticker, the reported ticker is resolved the same way (matched_by 'reported ticker').
    """
    entry = _resolve_figi(result, id_type, us_lines, mapped_on)
    if not reported or entry['status'] not in ('unmapped', 'delisted') or entry['ticker'] == normalise_ticker(reported):
        return entry
    data = (result.get('data') or []) + [{'name': n} for n in names]
    lines = us_lines.get(reported, [])
    same = next((r for r in lines if same_security(r, data)), None)
    if same:
        return _entry(same, same['ticker'], id_type, 'active', 'reported ticker', mapped_on)
    figi_line = f"; OpenFIGI's delisted line reads {entry['figi_ticker']}" if entry['status'] == 'delisted' else ''
    entry = dict(entry, matched_by='reported ticker', name=entry['name'] or (names[-1] if names else None))
    if lines:
        return dict(entry, status='reused', ticker=None,
                    note=f"{normalise_ticker(reported)} (N-PORT) now trades as {lines[0].get('name')} "
                         f"({lines[0].get('figi')}){figi_line}")
    return dict(entry, status='delisted', ticker=normalise_ticker(reported),
                note=f'{normalise_ticker(reported)} as reported in N-PORT; no US security uses it now{figi_line}')


def _resolve_figi(result, id_type, us_lines, mapped_on):
    """resolve_entry on OpenFIGI's own answer only."""
    data = result.get('data') or []
    own = 'isin' if id_type == 'ID_ISIN' else 'cusip'

    def confirmed(record):
        classes = {d.get('shareClassFIGI') for d in data} - {None}
        how = 'share class' if record.get('shareClassFIGI') in classes else 'name'
        return _entry(record, record['ticker'], id_type, 'active', how, mapped_on)

    pick = choose_listing(data)
    if pick and pick[0].get('exchCode') in ACTIVE_EXCH:
        return _entry(pick[0], pick[1], id_type, 'active', own, mapped_on)
    if pick:
        record, last = pick
        lines = us_lines.get(last, [])
        same = next((r for r in lines if same_security(r, data)), None)
        if same:
            return confirmed(same)
        if lines:
            return dict(_entry(record, last, id_type, 'reused', own, mapped_on), ticker=None,
                        note=f"{normalise_ticker(last)} now trades as {lines[0].get('name')} ({lines[0].get('figi')})")
        return _entry(record, last, id_type, 'delisted', own, mapped_on)
    for candidate in ticker_candidates(data):
        same = next((r for r in us_lines.get(candidate, []) if same_security(r, data)), None)
        if same:
            return confirmed(same)
    note = result.get('warning') or result.get('error') or f'no US listing among {len(data)} results'
    return {'id_type': id_type, 'status': 'unmapped', 'ticker': None, 'figi_ticker': None, 'figi': None,
            'name': data[0].get('name') if data else None, 'exchCode': None, 'note': note, 'mapped_on': mapped_on}


def _job_key(job):
    return '|'.join((job['idType'], job['idValue'], job.get('exchCode', '')))


def _post_jobs(jobs, responses, cache_path, api_key):
    """OpenFIGI results for `jobs` (dicts), from `responses` where cached, else fetched
    and added to it; the response cache is saved after every 20 requests."""
    todo = [j for j in jobs if _job_key(j) not in responses]
    per_request = 100 if api_key else 10
    limiter = RateLimiter(6.0 / 25 if api_key else 60.0 / 25 + 0.1)
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['X-OPENFIGI-APIKEY'] = api_key
    for n, i in enumerate(range(0, len(todo), per_request), start=1):
        chunk = todo[i:i + per_request]
        results = json.loads(http_get(OPENFIGI_URL, headers=headers, data=json.dumps(chunk).encode(),
                                      limiter=limiter, retries=8))
        if len(results) != len(chunk):
            raise RuntimeError(f'OpenFIGI returned {len(results)} results for {len(chunk)} jobs')
        responses.update((_job_key(j), r) for j, r in zip(chunk, results))
        if n % 20 == 0 or i + per_request >= len(todo):
            write_atomic(cache_path, json.dumps(responses))
            print(f'  OpenFIGI: {min(i + per_request, len(todo))}/{len(todo)} jobs', flush=True)
    return [responses[_job_key(j)] for j in jobs]


def query_openfigi(ids, entries, map_path, response_cache, api_key=None, refresh=False, reported=None):
    """Map [(identifier, idType)] into `entries` and save the map.

    Two passes: the identifiers themselves, then exchCode-US ticker lookups for those
    without an active US line (resolve_entry). `reported[identifier]` is (latest N-PORT
    ticker, N-PORT issuer names). Raw responses are cached in `response_cache`, so an
    interrupted run resumes where it stopped; `refresh` drops the cached responses for
    these identifiers and every cached ticker lookup first.
    """
    reported = reported or {}
    response_cache = pathlib.Path(response_cache)
    responses = json.loads(response_cache.read_text()) if response_cache.exists() else {}
    if refresh:
        stale = {_job_key({'idType': t, 'idValue': v}) for v, t in ids}
        responses = {k: r for k, r in responses.items() if k not in stale and not k.startswith('TICKER|')}
    results = _post_jobs([{'idType': t, 'idValue': v} for v, t in ids], responses, response_cache, api_key)
    tickers = sorted({t for (sid, _), r in zip(ids, results)
                      for t in pending_tickers(r, reported.get(sid, ('', ()))[0])})
    looked_up = _post_jobs([{'idType': 'TICKER', 'idValue': t, 'exchCode': 'US'} for t in tickers],
                           responses, response_cache, api_key)
    us_lines = {t: [d for d in (r.get('data') or []) if d.get('exchCode') == 'US' and d.get('ticker')]
                for t, r in zip(tickers, looked_up)}
    today = datetime.now(timezone.utc).date().isoformat()
    for (sid, id_type), result in zip(ids, results):
        entries[sid] = resolve_entry(result, id_type, us_lines, today, *reported.get(sid, ('', ())))
    write_map(entries, map_path)


def read_map(path):
    if not pathlib.Path(path).exists():
        return {}
    return json.loads(pathlib.Path(path).read_text())['entries']


def write_map(entries, path):
    """cusip_ticker_map.json: header fields, then one entry per line (reviewable diffs)."""
    head = OrderedDict([
        ('source', OPENFIGI_URL),
        ('rule', 'exchCode ' + ' > '.join(US_EXCH_PRIORITY) + ' > other US venue > XS/XB ticker less "USD"; '
                 'without an active US line, a candidate ticker whose exchCode-US record has the same '
                 'share-class FIGI or name; unmapped, or delisted under another ticker: the latest ticker '
                 "N-PORT reported, resolved the same way; ticker normalised to Yahoo style ('/' and '.' -> '-'); "
                 'status active | delisted (last ticker kept) | reused (ticker now another security: null) | unmapped'),
        ('n_entries', len(entries)),
        ('n_mapped', sum(1 for e in entries.values() if e.get('ticker'))),
        ('by_status', dict(sorted(Counter(str(e.get('status')) for e in entries.values()).items()))),
    ])
    lines = ['{'] + [f' {json.dumps(k)}: {json.dumps(v)},' for k, v in head.items()] + [' "entries": {']
    body = [f'  {json.dumps(k)}: {json.dumps(v, sort_keys=True)}' for k, v in sorted(entries.items())]
    write_atomic(path, '\n'.join(lines + [',\n'.join(body), ' }', '}']) + '\n')


# ---------------------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------------------

def reported_tickers(snapshots):
    """identifier -> (latest valid N-PORT ticker, N-PORT issuer names in order of appearance),
    from each snapshot's equity_securities, oldest first."""
    out = {}
    for securities in snapshots:
        for s in securities:
            if s['id']:
                ticker, names = out.get(s['id'], ('', ()))
                out[s['id']] = (s['reported_ticker'] or ticker, names if s['name'] in names else names + (s['name'],))
    return out


def issuer_successions(snapshots, entries):
    """{old CUSIP: {'successor': new CUSIP, 'ticker': its ticker}} for securities without an
    active mapping that a new CUSIP of the same issuer replaces.

    `snapshots` is each snapshot's equity_securities, oldest first. A CUSIP's first six
    characters are its issuer number; a new issue number under the same issuer and issuer
    name (issuer_key), first held in the snapshot right after the old CUSIP was last held,
    is the old security after a reverse split, a reclassification or a rename. The link is
    made only when exactly one such CUSIP has a ticker and no other security held alongside
    the old CUSIP carries that ticker (two share classes of one issuer never qualify: they
    are held together). Chains resolve to the latest CUSIP's ticker.
    """
    held, first_name, last_name = {}, {}, {}
    for k, securities in enumerate(snapshots):
        for s in securities:
            if s['id_type'] == 'ID_CUSIP':
                held.setdefault(s['id'], []).append(k)
                first_name.setdefault(s['id'], issuer_key(s['name']))
                last_name[s['id']] = issuer_key(s['name'])
    starting = {}
    for sid, ks in held.items():
        starting.setdefault(ks[0], []).append(sid)
    out = {}

    def ticker(sid):
        return out[sid]['ticker'] if sid in out else (entries.get(sid) or {}).get('ticker')

    for old in sorted(held, key=lambda sid: (-held[sid][-1], sid)):       # successors first
        if (entries.get(old) or {}).get('status') == 'active' or not last_name[old]:
            continue
        nxt = [new for new in starting.get(held[old][-1] + 1, ())
               if new[:6] == old[:6] and first_name[new] == last_name[old] and ticker(new)]
        if len(nxt) != 1:
            continue
        t = ticker(nxt[0])
        if any(s['id'] != old and ticker(s['id']) == t for k in held[old] for s in snapshots[k] if s['id']):
            continue
        out[old] = {'successor': nxt[0], 'ticker': t}
    return out


def snapshot_rows(securities, entries, successions=None):
    """CSV rows (ticker, cusip, isin, name, weight) by descending weight; weight = value share."""
    total = sum(s['val_usd'] for s in securities)
    if total <= 0:
        raise ValueError('snapshot has no equity value')
    successions = successions or {}
    rows = []
    for s in securities:
        if s['id'] in successions:
            ticker = successions[s['id']]['ticker']
        else:
            ticker = ((entries.get(s['id']) if s['id'] else None) or {}).get('ticker') or ''
        rows.append({'ticker': ticker, 'cusip': s['cusip'], 'isin': s['isin'],
                     'name': s['name'], 'weight': s['val_usd'] / total})
    rows.sort(key=lambda r: (-r['weight'], r['cusip'], r['isin'], r['name']))
    return rows


def write_snapshot(rows, path):
    with open(path, 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['ticker', 'cusip', 'isin', 'name', 'weight'])
        for r in rows:
            w.writerow([r['ticker'], r['cusip'], r['isin'], r['name'], f"{r['weight']:.9g}"])


def snapshot_entry(filing, parsed, securities, rows, sha256, source_url, filename):
    mapped = [r for r in rows if r['ticker']]
    tickers = [r['ticker'] for r in mapped]
    dupes = sorted({t for t in tickers if tickers.count(t) > 1})
    entry = OrderedDict([
        ('period_date', parsed['period_date']), ('filing_date', filing['filing_date']),
        ('accession', filing['accession']), ('form', filing['form']), ('source_url', source_url),
        ('sha256', sha256), ('file', filename),
        ('n_holdings', len(parsed['holdings'])), ('n_equity', len(securities)), ('n_mapped', len(mapped)),
        ('n_tickers', len(set(tickers))),
        ('mapped_value_share', round(sum(r['weight'] for r in mapped), 6)),
        ('equity_value_usd', round(sum(s['val_usd'] for s in securities), 2)),
    ])
    if dupes:
        entry['shared_tickers'] = dupes
    if filing.get('supersedes'):
        entry['supersedes'] = filing['supersedes']
    return entry


def _cached(path, url, offline, refresh=False):
    path = pathlib.Path(path)
    if path.exists() and not refresh:
        return path.read_bytes()
    if offline:
        raise SystemExit(f'--offline: {path} is not cached (source: {url})')
    blob = sec_get(url)
    write_atomic(path, blob)
    return blob


def latest_per_period(filings):
    """One filing per period date: an amendment (filed later) replaces the original."""
    by_period = OrderedDict()
    for f in sorted(filings, key=lambda f: (f['period_date'], f['filing_date'], f['accession'])):
        prev = by_period.get(f['period_date'])
        if prev is not None:
            f = dict(f, supersedes=prev.get('supersedes', []) + [prev['accession']])
        by_period[f['period_date']] = f
    return list(by_period.values())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--offline', action='store_true', help='rebuild from data/raw/nport and the committed map only')
    ap.add_argument('--include-sealed', action='store_true',
                    help=f'also download snapshots dated {SEALED_FROM} or later (the sealed holdout)')
    ap.add_argument('--remap-missing', action='store_true',
                    help='query OpenFIGI again for identifiers without an active US listing')
    ap.add_argument('--openfigi-cache', default=str(ROOT / 'data' / 'raw' / 'openfigi' / 'responses.json'))
    ap.add_argument('--raw-dir', default=str(ROOT / 'data' / 'raw' / 'nport'))
    ap.add_argument('--out-dir', default=str(ROOT / 'reference' / 'universe'))
    args = ap.parse_args(argv)
    raw, out = pathlib.Path(args.raw_dir), pathlib.Path(args.out_dir)
    map_path = out / 'cusip_ticker_map.json'

    filings = parse_filing_list(_cached(raw / 'filings.atom', FILINGS_URL, args.offline, refresh=not args.offline))
    for f in filings:
        hdr = _cached(raw / f"{f['accession']}.hdr", folder_url(f['accession'])
                      + f"{f['accession']}-index-headers.html", args.offline).decode('latin-1')
        meta = parse_header(hdr)
        if SERIES_ID not in meta['series']:
            raise SystemExit(f"{f['accession']}: series {meta['series']} is not {SERIES_ID}")
        f['period_date'] = meta['period_date']
    filings = latest_per_period(filings)
    sealed = [f for f in filings if f['period_date'] >= SEALED_FROM and not args.include_sealed]
    active = [f for f in filings if f not in sealed]

    parsed_all = []
    for f in active:
        folder = folder_url(f['accession'])
        name = primary_doc_name(_cached(raw / f"{f['accession']}.index.json", folder + 'index.json', args.offline))
        blob = _cached(raw / f"{f['accession']}.xml", folder + name, args.offline)
        parsed = parse_nport(blob)
        if parsed['series_id'] != SERIES_ID or parsed['period_date'] != f['period_date']:
            raise SystemExit(f"{f['accession']}: document says series {parsed['series_id']}, period "
                             f"{parsed['period_date']}; header says {SERIES_ID}, {f['period_date']}")
        parsed_all.append((f, parsed, equity_securities(parsed['holdings']), hashlib.sha256(blob).hexdigest(),
                           folder + name))

    entries = read_map(map_path)
    held = [securities for _, _, securities, _, _ in parsed_all]
    if not args.offline:
        wanted = OrderedDict()
        for securities in held:
            for s in securities:
                if s['id'] and (s['id'] not in entries
                                or (args.remap_missing and entries[s['id']].get('status') != 'active')):
                    wanted[s['id']] = s['id_type']
        if wanted:
            print(f'OpenFIGI: mapping {len(wanted)} identifiers', flush=True)
            query_openfigi(list(wanted.items()), entries, map_path, args.openfigi_cache,
                           os.environ.get('OPENFIGI_API_KEY'), refresh=args.remap_missing,
                           reported=reported_tickers(held))
        held_ids = {s['id'] for securities in held for s in securities if s['id']}
        if set(entries) - held_ids:                         # identifiers no snapshot holds any more
            entries = {k: e for k, e in entries.items() if k in held_ids}
            write_map(entries, map_path)
    successions = issuer_successions(held, entries)

    out.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for f, parsed, securities, sha, url in parsed_all:
        rows = snapshot_rows(securities, entries, successions)
        filename = f"iwv_{parsed['period_date']}.csv"
        write_snapshot(rows, out / filename)
        snapshots.append(snapshot_entry(f, parsed, securities, rows, sha, url, filename))
    keep = {s['file'] for s in snapshots}
    for stale in out.glob('iwv_*.csv'):
        if stale.name not in keep:
            stale.unlink()
    index = OrderedDict([
        ('fund', 'iShares Russell 3000 ETF (IWV)'), ('trust_cik', TRUST_CIK), ('series_id', SERIES_ID),
        ('filings_url', FILINGS_URL),
        ('holdings', 'assetCat EC (equity common) of each N-PORT-P primary_doc.xml; one row per CUSIP '
                     '(ISIN where N-PORT gives no CUSIP)'),
        ('weight', 'valUSD / total valUSD of the equity-common holdings on the period date'),
        ('membership_rule', 'a snapshot is in force from its period_date until the next snapshot'),
        ('ticker_map', 'cusip_ticker_map.json (OpenFIGI, with the tickers N-PORT reports); a CUSIP listed '
                       'under "successions" takes its successor CUSIP\'s ticker'),
        ('successions', OrderedDict((old, successions[old]) for old in sorted(successions))),
        ('sealed_from', SEALED_FROM),
        ('sealed', [OrderedDict([('period_date', f['period_date']), ('filing_date', f['filing_date']),
                                 ('accession', f['accession']), ('form', f['form'])]) for f in sealed]),
        ('snapshots', snapshots),
    ])
    write_atomic(out / 'index.json', json.dumps(index, indent=1) + '\n')

    print(f"{'period':<11} {'filed':<11} {'holdings':>8} {'equity':>7} {'mapped':>7} {'value mapped':>12}")
    for s in snapshots:
        print(f"{s['period_date']:<11} {s['filing_date']:<11} {s['n_holdings']:>8} {s['n_equity']:>7} "
              f"{s['n_mapped']:>7} {s['mapped_value_share']:>11.2%}")
    if sealed:
        print(f"sealed (not downloaded): {', '.join(f['period_date'] for f in sealed)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
