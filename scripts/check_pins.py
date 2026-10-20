#!/usr/bin/env python3
"""Check that the running interpreter's packages are requirements.txt's exact pins.

The registered holdout runs only in the pinned environment (scripts/run_holdout.sh). PEP 440
semantics: a pin without a local version label matches any local build of that version
(torch==2.13.0 is satisfied by the CPU wheel's 2.13.0+cpu); a pin with a label must match it.

usage: python scripts/check_pins.py [requirements.txt]   (exit 1 and a list on a mismatch)
"""
import importlib.metadata as md
import re
import sys

PIN = re.compile(r'\s*([A-Za-z0-9_.\-]+)==(\S+)')


def mismatches(lines, version_of=None) -> list:
    """['name have (pinned want)', ...] for every '==' pin the environment does not satisfy."""
    def installed(name):
        try:
            return md.version(name)
        except md.PackageNotFoundError:
            return None
    version_of = version_of or installed
    bad = []
    for line in lines:
        m = PIN.match(line.split('#', 1)[0])
        if not m:
            continue
        name, want = m.groups()
        have = version_of(name)
        comparable = have.split('+', 1)[0] if have and '+' not in want else have
        if comparable != want:
            bad.append(f'{name} {have} (pinned {want})')
    return bad


def main(argv=None) -> int:
    path = (argv if argv is not None else sys.argv[1:]) or ['requirements.txt']
    with open(path[0]) as f:
        bad = mismatches(f)
    if bad:
        print('not as pinned: ' + ', '.join(bad), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
