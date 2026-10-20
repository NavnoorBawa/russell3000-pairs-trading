#!/usr/bin/env python3
"""Append a trial to results/trial_registry.jsonl, the study's append-only record of runs.

Every configuration whose result was looked at belongs in the registry, whatever it showed:
it is the count behind the deflated Sharpe ratio's number of trials and the evidence that
the 2026 holdout was evaluated once. One JSON line per trial: its name, when it was
registered, the commit it ran from, and for each run its profile and calendar (with their
hashes), the price cache's sha256 and the headline numbers; for the holdout also the
pre-registration commit, the registered test's outcome per strategy with the sha256 of
every file it evaluated, and every attempt at the trial (results/trial_attempts.jsonl,
crashed ones included). A name is registered once: the script refuses a name already in
the file, and never rewrites a line. A trial with a pre-registration commit is refused
when a run is not from --head or not from a clean tree, or when a published export
(MANIFEST.json next to the evaluation) is not the file the evaluation read.

usage: python scripts/register_trial.py --name NAME [--run DIR ...] [--evaluation FILE]
                                        [--prereg-commit SHA] [--head SHA] [--note TEXT]
       python scripts/register_trial.py --name NAME --check-new
DIR is a run's output or results/ directory (with headline_metrics.json).
"""
import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
REGISTRY = ROOT / 'results' / 'trial_registry.jsonl'

from trial_attempts import ATTEMPTS, read_attempts  # noqa: E402


def _git(*args) -> str:
    try:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def read_registry(path: pathlib.Path = REGISTRY) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_summary(directory: pathlib.Path) -> dict:
    """What the registry keeps of one run: provenance and the headline numbers."""
    doc = json.loads((directory / 'headline_metrics.json').read_text())
    rc = doc.get('run_config') or {}
    study = rc.get('study') or {}
    main, oos = doc.get('main') or {}, doc.get('oos') or {}
    return {
        'dir': str(directory.resolve().relative_to(ROOT)) if directory.resolve().is_relative_to(ROOT)
        else str(directory),
        'git_commit': rc.get('git_commit'), 'git_dirty': rc.get('git_dirty'),
        'run_timestamp_utc': rc.get('run_timestamp_utc'),
        'profile': (study.get('profile') or {}).get('name'), 'profile_hash': study.get('profile_hash'),
        'calendar': (study.get('calendar') or {}).get('name'), 'calendar_hash': study.get('calendar_hash'),
        'non_default_switches': doc.get('non_default_switches'),
        'price_cache_sha256': ((rc.get('data') or {}).get('price_cache') or {}).get('sha256'),
        'complete': doc.get('complete'),
        'main': {k: main.get(k) for k in ('period_start', 'period_end', 'total_return_pct', 'sharpe', 'trades')},
        'oos': {k: oos.get(k) for k in ('total_return_pct', 'pooled_sharpe', 'trades')} if oos.get('windows') else None,
    }


def evaluation_summary(path: pathlib.Path) -> dict:
    """The registered test's outcome per strategy (scripts/evaluate_holdout.py output)."""
    doc = json.loads(path.read_text())
    keep = ('period', 'days', 'total_return_pct', 'sharpe', 't', 'p_one_sided', 'p_holm',
            'edge_out_of_sample')
    return {'alpha': doc.get('alpha'), 'test': doc.get('test'),
            'strategies': {k: {f: v.get(f) for f in keep} for k, v in (doc.get('strategies') or {}).items()},
            'inputs': doc.get('inputs')}


def published_mismatches(evaluation: pathlib.Path) -> list:
    """Published files (MANIFEST.json in the evaluation's sibling directories) whose sha256
    is not that of the same-named file the evaluation read."""
    doc = json.loads(pathlib.Path(evaluation).read_text())
    read = {}
    for run in ((doc.get('inputs') or {}).get('runs') or {}).values():
        for name, sha in (run.get('sha256') or {}).items():
            read.setdefault(name, set()).add(sha)
    bad = []
    for manifest in sorted(pathlib.Path(evaluation).parent.glob('*/MANIFEST.json')):
        files = json.loads(manifest.read_text()).get('files') or {}
        bad += [f'{manifest.parent.name}/{name}' for name, f in files.items()
                if name in read and f.get('sha256') not in read[name]]
    return bad


def check_new(name: str, path: pathlib.Path = REGISTRY) -> None:
    if any(entry.get('name') == name for entry in read_registry(path)):
        raise SystemExit(f"trial {name!r} is already registered in {path.name}; names are registered once")


def register(name: str, runs=(), evaluation: pathlib.Path = None, prereg_commit: str = None,
             head: str = None, note: str = None, path: pathlib.Path = REGISTRY,
             now: dt.datetime = None, attempts: pathlib.Path = ATTEMPTS) -> dict:
    check_new(name, path)
    head = head or _git('rev-parse', 'HEAD')
    summaries = [run_summary(pathlib.Path(d)) for d in runs]
    if prereg_commit:
        bad = [r['dir'] for r in summaries if r['git_commit'] != head or r['git_dirty'] is not False]
        if bad:
            raise SystemExit(f"runs not from a clean tree at {head}: {bad}")
        if evaluation and published_mismatches(pathlib.Path(evaluation)):
            raise SystemExit(f"published files differ from the evaluated ones: "
                             f"{published_mismatches(pathlib.Path(evaluation))}")
    entry = {
        'name': name,
        'registered_utc': (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec='seconds'),
        'head': head,
        'prereg_commit': prereg_commit,
        'runs': summaries,
        'evaluation': evaluation_summary(pathlib.Path(evaluation)) if evaluation else None,
        'attempts': read_attempts(name, attempts),
        'note': note,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(entry, sort_keys=True) + '\n')
    return entry


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--name', required=True)
    ap.add_argument('--check-new', action='store_true', help='only check that NAME is not registered yet')
    ap.add_argument('--run', action='append', default=[], help='a run directory (repeatable)')
    ap.add_argument('--evaluation', help="evaluate_holdout.py's JSON")
    ap.add_argument('--prereg-commit')
    ap.add_argument('--head')
    ap.add_argument('--note')
    args = ap.parse_args(argv)
    if args.check_new:
        check_new(args.name)
        return 0
    entry = register(args.name, args.run, args.evaluation, args.prereg_commit, args.head, args.note)
    print(f"registered {entry['name']} -> {REGISTRY.relative_to(ROOT)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
