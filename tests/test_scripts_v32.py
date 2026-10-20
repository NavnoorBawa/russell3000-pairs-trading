"""scripts/check_published_numbers.py and scripts/make_og_image.py (v32 rewrites).

Both scripts read outputs/headline_metrics.json; these tests build temporary JSON,
README and HTML fixtures, so they never touch the repository's real published files.
"""
import importlib.util
import json
import os
import subprocess
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, 'scripts')


def _load(name):
    spec = importlib.util.spec_from_file_location(f'_script_{name}', os.path.join(SCRIPTS, f'{name}.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chk = _load('check_published_numbers')
og = _load('make_og_image')

MINUS = '−'


def _headline():
    """A headline_metrics.json shaped like export_headline_metrics' output (v31-like values)."""
    return {
        'schema': 1, 'version': '32.0.0',
        'run_config': {'run_timestamp_utc': '2026-09-05T12:00:00+00:00', 'git_commit': 'a' * 40,
                       'data': {'data_start': '2020-01-02', 'data_end': '2025-06-30'}},
        'main': {'period_start': '2023-07-03', 'period_end': '2025-06-30', 'total_return_pct': -0.31,
                 'sharpe': -0.31, 'trades': 14, 'win_rate_pct': 28.6, 'max_drawdown_pct': -0.81,
                 'exit_reasons': {'stop': 3, 'target': 4, 'time': 7}},
        'oos': {'period_start': '2023-01-05', 'period_end': '2025-06-30', 'windows': 10, 'windows_positive': 1,
                'windows_no_trades': 3, 'windows_selection_clean': 10, 'windows_skipped': 9,
                'avg_window_return_pct': -0.28, 'median_window_return_pct': -0.37, 'pooled_sharpe': -1.23,
                'total_return_pct': -2.79, 'trades': 40, 'max_drawdown_pct': -3.1,
                'window_ids': list(range(10, 20)),
                'window_returns_pct': [-0.463, -0.448, -0.093, 0.568, -0.737, -0.995, -0.648, 0.0, 0.0, 0.0],
                'window_trades': [5, 6, 4, 7, 5, 6, 7, 0, 0, 0]},
        'significance': {
            'main': {'ann_sharpe': -0.31, 'hac_t': -0.49, 'hac_p': 0.633, 'psr': 0.3255, 'psr_pct': 32.5,
                     'boot_lo': -1.7, 'boot_hi': 0.8, 'dsr': 0.009, 'dsr_pct': 0.9},
            'oos_daily': {'ann_sharpe': -1.23, 'hac_t': -1.86, 'hac_p': 0.063, 'psr': 0.022, 'psr_pct': 2.2,
                          'boot_lo': -2.41, 'boot_hi': 0.06, 'dsr': 0.0, 'dsr_pct': 0.0},
            'oos_windows': {'n': 10, 'mean_pct': -0.282, 't': -1.94, 'p': 0.085, 'p_one_sided_negative': 0.042,
                            'ci_lo_pct': -0.611, 'ci_hi_pct': 0.047, 'boot_ci_lo_pct': -0.548,
                            'boot_ci_hi_pct': -0.008, 'positive': 1}},
        'benchmarks': {'gatev': {'total_return_pct': 2.78, 'sharpe': 0.26},
                       'random_control': {'median_sharpe': None, 'p5_sharpe': None, 'p95_sharpe': None,
                                          'n_draws': 5},
                       'sharpe_diff_vs_gatev': {'diff': None, 'p': None}},
        'fdr': {'pairs_tested': 36524, 'significant_raw_p05': 3725, 'survive_bh_fdr_q05': 0,
                'survive_bh_fdr_q10': 0, 'final_selected_pairs': 40},
        'fund_profiles': {'quant_hf': {'name': 'Systematic Stat-Arb', 'total_return_pct': -1.46,
                                       'sharpe': -0.57, 'max_drawdown_pct': -2.5, 'max_gross_leverage': 0.54}},
    }


def m(key, text):
    return f'<!--m:{key}-->{text}<!--/m-->'


README_OK = f"""# Results

The out-of-sample result is **{m('oos.avg_window_return_pct', MINUS + '0.28%')}/qtr** (pooled Sharpe
{m('oos.pooled_sharpe', MINUS + '1.23')}, {m('oos.windows_positive', '1')} of {m('oos.windows', '10')}
windows positive, per-window p={m('significance.oos_windows.p', '0.085')}).

| Metric | Value |
|---|---|
| Main return / Sharpe | {m('main.total_return_pct', MINUS + '0.31%')} / {m('main.sharpe', MINUS + '0.31')} |
| Trades | {m('main.trades', '14')} |
| Gatev (2006) | {m('benchmarks.gatev.total_return_pct', '+2.780%')} at Sharpe {m('benchmarks.gatev.sharpe', '+0.26')} |
| Pairs tested | {m('fdr.pairs_tested', '36,524')} |
| PSR main | {m('significance.main.psr_pct', '32.5%')} |
| First window | {m('oos.window_returns_pct.0', '&minus;0.46%')} |

Markers look like `<!--m:KEY-->VALUE<!--/m-->`:

```html
<td data-metric="KEY">VALUE</td>
<!--m:KEY-->1.0<!--/m-->
```
"""

HTML_OK = f"""<!doctype html><html><body>
<div class="mval" data-metric="oos.avg_window_return_pct">{MINUS}0.28%</div>
<p>Pooled Sharpe <span data-metric="oos.pooled_sharpe">&minus;1.23</span>,
<span data-metric="oos.windows_positive">1</span>/<span data-metric="oos.windows">10</span> windows positive,
<strong>p=<span data-metric="significance.oos_windows.p">0.085</span></strong>.</p>
<table><tr><td data-metric="main.total_return_pct"><strong>{MINUS}0.31</strong>%</td>
<td data-metric="main.sharpe">{MINUS}0.31</td><td data-metric="main.trades">14</td>
<td class="pos" data-metric="benchmarks.gatev.sharpe">+0.26</td>
<td data-metric="fund_profiles.quant_hf.max_drawdown_pct">{MINUS}2.5%</td></tr></table>
<br data-x="1"><img src="x.png" alt="">
</body></html>
"""


@pytest.fixture
def site(tmp_path):
    js = tmp_path / 'headline_metrics.json'
    js.write_text(json.dumps(_headline()), encoding='utf-8')
    readme = tmp_path / 'README.md'
    readme.write_text(README_OK, encoding='utf-8')
    page = tmp_path / 'index.html'
    page.write_text(HTML_OK, encoding='utf-8')
    return js, readme, page


def run(site_paths, *extra):
    js, readme, page = site_paths
    return chk.main(['--json', str(js), '--files', str(readme), str(page), *extra])


# ── check_published_numbers: parsing ───────────────────────────────────────────

@pytest.mark.parametrize('text,expected', [
    (MINUS + '1.23', (-1.23, 2)),
    ('+2.780%', (2.78, 3)),          # the signed Gatev headline the old regex could never parse
    ('-0.28%', (-0.28, 2)),
    ('36,524', (36524.0, 0)),
    (' 0.085 ', (0.085, 3)),
    ('&minus;0.46%', (-0.46, 2)),
    ('14', (14.0, 0)),
    ('−0.31 %', (-0.31, 2)),
])
def test_parse_marker_value(text, expected):
    assert chk.parse_marker_value(text) == expected


@pytest.mark.parametrize('text', ['', 'n/a', '1.2.3', '12,34', '−', '0.28%/qtr', '~5x', '1e3'])
def test_parse_marker_value_rejects_non_numbers(text):
    with pytest.raises(ValueError):
        chk.parse_marker_value(text)


def test_match_is_at_the_shown_precision():
    assert chk.matches(-1.2345, -1.23, 2)
    assert chk.matches(0.245, 0.25, 2) and chk.matches(0.245, 0.24, 2)   # half-unit boundary
    assert not chk.matches(-1.23, 1.23, 2)                               # sign matters
    assert not chk.matches(-1.23, -1.20, 2)
    assert chk.matches(14, 14, 0) and not chk.matches(14, 1, 0)
    assert chk.matches(2.78, 2.780, 3) and not chk.matches(2.78, 2.785, 3)


def test_resolve_key_paths():
    data = _headline()
    assert chk.resolve_key(data, 'benchmarks.gatev.sharpe') == 0.26
    assert chk.resolve_key(data, 'oos.window_returns_pct.3') == 0.568
    for bad in ('benchmarks.gatev.sharp', 'oos.window_returns_pct.99', 'main.sharpe.x', ''):
        with pytest.raises(KeyError):
            chk.resolve_key(data, bad)


def test_markdown_code_is_not_scanned():
    markers, errors = chk.extract_markers(README_OK, is_markdown=True)
    assert 'KEY' not in {k for k, _, _ in markers} and not errors
    # the same text treated as HTML does see the example marker
    assert 'KEY' in {k for k, _, _ in chk.extract_markers(README_OK)[0]}


# ── check_published_numbers: end to end ────────────────────────────────────────

def test_all_markers_match(site, capsys):
    assert run(site) == 0
    out = capsys.readouterr().out
    # README: 13 markers; index.html: 10 elements (the nested <strong> is part of one value)
    assert 'Compared 23 values' in out and 'README.md: 13' in out and 'index.html: 10' in out
    assert 'OK: every marked value matches' in out


def test_stale_value_fails_with_location(site, capsys):
    js, readme, page = site
    readme.write_text(README_OK.replace(f"{m('oos.pooled_sharpe', MINUS + '1.23')}",
                                        f"{m('oos.pooled_sharpe', MINUS + '1.20')}"), encoding='utf-8')
    assert run(site) == 1
    out = capsys.readouterr().out
    assert 'FAIL:' in out and 'README.md:4: oos.pooled_sharpe' in out and "'−1.20'" in out
    assert '1 failure(s)' in out


def test_sign_error_fails(site, capsys):
    js, readme, page = site
    page.write_text(HTML_OK.replace('data-metric="main.sharpe">−0.31', 'data-metric="main.sharpe">0.31'),
                    encoding='utf-8')
    assert run(site) == 1
    assert 'index.html' in capsys.readouterr().out


def test_integer_is_not_a_substring_match(site, capsys):
    # the old checker accepted any '1' anywhere on the page for "14 trades"
    js, readme, page = site
    readme.write_text(README_OK.replace(m('main.trades', '14'), m('main.trades', '1')), encoding='utf-8')
    assert run(site) == 1
    assert 'main.trades' in capsys.readouterr().out


@pytest.mark.parametrize('bad,needle', [
    (m('benchmarks.gatev.sharp', '0.26'), 'unknown key'),
    (m('benchmarks.random_control.median_sharpe', '0.10'), 'null'),
    (m('main.exit_reasons', '14'), 'not a number'),
    (m('main.sharpe', 'about -0.3'), 'unparseable'),
    ('<!--m:main.sharpe-->' + MINUS + '0.31', 'without a matching'),
])
def test_bad_markers_fail(site, capsys, bad, needle):
    js, readme, page = site
    readme.write_text(README_OK + '\n' + bad + '\n', encoding='utf-8')
    assert run(site) == 1
    assert needle in capsys.readouterr().out


def test_unclosed_html_element_fails(site, capsys):
    js, readme, page = site
    page.write_text(HTML_OK.replace('</body>', '<span data-metric="main.sharpe">−0.31</body>'), encoding='utf-8')
    assert run(site) == 1
    assert 'never closed' in capsys.readouterr().out


def test_required_markers(site, capsys):
    js, readme, page = site
    readme.write_text('# nothing marked yet\n', encoding='utf-8')
    assert run(site) == 1
    out = capsys.readouterr().out
    assert 'README.md: no marker for required key(s)' in out
    for key in chk.REQUIRED_KEYS:
        assert key in out
    assert run(site, '--allow-missing-markers') == 0
    out = capsys.readouterr().out
    warning = next(line for line in out.splitlines() if line.startswith('WARNING:'))
    assert 'README.md: no marker for required key(s)' in warning and 'README.md: 0' in out


def test_required_key_set_covers_the_headlines():
    assert {'main.total_return_pct', 'main.sharpe', 'main.trades', 'oos.avg_window_return_pct',
            'oos.pooled_sharpe', 'oos.windows_positive', 'oos.windows', 'benchmarks.gatev.sharpe',
            'significance.oos_windows.p'} <= set(chk.REQUIRED_KEYS)
    for key in chk.REQUIRED_KEYS:                          # every required key exists in the schema
        chk.resolve_key(_headline(), key)


def test_missing_json_exits_2_unless_allowed(site, tmp_path, capsys):
    js, readme, page = site
    missing = tmp_path / 'nope.json'
    assert chk.main(['--json', str(missing), '--files', str(readme), str(page)]) == 2
    assert chk.main(['--json', str(missing), '--files', str(readme), str(page), '--allow-missing']) == 0
    assert 'SKIPPED' in capsys.readouterr().out


def test_bad_schema_and_missing_page_exit_2(site, tmp_path):
    js, readme, page = site
    js.write_text(json.dumps({**_headline(), 'schema': 2}), encoding='utf-8')
    assert run(site) == 2
    js.write_text('{not json', encoding='utf-8')
    assert run(site) == 2
    js.write_text(json.dumps(_headline()), encoding='utf-8')
    assert chk.main(['--json', str(js), '--files', str(tmp_path / 'missing.html')]) == 2


def test_cli_entry_point(site):
    js, readme, page = site
    ok = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check_published_numbers.py'), '--json', str(js),
                         '--files', str(readme), str(page)], capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert 'Compared 23 values' in ok.stdout


def test_checks_a_real_export(tmp_path):
    """export_headline_metrics -> marked README -> checker: the whole loop agrees."""
    from pairs_trading.json_export import build_headline_metrics
    res = {'total_return': -0.003149, 'sharpe_ratio': -0.3149, 'total_trades': 14,
           'walk_forward': {'avg_window_return_pct': -0.28234, 'pooled_sharpe': -1.2345, 'profitable_windows': 1,
                            'total_windows': 10, 'windows': []},
           'benchmarks': {'distance_method': {'sharpe_ratio': 0.2612}},
           'significance': {'oos_windows': {'n': 10, 'tstat': -1.94, 'pvalue': 0.08466}},
           'run_config': {'run_timestamp_utc': 'x'}}
    js = tmp_path / 'h.json'
    js.write_text(json.dumps(build_headline_metrics(res, {})), encoding='utf-8')
    doc = tmp_path / 'README.md'
    doc.write_text(' '.join(m(k, v) for k, v in [
        ('main.total_return_pct', MINUS + '0.31%'), ('main.sharpe', MINUS + '0.31'), ('main.trades', '14'),
        ('oos.avg_window_return_pct', MINUS + '0.28%'), ('oos.pooled_sharpe', MINUS + '1.23'),
        ('oos.windows_positive', '1'), ('oos.windows', '10'), ('benchmarks.gatev.sharpe', '+0.26'),
        ('significance.oos_windows.p', '0.085')]), encoding='utf-8')
    assert chk.main(['--json', str(js), '--files', str(doc)]) == 0


# ── make_og_image ──────────────────────────────────────────────────────────────

def test_card_content_comes_from_the_json():
    c = og.card_content(_headline())
    assert [b[1] for b in c['bars']] == _headline()['oos']['window_returns_pct']
    assert [b[0] for b in c['bars']][0] == 10 and c['bars'][-1][0] == 19
    assert sum(1 for b in c['bars'] if b[2] == 0) == 3
    assert c['subtitle'].splitlines()[0] == f'Out-of-sample {MINUS}0.28%/qtr, pooled Sharpe {MINUS}1.23'
    assert 'loses to the textbook baseline' in c['subtitle'] and f'{MINUS}0.31 vs +0.26' in c['subtitle']
    assert c['caption'] == '10 SELECTION-CLEAN WINDOWS  ·  1 POSITIVE  ·  3 TRADED NOTHING'
    assert c['eyebrow'].endswith('2020—2025')


def test_card_content_tracks_changed_results():
    h = _headline()
    h['oos'].update(window_returns_pct=[0.5, 0.2], window_trades=[3, 2], window_ids=[1, 2],
                    avg_window_return_pct=0.35, pooled_sharpe=1.1, windows_selection_clean=1,
                    period_start='2023-01-01', period_end='2023-12-31')
    h['main']['sharpe'] = 0.9
    c = og.card_content(h)
    assert c['subtitle'].startswith('Out-of-sample +0.35%/window, pooled Sharpe +1.10')   # not quarterly
    assert 'It beats the textbook baseline (Sharpe +0.90 vs +0.26).' in c['subtitle']
    assert c['caption'] == '2 OOS WINDOWS  ·  2 POSITIVE'


@pytest.mark.parametrize('p,expected', [
    (0.36, f'Not distinguishable from the textbook baseline (Sharpe {MINUS}0.31 vs +0.26, p=0.36).'),
    (0.01, f'It loses to the textbook baseline (Sharpe {MINUS}0.31 vs +0.26, p=0.01).'),
])
def test_card_wording_follows_the_sharpe_difference_test(p, expected):
    h = _headline()
    h['benchmarks']['sharpe_diff_vs_gatev'] = {'diff': -0.57, 'p': p}
    assert og.card_content(h)['subtitle'].splitlines()[1] == expected


def test_card_refuses_missing_values(tmp_path, capsys):
    h = _headline()
    h['oos']['pooled_sharpe'] = None
    js = tmp_path / 'h.json'
    js.write_text(json.dumps(h), encoding='utf-8')
    out = tmp_path / 'card.png'
    assert og.main(['--json', str(js), '--out', str(out)]) == 1
    assert 'oos.pooled_sharpe' in capsys.readouterr().err and not out.exists()


def test_card_missing_json_fails_clearly(tmp_path, capsys):
    assert og.main(['--json', str(tmp_path / 'missing.json'), '--out', str(tmp_path / 'c.png')]) == 2
    assert 'python -m pairs_trading.main' in capsys.readouterr().err


def test_card_renders_to_the_requested_path(tmp_path):
    import matplotlib.image as mpimg
    js = tmp_path / 'h.json'
    js.write_text(json.dumps(_headline()), encoding='utf-8')
    out = tmp_path / 'card.png'
    assert og.main(['--json', str(js), '--out', str(out)]) == 0
    assert mpimg.imread(str(out)).shape[:2] == (630, 1200)


def test_card_default_output_is_the_repo_root():
    assert str(og.DEFAULT_OUT) == os.path.join(REPO, 'og-image.png')
    assert str(og.DEFAULT_JSON) == os.path.join(REPO, 'outputs', 'headline_metrics.json')


# ── the scripts directory ──────────────────────────────────────────────────────

@pytest.mark.parametrize('script', ['check_published_numbers.py', 'make_og_image.py'])
def test_scripts_have_a_working_cli(script):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), '--help'],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and 'usage' in r.stdout.lower()


