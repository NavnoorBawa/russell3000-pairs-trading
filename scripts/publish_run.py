#!/usr/bin/env python3
"""Copy a finished run's exports into results/<name>/ as committed evidence.

A run writes to its output directory (git-ignored, overwritten by the next run). Publishing
copies its JSON exports there unchanged, adds a cleaned copy of the run log (progress bars
removed, absolute paths made relative) and writes MANIFEST.json: every file's sha256 and
size, and the run's provenance (commit, profile, calendar, data fingerprint) read from its
headline export. The site and the paper are built only from results/.

A destination that already holds files is refused, so a later run never mixes its files
with an earlier one's; --replace empties it first. A run whose headline marks it
incomplete or a sensitivity variant (non_default_switches) is refused unless --variant.

usage: python scripts/publish_run.py OUTPUT_DIR NAME [--log logs/run.log] [--replace] [--variant]
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


def publish(src: pathlib.Path, name: str, log: pathlib.Path = None, replace: bool = False,
            variant: bool = False) -> pathlib.Path:
    dest = ROOT / 'results' / name
    files = sorted(p for p in src.glob('*.json') if p.is_file())
    if not files:
        raise SystemExit(f"no JSON exports in {src}")
    src_head = src / 'headline_metrics.json'
    if src_head.exists() and not variant:
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
    headline = dest / 'headline_metrics.json'
    rc = json.loads(headline.read_text()).get('run_config', {}) if headline.exists() else {}
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
    args = ap.parse_args(argv)
    dest = publish(pathlib.Path(args.output_dir), args.name,
                   pathlib.Path(args.log) if args.log else None, args.replace, args.variant)
    print(f"published -> {dest.relative_to(ROOT)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
