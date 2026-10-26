"""scripts/build_paper.py (paper/build/paper_data.json, the figures, paper/pairs_study.pdf).

The data extraction is checked on the committed v33 development run (results/v33_dev, with
its evidence layer, its robustness checks, the second strategy family, the declared variant
family's data-snooping tests, the validation and the published v32 run) and on copies of its
site data altered to drop an optional section, so every renderer runs both ways. A result that does
not exist yet has no exhibit or table in the body and is listed as forthcoming.
Compiling the paper needs the optional typst package (pip install -e ".[paper]"); CI
installs the pinned requirements only, so those tests skip there and the rest still run.
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


@pytest.fixture(scope='module')
def sealed_inputs(inputs):
    """The paper's inputs with the holdout sealed: the committed ones while it is, and once its
    result is committed a copy with the sealed stub, so the sealed branch stays tested."""
    if (inputs['study'].get('holdout') or {}).get('status') == 'sealed':
        return inputs
    inp = copy.deepcopy(inputs)
    inp['study']['holdout'] = {'status': 'sealed',
                               'calendar_start': bp.CALENDARS[bp.HOLDOUT_CALENDAR].backtest_start}
    return inp


@pytest.fixture(scope='module')
def sealed_built(inputs, built, sealed_inputs):
    return built if sealed_inputs is inputs else bp.build_data(sealed_inputs)


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
    assert '"main.sharpe": "−0.06"' in data
    (build / 'paper_data.json').write_text(data.replace('"main.sharpe": "−0.06"', '"main.sharpe": "−0.07"'))
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
    """Every number the site marks and the paper also prints is the same number, shown to a
    precision the site uses for it (signs, '%' and '×' aside). The site prints a few numbers
    at two precisions (the average cost per trade as 16.1 and 16.13); the paper's must be
    one of them and agree with every rendering at that rendering's precision."""
    paper, _ = built
    markers, errors = chk.extract_markers((REPO / 'index.html').read_text(encoding='utf-8'))
    assert not errors
    site = {}
    for key, body, line in markers:
        if paper['m'].get(key) is not None:
            site.setdefault(key, []).append((chk.parse_marker_value(body), line, body))
    for key, renderings in site.items():
        text = paper['m'][key]
        value, dp = chk.parse_marker_value(text.rstrip('×'))
        assert dp in {r[0][1] for r in renderings}, f'{key}: paper {text!r}, site {[r[2] for r in renderings]}'
        for (site_value, site_dp), line, body in renderings:
            assert round(value, site_dp) == site_value if dp >= site_dp else value == round(site_value, dp), \
                f'index.html:{line} {key}: site {body!r}, paper {text!r}'
    assert len(site) >= 150


def test_holdout_numbers_round_as_the_site_does():
    """The site's num() rounds half up on the shortest decimal form of the stored value
    (toLocaleString); the holdout's numbers, which both print, are rounded so here. Python's
    own formatting rounds the binary value, which the other numbers keep."""
    assert bp.fmt(2.675, '.2', half_up=True) == '2.68' and bp.fmt(2.675, '.2') == '2.67'
    assert bp.fmt(1.005, '.2', half_up=True) == '1.01' and bp.fmt(1.005, '.2') == '1.00'
    assert bp.fmt(-2.675, '+.2', half_up=True) == '−2.68' and bp.fmt(0.0049, '+.2', half_up=True) == '0.00'
    assert bp.fmt(1234.5, ',.0', half_up=True) == '1,235' and bp.fmt(0.125, '.2%', half_up=True) == '0.13%'
    # a Holm-adjusted p below alpha never prints as alpha beside a rejection
    assert bp._p_text(0.0498, True) == '<0.050' and bp._p_rel('<0.050') == '< 0.050'
    assert bp._p_text(0.0503, False) == '0.050' and bp._p_text(0.0004) == '<0.001'
    assert bp._p_text(0.0042, True) == '0.004' and bp._p_rel('0.004') == '= 0.004'


def test_null_results_print_as_pending_never_as_a_number(sealed_built):
    paper, _ = sealed_built
    nulls = {k for k, v in paper['m'].items() if v is None}
    assert nulls, 'the committed data have pending results (the sealed holdout)'
    for key in nulls:
        assert paper['why'][key].startswith('pending ('), key
        assert not re.search(r'\d+\.\d|[−+-]\d', paper['why'][key]), key
    assert set(paper['why']) == nulls
    assert not any('pending' in r[1] for r in paper['tables']['snooping'])         # the family's tests are committed
    assert all(r[2] != 'pending' for r in paper['tables']['validation'])     # the validation is committed
    # the sealed holdout has no result column at all, only the arms and their hypotheses
    assert [r[0] for r in paper['tables']['hypotheses']] == ['H1 · S1', 'H2 · S2', 'S3'] and all(len(r) == 3 for r in paper['tables']['hypotheses'])
    for name, path in paper['figures'].items():
        assert (path is None) == (name in paper['pending'])


def test_absent_results_are_listed_as_forthcoming(sealed_built):
    """Every result that does not exist yet is in the forthcoming table, with what it will
    show and what it awaits; every exhibit without data is among them; none is a number."""
    paper, _ = sealed_built
    later = {r[0]: r for r in paper['forthcoming']}
    assert set(paper['pending']) - {'snapshots', 'schedules'} <= set(later)
    for flag in ('snooping', 'residual', 'validation', 'multi_factor', 'random_band'):
        assert (flag in later) == (not paper['flags'][flag]), flag
    for key, what, shows, awaits in paper['forthcoming']:
        assert what and shows and awaits, key
        assert not re.search(r'[−+]\d', shows + awaits), key          # design values only, no results
    assert later['holdout'][3].startswith('The pre-registration')


def test_site_concordance_maps_every_site_exhibit(sealed_built):
    """Each exhibit of the site is mapped to the paper's exhibit, to the forthcoming table,
    or marked as not shown; the paper's two diagrams match by title."""
    paper, _ = sealed_built
    rows = paper['concordance']
    site = bp.site_exhibits((REPO / 'index.html').read_text(encoding='utf-8'))
    assert [r[0] for r in rows] == [e['n'] for e in site] and len(rows) >= 20
    targets = {r[2] for r in rows}
    assert {'ex-pipeline', 'ex-timeline', 'ex-equity', 'forthcoming'} <= targets
    for _, _, target in rows:
        if target and target.startswith('ex-'):
            assert paper['figures'].get(target[3:]) or target in ('ex-pipeline',), target