def test_obsolete_scripts_are_gone():
    removed = ['autopilot.py', 'monitor_v9.sh', 'monitor_v10.sh', 'monitor_v11_continuous.sh',
               'decide_v11_fixes.sh', 'extract_v10_results.sh', 'check_stop_reason.py', 'find_actual_stop.py',
               'quick_diagnosis.py', 'diagnose_date_issue.py', 'trace_single_pair.py', 'run_trading_system.py']
    assert not [s for s in removed if os.path.exists(os.path.join(SCRIPTS, s))]


# ── check_published_numbers --write ───────────────────────────────────────────

def test_write_refreshes_every_marker_in_place(site, capsys):
    js, readme, page = site
    data = _headline()
    data['oos']['pooled_sharpe'] = -0.976
    data['main']['total_return_pct'] = 1.234
    data['main']['trades'] = 1234
    data['fdr']['pairs_tested'] = 40000
    data['benchmarks']['gatev']['sharpe'] = -0.1
    data['benchmarks']['gatev']['total_return_pct'] = 3.5
    data['oos']['window_returns_pct'][0] = 0.5
    js.write_text(json.dumps(data), encoding='utf-8')
    assert run(site) == 1                                   # stale before writing
    assert run(site, '--write') == 0                        # refreshed, then checked
    md, html_text = readme.read_text(encoding='utf-8'), page.read_text(encoding='utf-8')
    assert m('oos.pooled_sharpe', MINUS + '0.98') in md
    assert m('main.total_return_pct', '1.23%') in md
    assert m('main.trades', '1234') in md
    assert m('fdr.pairs_tested', '40,000') in md            # thousands separator kept
    assert m('benchmarks.gatev.sharpe', MINUS + '0.10') in md
    assert m('benchmarks.gatev.total_return_pct', '+3.500%') in md   # '+' and precision kept
    assert m('oos.window_returns_pct.0', '0.50%') in md
    assert '<!--m:KEY-->1.0<!--/m-->' in md                 # code blocks are not touched
    assert '<td data-metric="main.total_return_pct"><strong>1.23</strong>%</td>' in html_text
    assert '<span data-metric="oos.pooled_sharpe">&minus;0.98</span>' in html_text
    assert run(site) == 0
    # idempotent: a second write changes nothing
    before = (readme.read_text(encoding='utf-8'), page.read_text(encoding='utf-8'))
    assert run(site, '--write') == 0
    assert (readme.read_text(encoding='utf-8'), page.read_text(encoding='utf-8')) == before


