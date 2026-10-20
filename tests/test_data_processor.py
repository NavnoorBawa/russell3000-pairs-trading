"""Tests for pairs_trading.data_processor validation + indicator helpers."""
import numpy as np
import pandas as pd
import pytest

from pairs_trading.data_processor import EnhancedRussell3000DataProcessor

RNG = np.random.default_rng(0)


@pytest.fixture
def dp():
    return EnhancedRussell3000DataProcessor()


def _df(close):
    idx = pd.date_range("2022-01-03", periods=len(close), freq="B")
    return pd.DataFrame({"Close": close}, index=idx)


# ── _validate_data ──────────────────────────────────────────────────────────
def test_validate_accepts_clean_data(dp):
    assert dp._validate_data(_df(np.linspace(50, 80, 200))) is True


def test_validate_rejects_missing_close(dp):
    df = pd.DataFrame({"Open": [10, 11, 12]})
    assert dp._validate_data(df) is False


def test_validate_rejects_nonpositive_prices(dp):
    c = np.linspace(50, 80, 100)
    c[10] = -1.0
    assert dp._validate_data(_df(c)) is False


def test_validate_rejects_penny_stock(dp):
    assert dp._validate_data(_df(np.full(100, 1.0))) is False     # min < $2 floor


# ── _calculate_rsi ──────────────────────────────────────────────────────────
def test_rsi_bounded_0_100(dp):
    prices = pd.Series(100 * np.exp(np.cumsum(RNG.normal(0, 0.01, 300))))
    rsi = dp._calculate_rsi(prices)
    assert rsi.min() >= 0.0 and rsi.max() <= 100.0


def test_rsi_high_for_monotonic_uptrend(dp):
    prices = pd.Series(np.linspace(10, 50, 100))                  # only gains
    rsi = dp._calculate_rsi(prices)
    assert rsi.iloc[-1] > 90.0


def test_rsi_length_matches_input(dp):
    prices = pd.Series(np.linspace(10, 50, 60))
    assert len(dp._calculate_rsi(prices)) == 60


# ── v32: point-in-time reconstruction and gap handling ─────────────────────────

from pairs_trading.data_processor import EnhancedRussell3000DataProcessor as _P  # noqa: E402


def _split_frame(traded, split_at, ratio):
    """Yahoo-style back-adjusted frame for a stock that traded at `traded` and split
    `ratio`:1 on row `split_at` (earlier closes / ratio, earlier volumes x ratio)."""
    idx = pd.bdate_range('2021-01-01', periods=len(traded), tz='America/New_York')
    adj = traded.astype(float).copy()
    adj[:split_at] = traded[:split_at] / ratio
    vol = np.where(np.arange(len(traded)) < split_at, 1e6 * ratio, 1e6)
    df = pd.DataFrame({'Open': adj, 'High': adj * 1.01, 'Low': adj * 0.99, 'Close': adj,
                       'Volume': vol, 'Stock Splits': 0.0}, index=idx)
    df.iloc[split_at, df.columns.get_loc('Stock Splits')] = ratio
    return df


@pytest.mark.parametrize('pre, post, ratio', [(19.0, 1.9, 10.0), (1.5, 15.0, 0.1)])
def test_point_in_time_price_and_volume_undo_later_splits(pre, post, ratio):
    traded = np.r_[np.full(150, pre), np.full(150, post)]
    df = _split_frame(traded, 150, ratio)
    out = _P.__new__(_P)._process_indicators(df)
    np.testing.assert_allclose(out['Close_PIT'].to_numpy(), traded)
    np.testing.assert_allclose(out['Volume_PIT'].to_numpy(), 1e6)
    f = _P.future_split_factor(df)
    assert f.iloc[149] == pytest.approx(ratio) and f.iloc[150] == 1.0


def test_penny_screen_uses_the_traded_price():
    """A $19 stock that later split 10:1 shows ~$1.90 in adjusted history; it must pass
    the $2 screen, which is about the price at the time."""
    proc = _P.__new__(_P)
    rng = np.random.default_rng(0)
    traded = np.r_[19.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), np.full(100, 1.9)]
    assert proc._validate_data(_split_frame(traded, 300, 10.0)) is True