def test_power_figures_are_the_evidence_blocks(inputs, built):
    """The power, the bound and the track records the paper prints are those of the run's
    evidence block (non-normal AR(1) variance), which pairs_trading.power reproduces from the
    daily returns; the p-values fall as the alternative rises."""
    paper, _ = built
    dev = inputs['study']['dev']
    rep = bp.pw.power_report([x / 100 for x in dev['daily']['net']], periods=252)
    assert rep['se_ann'] == pytest.approx(dev['power']['se'], abs=5e-4)
    assert rep['upper_bound_ann'] == pytest.approx(dev['power']['ucb'], abs=5e-4)
    assert rep['min_detectable_sr_ann'] == pytest.approx(dev['power']['mde'], abs=5e-4)
    rows = paper['tables']['alternatives']
    assert [r[0] for r in rows] == ['0.5', '1.0', '1.5', '2.0']
    p = [a['p_ge'] for a in dev['power']['alternatives']]
    assert p == sorted(p, reverse=True)
    assert rows[-1][1] == '< 0.001' and rows[0][1] == paper['m']['study.dev.facts.p_sr_ge_0_5']


def test_edge_per_trade_is_on_the_break_even_basis(inputs, built):
    """The notional-weighted gross over cost is the break-even cost multiple."""
    paper, _ = built
    trades = inputs['results']['all_trades']
    e = bp.trade_edge(trades)
    assert abs(e['gross_bp'] / e['cost_bp'] - inputs['study']['dev']['facts']['break_even_x']) < 0.005
    assert paper['m']['paper.edge.gross_bp'] == bp.fmt(e['gross_bp'], '+.1')


def test_the_export_is_the_headline_runs(inputs):
    """study.json also lists the published v32 run's export; the paper reads the export of the
    run its headline JSON describes, never v32's."""
    run_dir = inputs['headline_path'].rsplit('/', 1)[0]
    assert inputs['results_path'].startswith(run_dir + '/')
    assert len(inputs['results']['all_trades']) == inputs['headline']['main']['trades']


def test_performance_table(built):
    paper, _ = built
    rows = {r[0]: r[1:] for r in paper['tables']['performance']}
    assert rows['Trading days'] == ['628', '716', '628']
    assert rows['Maximum drawdown, %'][0] == '−4.05'
    # the main backtest's figures are the headline JSON's, as the text quotes them
    assert rows['Annual turnover, × capital'][0] == paper['m']['main.annual_turnover_x'].rstrip('×')
    assert all(len(v) == 3 for v in rows.values())


def test_figures_keep_their_text(built):
    """Chart text is text (searchable, copyable), set in the Plex families Typst embeds."""
    _, figs = built
    for name, svg in figs.items():
        assert '<text' in svg, name
        families = set(re.findall(r"font-family: '([^']+)'", svg))
        assert families and families <= {'IBM Plex Sans', 'IBM Plex Sans Medm', 'IBM Plex Sans SmBld'}, name
        assert 'font-weight' not in svg, name


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
        '0.002', '0.05', '0.1', '0.20', '0.25', '0.3', '0.30', '0.4', '0.5', '0.50', '0.55', '0.6', '0.75', '1.0',
        '1.25', '1.5', '1.8', '1.96', '2.5', '126', '252', '500',
        '0.10',                                          # the Benjamini-Hochberg diagnostic's second level
        '404',                                           # the HTTP status of a symbol the vendor no longer serves
        # published results quoted in the text (Avellaneda and Lee 2010; Almgren et al. 2005;
        # Do and Faff 2010; Chen et al. 2019; Goyal, Jegadeesh and Wu 2026; Clegg 2014)
        '1.44', '1.1', '0.9', '0.314', '0.86', '0.37', '0.24', '1.40', '8.81', '4.5', '10.2', '860,000',
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


def test_main_typ_keys_and_claims_exist(sealed_built, evaluated_built):
    """Every key, claim, flag, table and exhibit main.typ names exists in the data: the sealed
    holdout's build, or (for the evaluated holdout's, 'paper.ho.' keys and 'ho_' claims and
    flags, which main.typ reads only once the holdout is complete) the evaluated one's. A claim
    outside the holdout's branches holds for the committed data, the holdout sealed."""
    paper, _ = sealed_built
    evaluated, _ = evaluated_built
    text = _main_typ()
    keys = set(re.findall(r'(?:#m|kpi-value|#path|\bm)\("([\w.]+)"', text)) | set(re.findall(r'D\.m\.at\("([\w.]+)"\)', text))
    holdout = {k for k in keys if k.startswith('paper.ho.')}
    assert keys and keys - holdout <= set(paper['m']), sorted(keys - holdout - set(paper['m']))
    assert holdout and holdout <= set(evaluated['m']), sorted(holdout - set(evaluated['m']))
    assert not holdout & set(paper['m']) and not any(k.startswith('paper.holdout.') for k in evaluated['m'])
    for name in set(re.findall(r'claim\("(\w+)"\)', text)):
        if name.startswith('ho_'):
            assert name in evaluated['claims'] and name not in paper['claims'], name
        else:
            assert paper['claims'][name] is True, name
    for name in set(re.findall(r'flag\("(\w+)"\)', text)):
        assert name in (evaluated['flags'] if name.startswith('ho_') else paper['flags']), name
    for name in set(re.findall(r'\bT\("(\w+)"\)', text)):
        assert name in (evaluated['tables'] if name.startswith('ho_') else paper['tables']), name
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

def test_absent_snooping_results_are_forthcoming(sealed_inputs):
    """Without the variant family's results its numbers print as pending, its table holds no
    number, its claims are false and it is listed as forthcoming; the exhibit keeps the
    deflated Sharpe curve alone."""
    inp = copy.deepcopy(sealed_inputs)
    inp['study']['dev']['snooping']['results'] = None
    paper, figs = bp.build_data(inp)
    assert [r[0] for r in paper['forthcoming']] == ['snooping', 'holdout']
    assert paper['m']['study.dev.snooping.results.spa_zero.p'] is None
    assert paper['why']['study.dev.snooping.results.pbo_pct'].startswith('pending (')
    assert all('pending' in r[1] for r in paper['tables']['snooping'])
    assert not paper['flags']['snooping'] and paper['claims']['family_beats_neither_cash_nor_gatev'] is False
    assert figs.get('dsr')                                     # the deflated Sharpe panel alone


