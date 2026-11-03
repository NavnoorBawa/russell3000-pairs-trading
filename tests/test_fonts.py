"""The site's subset fonts (assets/fonts/Study*.woff2) are the build of scripts/build_fonts.py:
a rebuild from the IBM Plex sources reproduces them byte for byte. Needs the pinned fontTools
and brotli (pip install -e ".[site]"); skipped without them."""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

pytestmark = pytest.mark.skipif(importlib.util.find_spec('fontTools') is None
                                or importlib.util.find_spec('brotli') is None,
                                reason='fontTools and brotli are not installed (pip install -e ".[site]")')


def test_fonts_are_reproducible():
    import build_fonts
    assert build_fonts.main(['--check']) == 0


def test_fonts_carry_no_reserved_name():
    from fontTools.ttLib import TTFont
    for path in sorted((ROOT / 'assets' / 'fonts').glob('Study*.woff2')):
        names = TTFont(path)['name']
        assert not any('Plex' in r.toUnicode() for r in names.names if r.nameID in (1, 3, 4, 6, 16, 17, 18, 21, 25)), path