def test_returns_keep_the_true_move_across_a_missing_close():
    idx = pd.bdate_range('2022-01-03', periods=400, tz='America/New_York')
    close = 50 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, 400)))
    df = pd.DataFrame({'Open': close, 'High': close, 'Low': close, 'Close': close,
                       'Volume': 1e6}, index=idx)
    df.iloc[100, df.columns.get_loc('Close')] = np.nan
    out = _P.__new__(_P)._process_indicators(df)
    r = out['Returns'].to_numpy()
    assert r[100] == 0.0                                       # no invented move on the gap day
    assert (1 + r[100]) * (1 + r[101]) - 1 == pytest.approx(close[101] / close[99] - 1)
    assert r[99] == pytest.approx(close[99] / close[98] - 1)
    assert np.isnan(out['Close'].iloc[100])                    # raw close stays unfilled


def _write_cache(tmp_path, n_cached, outcomes):
    """A price cache of n_cached synthetic symbols plus a fetch manifest."""
    import json
    import pickle
    from pairs_trading.synthetic import make_market
    frames, _, _ = make_market(n_pairs=1, n_noise=n_cached - 2, seed=1, end='2021-06-30')
    syms = sorted(frames)
    path = tmp_path / 'cache.pkl'
    with open(path, 'wb') as f:
        pickle.dump(frames, f)
    if outcomes is not None:
        (tmp_path / 'cache_manifest.json').write_text(json.dumps({'outcomes': outcomes(syms)}))
    return str(path), syms


def test_a_partial_cache_is_refused_on_load(tmp_path, monkeypatch):
    """v32 regression review: a partial (or demo-universe) fetch accepted once with
    PAIRS_ALLOW_PARTIAL_FETCH=1 is cached; later runs must not reuse it silently."""
    path, syms = _write_cache(tmp_path, 4, lambda s: {**{x: 'ok' for x in s},
                                                      **{f'Z{i:03d}': 'error:HTTPError' for i in range(96)}})
    universe = syms + [f'Z{i:03d}' for i in range(96)]
    dp = _P()
    dp.data_file = path
    monkeypatch.delenv('PAIRS_ALLOW_PARTIAL_FETCH', raising=False)
    with pytest.raises(RuntimeError, match='covers only 4.0%'):
        dp.load_or_fetch_data(universe)
    monkeypatch.setenv('PAIRS_ALLOW_PARTIAL_FETCH', '1')
    data = dp.load_or_fetch_data(universe)
    assert sorted(data) == syms and dp.universe_coverage == pytest.approx(0.04)


def test_a_full_or_pre_v32_cache_loads(tmp_path, monkeypatch):
    monkeypatch.delenv('PAIRS_ALLOW_PARTIAL_FETCH', raising=False)
    path, syms = _write_cache(tmp_path, 4, lambda s: {x: 'ok' for x in s})
    dp = _P()
    dp.data_file = path
    assert sorted(dp.load_or_fetch_data(syms)) == syms and dp.universe_coverage == 1.0
    (tmp_path / 'cache_manifest.json').unlink()                     # pre-v32: no manifest
    dp2 = _P()
    dp2.data_file = path
    assert sorted(dp2.load_or_fetch_data(syms)) == syms and dp2.universe_coverage is None


def test_a_manifest_that_does_not_describe_the_cache_is_ignored(tmp_path, monkeypatch):
    """A manifest left over from another fetch (different symbols) must neither refuse a
    good cache nor certify a bad one: coverage becomes unknown, with a warning."""
    monkeypatch.delenv('PAIRS_ALLOW_PARTIAL_FETCH', raising=False)
    path, syms = _write_cache(tmp_path, 4, lambda s: {'OTHER': 'ok', **{f'Z{i}': 'error:X' for i in range(50)}})
    dp = _P()
    dp.data_file = path
    assert sorted(dp.load_or_fetch_data(syms)) == syms
    assert dp.universe_coverage is None and dp.universe_cached_fraction == 1.0