def test_snooping_and_robustness_numbers_are_the_site_data(inputs, built):
    """The family's and the robustness checks' numbers are study.json's, formatted once."""
    paper, _ = built
    sn = inputs['study']['dev']['snooping']['results']
    f = inputs['study']['dev']['facts']
    assert paper['m']['study.dev.snooping.results.spa_zero.p'] == bp.fmt(sn['spa_zero']['p'], '.3')
    assert paper['m']['study.dev.snooping.results.pbo_pct'] == bp.fmt(sn['pbo_pct'], '.1%')
    assert paper['m']['study.dev.facts.start_sharpe_median'] == bp.fmt(f['start_sharpe_median'], '.2')
    assert [r[0] for r in paper['tables']['startdates']][0].endswith('(published)')
    assert len(paper['tables']['startdates']) == f['start_n'] and len(paper['tables']['halves']) == 2
    assert paper['claims']['headline_start_first_unmatched'] and paper['claims']['family_overfits']
    # like for like: the published path beats most later starts on their own days, but is not
    # the best start on the days all twelve share
    assert paper['claims']['headline_path_beats_most_later_starts']
    assert paper['claims']['headline_not_first_on_shared_days']
    assert paper['m']['study.dev.facts.start_matched_wins'] == bp.fmt(f['start_matched_wins'], '.0')
    # selection on the family does worse than a variant picked without looking, on the same splits
    assert paper['claims']['family_selection_worse_than_base'] and paper['claims']['family_best_dsr_not_significant']
    reg = inputs['study']['registry']
    assert len(paper['tables']['trials']) == reg['rows'] and reg['recorded_runs'] < reg['rows']


def test_committed_results_fill_every_exhibit(inputs, built):
    """Every exhibit has its data except the sealed holdout's, which alone is forthcoming; once
    the holdout's result is committed, every exhibit has its data."""
    paper, figs = built
    for name in ('costcurve', 'exitrace', 'decay', 'persistence', 'halflife', 'capacity', 'scenarios', 'universe',
                 'residual', 'validation', 'snapshots', 'schedules'):
        assert figs.get(name), name
    if inputs['study']['holdout']['status'] == 'sealed':
        assert paper['pending'] == {'holdout': 'Sealed.'}
        assert [r[0] for r in paper['forthcoming']] == ['holdout']
    else:
        assert paper['pending'] == {} and paper['forthcoming'] == [] and figs.get('holdout')
    assert paper['tables']['validation'][0][2].startswith('4,692 trades, +82.6 bp')
    assert paper['flags']['random_band'] and paper['flags']['residual'] and paper['flags']['scenarios']


def test_an_absent_optional_section_is_listed_as_forthcoming(inputs):
    """A run without the evidence layer, the scenarios, the second family or the validation
    still builds: each missing exhibit is left out and listed as forthcoming, never drawn."""
    inp = copy.deepcopy(inputs)
    dev = inp['study']['dev']
    for k in ('exit_race', 'decay', 'persistence', 'half_lives', 'capacity', 'cost_sensitivity', 'cost_curve'):
        dev.pop(k)
    inp['study'].pop('residual')
    inp['study'].pop('validation')
    paper, figs = bp.build_data(inp)
    later = [r[0] for r in paper['forthcoming']]
    for name in ('exitrace', 'decay', 'persistence', 'halflife', 'capacity', 'scenarios', 'costcurve', 'residual',
                 'validation'):
        assert name not in figs and name in later, name
    assert paper['tables']['scenarios'] == [] and all(r[2] == 'pending' for r in paper['tables']['validation'])
    assert paper['claims']['residual_ci_spans_zero'] is False          # the text cannot assert it


def test_the_residual_arm_must_be_the_published_export_study_json_was_built_from(tmp_path):
    """The paper prints the residual arm from study.json only when that file was built from the
    published export (results/residual_dev/residual_statarb.json) and the export is unchanged."""
    root = tmp_path / 'repo'
    study = json.loads((REPO / 'assets' / 'study.json').read_text(encoding='utf-8'))
    for rel in study['meta']['sources']:
        if (REPO / rel).is_file():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / rel, root / rel)
    (root / 'assets').mkdir()

    def write(study_):
        (root / 'assets' / 'study.json').write_text(json.dumps(study_), encoding='utf-8')

    published = 'results/residual_dev/residual_statarb.json'
    study['meta']['sources'].pop(published)          # a study.json that does not list the export
    (root / published).unlink()
    study['residual'] = {'sharpe': 0.31, 'ret_pct': 1.2, 'trades': 5400, 'lo': -0.9, 'hi': 1.5, 'p': 0.31,
                         'period': ['2023-07-03', '2025-12-31'], 'commit': 'abc'}
    write(study)
    with pytest.raises(bp.PaperDataError, match='residual'):
        bp.load_inputs(root)
    export = root / 'results' / 'residual_dev' / 'residual_statarb.json'
    export.parent.mkdir(parents=True, exist_ok=True)
    export.write_text('{"summary": {}}', encoding='utf-8')
    study['meta']['sources']['results/residual_dev/residual_statarb.json'] = bp._sha256(export)
    write(study)
    assert bp.load_inputs(root)['residual_path'] == 'results/residual_dev/residual_statarb.json'
    export.write_text('{"summary": {"sharpe": 9.9}}', encoding='utf-8')
    with pytest.raises(bp.PaperDataError, match='changed after'):
        bp.load_inputs(root)


def test_unknown_or_unprintable_sections_stop_the_build(inputs):
    inp = copy.deepcopy(inputs)
    inp['study']['dev']['new_section'] = [1, 2, 3]
    with pytest.raises(bp.PaperDataError, match='new_section'):
        bp.build_data(inp)
    # an evaluated holdout of another shape (an earlier single-arm one) is not printed
    inp = copy.deepcopy(inputs)
    inp['study']['holdout'] = {'status': 'complete', 'sharpe': 1.0, 'lo': 0.1, 'hi': 1.9, 'p': 0.01}
    with pytest.raises(bp.PaperDataError, match='holdout'):
        bp.build_data(inp)
    inp['study']['holdout'] = {'status': 'evaluated'}
    with pytest.raises(bp.PaperDataError, match='holdout'):
        bp.build_data(inp)


def test_site_tokens_are_the_light_theme():
    tokens = bp.site_tokens()
    assert tokens['ink'] == '#141413' and tokens['series-1'] == '#2a78d6'


def test_holdout_power_shrinks_with_length(inputs):
    p = bp.holdout_power(inputs['study']['dev']['daily']['net'])
    mde = [r['mde_shape'] for r in p['rows']]
    assert mde == sorted(mde, reverse=True) and all(x > 1.5 for x in mde)