def test_write_fills_placeholders_and_reports_nulls(tmp_path, capsys):
    js = tmp_path / 'h.json'
    data = _headline()
    data['main']['sharpe'] = None
    js.write_text(json.dumps(data), encoding='utf-8')
    doc = tmp_path / 'README.md'
    doc.write_text(f"{m('oos.avg_window_return_pct', '—')} {m('main.trades', 'tbd')} "
                   f"{m('main.sharpe', '—')} <!--m:significance.oos_windows.p|3-->—<!--/m-->",
                   encoding='utf-8')
    page = tmp_path / 'index.html'
    page.write_text('<p><span data-metric="oos.pooled_sharpe" data-dp="1">—</span></p>', encoding='utf-8')
    rc = chk.main(['--json', str(js), '--files', str(doc), str(page), '--write', '--allow-missing-markers'])
    out = capsys.readouterr().out
    text = doc.read_text(encoding='utf-8')
    assert '<!--m:significance.oos_windows.p|3-->0.085<!--/m-->' in text      # precision hint
    assert '<span data-metric="oos.pooled_sharpe" data-dp="1">−1.2</span>' in page.read_text(encoding='utf-8')
    assert m('oos.avg_window_return_pct', MINUS + '0.28%') in text
    assert m('main.trades', '14') in text
    assert m('main.sharpe', '—') in text and 'main.sharpe' in out   # null: left as is, reported
    assert rc == 1                                                  # and the check still fails on it


