"""The page's tables module (assets/tables.js, and its styles in assets/site.css): the markup it relies on.

Every in-page table region carries a permalink id derived from its aria-label, and the phone
layout each one takes is declared on it (data-phone); the Reproduce commands are a named,
focusable region. The script stays within the page's Content-Security-Policy (no inline
handlers, no code from strings, no requests), and its controls exist only with JavaScript
and never print."""
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE = (REPO / 'index.html').read_text(encoding='utf-8')
JS = (REPO / 'assets' / 'tables.js').read_text(encoding='utf-8')
CSS = (REPO / 'assets' / 'site.css').read_text(encoding='utf-8')     # tables.css is merged into it

TABLES = {
    'Pre-registered hypotheses': ('t-holdout', 'cards'),
    'Performance': ('t-performance', 'matrix'),
    'Start-date sensitivity': ('t-start-dates', 'matrix'),
    'Significance tests': ('t-significance', 'matrix'),
    'Data-snooping tests': ('t-snooping', None),
    "Persistence on the strategy's candidate pairs": ('t-persistence', 'matrix'),
    'Cost model': ('t-cost-model', 'cards'),
    'Cost and capacity scenarios': ('t-scenarios', 'scroll'),
    'Net returns by regime': ('t-regimes', None),
    'Trial registry': ('t-registry', 'scroll'),
    'From v32 to v33': ('t-v32-v33', 'cards'),
    'v32 and v33 results': ('t-v32-v33-results', 'matrix'),
    'Specification': ('t-spec', None),
    'Known-answer checks': ('t-known-answers', 'cards'),
    'Threats to validity': ('t-threats', 'cards'),
    'Literature': ('t-literature', 'cards'),
    'Version history': ('t-history', None),
}


def _regions():
    return re.findall(r'<div class="tbl-wrap"([^>]*)>', PAGE)


def test_every_table_region_has_its_id_and_phone_layout():
    found = {}
    for attrs in _regions():
        label = re.search(r'aria-label="([^"]+)"', attrs).group(1)
        ident = re.search(r'\bid="([^"]+)"', attrs)
        phone = re.search(r'data-phone="([^"]+)"', attrs)
        assert 'role="region"' in attrs and 'tabindex="0"' in attrs, attrs
        found[label] = (ident.group(1) if ident else None, phone.group(1) if phone else None)
    assert found == TABLES


def test_ids_are_unique_on_the_page():
    ids = re.findall(r'\bid="([^"]+)"', PAGE)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, dupes


def test_card_tables_have_one_header_row_and_matrices_a_label_column():
    """Card labels come from the one header row; a two-row header (the scenarios) stays a table."""
    for label, (ident, phone) in TABLES.items():
        start = PAGE.index('id="%s"' % ident)
        table = PAGE[start:PAGE.index('</table>', start)]
        head = table.split('<thead>', 1)[1].split('</thead>', 1)[0] if '<thead>' in table else ''
        if phone in ('cards', 'matrix'):
            assert head.count('<tr') == 1, label
            assert 'colspan' not in head and 'rowspan' not in head, label
        if phone == 'matrix':
            assert re.search(r'<tr><th scope="row">', table), label


def test_reproduce_commands_are_a_named_focusable_region():
    assert PAGE.count('<pre tabindex="0" role="region" aria-label="Commands to reproduce the study">') == 1


def test_script_is_csp_safe():
    for bad in ('eval(', 'new Function', 'innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write',
                'fetch(', 'XMLHttpRequest', 'setAttribute(\'on', 'http://', 'https://'):
        assert bad not in JS, bad
    assert 'window.TableTools' in JS and 'attach' in JS


def test_controls_need_javascript_and_do_not_print():
    assert re.search(r'html:not\(\.js\) \.tbl-tools', CSS)
    print_block = CSS.split('@media print', 1)[1]
    assert '.tbl-tools' in print_block and '.tt-toast' in print_block
    # the phone layouts are screen-only and need the script's classes
    css = re.sub(r'/\*.*?\*/', '', CSS, flags=re.S)
    phone = css.split('@media screen and (max-width: 600px)', 1)[1].split('\n}\n', 1)[0]
    for rule in re.findall(r'(?:^|\})\s*([^{}]+)\{', phone.split('{', 1)[1]):
        if 'tt-cards' in rule or 'tt-matrix' in rule:
            assert all(sel.strip().startswith('html.js') for sel in rule.split(',')), rule