# ── the evaluated holdout: the 2025 dress rehearsal registered as the holdout ─────

bsd = _load('build_site_data')
rt = _load('register_trial')
REHEARSAL_CALENDAR = 'rehearsal2025'
RUN_COMMIT = '6aaf7efb1eb074cdb4e2137f961112ba62234c51'     # the rehearsal's runs
REGISTERED = '7c7d3f904ec643b9a9dc658c2aa46bad506cc3a5'      # the registered commit, before a crash fix


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]


def _evaluated_tree(base, results=REPO / 'results'):
    """A results tree whose holdout2026/ is the published dress rehearsal (results/rehearsal2025b,
    calendar rehearsal2025), registered after the committed trials as the holdout, with its
    attempt lines (modelled on rehearsal2025b's) and the completion line; every other entry is
    the committed results/ (`results`). A committed holdout (its directory, its registry line
    and attempt lines) is left out, so the tree is the same before and after publication."""
    root = base / 'results'
    root.mkdir()
    for path in sorted(results.iterdir()):
        if path.name not in ('trial_registry.jsonl', 'trial_attempts.jsonl', 'holdout2026'):
            (root / path.name).symlink_to(path)
    shutil.copytree(REPO / 'results' / 'rehearsal2025b', root / 'holdout2026')
    registry = [e for e in _lines(results / 'trial_registry.jsonl') if e['name'] != 'holdout2026']
    rehearsal = next(e for e in registry if e['name'] == 'rehearsal2025b')
    attempts = []
    for x in copy.deepcopy(rehearsal['attempts']):
        x.pop('note', None)
        x.update(name='holdout2026')
        if x['event'] == 'start':
            x['prereg_commit'] = RUN_COMMIT
        attempts.append(x)
    entry = dict(rehearsal, name='holdout2026', prereg_commit=RUN_COMMIT, note=None, attempts=attempts,
                 head=attempts[-1]['head'], evaluation=rt.evaluation_summary(root / 'holdout2026' / 'evaluation.json'))
    (root / 'trial_registry.jsonl').write_text(''.join(json.dumps(e, sort_keys=True) + '\n' for e in registry + [entry]),
                                                encoding='utf-8')
    done = {'attempt': attempts[-1]['attempt'], 'event': 'completed', 'name': 'holdout2026',
            'utc': '2026-10-21T14:03:09+00:00'}
    committed = ''.join(line + '\n' for line in (results / 'trial_attempts.jsonl').read_text(encoding='utf-8').splitlines()
                        if line.strip() and json.loads(line).get('name') != 'holdout2026')
    (root / 'trial_attempts.jsonl').write_text(committed + ''.join(json.dumps(x, sort_keys=True) + '\n'
                                                                   for x in attempts + [done]), encoding='utf-8')
    return root


@pytest.fixture(scope='module')
def evaluated_tree(tmp_path_factory):
    """(results tree, study.json): the site data of the tree above, built by build_site_data.py
    --results (calendar rehearsal2025 stands in for holdout2026)."""
    base = tmp_path_factory.mktemp('evaluated')
    root = _evaluated_tree(base)
    study = bsd.build(root / 'v33_dev', results_root=root, holdout_calendar=REHEARSAL_CALENDAR)
    path = base / 'study.json'
    path.write_text(bsd.dumps(study), encoding='utf-8')
    return root, path


@pytest.fixture(scope='module')
def evaluated(evaluated_tree):
    """The paper's inputs once the holdout is evaluated."""
    root, path = evaluated_tree
    return bp.load_inputs(bp.ROOT, path, root, REHEARSAL_CALENDAR)


@pytest.fixture(scope='module')
def evaluated_built(evaluated):
    return bp.build_data(evaluated)


def _arm(H, key):
    return next(a for a in H['arms'] if a['key'] == key)


def _variant(inputs, *edits):
    """A copy of the inputs with the evaluated holdout edited (each edit takes the holdout block)."""
    inp = copy.deepcopy(inputs)
    for edit in edits:
        edit(inp['study']['holdout'])
    return inp


def _decide(key, p_holm, edge, **fields):
    """An edit: one confirmatory arm's Holm-adjusted p and decision, in the arm and the decision
    alike (as build_site_data.py writes them), and any other fields of the arm."""
    def edit(H):
        _arm(H, key).update(p_holm=p_holm, edge=edge, p_holm_below_alpha=edge, **fields)
        H['decision']['arms'][key].update(p_holm=p_holm, edge=edge, p_holm_below_alpha=edge)
        H['decision']['rejected'] = [k for k in H['family'] if H['decision']['arms'][k]['edge']]
    return edit


_REJECT_S1 = _decide('v33_pairs', 0.0084, True, sharpe=2.8872, lo=0.7096, hi=5.1316, t=2.635, p_one_sided=0.0042)


def _flat(key):
    """An edit: `key` opened no position, as the evaluation reports such an arm (t = 0, p = 0.5,
    lag 0, no Sharpe ratio), with a flat path."""
    def edit(H):
        a = _arm(H, key)
        a.update(flat=True, trades=0, t=0.0, lags=0, p_one_sided=0.5, ret_pct=0.0, gross_ret_pct=0.0,
                 **{f: None for f in ('sharpe', 'lo', 'hi', 'gross_sharpe', 'sharpe_lo2002', 'psr_pct', 'sharpe_se',
                                      'ucb', 'mde', 'mde_single')})
        if H.get('daily'):
            H['daily']['cum'][key] = [0.0] * len(H['daily']['dates'])
        if a['hypothesis']:
            _decide(key, 1.0, False)(H)
    return edit


def _crash_fix(H):
    """An edit: attempt 1 at the registered commit failed at S1; attempt 2 ran every step at a
    crash-fix commit whose diff is published."""
    R = H['provenance']
    fix = {'fix': 'json_export: write a non-finite float as null', 'diff': 'holdout2026_crash_fix_6aaf7efb1eb0.diff',
           'sha256': 'a' * 64}
    first = dict(R['attempts'][0], attempt=1, head=REGISTERED, at_registered_commit=True, crash_fix=None,
                 steps_done=['universe', 'data'], completed_utc=None,
                 failed={'step': 'v33', 'note': 'exit 1', 'utc': '2026-10-21T12:40:31+00:00'})
    second = dict(R['attempts'][0], attempt=2, at_registered_commit=False, crash_fix=fix)
    R.update(attempts=[first, second], n_attempts=2, n_failed=1, registered_commit=REGISTERED,
             at_registered_commit=False, crash_fix=fix,
             crash_fix_diffs=[{'file': 'logs/' + fix['diff'], 'commit': '6aaf7efb1eb0', 'sha256': fix['sha256'],
                               'bytes': 531, 'files': ['pairs_trading/json_export.py'], 'insertions': 3,
                               'deletions': 1, 'attempts': [2]}])
    R['registry'] = dict(R['registry'], prereg_commit=REGISTERED)


