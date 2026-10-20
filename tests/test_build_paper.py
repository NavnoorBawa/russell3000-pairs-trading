"""scripts/build_paper.py (paper/build/paper_data.json, the figures, paper/pairs_study.pdf).

The data extraction is checked on the committed v32 run and on copies of its site data
altered to carry what later runs add (the second strategy family, the data-snooping tests,
the evidence layer's anatomy, ...), so every renderer runs without new data. Compiling the
paper needs the optional typst package (pip install -e ".[paper]"); CI installs the pinned
requirements only, so those tests skip there and the rest still run.
"""
import copy
import importlib.util
import json
import pathlib
import re
import shutil

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
MAIN = REPO / 'paper' / 'main.typ'


def _load(name):
    spec = importlib.util.spec_from_file_location(f'_script_{name}', REPO / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bp = _load('build_paper')
chk = _load('check_published_numbers')


def _typst():
    return pytest.importorskip('typst', reason='typst is optional (pip install -e ".[paper]")')


@pytest.fixture(scope='module')
def inputs():
    return bp.load_inputs()


@pytest.fixture(scope='module')
def built(inputs):
    return bp.build_data(inputs)


def _main_typ():
    """main.typ without its comment lines."""
    return '\n'.join(line for line in MAIN.read_text(encoding='utf-8').split('\n')
                     if not line.lstrip().startswith('//'))


# ── the committed products ────────────────────────────────────────────────────────

def test_committed_paper_is_current(capsys):
    """paper_data.json, the figures and the PDF are what the builder makes from the data."""
    assert bp.main(['--check']) == 0, capsys.readouterr().err


def test_build_is_deterministic(inputs, built):
    paper, figs = built
    again, figs_again = bp.build_data(inputs)
    assert bp.dumps(paper) == bp.dumps(again)
    assert figs == figs_again
    text = bp.dumps(paper)
    assert 'NaN' not in text and 'Infinity' not in text
    for svg in figs.values():                      # no wall-clock time, no random ids
        assert '<dc:date>' not in svg and 'Matplotlib v' not in svg


def test_check_detects_stale_products(tmp_path, monkeypatch):
    """--check fails when the data file, a figure or the PDF no longer matches (on a copy)."""
    build = tmp_path / 'build'
    shutil.copytree(bp.BUILD, build)
    pdf = tmp_path / 'pairs_study.pdf'
    shutil.copy(bp.PDF, pdf)
    manifest = json.loads((build / 'manifest.json').read_text())
    for name, path in (('BUILD', build), ('DATA', build / 'paper_data.json'), ('FIGURES', build / 'figures'),
                       ('MANIFEST', build / 'manifest.json'), ('PDF', pdf)):
        monkeypatch.setattr(bp, name, path)
    monkeypatch.setattr(bp, 'compile_inputs', lambda: manifest['inputs'])   # sources stay in the repo
    monkeypatch.setattr(bp, '_typst_version', lambda: None)                 # no recompile here
    assert bp.check() == 0

    data = (build / 'paper_data.json').read_text()
    (build / 'paper_data.json').write_text(data.replace('"main.sharpe": "−0.07"', '"main.sharpe": "−0.08"'))
    assert bp.check() == 1
    (build / 'paper_data.json').write_text(data)

    figure = build / 'figures' / 'equity.svg'
    svg = figure.read_text()
    figure.write_text(svg.replace('</svg>', '<!-- edited --></svg>'))
    if bp._mpl_version() == manifest['tools']['matplotlib']:
        assert bp.check() == 1
    figure.write_text(svg)

    pdf.write_bytes(pdf.read_bytes() + b'\n')
    assert bp.check() == 1


# ── numbers: formatted once, from the data, as the site formats them ─────────────

def test_fmt_follows_the_site_conventions():
    assert bp.fmt(-0.3, '.2%') == '−0.30%'
    assert bp.fmt(0.57, '+.2%') == '+0.57%'
    assert bp.fmt(35491, ',.0') == '35,491'
    assert bp.fmt(-0.004, '.2') == '0.00'                # no "−0.00"
    assert bp.fmt(0.0, '+.2') == '0.00'                  # no "+0.00"
    assert bp.fmt(0.688, '.2×') == '0.69×'
    assert bp.fmt(None, '.2') is None and bp.fmt(float('nan'), '.2') is None
    with pytest.raises(TypeError):
        bp.fmt(True, '.2')
    with pytest.raises(ValueError):
        bp.fmt(1.0, '2f')


def test_paper_numbers_agree_with_the_site(built):
    """Every number the site marks and the paper also prints is the same number, shown to
    the same precision (signs, '%' and '×' aside)."""
    paper, _ = built
    markers, errors = chk.extract_markers((REPO / 'index.html').read_text(encoding='utf-8'))
    assert not errors
    compared = 0
    for key, body, line in markers:
        text = paper['m'].get(key)
        if text is None:
            continue
        site_value, site_dp = chk.parse_marker_value(body)
        value, dp = chk.parse_marker_value(text.rstrip('×'))
        assert (value, dp) == (site_value, site_dp), f'index.html:{line} {key}: site {body!r}, paper {text!r}'
        compared += 1
    assert compared >= 80


def test_null_results_print_as_pending_never_as_a_number(built):
    paper, _ = built
    nulls = {k for k, v in paper['m'].items() if v is None}
    assert nulls, 'the v32 data have pending results (holdout, residual arm, snooping tests)'
    for key in nulls:
        assert paper['why'][key].startswith('pending ('), key
        assert not re.search(r'\d+\.\d|[−+-]\d', paper['why'][key]), key
    assert set(paper['why']) == nulls
    for key, cells in (('snooping', [r[1] for r in paper['tables']['snooping']]),
                       ('validation', [r[2] for r in paper['tables']['validation']])):
        assert all(c == 'pending' for c in cells), key
    assert all(r[3] == r[4] == 'sealed' for r in paper['tables']['hypotheses'])
    for name, path in paper['figures'].items():
        assert (path is None) == (name in paper['pending'])


def test_unexpected_null_is_an_error(inputs):
    broken = copy.deepcopy(inputs)
    broken['study']['dev']['facts']['gross_bp'] = None
    with pytest.raises(bp.PaperDataError, match='gross_bp'):
        bp.build_data(broken)


def test_main_typ_has_no_hand_typed_results():
    """Every decimal, thousands-separated or three-digit number left in main.typ is a design
    parameter, a hypothesis value or a published figure of another study; results come from
    paper_data.json through #m(). A number typed into the text fails here until it is
    either replaced by #m() or added below with its reason."""
    allowed = {
        # design parameters of the strategy and the tests (pairs_trading/, docs/)
        '0.002', '0.05', '0.1', '0.20', '0.25', '0.3', '0.5', '0.50', '0.6', '0.75', '1.0', '1.25', '1.5',
        '1.8', '1.96', '2.5', '126', '252', '500',
        # published results quoted in the literature table (Avellaneda and Lee 2010)
        '1.44', '1.1', '0.9',
    }
    text = _main_typ()
    text = text.replace('Russell 3000', 'Russell')                     # the index's name
    text = re.sub(r':\s*\d+%', ':', text)                              # layout arguments (width: 100%)
    number = re.compile(r'(?<![\w.#])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\d.]*\s*(?:pt|em|mm|cm|fr|in)\b)(?!\.\d)')
    found = set()
    for m in number.finditer(text):
        tok = m.group(1)
        if ('.' in tok or ',' in tok or len(tok) >= 3) and not re.fullmatch(r'(19|20)\d\d', tok):
            found.add(tok)
    assert found <= allowed, f'numbers typed into main.typ: {sorted(found - allowed)}'


def test_main_typ_keys_and_claims_exist(built):
    paper, _ = built
    text = _main_typ()
    keys = set(re.findall(r'(?:#m|kpi-value|#path|\bm)\("([\w.]+)"', text))
    assert keys and keys <= set(paper['m']), sorted(keys - set(paper['m']))
    for name in set(re.findall(r'#claim\("(\w+)"\)', text)):
        assert paper['claims'][name] is True, name
    for name in set(re.findall(r'flag\("(\w+)"\)', text)):
        assert name in paper['flags'], name
    for name in set(re.findall(r'\bT\("(\w+)"\)', text)):
        assert name in paper['tables'], name
    for name in set(re.findall(r'exhibit\("(\w+)"|mini\("(\w+)"', text)) - {('', '')}:
        assert (name[0] or name[1]) in paper['figures'], name


def test_every_reference_is_cited():
    """references.bib holds only works the text cites (Typst prints cited entries only, so an
    uncited entry would sit unchecked in the file)."""
    keys = set(re.findall(r'^@\w+\{(\w+),', (REPO / 'paper' / 'references.bib').read_text(), re.M))
    text = _main_typ()
    cited = set(re.findall(r'<(\w+)>', text)) | set(re.findall(r'@(\w+)', text))
    assert keys and keys <= cited, sorted(keys - cited)


def test_claims_follow_the_data(inputs):
    """A claim the text makes turns false (and stops the compile) when the data change."""
    altered = copy.deepcopy(inputs)
    facts = altered['study']['dev']['facts']
    facts['gross_t'] = 2.5
    facts['gross_bp'] = 20.0
    paper, _ = bp.build_data(altered)
    assert paper['claims']['gross_not_significant'] is False
    assert paper['claims']['gross_below_cost'] is False


# ── optional results fill their sections ─────────────────────────────────────────

def _with_later_results(inputs):
    """The v32 inputs plus what the v33 runs, the evidence layer and the validation add."""
    inp = copy.deepcopy(inputs)
    study = inp['study']
    dev = study['dev']
    n = len(dev['daily']['dates'])
    dev['random_band'] = {'dates': dev['daily']['dates'], 'n_draws': 200,
                          **{k: [round(z * 0.01 * (i + 1) ** 0.5, 4) for i in range(n)]
                             for k, z in (('p05', -1.6), ('p25', -0.7), ('p50', 0.0), ('p75', 0.7), ('p95', 1.6))}}
    dev['cost_curve'] = [{'k': k / 4, 'sharpe': 0.2 - 0.3 * k / 4, 'ret_pct': 0.5 - k / 4} for k in range(9)]
    dev['exit_race'] = {'targets': 61, 'stops': 65, 'expected_targets': 63.0, 'z': -0.4}
    dev['decay'] = [{'period': 'Formation', 'bp': 40.0, 'lo': 30.0, 'hi': 50.0, 'n': 900},
                    {'period': 'Trading', 'bp': 11.4, 'lo': -50.0, 'hi': 72.0, 'n': 161}]
    dev['persistence'] = {'chance_pct': 5.0, 'windows': [{'window': 'W1', 'pct': 22.0}, {'window': 'W2', 'pct': 9.0}]}
    dev['capacity'] = [{'aum_musd': a, 'net_bp': 10.0 - a / 100} for a in (10, 100, 1000)]
    dev['pvalue_hist'] = {'edges': [i / 20 for i in range(21)], 'counts': [3000] + [1700] * 19}
    dev['universe_by_formation'] = [{'formation_date': '2022-12-30', 'snapshot': '2022-12-30', 'members': 2600,
                                     'with_prices': 2550, 'missing': 50, 'missing_weight_pct': 0.4,
                                     'unmapped_weight_pct': 1.7}]
    dev['snooping']['results'] = {'spa_p': 0.41, 'reality_check_p': 0.63, 'romano_wolf_rejected': [],
                                  'mcs_included': ['a', 'b'], 'effective_trials': 7.3, 'pbo': 0.48}
    study['residual'] = {'sharpe': 0.31, 'ret_pct': 1.2, 'trades': 5400, 'lo': -0.9, 'hi': 1.5, 'p': 0.31,
                         'period': ['2023-07-03', '2025-12-31'], 'commit': 'abc'}
    study['validation'] = {'seeds': 5, 'all_pass': True,
                           'edge': {'trades': 2241, 'mean_bp': 80.7, 'se_bp': 3.4, 't': 23.7, 'median_net_sharpe': 3.3,
                                    'pass': True},
                           'forced_null': {'trades': 2485, 'mean_bp': 4.6, 'se_bp': 4.0, 't': 1.15, 'pass': True},
                           'hedge_ratio': {'median_abs_error': 0.031, 'p90_abs_error': 0.073},
                           'selection': {'recall': 1.0, 'unrelated_per_planted_market': 2.4, 'per_null_market': 2.6,
                                         'worst_fp_rate': 0.03, 'pass': True}}
    return inp


def test_later_results_fill_their_exhibits_and_tables(inputs):
    paper, figs = bp.build_data(_with_later_results(inputs))
    for name in ('costcurve', 'exitrace', 'decay', 'persistence', 'capacity', 'pvalues', 'universe',
                 'residual', 'validation'):
        assert figs.get(name), name
        assert name not in paper['pending']
    assert paper['pending'] == {'holdout': 'Sealed.'}
    assert paper['m']['paper.residual.sharpe'] == '0.31'
    assert paper['m']['paper.snooping.pbo_pct'] == '48.0%'
    assert not any(k.startswith(('paper.residual.', 'paper.snooping.')) for k in paper['why'])
    assert 'pending' not in {r[1] for r in paper['tables']['snooping']}
    assert paper['tables']['validation'][0][2].startswith('2,241 trades, +80.7 bp')
    assert paper['flags']['random_band'] and paper['flags']['snooping'] and paper['flags']['residual']
    assert paper['claims']['residual_pending'] is False


def test_unknown_or_unprintable_sections_stop_the_build(inputs):
    inp = copy.deepcopy(inputs)
    inp['study']['dev']['new_section'] = [1, 2, 3]
    with pytest.raises(bp.PaperDataError, match='new_section'):
        bp.build_data(inp)
    inp = copy.deepcopy(inputs)
    inp['study']['holdout'] = {'status': 'complete', 'sharpe': 1.0, 'lo': 0.1, 'hi': 1.9, 'p': 0.01}
    with pytest.raises(bp.PaperDataError, match='holdout'):
        bp.build_data(inp)


def test_site_tokens_are_the_light_theme():
    tokens = bp.site_tokens()
    assert tokens['ink'] == '#141413' and tokens['series-1'] == '#2a78d6'


def test_holdout_power_shrinks_with_length(inputs):
    p = bp.holdout_power(inputs['study']['dev']['daily']['net'])
    mde = [r['mde_shape'] for r in p['rows']]
    assert mde == sorted(mde, reverse=True) and all(x > 1.5 for x in mde)


# ── the compile (needs the optional typst package) ───────────────────────────────

def test_paper_compiles_to_the_committed_pdf(built):
    typst_ = _typst()
    paper, _ = built
    pdf = bp.compile_pdf(paper)
    assert pdf.startswith(b'%PDF')
    pages = len(re.findall(rb'/Type\s*/Page(?![s\w])', pdf))
    assert 14 <= pages <= 22, pages
    manifest = json.loads(bp.MANIFEST.read_text())
    if manifest['tools']['typst'] == bp._typst_version():
        assert pdf == bp.PDF.read_bytes()
    keys = typst_.query(str(MAIN), '<pending>', field='value', root=str(REPO), font_paths=[str(bp.FONTS)],
                        ignore_system_fonts=True)
    printed = json.loads(keys) if isinstance(keys, str) else keys
    assert set(printed) <= {k for k, v in paper['m'].items() if v is None}


def test_a_null_in_the_data_prints_as_pending(tmp_path):
    """Nulling a printed number in paper_data.json makes the compiled paper print it as
    pending (the null branch of #m), not as a number."""
    typst_ = _typst()
    root = tmp_path / 'repo'
    shutil.copytree(REPO / 'paper', root / 'paper', ignore=shutil.ignore_patterns('*.pdf'))
    data_path = root / 'paper' / 'build' / 'paper_data.json'
    data = json.loads(data_path.read_text())
    data['m']['main.sharpe'] = None
    data['why']['main.sharpe'] = 'pending (test)'
    data_path.write_text(json.dumps(data))
    keys = typst_.query(str(root / 'paper' / 'main.typ'), '<pending>', field='value', root=str(root),
                        font_paths=[str(root / 'paper' / 'fonts')], ignore_system_fonts=True)
    printed = json.loads(keys) if isinstance(keys, str) else keys
    assert 'main.sharpe' in printed


def test_a_false_claim_stops_the_compile(tmp_path):
    typst_ = _typst()
    root = tmp_path / 'repo'
    shutil.copytree(REPO / 'paper', root / 'paper', ignore=shutil.ignore_patterns('*.pdf'))
    data_path = root / 'paper' / 'build' / 'paper_data.json'
    data = json.loads(data_path.read_text())
    data['claims']['every_interval_spans_zero'] = False
    data_path.write_text(json.dumps(data))
    with pytest.raises(Exception, match='every_interval_spans_zero'):
        typst_.compile(str(root / 'paper' / 'main.typ'), root=str(root),
                       font_paths=[str(root / 'paper' / 'fonts')], ignore_system_fonts=True)
