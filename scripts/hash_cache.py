#!/usr/bin/env python3
"""Fingerprint a price cache symbol by symbol, so a later fetch can be diffed without the prices.

A run records its price cache's sha256 (headline_metrics.json, run_config.data.price_cache), but
one hash over a 1.2 GB pickle says only "same" or "different": when the development caches were
lost with the working storage (docs/PROGRESS.md, 2026-10-22), nothing could say which symbols a
re-fetch matched. This script writes, for every symbol in the cache, its first and last bar,
its number of bars and a sha256 of each of the four fetched series the study reads: Close
(adjusted for splits and dividends), Volume, Dividends and Stock Splits. The prices themselves
are not in the output, so it can be committed without redistributing the vendor's data.

Encoding, per series: sha256 over the bar dates as int64 days since 1970-01-01 (the bar's local
date) followed by the values as little-endian float64, every NaN written as the one canonical
quiet NaN. Two caches with the same bars and the same numbers to the last bit give the same hash
on any platform; a revision of one value in one bar changes it.

The fetch manifest written next to the cache and, when given, the macro cache are hashed too
(the macro cache series by series, with the same encoding).

usage: python scripts/hash_cache.py [--prices data/enhanced_russell_3000_data.pkl]
                                    [--macro data/macro_data.pkl] [--out FILE]
       python scripts/hash_cache.py --compare A.json B.json     (counts of matching symbols)
"""
import argparse
import hashlib
import json
import pathlib
import pickle
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERIES = {'close': 'Close', 'volume': 'Volume', 'dividends': 'Dividends', 'splits': 'Stock Splits'}
CANONICAL_NAN = np.frombuffer(np.array([np.nan], dtype='<f8').tobytes(), dtype='<f8')[0]
ENCODING = ('per series: sha256 over the bar dates as little-endian int64 days since 1970-01-01 '
            '(the local date of the bar) followed by the values as little-endian float64, every '
            'NaN as the canonical quiet NaN')


def file_record(path: pathlib.Path) -> dict:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return {'path': _rel(path), 'sha256': h.hexdigest(), 'bytes': path.stat().st_size}


def _rel(path: pathlib.Path) -> str:
    path = pathlib.Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _days(index) -> np.ndarray:
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return (idx.normalize().values.astype('datetime64[D]').astype('<i8'))


def series_sha256(index, values) -> str:
    """The documented encoding of one dated series."""
    v = np.asarray(values, dtype='<f8').copy()
    v[np.isnan(v)] = CANONICAL_NAN
    h = hashlib.sha256()
    h.update(_days(index).tobytes())
    h.update(v.tobytes())
    return h.hexdigest()


def symbol_record(df: pd.DataFrame) -> dict:
    rec = {'bars': int(len(df)),
           'first': str(pd.DatetimeIndex(df.index)[0].date()) if len(df) else None,
           'last': str(pd.DatetimeIndex(df.index)[-1].date()) if len(df) else None}
    for key, col in SERIES.items():
        rec[key] = series_sha256(df.index, df[col]) if col in df.columns else None
    return rec


def combined(symbols: dict) -> str:
    """One hash over every symbol's record, in symbol order."""
    h = hashlib.sha256()
    for sym in sorted(symbols):
        r = symbols[sym]
        h.update(f"{sym} {r['bars']} {r['first']} {r['last']} "
                 f"{' '.join(str(r[k]) for k in SERIES)}\n".encode())
    return h.hexdigest()


def macro_records(macro) -> dict:
    """{name: {'bars', 'first', 'last', 'sha256'}} for every dated numeric series in the macro cache."""
    out = {}

    def add(name, s):
        s = pd.to_numeric(pd.Series(s), errors='coerce')
        if not isinstance(s.index, pd.DatetimeIndex):
            return
        out[name] = {'bars': int(len(s)), 'first': str(s.index[0].date()) if len(s) else None,
                     'last': str(s.index[-1].date()) if len(s) else None,
                     'sha256': series_sha256(s.index, s.to_numpy())}

    def walk(prefix, obj):
        if isinstance(obj, pd.Series):
            add(prefix, obj)
        elif isinstance(obj, pd.DataFrame):
            for col in obj.columns:
                if pd.api.types.is_numeric_dtype(obj[col]):
                    add(f'{prefix}.{col}' if prefix else str(col), obj[col])
        elif isinstance(obj, dict):
            for k in sorted(obj, key=str):
                walk(f'{prefix}.{k}' if prefix else str(k), obj[k])
    walk('', macro)
    return out


def fingerprint(prices: pathlib.Path, macro: pathlib.Path = None, manifest: pathlib.Path = None) -> dict:
    with open(prices, 'rb') as f:
        cache = pickle.load(f)
    if not isinstance(cache, dict):
        raise SystemExit(f"{prices} is not a price cache (a dict of symbol -> DataFrame)")
    symbols = {s: symbol_record(cache[s]) for s in sorted(cache)}
    manifest = manifest or pathlib.Path(str(prices).replace('.pkl', '_manifest.json'))
    doc = {
        'schema': 1,
        'what': 'per-symbol fingerprints of a price cache (scripts/hash_cache.py); no prices',
        'encoding': ENCODING,
        'series': SERIES,
        'price_cache': file_record(prices),
        'fetch_manifest': file_record(manifest) if manifest.exists() else None,
        'n_symbols': len(symbols),
        'symbols_sha256': combined(symbols),
        'symbols': symbols,
    }
    if macro is not None:
        with open(macro, 'rb') as f:
            m = pickle.load(f)
        doc['macro_cache'] = dict(file_record(macro), series=macro_records(m))
    return doc


def compare(a: dict, b: dict) -> dict:
    """Symbol-by-symbol agreement of two fingerprints."""
    sa, sb = a['symbols'], b['symbols']
    both = sorted(set(sa) & set(sb))
    out = {'only_a': len(set(sa) - set(sb)), 'only_b': len(set(sb) - set(sa)), 'both': len(both),
           'identical': sum(1 for s in both if all(sa[s][k] == sb[s][k] for k in ('bars', 'first', 'last', *SERIES)))}
    for k in ('bars', 'first', 'last', *SERIES):
        out[f'same_{k}'] = sum(1 for s in both if sa[s][k] == sb[s][k])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--prices', default='data/enhanced_russell_3000_data.pkl')
    ap.add_argument('--macro', help='also fingerprint this macro cache (e.g. data/macro_data.pkl)')
    ap.add_argument('--manifest', help="the cache's fetch manifest (default: next to the cache)")
    ap.add_argument('--out', help='write here (default: stdout)')
    ap.add_argument('--compare', nargs=2, metavar=('A', 'B'), help='compare two fingerprint files')
    args = ap.parse_args(argv)
    if args.compare:
        a, b = (json.loads(pathlib.Path(p).read_text()) for p in args.compare)
        print(json.dumps(compare(a, b), indent=1))
        return 0
    doc = fingerprint(pathlib.Path(args.prices), pathlib.Path(args.macro) if args.macro else None,
                      pathlib.Path(args.manifest) if args.manifest else None)
    text = json.dumps(doc, indent=1, sort_keys=True) + '\n'
    if args.out:
        pathlib.Path(args.out).write_text(text)
        print(f"{args.out}: {doc['n_symbols']} symbols, sha256 {doc['price_cache']['sha256'][:16]}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
