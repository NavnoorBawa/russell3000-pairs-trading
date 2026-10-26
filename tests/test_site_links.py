"""The page's links: every cross-reference is a link, and every in-page link lands on something."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import link_refs  # noqa: E402

PAGE = (ROOT / 'index.html').read_text(encoding='utf-8')


def test_every_exhibit_and_section_reference_is_linked():
    assert link_refs.unlinked(PAGE) == []


def test_linking_is_idempotent():
    new, missing = link_refs.apply(PAGE)
    assert missing == []
    assert new == PAGE


def test_ids_are_unique():
    ids = re.findall(r'\sid="([^"]+)"', PAGE)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert dupes == []


def test_every_in_page_link_has_a_target():
    ids = set(re.findall(r'\sid="([^"]+)"', PAGE))
    hrefs = set(re.findall(r'href="#([^"]+)"', PAGE))
    assert sorted(h for h in hrefs if h not in ids) == []


def test_every_aria_reference_has_a_target():
    ids = set(re.findall(r'\sid="([^"]+)"', PAGE))
    refs = set()
    for v in re.findall(r'aria-(?:labelledby|describedby|controls)="([^"]+)"', PAGE):
        refs.update(v.split())
    assert sorted(r for r in refs if r not in ids) == []


def test_each_key_finding_cites_its_evidence():
    block = PAGE[PAGE.index('<ol class="findings"'):]
    block = block[:block.index('</ol>')]
    items = re.findall(r'<li id="f\d+">(.*?)</li>', block, flags=re.S)
    assert len(items) >= 5
    for item in items:
        assert '<span class="ev">' in item, item[:80]
        assert re.search(r'<a href="#[\w-]+"', item[item.index('<span class="ev">'):]), item[:80]


def test_section_numbers_are_permalinks():
    nums = re.findall(r'<h2 id="h-([\w-]+)"><a class="secno" href="#([\w-]+)"', PAGE)
    assert len(nums) == 14
    for heading, target in nums:
        assert heading == target


def test_links_to_commits_name_a_full_hash_of_this_repository():
    for full, short in re.findall(
            r'<a class="commit" href="https://github.com/NavnoorBawa/russell3000-pairs-trading/commit/([0-9a-f]+)">'
            r'<code>([0-9a-f]+)</code></a>', PAGE):
        assert len(full) == 40 and full.startswith(short)


def test_bare_number_links_are_named_in_full():
    # "Exhibit 2, 6" links its 6 as "Exhibit 6" for a screen reader
    for m in re.finditer(r'<a([^>]*)>(\d+)</a>', PAGE):
        assert 'aria-label=' in m.group(1), m.group(0)


def test_prereg_timeline_is_current_and_states_only_the_pages_dates():
    import build_prereg_timeline as tl
    assert tl.main(['--check']) == 0
    a, b = PAGE.index(tl.BEGIN), PAGE.index(tl.END)
    rest = re.sub(r'<[^>]+>', '', PAGE[:a] + PAGE[b:])
    for phrase in tl.PHRASES:
        assert phrase in rest, phrase


def test_every_chart_has_a_static_figure_for_readers_without_javascript():
    figs = re.findall(r'<figure class="exhibit[^"]*" id="(ex-\d+)" data-exhibit="(\w+)"[^>]*>(.*?)</figure>', PAGE, flags=re.S)
    assert figs
    for ex, name, body in figs:
        m = re.search(r'<noscript><img class="ex-static" src="(paper/build/figures/(\w+)\.svg)" width="\d+" height="\d+"', body)
        assert m, ex
        assert m.group(2) == name and (ROOT / m.group(1)).exists(), ex
