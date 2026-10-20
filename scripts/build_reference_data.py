#!/usr/bin/env python3
"""Build the per-ticker reference tables: Fama-French 49 industry, sector ETF, listing venue.

(a) reference/industry_ff49.csv (ticker, cik, sic, ff49, ff49_name, sector_etf, entity_type)
    for every ticker in any reference/universe/iwv_*.csv snapshot or in data/marketcap.csv:
    ticker -> CIK from SEC's company_tickers.json, SIC and entity type from the EDGAR
    submissions API, SIC -> Fama-French 49 industry from Ken French's Siccodes49 ranges,
    industry -> Select Sector SPDR from the fixed table below. A ticker SEC no longer
    lists (delisted, or renamed since) gets blank fields. A SIC that no FF49 range lists
    goes to 49 'Other', French's catch-all; SIC 0 or missing (most BDCs, some funds) is
    left unclassified.
(b) reference/listing_venue.csv (ticker, venue, etf_flag, as_of) from Nasdaq Trader's
    nasdaqtraded.txt directory (every non-test issue, ETFs flagged).

Both are as of the download date, not point-in-time: EDGAR keeps one current SIC per
registrant (industry changes are rare) and the directory lists today's venue.

Raw downloads are cached under data/raw/ (sec/, french/, nasdaqtrader/); a cached file is
reused unless --refresh, and --offline never touches the network. EDGAR requests carry
SEC_USER_AGENT and stay under 10 per second.

usage: python scripts/build_reference_data.py [--offline] [--refresh]
"""
import argparse
import csv
import io
import json
import pathlib
import re
import sys
import urllib.error
import zipfile
from collections import Counter
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pairs_trading.external_data import http_get, sec_get, write_atomic  # noqa: E402
from pairs_trading.universe import normalise_ticker  # noqa: E402

COMPANY_TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
SUBMISSIONS_URL = 'https://data.sec.gov/submissions/CIK{cik:010d}.json'
SICCODES49_URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Siccodes49.zip'
NASDAQ_TRADED_URL = 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt'

# Fama-French 49 industry -> Select Sector SPDR, following the GICS sector that holds most
# of the industry's market value (GICS as revised in 2018 and 2023).
FF49_SECTOR_ETF = {
    'Agric': 'XLP',   # crop and livestock producers: GICS Food Products
    'Food': 'XLP',    # packaged foods: GICS Food Products
    'Soda': 'XLP',    # soft drinks and confectionery: GICS Beverages / Food Products
    'Beer': 'XLP',    # brewers and distillers: GICS Beverages
    'Smoke': 'XLP',   # tobacco: GICS Tobacco
    'Toys': 'XLY',    # recreational products and boats: GICS Leisure Products
    'Fun': 'XLC',     # motion pictures, video distribution, live entertainment: GICS Entertainment
    'Books': 'XLC',   # newspapers and publishing: GICS Publishing (Media)
    'Hshld': 'XLP',   # soaps, cosmetics, household products dominate by value: GICS Household & Personal Products
    'Clths': 'XLY',   # apparel and footwear: GICS Textiles, Apparel & Luxury Goods
    'Hlth': 'XLV',    # hospitals, labs, nursing: GICS Health Care Providers & Services
    'MedEq': 'XLV',   # medical instruments and supplies: GICS Health Care Equipment
    'Drugs': 'XLV',   # pharmaceuticals and biologics: GICS Pharmaceuticals / Biotechnology
    'Chems': 'XLB',   # chemicals: GICS Chemicals
    'Rubbr': 'XLB',   # plastic and rubber products, packaging: GICS Materials
    'Txtls': 'XLY',   # textile mills and home textiles: GICS Textiles & Apparel
    'BldMt': 'XLI',   # millwork, fixtures, structural products: GICS Building Products
    'Cnstr': 'XLI',   # heavy and specialty contractors: GICS Construction & Engineering
    'Steel': 'XLB',   # steel and metal works: GICS Metals & Mining
    'FabPr': 'XLI',   # fabricated metal products: GICS Machinery / Building Products
    'Mach': 'XLI',    # machinery: GICS Machinery
    'ElcEq': 'XLI',   # electrical equipment: GICS Electrical Equipment
    'Autos': 'XLY',   # motor vehicles and parts: GICS Automobiles & Components
    'Aero': 'XLI',    # aircraft and parts: GICS Aerospace & Defense
    'Ships': 'XLI',   # ship and railroad equipment: GICS Machinery
    'Guns': 'XLI',    # ordnance: GICS Aerospace & Defense
    'Gold': 'XLB',    # precious metals mining: GICS Metals & Mining
    'Mines': 'XLB',   # industrial metal and non-metallic mining, aggregates: GICS Materials
    'Coal': 'XLE',    # coal: GICS Coal & Consumable Fuels
    'Oil': 'XLE',     # oil and gas extraction, refining, services: GICS Energy
    'Util': 'XLU',    # electric, gas and water utilities: GICS Utilities
    'Telcm': 'XLC',   # telephone, cable and broadcasting: GICS Communication Services
    'PerSv': 'XLY',   # education, funeral, laundry and personal services: GICS Diversified Consumer Services
    'BusSv': 'XLI',   # business, staffing and data services: GICS Commercial & Professional Services
    'Hardw': 'XLK',   # computers and peripherals: GICS Technology Hardware
    'Softw': 'XLK',   # software and data processing: GICS Software & Services
    'Chips': 'XLK',   # semiconductors and electronic components: GICS Semiconductors
    'LabEq': 'XLK',   # measuring and control instruments: GICS Electronic Equipment & Instruments
    'Paper': 'XLB',   # paper and business supplies: GICS Paper & Forest Products
    'Boxes': 'XLB',   # shipping containers: GICS Containers & Packaging
    'Trans': 'XLI',   # railroads, trucking, airlines, shipping: GICS Transportation
    'Whlsl': 'XLI',   # distributors: GICS Trading Companies & Distributors
    'Rtail': 'XLY',   # retailers: GICS Consumer Discretionary Distribution & Retail
    'Meals': 'XLY',   # restaurants and hotels: GICS Hotels, Restaurants & Leisure
    'Banks': 'XLF',   # banks, thrifts, consumer and mortgage lenders: GICS Banks / Consumer Finance
    'Insur': 'XLF',   # insurers and brokers: GICS Insurance
    'RlEst': 'XLRE',  # real-estate operators, agents and developers: GICS Real Estate Management & Development
    'Fin': 'XLF',     # brokers, exchanges, asset managers, holding companies: GICS Capital Markets
    'Other': None,    # French's catch-all; only its listed SIC ranges are assigned below
}