def test_the_evaluated_holdout_fills_its_sections(evaluated, evaluated_built):
    """Once evaluated, the holdout is printed from study.json alone: its exhibit is drawn and no
    longer forthcoming, the sealed placeholders give way to its numbers (rounded as the site
    rounds them), each arm has a row with its decision as the evaluation states it, and the
    registry's holdout line adds one trial with its three runs."""
    paper, figs = evaluated_built
    H = evaluated['study']['holdout']
    assert paper['flags']['holdout_complete'] and figs.get('holdout') and 'holdout' not in paper['pending']
    assert 'holdout' not in [r[0] for r in paper['forthcoming']]
    assert ['ex-holdout'] == [r[2] for r in paper['concordance'] if r[2] == 'ex-holdout']
    rows = paper['tables']['ho_results']
    assert [r[:2] for r in rows] == [['H1 · S1', 'v33 pairs'], ['H2 · S2', 'Avellaneda–Lee'], ['S3', 'v32, frozen']]
    for row, a in zip(rows, H['arms']):
        assert row[5] == bp.fmt(a['sharpe'], '+.2', half_up=True) and row[7] == bp.fmt(a['t'], '.2', half_up=True)
        assert row[10] == {True: 'Rejected', False: 'Not rejected', None: 'Not tested'}[a['edge']]
    assert rows[2][9] == '—' and rows[2][10] == 'Not tested'
    m = paper['m']
    assert m['paper.ho.s1.p_holm_text'] == bp._p_text(H['decision']['arms']['v33_pairs']['p_holm'], False)
    assert m['paper.ho.days'] == str(H['arms'][0]['days']) and m['paper.ho.run.commit'] == RUN_COMMIT[:12]
    assert not [k for k in m if k.startswith('paper.holdout.')]
    # what is null is so for a reason of its own, never a pending result: S3 has no point-in-time
    # universe, and no crash fix was recorded
    assert paper['why'] and all(k.startswith(('paper.ho.s3.gap_', 'paper.ho.run.crash_fix')) for k in paper['why'])
    assert not any(why.startswith('pending') for why in paper['why'].values())
    assert paper['claims']['ho_h1_no_edge'] and paper['claims']['ho_h2_no_edge'] and paper['claims']['ho_none_rejected']
    assert paper['claims']['ho_runs_at_registered_commit'] and paper['claims']['ho_single_attempt']
    assert [r[0] for r in paper['tables']['trials']][-3:] == ['holdout2026'] * 3
    assert [r[2] for r in paper['tables']['ho_record']] == ['registered']
    assert len(paper['tables']['ho_universe']) == len(_arm(H, 'v33_pairs')['universe']) + len(
        _arm(H, 'avellaneda_lee')['universe'])
    # the paper's date is the holdout's: its runs, its registration and its completion are the
    # newest dated inputs
    R = H['provenance']
    assert paper['meta']['paper_date'] == max([*R['run_utc'].values(), R['registry']['registered_utc'],
                                               R['completed_utc']])[:10]
    # the other statistics of every arm, each the arm's value as the site rounds it
    detail = {r[0]: r[1:] for r in paper['tables']['ho_detail']}
    arms = H['arms']

    def f(x, spec):
        return bp.fmt(x, spec, half_up=True) if x is not None else '—'
    assert detail['Gross return, %'] == [f(a['gross_ret_pct'], '+.2') for a in arms]
    assert detail['Sharpe ratio before costs'] == [f(a['gross_sharpe'], '+.2') for a in arms]
    assert detail['Sharpe ratio, Lo (2002) annualisation'] == [f(a['sharpe_lo2002'], '+.2') for a in arms]
    assert detail['Probabilistic Sharpe ratio, %'] == [f(a['psr_pct'], '.1') for a in arms]
    assert detail['Standard error of the Sharpe ratio'] == [f(a['sharpe_se'], '.2') for a in arms]
    assert detail['Minimum detectable Sharpe, one-sided 2.5% / 5%'] == [
        f"{f(a['mde'], '.2')} / {f(a['mde_single'], '.2')}" for a in arms]
    assert detail['Newey–West lags'] == [str(a['lags']) for a in arms]
    assert detail['Gross exposure, % of equity: average / maximum'] == [
        f"{f(a['exposure']['avg_pct'], '.1')} / {f(a['exposure']['max_pct'], '.1')}" for a in arms]
    assert detail['Days with open positions'] == [str(a['exposure']['days_open']) for a in arms]
    assert detail['Gatev distance method: Sharpe ratio (common days)'] == [
        f"{f(a['vs_gatev']['distance_sharpe'], '+.2')} ({a['vs_gatev']['days']})" for a in arms]
    assert detail['Arm minus Gatev, Sharpe [95% interval]'] == [
        f"{f(a['vs_gatev']['diff'], '+.2')} [{f(a['vs_gatev']['lo'], '+.2')}, {f(a['vs_gatev']['hi'], '+.2')}]" for a in arms]
    assert detail['Ledoit–Wolf p of the difference, two-sided'] == [bp._p_text(a['vs_gatev']['p']) for a in arms]
    assert detail['Baselines from'] == ['its own run', 'S1’s run', 'its own run']


def test_a_rejection_is_worded_by_the_decision(evaluated):
    paper, figs = bp.build_data(_variant(evaluated, _REJECT_S1))
    assert paper['flags']['ho_h1_edge'] and not paper['flags']['ho_h2_edge'] and paper['flags']['ho_any_edge']
    assert paper['claims']['ho_h1_edge'] and paper['claims']['ho_h2_no_edge'] and paper['claims']['ho_s1_ci_excludes_zero']
    assert paper['m']['paper.ho.s1.p_holm_rel'] == '= 0.008' and paper['tables']['ho_results'][0][10] == 'Rejected'
    both = bp.build_data(_variant(evaluated, _REJECT_S1, _decide('avellaneda_lee', 0.0002, True, sharpe=3.29,
                                                                  lo=1.06, hi=5.68, t=3.686, p_one_sided=0.0001)))[0]
    assert both['flags']['ho_both_edge'] and both['m']['paper.ho.s2.p_holm_text'] == '<0.001'


