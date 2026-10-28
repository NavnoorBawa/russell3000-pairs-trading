"""scripts/hash_cache.py and its use by scripts/publish_run.py: per-symbol fingerprints of a
price cache, so a later fetch can be diffed symbol by symbol without the prices."""
import hashlib
import importlib.util
import json
import os
import pickle

import numpy as np
import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, 'scripts')


def _load(name):
    spec = importlib.util.spec_from_file_location(f'_script_{name}', os.path.join(SCRIPTS, f'{name}.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hc = _load('hash_cache')


def _bars(seed, n=30, tz='America/New_York'):
    rng = np.random.default_rng(seed)
    idx = pd.date_range('2024-01-02', periods=n, freq='B', tz=tz, name='Date')
    close = 50 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return pd.DataFrame({'Open': close, 'High': close, 'Low': close, 'Close': close,
                         'Volume': rng.integers(1e5, 1e6, n).astype(float),
                         'Dividends': 0.0, 'Stock Splits': 0.0, 'RSI': np.nan}, index=idx)


def _cache(tmp_path, data, name='prices.pkl'):
    path = tmp_path / name
    with open(path, 'wb') as f:
        pickle.dump(data, f)
    return path


def test_the_encoding_is_the_documented_one():
    df = _bars(0, n=3)
    days = df.index.tz_localize(None).values.astype('datetime64[D]').astype('<i8')
    want = hashlib.sha256(days.tobytes() + df['Close'].to_numpy('<f8').tobytes()).hexdigest()
    assert hc.series_sha256(df.index, df['Close']) == want
    # the local date counts, not the instant: a naive index of the same dates hashes the same
    assert hc.series_sha256(df.index.tz_localize(None), df['Close']) == want


def test_every_nan_hashes_alike_and_one_revised_value_changes_the_hash():
    idx = pd.date_range('2024-01-02', periods=4, freq='B')
    a = np.array([1.0, np.nan, 3.0, 4.0])
    b = a.copy()
    b.view('<u8')[1] = 0x7ff8000000000001           # a NaN with another payload
    assert hc.series_sha256(idx, a) == hc.series_sha256(idx, b)
    c = a.copy()
    c[3] = np.nextafter(4.0, 5.0)                   # one ulp
    assert hc.series_sha256(idx, a) != hc.series_sha256(idx, c)


def test_fingerprint_and_compare(tmp_path):
    data = {'AAA': _bars(1), 'BBB': _bars(2), 'CCC': _bars(3)}
    path = _cache(tmp_path, data)
    (tmp_path / 'prices_manifest.json').write_text('{"outcomes": {}}')
    doc = hc.fingerprint(path)
    assert doc['n_symbols'] == 3 and sorted(doc['symbols']) == ['AAA', 'BBB', 'CCC']
    rec = doc['symbols']['AAA']
    assert rec['bars'] == 30 and rec['first'] == '2024-01-02' and set(hc.SERIES) <= set(rec)
    assert doc['price_cache']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert doc['fetch_manifest']['sha256'] == hashlib.sha256(b'{"outcomes": {}}').hexdigest()
    assert 'Close' not in json.dumps(doc['symbols'])  # fingerprints only, no prices

    revised = {k: v.copy() for k, v in data.items()}
    revised['BBB'].iloc[5, revised['BBB'].columns.get_loc('Volume')] += 1
    del revised['CCC']
    revised['DDD'] = _bars(4)
    doc2 = hc.fingerprint(_cache(tmp_path, revised, 'b.pkl'))
    cmp = hc.compare(doc, doc2)
    assert cmp == {'only_a': 1, 'only_b': 1, 'both': 2, 'identical': 1, 'same_bars': 2, 'same_first': 2,
                   'same_last': 2, 'same_close': 2, 'same_volume': 1, 'same_dividends': 2, 'same_splits': 2}
    assert doc['symbols_sha256'] != doc2['symbols_sha256']
    assert hc.fingerprint(path)['symbols_sha256'] == doc['symbols_sha256']   # deterministic


def test_macro_series_are_fingerprinted(tmp_path):
    idx = pd.date_range('2024-01-02', periods=5, freq='B')
    macro = {'vix': pd.Series(np.arange(5.0), index=idx),
             'sector_etfs': {'XLK': pd.DataFrame({'Close': np.arange(5.0), 'Name': list('abcde')}, index=idx)}}
    doc = hc.fingerprint(_cache(tmp_path, {'AAA': _bars(1)}), macro=_cache(tmp_path, macro, 'macro.pkl'))
    assert sorted(doc['macro_cache']['series']) == ['sector_etfs.XLK.Close', 'vix']
    assert doc['macro_cache']['series']['vix']['bars'] == 5


def _headline(tmp_path, cache_path, sha):
    return {'complete': True, 'non_default_switches': [],
            'run_config': {'git_commit': 'abc',
                           'data': {'price_cache': {'path': str(cache_path.relative_to(tmp_path)), 'sha256': sha}}}}


def test_publish_writes_the_fingerprints_of_the_cache_the_run_read(tmp_path):
    pr = _load('publish_run')
    pr.ROOT = tmp_path
    (tmp_path / 'data').mkdir()
    cache = _cache(tmp_path / 'data', {'AAA': _bars(1)})
    sha = hashlib.sha256(cache.read_bytes()).hexdigest()
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'headline_metrics.json').write_text(json.dumps(_headline(tmp_path, cache, sha)))
    dest = pr.publish(out, 'run')
    fp = json.loads((dest / 'price_cache_hashes.json').read_text())
    assert fp['price_cache']['sha256'] == sha and list(fp['symbols']) == ['AAA']
    assert 'price_cache_hashes.json' in json.loads((dest / 'MANIFEST.json').read_text())['files']


def test_publish_refuses_a_cache_that_changed_after_the_run(tmp_path):
    pr = _load('publish_run')
    pr.ROOT = tmp_path
    (tmp_path / 'data').mkdir()
    cache = _cache(tmp_path / 'data', {'AAA': _bars(1)})
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'headline_metrics.json').write_text(json.dumps(_headline(tmp_path, cache, '0' * 64)))
    with pytest.raises(SystemExit, match='changed after the run'):
        pr.publish(out, 'run')


def test_publish_without_the_cache_skips_or_stops(tmp_path):
    pr = _load('publish_run')
    pr.ROOT = tmp_path
    out = tmp_path / 'out'
    out.mkdir()
    head = {'complete': True, 'run_config': {'data': {'price_cache': {'path': 'data/gone.pkl', 'sha256': 'f'}}}}
    (out / 'headline_metrics.json').write_text(json.dumps(head))
    dest = pr.publish(out, 'a')
    assert not (dest / 'price_cache_hashes.json').exists()
    with pytest.raises(SystemExit, match='not on disk'):
        pr.publish(out, 'b', cache_hashes='require')