# SIC codes whose GICS sector differs from their FF49 industry's (inclusive ranges), by the
# same rule: the sector holding most of the code's market value.
SECTOR_ETF_SIC_OVERRIDES = (
    (1531, 1531, 'XLY'),   # operative builders: GICS Homebuilding
    (3826, 3826, 'XLV'),   # laboratory analytical instruments: GICS Life Sciences Tools & Services
    (4400, 4400, 'XLY'),   # water transportation, by value the cruise lines: GICS Hotels, Restaurants & Leisure
    (4700, 4700, 'XLY'),   # transportation services, by value the online travel agencies: GICS Hotels, Restaurants & Leisure
    (4950, 4959, 'XLI'),   # sanitary services: GICS Environmental & Facilities Services
    (4960, 4961, 'XLU'),   # steam and air-conditioning supply: GICS Utilities
    (4970, 4971, 'XLU'),   # irrigation systems: GICS Water Utilities
    (4990, 4991, 'XLU'),   # cogeneration: GICS Independent Power Producers
    (5047, 5047, 'XLV'),   # medical, dental and hospital equipment wholesale: GICS Health Care Distributors
    (5122, 5122, 'XLV'),   # drug wholesale: GICS Health Care Distributors
    (5140, 5149, 'XLP'),   # grocery wholesale: GICS Food Distributors
    (5330, 5331, 'XLP'),   # variety stores: GICS Consumer Staples Merchandise Retail (2023)
    (5399, 5399, 'XLP'),   # warehouse clubs and general merchandise: GICS Consumer Staples Merchandise Retail
    (5410, 5411, 'XLP'),   # grocery stores: GICS Food Retail
    (5910, 5912, 'XLP'),   # drug stores: GICS Drug Retail
    (6324, 6324, 'XLV'),   # hospital and medical service plans: GICS Managed Health Care
    (6798, 6798, 'XLRE'),  # real estate investment trusts: GICS Real Estate (Equity REITs)
    (7370, 7370, 'XLC'),   # computer programming and data processing, by value Alphabet and Meta: GICS Interactive Media
    (7389, 7389, 'XLF'),   # business services n.e.c., by value the card networks and processors: GICS Financials (2023)
    (8731, 8731, 'XLV'),   # commercial biological research, contract research organisations: GICS Life Sciences Tools
)

# nasdaqtraded.txt 'Listing Exchange' codes.
VENUES = {'N': 'NYSE', 'Q': 'Nasdaq', 'A': 'NYSE American', 'P': 'NYSE Arca', 'Z': 'Cboe BZX', 'V': 'IEX',
          'M': 'NYSE Texas', 'F': 'TXSE'}


def _cached(path, url, offline, refresh, fetch=None):
    path = pathlib.Path(path)
    if path.exists() and not refresh:
        return path.read_bytes()
    if offline:
        raise SystemExit(f'--offline: {path} is not cached (source: {url})')
    blob = (fetch or (lambda u: http_get(u, headers={'User-Agent': 'Mozilla/5.0 (research)'})))(url)
    write_atomic(path, blob)
    return blob