@pytest.mark.parametrize('p_holm, edge, text, decision', [(0.0498, True, '<0.050', 'Rejected'),
                                                          (0.0500, False, '0.050', 'Not rejected'),
                                                          (0.0503, False, '0.050', 'Not rejected')])
def test_a_holm_p_at_alpha_prints_with_its_decision(evaluated, p_holm, edge, text, decision):
    """A Holm-adjusted p below alpha that rounds to it prints as '<0.050', never as '0.050'
    beside a rejection; one at or above alpha prints as itself. An interval across zero beside
    a rejection is said to include zero."""
    inp = _variant(evaluated, _decide('v33_pairs', p_holm, edge, sharpe=2.15, lo=-0.04, hi=4.34, t=1.962,
                                      p_one_sided=0.0249))
    paper, _ = bp.build_data(inp)
    row = paper['tables']['ho_results'][0]
    assert row[9] == text and row[10] == decision and paper['m']['paper.ho.s1.p_holm_text'] == text
    assert paper['flags']['ho_h1_edge'] is edge and paper['claims']['ho_s1_ci_includes_zero']


def _contradict(key, **fields):
    def edit(H):
        _arm(H, key).update(**fields)
    return edit


@pytest.mark.parametrize('edit, match', [
    (_contradict('v33_pairs', edge=True), 'contradicts|decision'),                    # the arm against the decision
    (_decide('v33_pairs', 0.06, True), 'contradicts'),                                # an edge at p above alpha
    (_decide('v33_pairs', 0.04, False), 'contradicts'),                               # no edge at p below alpha
    (lambda H: H['decision'].update(rejected=['v33_pairs']), 'rejected|contradicts'),
    (_contradict('v32_pairs', p_holm=0.01), 'descriptive'),
    (_contradict('v32_pairs', role='confirmatory'), 'role'),
    (lambda H: H.update(alpha=0.1), 'alpha'),
    (lambda H: H.update(family=['v33_pairs']), 'family'),
    (lambda H: H['arms'].reverse(), 'arms'),
    (lambda H: _flat('v33_pairs')(H) or _decide('v33_pairs', 0.01, True)(H), 'edge'),     # an edge on a flat arm
    (_contradict('v33_pairs', flat=True), 'flat'),
    (lambda H: H.update(period_matches_calendar=False), 'period_matches_calendar'),
    (lambda H: H['provenance'].update(n_attempts=2), 'attempt'),
    (lambda H: H['provenance'].update(n_unfinished=1), 'attempt counts'),
    (lambda H: H['provenance'].update(attempt_record_lines=3), 'disagree'),             # the attempt file and the registry
    (lambda H: (H['provenance']['attempts'][-1].update(failed={'step': 'register', 'note': 'exit 1', 'utc': 'x'}),
                H['provenance'].update(n_failed=1)), 'disagree'),                      # the last attempt failed
    (lambda H: H['provenance']['run_commits'].update(v32_pairs='f' * 40), 'not all from'),
    (lambda H: H['provenance'].update(at_registered_commit=False), 'registered'),
    (lambda H: _crash_fix(H) or H['provenance'].update(crash_fix_diffs=[]), 'not published|registered'),
    (lambda H: H['daily']['dates'].pop(), 'daily'),
])
def test_a_holdout_that_contradicts_itself_stops_the_build(evaluated, edit, match):
    """The decision is read from the evaluation, never recomputed; parts that disagree with it
    or with each other stop the build rather than print."""
    with pytest.raises(bp.PaperDataError, match=match):
        bp.build_data(_variant(evaluated, edit))


def test_the_holdout_must_be_on_the_expected_calendar(evaluated):
    inp = copy.deepcopy(evaluated)
    inp['holdout_calendar'] = 'holdout2026'
    with pytest.raises(bp.PaperDataError, match='calendar'):
        bp.build_data(inp)


@pytest.mark.parametrize('key, sid', [('v33_pairs', 's1'), ('v32_pairs', 's3')])
def test_an_arm_that_never_trades_has_no_sharpe_ratio(evaluated, key, sid):
    """A tested or descriptive arm with no position: no Sharpe ratio (never 0, None or a number),
    t = 0 and p = 0.5 as the evaluation reports them; its row and the exhibit say so."""
    paper, figs = bp.build_data(_variant(evaluated, _flat(key)))
    row = paper['tables']['ho_results'][int(sid[1]) - 1]
    assert row[5] == row[6] == row[11] == row[12] == '—' and row[7] == '0.00' and row[8] == '0.500'
    assert paper['m'][f'paper.ho.{sid}.sharpe'] is None and paper['why'][f'paper.ho.{sid}.sharpe'].startswith('not defined')
    assert paper['m'][f'paper.ho.{sid}.sharpe_or'] == 'no position' and paper['flags'][f'ho_{sid}_flat']
    assert paper['claims'][f'ho_{sid}_flat'] and 'no position' in figs['holdout']
    held = json.dumps({k: v for k, v in paper['tables'].items() if k.startswith('ho_')})
    assert not re.search(r'\b(None|nan|NaN|null)\b', held + ' '.join(v for k, v in paper['m'].items()
                                                                       if k.startswith('paper.ho.') and v))


def test_the_run_record_after_a_crash_fix(evaluated):
    """Attempts, failures and the crash-fix diff are on record: the text cannot say the runs
    came from the registered commit."""
    paper, _ = bp.build_data(_variant(evaluated, _crash_fix))
    assert paper['flags']['ho_crash_fix'] and not paper['flags']['ho_at_registered_commit']
    assert paper['claims']['ho_crash_fix_published'] and not paper['claims']['ho_runs_at_registered_commit']
    assert not paper['claims']['ho_single_attempt']
    assert [r[1:3] for r in paper['tables']['ho_record']] == [[REGISTERED[:7], 'registered'], [RUN_COMMIT[:7], 'crash fix']]
    assert paper['tables']['ho_record'][0][5] == 'S1 (exit 1)'
    assert paper['m']['paper.ho.run.crash_fix_diff'] == 'holdout2026_crash_fix_6aaf7efb1eb0.diff'
    assert paper['m']['paper.ho.run.registered'] == REGISTERED[:12]
    assert paper['m']['paper.ho.run.attempts_phrase'] == 'two attempts: one failed and the last completed'
    assert paper['claims']['ho_attempts_on_record'] and not paper['claims']['ho_all_attempts_at_registered_commit']


OTHER = 'f77929a' + '0' * 33                                     # a later commit, frozen paths unchanged


