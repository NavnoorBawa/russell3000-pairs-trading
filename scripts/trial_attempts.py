#!/usr/bin/env python3
"""Append-only record of every attempt at a registered trial: results/trial_attempts.jsonl.

scripts/run_holdout.sh writes one line when an attempt starts (its number, the commit, the
pre-registration commit, a note such as a crash fix, the environment listing's sha256),
one when a step finishes (with the sha256 of each output) and one when it fails or the
trial completes. A crashed attempt is therefore on record even though no trial was
registered, and a re-run at the same commit skips a step whose recorded outputs are on
disk unchanged ('is-done') instead of running a strategy on the holdout a second time.
register_trial.py copies a trial's attempt lines into its registry entry.

usage: python scripts/trial_attempts.py start NAME --head SHA [--prereg-commit SHA] [--note TEXT]
                                              [--environment FILE]   (prints the attempt number)
       python scripts/trial_attempts.py done NAME STEP --head SHA FILE...
       python scripts/trial_attempts.py is-done NAME STEP --head SHA FILE...   (exit 0: done)
       python scripts/trial_attempts.py failed NAME STEP [--note TEXT]
       python scripts/trial_attempts.py completed NAME
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ATTEMPTS = ROOT / 'results' / 'trial_attempts.jsonl'


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_attempts(name: str = None, path: pathlib.Path = ATTEMPTS) -> list:
    if not path.exists():
        return []
    lines = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    return [x for x in lines if name is None or x.get('name') == name]


def current_attempt(name: str, path: pathlib.Path = ATTEMPTS) -> int:
    return sum(1 for x in read_attempts(name, path) if x.get('event') == 'start')


def append(name: str, event: str, path: pathlib.Path = ATTEMPTS, now: dt.datetime = None, **fields) -> dict:
    line = {'name': name, 'event': event,
            'attempt': current_attempt(name, path) + (event == 'start'),
            'utc': (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec='seconds'),
            **{k: v for k, v in fields.items() if v is not None}}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(line, sort_keys=True) + '\n')
    return line


def outputs(files) -> dict:
    return {str(f): _sha256(f) for f in files}


def is_done(name: str, step: str, head: str, files, path: pathlib.Path = ATTEMPTS) -> bool:
    """An earlier attempt at commit `head` finished `step`, and its outputs are unchanged."""
    if not files or not all(pathlib.Path(f).is_file() for f in files):
        return False
    now = outputs(files)
    return any(x.get('event') == 'done' and x.get('step') == step and x.get('head') == head
               and x.get('outputs') == now for x in read_attempts(name, path))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('event', choices=['start', 'done', 'is-done', 'failed', 'completed'])
    ap.add_argument('name')
    ap.add_argument('step', nargs='?')
    ap.add_argument('files', nargs='*')
    ap.add_argument('--head')
    ap.add_argument('--prereg-commit')
    ap.add_argument('--note')
    ap.add_argument('--environment', help='the environment listing, recorded by its sha256')
    args = ap.parse_intermixed_args(argv)
    if args.event in ('done', 'is-done', 'failed') and not args.step:
        ap.error(f'{args.event} needs a STEP')
    if args.event in ('start', 'done', 'is-done') and not args.head:
        ap.error(f'{args.event} needs --head')
    if args.event == 'is-done':
        return 0 if is_done(args.name, args.step, args.head, args.files) else 1
    if args.event == 'start':
        line = append(args.name, 'start', head=args.head, prereg_commit=args.prereg_commit, note=args.note,
                      environment_sha256=_sha256(args.environment) if args.environment else None)
        print(line['attempt'])
    elif args.event == 'done':
        append(args.name, 'done', step=args.step, head=args.head, outputs=outputs(args.files))
    else:
        append(args.name, args.event, step=args.step, note=args.note)
    return 0


if __name__ == '__main__':
    sys.exit(main())
