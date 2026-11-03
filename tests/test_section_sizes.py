"""The room assets/site.css holds for each section and chart before it is laid out or drawn.

The heights are measured in a browser by scripts/build_section_sizes.py. Here, without a
browser: every section and every chart of index.html has its heights, and none is left over.
The measurement itself (build_section_sizes.py --check) runs only when asked for with
SITE_BROWSER_CHECKS=1 and Playwright's Chromium is installed (CI has no browsers).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import build_section_sizes  # noqa: E402

PAGE = (ROOT / 'index.html').read_text(encoding='utf-8')
CSS = (ROOT / 'assets' / 'site.css').read_text(encoding='utf-8')


def test_every_section_has_its_heights():
    sections = [s for s in re.findall(r'<section id="([^"]+)"', PAGE) if s != 'summary']
    held = build_section_sizes.current(CSS)
    for layout in ('desktop', 'phone'):
        assert list(held[layout]['sections']) == sections, layout


def test_chart_heights_name_charts_of_the_page():
    # a chart whose data are absent is not drawn and holds no room, so not every chart need be here
    charts = set(re.findall(r'<figure [^>]*id="([^"]+)"[^>]*data-exhibit=', PAGE))
    held = build_section_sizes.current(CSS)
    for layout in ('desktop', 'phone'):
        assert held[layout]['charts'] and set(held[layout]['charts']) <= charts, layout
        assert set(held[layout]['legends']) <= set(held[layout]['charts']), layout


def _chromium():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


@pytest.mark.skipif(os.environ.get('SITE_BROWSER_CHECKS') != '1', reason='set SITE_BROWSER_CHECKS=1 to measure in a browser')
def test_heights_are_current():
    if not _chromium():
        pytest.skip("Playwright's Chromium is not installed")
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'build_section_sizes.py'), '--check'], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