def _interrupted(H):
    """An edit: attempt 1 at the registered commit finished the universe and data steps and
    stopped without recording a failure (killed); attempt 2 reused both and completed."""
    R = H['provenance']
    first = dict(R['attempts'][0], attempt=1, steps_done=['universe', 'data'], completed_utc=None, failed=None)
    second = dict(R['attempts'][0], attempt=2, steps_done=['v33', 'v32', 'residual', 'evaluate'])
    R.update(attempts=[first, second], n_attempts=2, n_failed=0, n_unfinished=1)


def _mixed_commits(H):
    """An edit: attempt 1 ran at a later commit and failed at the data step; attempt 2 ran every
    step at the registered commit, which the runs come from."""
    R = H['provenance']
    first = dict(R['attempts'][0], attempt=1, head=OTHER, at_registered_commit=False, crash_fix=None,
                 steps_done=['universe'], completed_utc=None,
                 failed={'step': 'data', 'note': 'exit 1', 'utc': '2026-10-21T11:30:02+00:00'})
    R.update(attempts=[first, dict(R['attempts'][0], attempt=2)], n_attempts=2, n_failed=1, n_unfinished=0)


def _no_completion(H):
    """An edit: the runbook stopped between registering the trial and appending its completion
    line, so the attempt record holds only the lines the registry line copies."""
    R = H['provenance']
    R['attempts'][-1]['completed_utc'] = None
    R.update(completed_utc=None, attempt_record_lines=R['registry']['attempt_lines'])


def test_an_attempt_that_stopped_without_a_failure_line(evaluated):
    """Killed, or its failure line not written: it neither failed nor completed, and the text
    says so ('none failed' is never printed as 'no of them failed')."""
    paper, _ = bp.build_data(_variant(evaluated, _interrupted))
    m = paper['m']
    assert m['paper.ho.run.attempts_phrase'] == ('two attempts: one stopped without finishing or recording a failure '
                                                 'and the last completed')
    assert paper['flags']['ho_unfinished'] and not paper['flags']['ho_failed'] and paper['claims']['ho_attempts_on_record']
    assert paper['claims']['ho_all_attempts_at_registered_commit']
    assert [r[5] for r in paper['tables']['ho_record']] == ['stopped; no failure recorded', '—']
    assert not any(re.search(r'\bno of\b', v or '') for v in m.values())


def test_attempts_at_different_commits_are_not_all_at_the_registered_one(evaluated):
    paper, _ = bp.build_data(_variant(evaluated, _mixed_commits))
    assert not paper['flags']['ho_all_attempts_at_registered_commit']
    assert not paper['claims']['ho_all_attempts_at_registered_commit']
    assert paper['claims']['ho_last_attempt_at_registered_commit'] and paper['claims']['ho_runs_at_registered_commit']
    assert [r[1:3] for r in paper['tables']['ho_record']] == [[OTHER[:7], 'later commit'], [RUN_COMMIT[:7], 'registered']]


def test_a_registered_trial_without_its_completion_line(evaluated):
    """The registry line is the record of a completed trial: without the completion line the
    paper still builds, says the line is missing, and ends the run at the registration."""
    paper, _ = bp.build_data(_variant(evaluated, _no_completion))
    m = paper['m']
    assert not paper['flags']['ho_completed'] and paper['claims']['ho_no_completion_line']
    assert m['paper.ho.run.completed'] is None and m['paper.ho.run.until'].endswith(', when it registered the trial')
    assert paper['tables']['ho_record'][-1][6].startswith('— (registered ')
    assert m['paper.ho.run.attempts_phrase'] == 'one attempt'


def test_the_paper_is_dated_by_the_holdout_record(evaluated):
    """A registration or completion on a later day than the runs dates the paper."""
    late = '2026-10-25T09:00:00+00:00'
    inp = _variant(evaluated, lambda H: (H['provenance'].update(completed_utc=late),
                                         H['provenance']['attempts'][-1].update(completed_utc=late)))
    assert bp.build_data(inp)[0]['meta']['paper_date'] == '2026-10-25'


@pytest.mark.parametrize('scale', [0.05, 0.3, 0.7, 1.0, 1.5, 2.2, 3.1, 4.7, 9.0])
def test_holdout_tick_labels_are_their_values(evaluated, scale):
    """Every tick of the holdout exhibit prints its own value at the printed precision: a tick at
    2.5 never prints as '+2', one at 0.25 never as '+0.2', on either pane."""
    H = copy.deepcopy(evaluated['study']['holdout'])
    H['daily']['cum'] = {k: [scale * x for x in v] for k, v in H['daily']['cum'].items()}
    for a in H['arms']:
        a.update(sharpe=scale * a['sharpe'], lo=scale * a['lo'], hi=scale * a['hi'])
    study = dict(evaluated['study'], holdout=H)
    tokens = bp.site_tokens()
    plt = bp._mpl(tokens)
    fig = bp.fig_holdout(study, bp.holdout_derived(bp.holdout_block(study, REHEARSAL_CALENDAR)), tokens, plt)
    try:
        for ax, axis in ((fig.axes[0], fig.axes[0].xaxis), (fig.axes[1], fig.axes[1].yaxis)):
            lo, hi = sorted(ax.get_xlim() if axis is ax.xaxis else ax.get_ylim())
            ticks = [v for v in axis.get_majorticklocs() if lo - 1e-9 <= v <= hi + 1e-9]
            assert len(ticks) >= 2
            for v in ticks:
                label = axis.get_major_formatter()(v, 0)
                printed = float(label.replace('−', '-').replace('+', ''))
                assert abs(printed - v) < 1e-9, (scale, v, label)
    finally:
        plt.close(fig)


def test_main_typ_writes_no_prime_after_a_digit():
    """Typst prints an apostrophe after a digit as a prime (S1′s): the text writes ’ there."""
    assert not re.findall(r"[0-9]'s\b", _main_typ())


def test_a_comparison_the_evaluation_leaves_out_says_why(evaluated):
    paper, _ = bp.build_data(_variant(evaluated, _no_percentile))
    assert paper['tables']['ho_detail_notes'] == ["S2: S2's trading dates are not the control's"]
    assert paper['tables']['ho_detail'][-2][2] == '—'


def test_without_daily_paths_the_exhibit_shows_the_arms_alone(evaluated):
    paper, figs = bp.build_data(_variant(evaluated, lambda H: H.update(daily=None)))
    assert not paper['flags']['ho_daily'] and figs['holdout'] and 'Cumulative' not in figs['holdout']


