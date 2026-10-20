"""scripts/selector_equivalence.py: the real-data equivalence check must be able to fail.

Hermetic: hand-built selection results, no price cache. Each decision the script
compares (universe, pairs and order, FDR diagnostic, every p < 0.05 decision, the PCA
flags) must stop it when changed, while rounding-level differences are only measured.
"""
import copy
import importlib.util
import os
import subprocess
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, 'scripts', 'selector_equivalence.py')


@pytest.fixture(scope='module')
def tool():
    spec = importlib.util.spec_from_file_location('selector_equivalence', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result():
    stats = {'correlation': 0.61, 'cointegration_pvalue': 0.004, 'half_life': 9.5,
             'quality_score': 0.83, 'pca_cointegrated': True}
    return {'universe': ['AAA', 'BBB', 'CCC'], 'pairs': [('AAA', 'CCC'), ('AAA', 'BBB')],
            'stats': {'AAA-CCC': dict(stats), 'AAA-BBB': dict(stats, quality_score=0.71)},
            'fdr': {'pairs_tested': 3, 'significant_raw_p05': 2},
            'pvalues': np.array([0.004, 0.02, 0.4]), 'seconds': 1.0}


def test_rounding_differences_are_measured_not_failed(tool):
    ref, new = _result(), _result()
    new['pvalues'] = new['pvalues'] + 3e-13
    new['stats']['AAA-BBB']['quality_score'] += 2e-12
    diffs = tool.compare_selections(ref, new, 'test')
    assert diffs['fdr_pvalue'] == pytest.approx(3e-13, rel=0.01)
    assert diffs['quality_score'] == pytest.approx(2e-12, rel=0.01)
    assert diffs['correlation'] == 0.0
    assert tool._bitwise(ref) == tool._bitwise(_result()) != tool._bitwise(new)


def _changed(edit):
    new = copy.deepcopy(_result())
    edit(new)
    return new


@pytest.mark.parametrize('edit, message', [
    (lambda r: r['universe'].pop(), 'universe'),
    (lambda r: r['pairs'].reverse(), 'order'),
    (lambda r: r['fdr'].update(significant_raw_p05=1), 'FDR'),
    (lambda r: r.update(pvalues=np.array([0.004, 0.051, 0.4])), 'decision'),
    (lambda r: r.update(pvalues=np.array([0.004, 0.02])), 'number of tested pairs'),
    (lambda r: r['stats']['AAA-BBB'].update(pca_cointegrated=False), 'PCA'),
    (lambda r: r['stats'].pop('AAA-BBB'), 'keys'),
])
def test_a_changed_decision_stops_the_check(tool, edit, message):
    with pytest.raises(AssertionError, match=message):
        tool.compare_selections(_result(), _changed(edit), 'test')


def test_reference_selector_is_imported_from_git(tool):
    cls = tool.reference_selector_class('HEAD')
    assert cls.__module__ == 'pair_selector_reference'
    assert hasattr(cls, 'find_quality_pairs') and hasattr(cls, 'cointegration_pvalue')


def test_cli_help():
    r = subprocess.run([sys.executable, SCRIPT, '--help'], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and '--reference' in r.stdout