def test_an_old_demo_cache_without_manifest_is_refused(tmp_path, monkeypatch):
    """No manifest (pre-v32) and only a small part of the universe: not the study cache."""
    monkeypatch.delenv('PAIRS_ALLOW_PARTIAL_FETCH', raising=False)
    path, syms = _write_cache(tmp_path, 4, None)
    universe = syms + [f'Z{i:03d}' for i in range(96)]
    dp = _P()
    dp.data_file = path
    with pytest.raises(RuntimeError, match='holds only 4.0%'):
        dp.load_or_fetch_data(universe)
    monkeypatch.setenv('PAIRS_ALLOW_PARTIAL_FETCH', '1')
    assert sorted(dp.load_or_fetch_data(universe)) == syms and dp.universe_cached_fraction == pytest.approx(0.04)


def test_a_refused_fetch_leaves_no_manifest(tmp_path, monkeypatch):
    """The manifest is written only together with a cache; a refused fetch removes a stale one."""
    monkeypatch.delenv('PAIRS_ALLOW_PARTIAL_FETCH', raising=False)
    dp = _P()
    dp.data_file = str(tmp_path / 'cache.pkl')
    stale = tmp_path / 'cache_manifest.json'
    stale.write_text('{"outcomes": {"A": "ok"}}')

    def fake_fetch(symbol):
        dp.fetch_manifest[symbol] = 'error:HTTPError'
        return None
    monkeypatch.setattr(dp, 'fetch_stock_data', fake_fetch)
    with pytest.raises(RuntimeError, match='NOT cached'):
        dp.load_or_fetch_data(['A', 'B', 'C'], max_workers=1)
    assert not stale.exists() and not (tmp_path / 'cache.pkl').exists()


@pytest.mark.parametrize('content', ['[]', 'null', '"x"', '{"outcomes": ["A"]}', '{"outcomes": "ok"}',
                                     '{"outcomes": {}, "cached_symbols": [[1]]}', '{"outcomes": {"A": "o'])
def test_a_malformed_manifest_stops_with_a_clear_message(tmp_path, monkeypatch, content):
    monkeypatch.delenv('PAIRS_ALLOW_PARTIAL_FETCH', raising=False)
    path, syms = _write_cache(tmp_path, 4, None)
    (tmp_path / 'cache_manifest.json').write_text(content)
    dp = _P()
    dp.data_file = path
    with pytest.raises(RuntimeError, match='not a fetch manifest written by this system'):
        dp.load_or_fetch_data(syms)


def test_chart_api_response_is_shaped_like_yfinance(monkeypatch):
    """The direct Yahoo chart-API download must give auto-adjusted OHLC (adjclose ratio),
    split-adjusted volume, event columns and a tz-aware midnight index, like yfinance."""
    import requests
    ts = [1598621400, 1598880600, 1598967000]            # 2020-08-28, 08-31, 09-01 13:30 UTC
    payload = {'chart': {'result': [{
        'meta': {'exchangeTimezoneName': 'America/New_York'},
        'timestamp': ts,
        'indicators': {'quote': [{'open': [120.0, 127.0, 132.0], 'high': [125.0, 131.0, 134.0],
                                  'low': [119.0, 126.0, 130.0], 'close': [124.0, 129.0, 134.0],
                                  'volume': [1e8, 2e8, None]}],
                       'adjclose': [{'adjclose': [62.0, 129.0, 134.0]}]},
        'events': {'splits': {'1': {'date': ts[1], 'numerator': 4.0, 'denominator': 1.0}},
                   'dividends': {'2': {'date': ts[2], 'amount': 0.2}}}}]}}

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return payload
    monkeypatch.setattr(requests, 'get', lambda *a, **k: R())
    df = _P()._download_history('AAPL')
    assert list(df.columns) == ['Open', 'High', 'Low', 'Close', 'Volume', 'Dividends', 'Stock Splits']
    assert str(df.index.tz) == 'America/New_York' and (df.index.hour == 0).all()
    assert df['Close'].tolist() == [62.0, 129.0, 134.0]
    assert df['Open'].iloc[0] == pytest.approx(120.0 * 62.0 / 124.0)
    assert df['Stock Splits'].tolist() == [0.0, 4.0, 0.0] and df['Dividends'].tolist() == [0.0, 0.0, 0.2]
    assert df['Volume'].tolist() == [1e8, 2e8, 0.0]