# ── parameter_sensitivity.py ───────────────────────────────────────────────────

def test_parameter_sensitivity_runs_the_grid_and_reports_pbo(tmp_path, capsys):
    ps = _load('parameter_sensitivity')
    out = tmp_path / 'ps.json'
    assert ps.main(['--synthetic', '--grid', 'quick', '--out', str(out)]) == 0
    rep = json.loads(out.read_text())
    assert rep['n_configurations'] == 4 and len(rep['configurations']) == 4
    assert rep['shipped'] == 'ENTRY_Z=1.8 EXIT_Z=0.5 STOP_Z=1.5' and 1 <= rep['shipped_rank_by_sharpe'] <= 4
    assert 0.0 <= rep['pbo']['pbo'] <= 1.0 and rep['pbo']['n_combinations'] == 252
    assert len({c['trades'] for c in rep['configurations']}) > 1, "the grid must change the rule"
    from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem as S
    assert (S.ENTRY_Z, S.EXIT_Z, S.STOP_Z) == (1.8, 0.5, 1.5), "class defaults must be untouched"


def test_og_pending_card_needs_no_run(tmp_path):
    out = tmp_path / 'card.png'
    assert og.main(['--pending', '--json', str(tmp_path / 'missing.json'), '--out', str(out)]) == 0
    assert out.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'


