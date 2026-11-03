"""The frozen paths and the spent holdout record, byte for byte.

docs/HANDOFF.md's rules freeze the engine (pairs_trading/), the reference data (reference/) and
the pre-registration (docs/PREREGISTRATION.md) at the registered commit 7c7d3f9, and the 2026
holdout's record (results/holdout2026/, commit c4930fd) once it was run. This test fails on any
change, addition or removal there, so CI enforces what was a convention. tests/fixtures/
frozen_files.sha256 lists every tracked file under those paths with its sha256 (sha256sum
format); it changes only with a new pre-registration, never to make this test pass.
"""
import hashlib
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIST = ROOT / 'tests' / 'fixtures' / 'frozen_files.sha256'
FROZEN = ('pairs_trading', 'reference', 'docs/PREREGISTRATION.md', 'results/holdout2026')


def _recorded():
    out = {}
    for line in LIST.read_text().splitlines():
        sha, path = line.split('  ', 1)
        out[path] = sha
    return out


def _tracked():
    try:
        out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', *FROZEN], capture_output=True, text=True,
                             check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip('not a git checkout')
    return set(out.stdout.split('\n')) - {''}


def test_every_frozen_file_is_unchanged():
    changed = [p for p, sha in _recorded().items()
               if not (ROOT / p).is_file() or hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != sha]
    assert not changed, f'frozen files changed or removed: {changed}'


def test_no_file_was_added_to_a_frozen_path():
    added = sorted(_tracked() - set(_recorded()))
    assert not added, f'files added under a frozen path: {added}'
