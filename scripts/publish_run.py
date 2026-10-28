#!/usr/bin/env python3
"""Copy a finished run's exports into results/<name>/ as committed evidence.

A run writes to its output directory (git-ignored, overwritten by the next run). Publishing
copies its JSON exports there unchanged, adds a cleaned copy of the run log (progress bars
removed, absolute paths made relative) and writes MANIFEST.json: every file's sha256 and
size, and the run's provenance (commit, profile or strategy, calendar, data fingerprint)
read from its headline: headline_metrics.json for a pairs run, the export itself
(residual_statarb.json) for the residual arm. The site and the paper are built only from
results/.

A destination that already holds files is refused, so a later run never mixes its files
with an earlier one's; --replace empties it first. A run whose headline marks it
incomplete or a sensitivity variant (non_default_switches) is refused unless --variant.

When the price cache the headline records is on disk, its per-symbol fingerprints
(scripts/hash_cache.py; the macro cache's too, when recorded and present) are written as
price_cache_hashes.json, so a later fetch can be diffed symbol by symbol. A cache whose sha256
is no longer the one the run recorded is refused: its fingerprints would describe another
cache. --cache-hashes require stops when the cache is missing; skip never fingerprints.

--also GLOB copies other files too (the variant family's daily_returns.csv).

usage: python scripts/publish_run.py OUTPUT_DIR NAME [--log logs/run.log] [--replace] [--variant]
                                     [--cache-hashes auto|require|skip] [--also GLOB ...]
"""
import argparse
import hashlib
import json
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROGRESS = re.compile(r'it/s|s/it|pair/s|symbol/s|\| *\d+/\d+ \[')
# The file that carries a run's provenance, complete flag and switches, by kind of run.
HEADLINE_FILES = ('headline_metrics.json', 'residual_statarb.json')


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def clean_log(text: str) -> str:
    """Drop progress-bar lines and make the repository's absolute path relative."""
    lines = [ln for ln in text.splitlines() if not PROGRESS.search(ln)]
    return '\n'.join(lines).replace(str(ROOT) + '/', './') + '\n'


def cache_fingerprints(data: dict, mode: str = 'auto'):
    """hash_cache.fingerprint of the price (and macro) cache a run recorded, or None.

    None when mode is 'skip', when the run records no cache path, or (mode 'auto') when the
    cache is not on disk. A cache on disk whose sha256 differs from the run's record stops.
    """
    pc = (data or {}).get('price_cache') or {}
    if mode == 'skip' or not pc.get('path'):
        if mode == 'require':
            raise SystemExit("--cache-hashes require: the run records no price cache path")
        return None
    path = ROOT / pc['path']
    if not path.exists():
        if mode == 'require':
            raise SystemExit(f"--cache-hashes require: {pc['path']} is not on disk")
        print(f"note: {pc['path']} is not on disk; no price_cache_hashes.json")
        return None
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import hash_cache
    mc = (data or {}).get('macro_cache') or {}
    macro = ROOT / mc['path'] if mc.get('path') and (ROOT / mc['path']).exists() else None
    doc = hash_cache.fingerprint(path, macro)
    for rec, got in ((pc, doc['price_cache']), (mc, doc.get('macro_cache'))):
        if got is not None and rec.get('sha256') and got['sha256'] != rec['sha256']:
            raise SystemExit(f"{rec['path']} has sha256 {got['sha256'][:16]}, not the run's "
                             f"{rec['sha256'][:16]}: the cache changed after the run")
    return doc


def publish(src: pathlib.Path, name: str, log: pathlib.Path = None, replace: bool = False,
            variant: bool = False, cache_hashes: str = 'auto', also: tuple = ()) -> pathlib.Path:
    dest = ROOT / 'results' / name
    files = sorted({p for pattern in ('*.json', *also) for p in src.glob(pattern) if p.is_file()})
    if not files:
        raise SystemExit(f"no JSON exports in {src}")
    src_head = next((src / n for n in HEADLINE_FILES if (src / n).exists()), None)
    if src_head is not None and not variant:
        h = json.loads(src_head.read_text())
        if h.get('complete') is False or h.get('non_default_switches'):
            raise SystemExit(f"{src} is incomplete or a sensitivity variant (non-default switches "
                             f"{h.get('non_default_switches')}); publish it with --variant")
    old = [p for p in dest.iterdir() if p.is_file()] if dest.exists() else []
    if old and not replace:
        raise SystemExit(f"{dest} already holds {len(old)} files; --replace empties it first")
    for p in old:
        p.unlink()
    dest.mkdir(parents=True, exist_ok=True)
    for p in files:
        shutil.copy2(p, dest / p.name)
    if log is not None:
        (dest / 'run.log').write_text(clean_log(log.read_text(errors='replace')))
    headline = dest / src_head.name if src_head is not None else None
    rc = json.loads(headline.read_text()).get('run_config', {}) if headline is not None else {}
    fp = cache_fingerprints(rc.get('data'), cache_hashes)
    if fp is not None:
        (dest / 'price_cache_hashes.json').write_text(json.dumps(fp, indent=1, sort_keys=True) + '\n')
    manifest = {
        'name': name,
        'run_config': {k: rc.get(k) for k in ('package_version', 'git_commit', 'git_dirty',
                                               'run_timestamp_utc', 'effective')},
        'study': rc.get('study'),
        'price_cache': (rc.get('data') or {}).get('price_cache'),
        'files': {p.name: {'sha256': sha256(p), 'bytes': p.stat().st_size}
                  for p in sorted(dest.iterdir()) if p.is_file() and p.name != 'MANIFEST.json'},
    }
    (dest / 'MANIFEST.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('output_dir')
    ap.add_argument('name', help='results/<name>/, e.g. v33_dev')
    ap.add_argument('--log', help='the run log to clean and include')
    ap.add_argument('--replace', action='store_true', help='empty an existing destination first')
    ap.add_argument('--variant', action='store_true', help='publish an incomplete or variant run')
    ap.add_argument('--cache-hashes', choices=('auto', 'require', 'skip'), default='auto',
                    help="fingerprint the run's price cache (auto: when it is on disk)")
    ap.add_argument('--also', nargs='*', default=(), metavar='GLOB', help='copy these files as well as *.json')
    args = ap.parse_args(argv)
    dest = publish(pathlib.Path(args.output_dir), args.name,
                   pathlib.Path(args.log) if args.log else None, args.replace, args.variant,
                   args.cache_hashes, tuple(args.also))
    print(f"published -> {dest.relative_to(ROOT)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