# ---------------------------------------------------------------------------------------
# Fama-French 49 industries
# ---------------------------------------------------------------------------------------

def parse_siccodes(text):
    """French's SiccodesNN.txt -> [(sic_lo, sic_hi, number, short_name)] and {number: (short, long)}.

    Industry lines read ' 1 Agric  Agriculture'; each following indented line opens with
    an inclusive SIC range 'dddd-dddd' and a description.
    """
    ranges, names, current = [], {}, None
    for line in text.splitlines():
        rng = re.match(r'\s+(\d{4})-(\d{4})\b', line)
        if rng:
            if current is None:
                raise ValueError(f'SIC range before any industry: {line!r}')
            ranges.append((int(rng.group(1)), int(rng.group(2)), current, names[current][0]))
            continue
        ind = re.match(r'\s?(\d{1,2})\s+(\S+)\s+(.*\S)', line)
        if ind:
            current = int(ind.group(1))
            names[current] = (ind.group(2), ind.group(3))
    if not ranges:
        raise ValueError('no SIC ranges found')
    return ranges, names


def ff49_of(sic, ranges, names):
    """(number, short name) of the FF49 industry for `sic`; unlisted SICs go to 49 'Other'.

    SIC 0 or None (no industry on file) returns None.
    """
    if not sic:
        return None
    for lo, hi, num, short in ranges:
        if lo <= sic <= hi:
            return num, short
    other = next(num for num, (short, _) in names.items() if short == 'Other')
    return other, 'Other'


def sector_etf(sic, ff49_short):
    """Select Sector SPDR for a stock: the SIC override if one applies, else its FF49 industry's."""
    if sic:
        for lo, hi, etf in SECTOR_ETF_SIC_OVERRIDES:
            if lo <= sic <= hi:
                return etf
    return FF49_SECTOR_ETF.get(ff49_short) if ff49_short else None


# ---------------------------------------------------------------------------------------
# Listing venues
# ---------------------------------------------------------------------------------------

def parse_nasdaq_traded(text):
    """nasdaqtraded.txt -> (rows of ticker, venue, etf_flag; file creation date).

    Pipe-delimited with a header row and a closing 'File Creation Time: MMDDYYYYHH:MM'
    line; test issues are dropped and symbols normalised to Yahoo style (BF.B -> BF-B).
    """
    lines = text.strip().splitlines()
    stamp = re.match(r'File Creation Time:\s*(\d{2})(\d{2})(\d{4})', lines[-1])
    if not stamp:
        raise ValueError('nasdaqtraded.txt: no File Creation Time line')
    as_of = f'{stamp.group(3)}-{stamp.group(1)}-{stamp.group(2)}'
    rows = {}
    for rec in csv.DictReader(io.StringIO('\n'.join(lines[:-1])), delimiter='|'):
        if rec['Test Issue'] == 'Y':
            continue
        code = rec['Listing Exchange'].strip()
        ticker = normalise_ticker(rec['Symbol'])
        if ticker and ticker not in rows:
            rows[ticker] = {'ticker': ticker, 'venue': VENUES.get(code, code), 'etf_flag': rec['ETF'] == 'Y'}
    return [rows[t] for t in sorted(rows)], as_of


# ---------------------------------------------------------------------------------------
# EDGAR
# ---------------------------------------------------------------------------------------

def ticker_ciks(company_tickers):
    """Normalised ticker -> CIK from SEC's company_tickers.json."""
    out = {}
    for rec in json.loads(company_tickers).values():
        out.setdefault(normalise_ticker(rec['ticker']), int(rec['cik_str']))
    return out


def submission_summary(blob):
    """The fields kept from an EDGAR submissions JSON (the full file runs to megabytes)."""
    d = json.loads(blob)
    sic = d.get('sic')
    return {'name': d.get('name'), 'entityType': d.get('entityType'),
            'sic': int(sic) if sic and str(sic).isdigit() else None,
            'sicDescription': d.get('sicDescription'), 'tickers': d.get('tickers') or [],
            'exchanges': d.get('exchanges') or []}


def study_tickers(universe_dir, marketcap_csv):
    """Every ticker in a committed IWV snapshot or in the v32 universe file."""
    tickers = set()
    for path in sorted(pathlib.Path(universe_dir).glob('iwv_*.csv')):
        with open(path, newline='') as f:
            tickers.update(r['ticker'] for r in csv.DictReader(f) if r['ticker'])
    if pathlib.Path(marketcap_csv).exists():
        with open(marketcap_csv, newline='') as f:
            tickers.update(normalise_ticker(r.get('Symbol') or r.get('Ticker')) for r in csv.DictReader(f))
    tickers.discard('')
    return sorted(tickers)


