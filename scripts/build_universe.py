#!/usr/bin/env python3
"""Build data/marketcap.csv — the study universe — from the Nasdaq stock screener.

The Russell 3000 is, by FTSE Russell's rule, the 3,000 largest US companies by total market
capitalisation. The original v31 universe file was never redistributed, so v32 rebuilds it
with that rule: every US-listed common stock in the Nasdaq screener (NASDAQ, NYSE, NYSE
American) whose country is the United States, excluding preferreds, warrants, units, rights,
notes and depositary receipts, ranked by market cap, top N (default 3,000).

This is an approximation of the index, not FTSE Russell's constituent list: membership is
as of the download date (so it has the same survivorship bias the README discloses), the
float and eligibility screens Russell applies are not reproduced, and the screener's
market caps are the vendor's. The output records the source and the as-of date.

usage: python scripts/build_universe.py [--n 3000] [--input screener.json] [--out data/marketcap.csv]
"""
import argparse
import json
import pathlib
import re
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
URL = 'https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true'
EXCLUDE_NAME = re.compile(r'\b(preferred|warrants?|units?|rights?|notes?|depositary|debentures?|'
                          r'trust preferred|subordinated|perpetual)\b', re.I)


def fetch(url=URL):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/126 Safari/537.36',
        'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def select(rows, n):
    picked = []
    for r in rows:
        sym = (r.get('symbol') or '').strip()
        name = (r.get('name') or '').strip()
        if not sym or '^' in sym or (r.get('country') or '') != 'United States':
            continue
        if EXCLUDE_NAME.search(name):
            continue
        try:
            cap = float(r.get('marketCap') or 0)
        except ValueError:
            continue
        if cap <= 0:
            continue
        picked.append({'Symbol': sym.replace('/', '-'), 'Name': name, 'MarketCap': cap,
                       'Sector': r.get('sector') or '', 'Industry': r.get('industry') or ''})
    picked.sort(key=lambda x: (-x['MarketCap'], x['Symbol']))
    seen, out = set(), []
    for p in picked:
        if p['Symbol'] not in seen:
            seen.add(p['Symbol'])
            out.append(p)
    return out[:n]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--n', type=int, default=3000)
    ap.add_argument('--input', help='a saved screener JSON instead of downloading')
    ap.add_argument('--out', default=str(ROOT / 'data' / 'marketcap.csv'))
    args = ap.parse_args(argv)
    data = json.loads(pathlib.Path(args.input).read_text()) if args.input else fetch()
    rows = data['data']['rows']
    universe = select(rows, args.n)
    as_of = datetime.now(timezone.utc).date().isoformat()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['Symbol', 'Name', 'MarketCap', 'Sector', 'Industry'])
        w.writeheader()
        w.writerows(universe)
    meta = {'source': URL, 'rule': f'top {args.n} US common stocks by market cap', 'as_of_utc': as_of,
            'screener_rows': len(rows), 'selected': len(universe),
            'smallest_market_cap': universe[-1]['MarketCap'] if universe else None}
    out.with_suffix('.meta.json').write_text(json.dumps(meta, indent=1))
    print(f"{len(universe)} symbols (from {len(rows)} screener rows) -> {out}; smallest cap "
          f"${meta['smallest_market_cap'] / 1e6:,.0f}M; as of {as_of}")
    return 0 if len(universe) >= min(args.n, 1000) else 1


if __name__ == '__main__':
    sys.exit(main())