def test_top_up_fetches_only_never_attempted_symbols(tmp_path, monkeypatch):
    """A point-in-time universe names stocks the cache never fetched: those (and only those —
    a recorded failure is not retried) are fetched over the cache's own period and merged,
    and the manifest is rewritten to describe the merged cache."""
    import json
    monkeypatch.setenv('PAIRS_ALLOW_PARTIAL_FETCH', '1')      # 6 of 7 is below the 90% floor
    path, syms = _write_cache(tmp_path, 4, lambda s: {**{x: 'ok' for x in s}, 'GONE': 'error:HTTPError'})
    manifest_path = tmp_path / 'cache_manifest.json'
    m = json.loads(manifest_path.read_text())
    manifest_path.write_text(json.dumps({**m, 'start': '2020-01-01', 'end': '2021-06-30',
                                         'cached_symbols': syms}))
    from pairs_trading.synthetic import make_market
    extra, _, _ = make_market(n_pairs=1, n_noise=0, seed=9, end='2021-06-30')
    new = dict(zip(['NEW1', 'NEW2'], extra.values()))
    dp = _P(start_date='2020-01-01', end_date='2021-06-30', data_file=path)
    asked = []

    def fake_fetch(symbol):
        asked.append(symbol)
        dp.fetch_manifest[symbol] = 'ok'
        return dp._process_indicators(new[symbol])
    monkeypatch.setattr(dp, 'fetch_stock_data', fake_fetch)
    data = dp.load_or_fetch_data(syms + ['GONE', 'NEW1', 'NEW2'], max_workers=1)
    assert sorted(asked) == ['NEW1', 'NEW2']                       # GONE failed before: not retried
    assert sorted(data) == sorted(syms + ['NEW1', 'NEW2'])
    m2 = json.loads(manifest_path.read_text())
    assert m2['cached_symbols'] == sorted(syms + ['NEW1', 'NEW2'])
    assert m2['outcomes']['NEW1'] == 'ok' and m2['outcomes']['GONE'] == 'error:HTTPError'
    assert dp.universe_coverage == pytest.approx(6 / 7)              # only GONE is missing
    # a cache of another period is never extended
    dp2 = _P(start_date='2020-01-01', end_date='2026-10-19', data_file=path)
    with pytest.raises(RuntimeError, match='another period'):
        dp2.load_or_fetch_data(syms + ['NEW3'], max_workers=1)


def test_a_symbol_the_vendor_does_not_know_is_final_and_not_a_fetch_failure(tmp_path, monkeypatch):
    """HTTP 404 (a delisted stock) is recorded as 'not_found' after ONE request, and counts
    as a data limit (reported as the not-found fraction), not as a failed fetch."""
    import json

    class _R:
        status_code = 404
    calls = []
    monkeypatch.setattr('requests.get', lambda *a, **k: calls.append(1) or _R())
    dp = _P()
    assert dp.fetch_stock_data('SIVB') is None
    assert dp.fetch_manifest['SIVB'] == 'not_found' and len(calls) == 1
    path, syms = _write_cache(tmp_path, 4, lambda s: {**{x: 'ok' for x in s}, 'SIVB': 'not_found'})
    dp2 = _P(data_file=path)
    monkeypatch.delenv('PAIRS_ALLOW_PARTIAL_FETCH', raising=False)
    assert sorted(dp2.load_or_fetch_data(syms + ['SIVB'])) == syms
    assert dp2.universe_coverage == 1.0 and dp2.universe_not_found_fraction == pytest.approx(0.2)
    assert json.loads((tmp_path / 'cache_manifest.json').read_text())['outcomes']['SIVB'] == 'not_found'