def fetch_submissions(ciks, cache_path, offline, refresh):
    """CIK -> submission summary, cached in one JSON file and saved every 200 fetches."""
    cache_path = pathlib.Path(cache_path)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() and not refresh else {}
    todo = [c for c in ciks if str(c) not in cache]
    if todo and offline:
        raise SystemExit(f'--offline: {len(todo)} CIKs are not in {cache_path}')
    for n, cik in enumerate(todo, start=1):
        try:
            summary = submission_summary(sec_get(SUBMISSIONS_URL.format(cik=cik)))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            summary = {'error': 'HTTP 404'}
        cache[str(cik)] = dict(summary, fetched_on=datetime.now(timezone.utc).date().isoformat())
        if n % 200 == 0 or n == len(todo):
            write_atomic(cache_path, json.dumps(cache, sort_keys=True, indent=0))
            print(f'  EDGAR submissions: {n}/{len(todo)}', flush=True)
    return cache


def industry_rows(tickers, ciks, submissions, ranges, names):
    rows = []
    for t in tickers:
        cik = ciks.get(t)
        sub = submissions.get(str(cik), {}) if cik else {}
        sic = sub.get('sic')
        ind = ff49_of(sic, ranges, names)
        rows.append({'ticker': t, 'cik': cik or '', 'sic': sic or '',
                     'ff49': ind[0] if ind else '', 'ff49_name': ind[1] if ind else '',
                     'sector_etf': (sector_etf(sic, ind[1]) if ind else None) or '',
                     'entity_type': sub.get('entityType') or ''})
    return rows


def write_csv(rows, columns, path):
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--offline', action='store_true', help='rebuild from the caches under data/raw/ only')
    ap.add_argument('--refresh', action='store_true', help='download every source again')
    ap.add_argument('--raw-dir', default=str(ROOT / 'data' / 'raw'))
    ap.add_argument('--reference-dir', default=str(ROOT / 'reference'))
    ap.add_argument('--marketcap', default=str(ROOT / 'data' / 'marketcap.csv'))
    args = ap.parse_args(argv)
    raw, ref = pathlib.Path(args.raw_dir), pathlib.Path(args.reference_dir)

    sic_zip = _cached(raw / 'french' / 'Siccodes49.zip', SICCODES49_URL, args.offline, args.refresh)
    with zipfile.ZipFile(io.BytesIO(sic_zip)) as zf:
        ranges, names = parse_siccodes(zf.read('Siccodes49.txt').decode('latin-1'))
    if sorted(names) != list(range(1, 50)) or set(FF49_SECTOR_ETF) != {v[0] for v in names.values()}:
        raise SystemExit('Siccodes49.zip does not define the 49 industries FF49_SECTOR_ETF expects')

    tickers = study_tickers(ref / 'universe', args.marketcap)
    ciks = ticker_ciks(_cached(raw / 'sec' / 'company_tickers.json', COMPANY_TICKERS_URL, args.offline,
                               args.refresh, fetch=sec_get))
    wanted = sorted({ciks[t] for t in tickers if t in ciks})
    print(f'{len(tickers)} tickers, {sum(t in ciks for t in tickers)} with a CIK ({len(wanted)} registrants)', flush=True)
    submissions = fetch_submissions(wanted, raw / 'sec' / 'submissions_summary.json', args.offline, args.refresh)
    rows = industry_rows(tickers, ciks, submissions, ranges, names)
    write_csv(rows, ['ticker', 'cik', 'sic', 'ff49', 'ff49_name', 'sector_etf', 'entity_type'],
              ref / 'industry_ff49.csv')

    listing, as_of = parse_nasdaq_traded(_cached(raw / 'nasdaqtrader' / 'nasdaqtraded.txt', NASDAQ_TRADED_URL,
                                                 args.offline, args.refresh).decode('latin-1'))
    write_csv([dict(r, etf_flag='Y' if r['etf_flag'] else 'N', as_of=as_of) for r in listing],
              ['ticker', 'venue', 'etf_flag', 'as_of'], ref / 'listing_venue.csv')

    n_sic = sum(1 for r in rows if r['sic'])
    n_ff = sum(1 for r in rows if r['ff49'])
    print(f'industry_ff49.csv: {len(rows)} tickers, {n_sic} with SIC, {n_ff} with an FF49 industry, '
          f"{sum(1 for r in rows if r['sector_etf'])} with a sector ETF")
    print('  sector ETFs:', dict(Counter(r['sector_etf'] or '-' for r in rows).most_common()))
    print(f"listing_venue.csv: {len(listing)} symbols as of {as_of}; venues "
          f"{dict(Counter(r['venue'] for r in listing).most_common())}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