def test_og_refuses_an_incomplete_run(tmp_path):
    data = _headline()
    data.update({'complete': False, 'pipeline_errors': ['benchmarks: boom']})
    js = tmp_path / 'h.json'
    js.write_text(json.dumps(data), encoding='utf-8')
    assert og.main(['--json', str(js), '--out', str(tmp_path / 'card.png')]) == 1
    assert not (tmp_path / 'card.png').exists()


def test_write_touches_only_the_value_text(tmp_path):
    """--write must not rewrite digits inside tag attributes or character references, must
    keep a numeric-reference minus, and must not choke on a self-closing marker."""
    data = _headline()
    data['oos']['pooled_sharpe'] = -0.976
    data['main']['sharpe'] = 0.4
    page = ('<p><span data-metric="oos.pooled_sharpe"><a href="#w2" class="c3">&#8722;1.23</a></span>'
            '<span data-metric="main.sharpe">&#160;0.31</span><br data-metric="main.trades"/>'
            '<span data-metric="main.total_return_pct"/></p>')
    new, n, problems = chk.write_text(data, page)
    assert '<a href="#w2" class="c3">&#8722;0.98</a>' in new
    assert '<span data-metric="main.sharpe">&#160;0.40</span>' in new
    assert new.count('data-metric="main.total_return_pct"') == 1      # not duplicated
    assert n == 2 and not [p for p in problems if 'unknown key' in p]