def test_a_holdout_record_changed_after_study_json_stops_the_build(evaluated_tree, tmp_path):
    """The holdout's files that study.json lists (its exports, evaluation and logs, the registry
    and the attempt record) must be the ones it was built from."""
    root, path = evaluated_tree
    for rel in ('results/trial_attempts.jsonl', 'results/holdout2026/evaluation.json'):
        study = json.loads(path.read_text(encoding='utf-8'))
        assert rel in study['meta']['sources']
        study['meta']['sources'][rel] = '0' * 64
        changed = tmp_path / 'study.json'
        changed.write_text(json.dumps(study), encoding='utf-8')
        with pytest.raises(bp.PaperDataError, match=re.escape(rel) + ' changed'):
            bp.load_inputs(bp.ROOT, changed, root, REHEARSAL_CALENDAR)


def test_a_paper_from_other_inputs_is_built_outside_the_repository(tmp_path):
    with pytest.raises(SystemExit):
        bp.main(['--study', str(tmp_path / 'study.json')])
    with pytest.raises(bp.PaperDataError, match='repository'):
        bp.write_copy({}, {}, REPO / 'paper' / 'elsewhere')
    # the copy's manifest names its files as the committed one does, never by a path outside
    main = bp.write_copy({'schema': 1}, {'x': '<svg/>'}, tmp_path / 'copy')
    names = bp.compile_inputs(main, main.parent / 'references.bib', main.parent / 'build' / 'paper_data.json',
                              main.parent / 'build' / 'figures')
    assert {'paper/main.typ', 'paper/references.bib', 'paper/build/paper_data.json', 'paper/build/figures/x.svg'} <= set(names)
    assert all(n.startswith('paper/') for n in names) and str(tmp_path) not in json.dumps(names)


def test_the_evaluated_tree_leaves_a_committed_holdout_out(tmp_path):
    """Once the holdout's result is committed, the stand-in tree is built the same way: the
    committed holdout2026/ and its lines are left out, never registered twice."""
    results = tmp_path / 'committed'
    results.mkdir()
    for path in sorted((REPO / 'results').iterdir()):
        if path.name not in ('trial_registry.jsonl', 'trial_attempts.jsonl', 'holdout2026'):
            (results / path.name).symlink_to(path)
    shutil.copytree(REPO / 'results' / 'rehearsal2025b', results / 'holdout2026')
    for name in ('trial_registry.jsonl', 'trial_attempts.jsonl'):
        text = (REPO / 'results' / name).read_text(encoding='utf-8')
        (results / name).write_text(text + json.dumps({'name': 'holdout2026', 'event': 'start', 'attempt': 1}) + '\n',
                                    encoding='utf-8')
    (tmp_path / 'tree').mkdir()
    root = _evaluated_tree(tmp_path / 'tree', results)
    assert not (root / 'holdout2026').is_symlink()
    assert [e['name'] for e in _lines(root / 'trial_registry.jsonl')].count('holdout2026') == 1
    hold = bsd.build(root / 'v33_dev', results_root=root, holdout_calendar=REHEARSAL_CALENDAR)['holdout']
    assert hold['status'] == 'complete' and hold['provenance']['n_attempts'] == 1


# ── the compile (needs the optional typst package) ───────────────────────────────

def test_paper_compiles_to_the_committed_pdf(built):
    typst_ = _typst()
    paper, _ = built
    pdf = bp.compile_pdf(paper)
    assert pdf.startswith(b'%PDF')
    pages = len(re.findall(rb'/Type\s*/Page(?![s\w])', pdf))
    # 26 exhibits, the start-date, snooping, persistence and regime tables, the disclosures of
    # the trial record and the appendix (37 pages); a runaway float would exceed it
    assert 14 <= pages <= 40, pages
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


def _no_percentile(H):
    """An edit: S2's random-pair percentile not computed, with the evaluation's note."""
    _arm(H, 'avellaneda_lee')['random_pair'].update(percentile=None, note="S2's trading dates are not the control's")


_REJECT_S2_AT_ALPHA = _decide('avellaneda_lee', 0.0498, True, sharpe=2.15, lo=-0.04, hi=4.34, t=1.962, p_one_sided=0.0249)


@pytest.mark.parametrize('edits', [(), (_REJECT_S1,), (_flat('v32_pairs'), _crash_fix, _no_percentile),
                                   (_flat('v33_pairs'), lambda H: H.update(daily=None)),
                                   (_REJECT_S1, _decide('avellaneda_lee', 0.0002, True, sharpe=3.29, lo=1.06, hi=5.68,
                                                        t=3.686, p_one_sided=0.0001)),
                                   (_REJECT_S2_AT_ALPHA,), (_flat('avellaneda_lee'),),
                                   (_interrupted, _no_completion), (_mixed_commits,)],
                         ids=['none-rejected', 'h1-rejected', 's3-flat-crash-fix', 's1-flat-no-daily', 'both-rejected',
                              'h2-rejected-at-alpha', 's2-flat', 'interrupted-no-completion', 'mixed-commits'])
def test_the_evaluated_holdout_compiles(evaluated, tmp_path, edits):
    """Once the holdout is evaluated the paper compiles whatever the result: every claim its
    branches make holds, nothing prints as pending, and the summary with its key figures
    still fits on page 1 (main.typ asserts it). The sealed branch is the committed PDF."""
    typst_ = _typst()
    paper, figs = bp.build_data(_variant(evaluated, *edits))
    main = bp.write_copy(paper, figs, tmp_path / 'paper')
    pdf = bp.compile_pdf(paper, main=main)
    assert pdf.startswith(b'%PDF')
    assert 14 <= len(re.findall(rb'/Type\s*/Page(?![s\w])', pdf)) <= 44
    printed = typst_.query(str(main), '<pending>', field='value', root=str(main.parent),
                           font_paths=[str(bp.FONTS)], ignore_system_fonts=True)
    assert (json.loads(printed) if isinstance(printed, str) else printed) == []


def test_a_summary_that_no_longer_fits_page_one_stops_the_compile(evaluated_built, tmp_path):
    typst_ = _typst()
    paper, figs = copy.deepcopy(evaluated_built)
    paper['m']['paper.ho.s2.decision'] = 'not rejected ' * 40
    main = bp.write_copy(paper, figs, tmp_path / 'paper')
    with pytest.raises(Exception, match='page 1'):
        typst_.compile(str(main), root=str(main.parent), font_paths=[str(bp.FONTS)], ignore_system_fonts=True)
