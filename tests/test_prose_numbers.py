"""Every number in the prose of index.html and README.md is a marker, or a number that no run
produces (docs/HANDOFF.md, rule 3).

scripts/check_published_numbers.py checks the markers that exist; this test catches a result
typed into the text without one. It strips scripts, SVG, code, links' targets and every marked
value, then lists the remaining numbers with a decimal point, a thousands separator or three
or more digits (years excepted). Each must be in ALLOWED with its reason: a design parameter, a
method's setting, a figure of another study, a version or an identifier. A result never belongs
here: mark it (data-metric="KEY" / <!--m:KEY-->) instead. tests/test_build_paper.py holds the
paper to the same rule.
"""
import html
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

ALLOWED = {
    # design parameters of the strategy and its tests (pairs_trading/study_config.py, docs/)
    **dict.fromkeys(('0.002', '0.05', '0.1', '0.10', '0.20', '0.25', '0.3', '0.30', '0.4', '0.5', '0.50',
                     '0.55', '0.6', '0.75', '1.0', '1.25', '1.5', '1.8', '1.96', '2.1', '2.5', '100', '126',
                     '252', '300', '500', '0.38'), 'design parameter'),
    # settings of a method: bootstrap resamples, simulated paths, a chart's axis limit
    **dict.fromkeys(('5,000', '20,000', '400'), "a method's setting"),
    # figures of other studies (Avellaneda and Lee 2010; Almgren et al. 2005; Do and Faff 2010;
    # Chen et al. 2019; Goyal, Jegadeesh and Wu 2026; Clegg 2014)
    **dict.fromkeys(('1.44', '1.1', '0.9', '0.314', '0.86', '0.37', '0.24', '1.40', '8.81', '4.5', '10.2',
                     '860,000'), 'figure of another study'),
    # the index and the v32 universe: the 3,000 largest stocks, its file's 2,999 symbols
    **dict.fromkeys(('3,000', '3000', '2,999'), "the universe's definition"),
    '404': 'an HTTP status',
    '3.12': 'the Python version',
    '270': 'the count of findings of the v32 audit (docs/PROGRESS.md)',
}


def _page_prose(text):
    text = text[text.index('<body'):]
    for tag in ('script', 'style', 'svg', 'pre', 'code', 'noscript'):
        text = re.sub(rf'<{tag}\b.*?</{tag}>', ' ', text, flags=re.S)
    prev = None
    while prev != text:                       # an element with a marker: its whole text is the value
        prev = text
        text = re.sub(r'<(\w+)[^>]*\bdata-metric="[^"]*"[^>]*>[^<]*</\1>', ' ', text)
    return html.unescape(re.sub(r'<[^>]+>', ' ', text))


def _markdown_prose(text):
    text = re.sub(r'```.*?```', ' ', text, flags=re.S)
    text = re.sub(r'`[^`\n]*`', ' ', text)
    text = re.sub(r'<!--m:[^>]*-->.*?<!--/m-->', ' ', text, flags=re.S)
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    text = re.sub(r'\]\([^)]*\)', ']', text)
    return re.sub(r'<[^>]+>', ' ', text)


NUMBER = re.compile(r'(?<![\w.#/-])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w.]*\d)')


def _numbers(prose):
    prose = prose.replace('Russell 3000', 'Russell')
    prose = re.sub(r'doi:\S+', ' ', prose)                          # identifiers
    prose = re.sub(r'\bcommits? [0-9a-f]{7,40}\b', ' ', prose)
    found = set()
    for m in NUMBER.finditer(prose):
        tok = m.group(1)
        if ('.' in tok or ',' in tok or len(tok) >= 3) and not re.fullmatch(r'(19|20)\d\d', tok):
            found.add(tok)
    return found


def test_page_prose_has_no_unmarked_result():
    found = _numbers(_page_prose((ROOT / 'index.html').read_text(encoding='utf-8')))
    assert found <= set(ALLOWED), f'numbers typed into index.html without a marker: {sorted(found - set(ALLOWED))}'


def test_readme_prose_has_no_unmarked_result():
    found = _numbers(_markdown_prose((ROOT / 'README.md').read_text(encoding='utf-8')))
    assert found <= set(ALLOWED), f'numbers typed into README.md without a marker: {sorted(found - set(ALLOWED))}'


def test_a_typed_result_is_caught():
    assert _numbers(_page_prose('<body><p>Sharpe <span data-metric="main.sharpe">−0.06</span>, '
                                'return −2.47% over 213 trades</p>')) == {'2.47', '213'}