def test_publishing_refuses_a_sensitivity_run(site, tmp_path, capsys):
    js, _, _ = site
    data = _headline()
    data['non_default_switches'] = ['PAIRS_FILL=open']
    js.write_text(json.dumps(data), encoding='utf-8')
    assert run(site) == 2 and 'sensitivity run' in capsys.readouterr().err
    assert run(site, '--allow-variant') == 0
    assert og.main(['--json', str(js), '--out', str(tmp_path / 'c.png')]) == 2
    assert og.main(['--json', str(js), '--out', str(tmp_path / 'c.png'), '--allow-variant']) == 0


def test_site_and_readme_list_the_same_limitations():
    """The page says it says the same things as the README; the limitations list is the
    part that drifted (v32 review). The page's threats-to-validity table opens with the
    README's limitations, in the README's order (it may add threats the README does not
    list); compare the README's bold lead-ins with the table's row headers."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    md = (root / 'README.md').read_text(encoding='utf-8')
    section = md.split('## Known limitations', 1)[1].split('\n## ', 1)[0]
    readme = [re.sub(r'[*“”"]', '', m).strip(' .') for m in re.findall(r'^- \*\*(.+?)\*\*', section, re.M)]
    page_html = (root / 'index.html').read_text(encoding='utf-8')
    threats = page_html.split('class="tbl threats"', 1)[1].split('</table>', 1)[0]
    page = [re.sub(r'<[^>]+>|[“”"]', '', m).strip(' .') for m in re.findall(r'<tr><th scope="row">(.+?)</th>', threats)]
    assert len(readme) >= 8 and len(page) >= len(readme), (readme, page)
    norm = [lambda s: re.sub(r'\W+', ' ', s).lower().strip()]
    assert [norm[0](x) for x in readme] == [norm[0](x) for x in page[:len(readme)]], list(zip(readme, page))


def test_cost_sensitivity_reruns_the_same_trades_under_each_scenario(monkeypatch):
    """Every scenario trades the same signals; costs only move in the declared direction,
    and the cost model is restored afterwards."""
    from tests.synthetic_market import build_system, make_market
    cs = _load('cost_sensitivity')
    monkeypatch.setenv('PAIRS_PROFILE', 'v33')
    frames, macro, _ = make_market(n_pairs=4, n_noise=2, seed=3)
    system = build_system(frames, macro)
    before = (system.cost_model.market_impact_coefficient, system.cost_model.gc_borrow_rate,
              system.initial_capital)
    report = cs.run('v33', 'dev', system=system)
    rows = {r['label']: r for r in report['scenarios']}
    assert set(rows) == {'headline'} | {s[1] for s in cs.SCENARIOS}
    head = rows['headline']
    assert head['trades'] > 0
    assert rows['Y=0.6']['total_cost_pct_of_capital'] > head['total_cost_pct_of_capital']
    assert rows['Y=1.0']['total_cost_pct_of_capital'] > rows['Y=0.6']['total_cost_pct_of_capital']
    assert rows['borrow 3%']['total_cost_pct_of_capital'] > rows['borrow 1%']['total_cost_pct_of_capital'] \
        > head['total_cost_pct_of_capital']
    assert rows['$5B']['avg_max_leg_adv_participation_pct'] > head['avg_max_leg_adv_participation_pct'] \
        > rows['$10M']['avg_max_leg_adv_participation_pct']
    assert rows['$5B']['mean_cost_bp_of_gross_notional'] > rows['$10M']['mean_cost_bp_of_gross_notional']
    assert (system.cost_model.market_impact_coefficient, system.cost_model.gc_borrow_rate,
            system.initial_capital) == before


def test_publish_run_copies_exports_with_a_manifest_and_a_clean_log(tmp_path):
    import hashlib
    pr = _load('publish_run')
    pr.ROOT = tmp_path
    out = tmp_path / 'outputs'
    out.mkdir()
    head = {'schema': 1, 'run_config': {'git_commit': 'abc', 'effective': {'profile': 'v33'},
                                        'study': {'profile': {'name': 'v33'}},
                                        'data': {'price_cache': {'sha256': 'f00'}}}}
    (out / 'headline_metrics.json').write_text(json.dumps(head))
    (out / 'results.json').write_text('{"x": 1}')
    (out / 'chart.png').write_bytes(b'png')                      # not an export: not copied
    log = tmp_path / 'run.log'
    log.write_text(f"start\nPair testing:  50%|##   | 5/10 [00:01<00:01, 5.0pair/s]\n"
                   f"wrote {tmp_path}/outputs/results.json\n")
    dest = pr.publish(out, 'v33_dev', log)
    assert sorted(p.name for p in dest.iterdir()) == ['MANIFEST.json', 'headline_metrics.json',
                                                      'results.json', 'run.log']
    assert (dest / 'run.log').read_text() == "start\nwrote ./outputs/results.json\n"
    m = json.loads((dest / 'MANIFEST.json').read_text())
    assert m['run_config']['git_commit'] == 'abc' and m['study']['profile']['name'] == 'v33'
    assert m['price_cache'] == {'sha256': 'f00'}
    assert m['files']['results.json']['sha256'] == hashlib.sha256(b'{"x": 1}').hexdigest()



def test_holdout_evaluation_holm_and_one_sided_test():
    """The pre-registered decision rule: one-sided HAC t (mean > 0), Holm across strategies."""
    ev = _load('evaluate_holdout')
    # Holm (1979): sorted p (0.01, 0.02, 0.04) x (3, 2, 1) = (0.03, 0.04, 0.04), monotone
    assert ev.holm({'a': 0.04, 'b': 0.01, 'c': 0.02}) == pytest.approx({'a': 0.04, 'b': 0.03, 'c': 0.04})
    assert ev.holm({'a': 0.5, 'b': 0.6}) == pytest.approx({'a': 1.0, 'b': 1.0})
    rng = np.random.default_rng(0)
    up = rng.normal(0.004, 0.01, 200)           # strongly positive mean: rejects
    down = -up                                  # mirror image: one-sided p near 1, not 0
    flat = rng.normal(0.0, 0.01, 200)
    assert ev.one_sided_test(up)['p_one_sided'] < 0.001
    assert ev.one_sided_test(down)['p_one_sided'] > 0.999
    rep = ev.evaluate({'up': {'net': list(up)}, 'down': {'net': list(down)}, 'flat': {'net': list(flat)}})
    s = rep['strategies']
    assert s['up']['edge_out_of_sample'] and not s['down']['edge_out_of_sample']
    assert s['up']['p_holm'] == pytest.approx(min(1.0, 3 * s['up']['p_one_sided']))
    for row in s.values():
        assert row['days'] == 200 and row['bootstrap_ci_95'][0] < row['sharpe'] < row['bootstrap_ci_95'][1]
        assert row['min_detectable_sharpe'] > 0 and row['upper_bound_95'] > row['sharpe']


def test_variant_family_is_the_declared_one_and_its_analysis_runs(tmp_path):
    """The run list is exactly the declaration (27-point grid first, then each toggle once),
    and the snooping battery + PBO run on a family matrix against a published base run."""
    vf = _load('variant_family')
    decl = json.loads((vf.DECLARATION).read_text())
    vs = vf.variants(decl)
    assert len(vs) == 27 + len(decl['toggles']) == 38
    assert len({v['name'] for v in vs}) == len(vs)
    assert all(v['name'].startswith('grid ') for v in vs[:27])
    assert vs[27]['name'] == decl['toggles'][0]['name']
    base = os.path.join(REPO, 'results', 'v32_dev')
    res = json.load(open(os.path.join(base, 'pairs_trading_results_2023_2025_unbiased.json')))
    days = res['daily_equity_curve']
    r = np.array([d['daily_return_pct'] / 100 for d in days])
    rng = np.random.default_rng(0)
    pd = pytest.importorskip('pandas')
    pd.DataFrame({f'v{k}': r + rng.normal(0, 5e-4, len(r)) for k in range(4)},
                 index=[d['date'] for d in days]).to_csv(tmp_path / 'daily_returns.csv', index_label='date')
    import pathlib
    rep = vf.analyse(tmp_path, pathlib.Path(base), reps=50)
    assert rep['declared_family']['variants'] == ['v0', 'v1', 'v2', 'v3']
    assert 0.0 <= rep['family']['spa_vs_zero']['pvalues']['consistent'] <= 1.0
    assert 0.0 <= rep['pbo']['pbo'] <= 1.0 and rep['pbo']['n_configurations'] == 4


def test_trial_registry_appends_once_per_name(tmp_path):
    """register_trial: one JSON line per trial with the run's provenance and numbers, the
    holdout's test outcome, and a refusal to register a name twice (the file is append-only)."""
    rt = _load('register_trial')
    reg = tmp_path / 'trial_registry.jsonl'
    run_dir = os.path.join(REPO, 'results', 'v32_dev')
    import datetime as dt
    import pathlib
    e = rt.register('v32_dev', [run_dir], path=reg, head='abc',
                    now=dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc))
    assert e['registered_utc'] == '2026-10-20T00:00:00+00:00' and e['head'] == 'abc'
    run = e['runs'][0]
    head = json.load(open(os.path.join(run_dir, 'headline_metrics.json')))
    assert run['dir'] == 'results/v32_dev' and run['git_commit'] == head['run_config']['git_commit']
    assert run['main']['sharpe'] == head['main']['sharpe'] and run['main']['trades'] == head['main']['trades']
    assert run['price_cache_sha256'] == head['run_config']['data']['price_cache']['sha256']
    ev = tmp_path / 'evaluation.json'
    ev.write_text(json.dumps({'alpha': 0.05, 'test': 't', 'strategies': {
        'v33_pairs': {'days': 198, 'sharpe': 0.4, 't': 0.35, 'p_one_sided': 0.36, 'p_holm': 1.0,
                      'edge_out_of_sample': False, 'bootstrap_ci_95': [-2, 3]}}}))
    rt.register('holdout2026', evaluation=ev, prereg_commit='def', head='abc', path=reg)
    lines = [json.loads(x) for x in reg.read_text().splitlines()]
    assert [x['name'] for x in lines] == ['v32_dev', 'holdout2026']
    s = lines[1]['evaluation']['strategies']['v33_pairs']
    assert s['p_holm'] == 1.0 and s['edge_out_of_sample'] is False and 'bootstrap_ci_95' not in s
    before = reg.read_text()
    with pytest.raises(SystemExit, match='already registered'):
        rt.register('holdout2026', path=reg)
    assert reg.read_text() == before
    assert pathlib.Path(rt.REGISTRY).name == 'trial_registry.jsonl'
