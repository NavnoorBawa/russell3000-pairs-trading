#!/usr/bin/env python3
"""Build the site's web fonts: subsets of IBM Plex, renamed as the font licence requires.

The page loads two fonts before it can paint its first screen, so their size sets how soon a
phone shows the answer. The IBM Plex files (assets/fonts/plex/, unchanged) cover far more
scripts than the note uses; this keeps Latin (Basic, Latin-1, Extended-A), Greek, punctuation,
super- and subscripts, currency, letterlike symbols, arrows, mathematical operators,
miscellaneous technical symbols, geometric shapes and check marks, with every OpenType feature
(tabular figures included), and roughly halves each file.

A subset is a Modified Version under the SIL Open Font License 1.1, and condition 3 forbids it
the Reserved Font Name "Plex". The subsets are therefore named Study Sans, Study Serif and Study
Mono (files assets/fonts/Study*.woff2); their name tables keep IBM's copyright, trademark and
licence notices and say what they are. site.css names them first and IBM Plex second, so a
reader who has IBM Plex installed is unaffected.

    python scripts/build_fonts.py          # writes assets/fonts/Study*.woff2
    python scripts/build_fonts.py --check  # exit 1 if a committed font differs from a rebuild

The build is deterministic: each subset keeps its source's head.modified timestamp (fontTools
would otherwise stamp the build's clock), so a rebuild with the pinned fontTools and brotli
(pip install -e ".[site]") reproduces the committed files byte for byte.
"""

import argparse
import pathlib
import sys
import tempfile

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / 'assets' / 'fonts' / 'plex'
OUT = ROOT / 'assets' / 'fonts'
UNICODES = ('U+0000-017F,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0370-03FF,U+2000-206F,U+2070-209F,'
            'U+20A0-20CF,U+2100-214F,U+2190-21FF,U+2200-22FF,U+2300-23FF,U+25A0-25FF,U+2713-2714,'
            'U+FB01-FB02')
RENAME = [('IBM Plex Sans', 'Study Sans'), ('IBM Plex Serif', 'Study Serif'), ('IBM Plex Mono', 'Study Mono'),
          ('IBMPlexSans', 'StudySans'), ('IBMPlexSerif', 'StudySerif'), ('IBMPlexMono', 'StudyMono'),
          ('Plex', 'Study')]
NAME_IDS = (1, 3, 4, 6, 16, 17, 18, 21, 25)       # the ids that name the font (not its notices)
NOTE = ('A subset of IBM Plex (Copyright 2017 IBM Corp., SIL Open Font License 1.1), renamed as the '
        'licence requires of a Modified Version: Reserved Font Name "Plex".')


def build(src, out=OUT):
    opts = subset.Options()
    opts.flavor = 'woff2'
    opts.layout_features = ['*']
    opts.name_IDs = ['*']
    opts.name_languages = ['*']
    opts.notdef_outline = True
    opts.hinting = True
    opts.glyph_names = False
    font = TTFont(src, recalcTimestamp=False)    # keep the source's timestamp: a reproducible file
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=subset.parse_unicodes(UNICODES))
    sub.subset(font)
    name = font['name']
    for rec in list(name.names):
        if rec.nameID in NAME_IDS:
            text = rec.toUnicode()
            for a, b in RENAME:
                text = text.replace(a, b)
            name.setName(text, rec.nameID, rec.platformID, rec.platEncID, rec.langID)
    name.setName(NOTE, 10, 3, 1, 0x409)
    for rec in name.names:
        assert rec.nameID not in NAME_IDS or 'Plex' not in rec.toUnicode(), (src.name, rec.nameID)
    font.flavor = 'woff2'
    dst = pathlib.Path(out) / src.name.replace('IBMPlex', 'Study')
    font.save(dst)
    return dst


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true', help='exit 1 if a committed font differs from a rebuild')
    args = ap.parse_args(argv)
    sources = sorted(SRC.glob('IBMPlex*.woff2'))
    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            stale = [d.name for d in (build(src, tmp) for src in sources)
                     if not (OUT / d.name).exists() or (OUT / d.name).read_bytes() != d.read_bytes()]
        if stale:
            print(f'fonts differ from a rebuild: {", ".join(stale)} (run python scripts/build_fonts.py)',
                  file=sys.stderr)
            return 1
        print(f'the {len(sources)} subset fonts in assets/fonts/ are current')
        return 0
    for src in sources:
        dst = build(src)
        print(f'{src.name} ({src.stat().st_size:,} bytes) -> {dst.name} ({dst.stat().st_size:,} bytes)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
