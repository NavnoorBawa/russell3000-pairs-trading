"""pairs_trading/external_data.py: French-library and FRED parsers, the fingerprinted cache.

The fixtures under tests/fixtures/external/ are small synthetic files with the exact
layout of the real downloads (CRLF line ends, free-text notes naming the CRSP vintage, a
header row starting with ',', a copyright trailer; monthly files with an annual block;
FRED's empty and '.' missing values). No test touches the network.
"""
import hashlib
import io
import json
import os
import zipfile

import numpy as np
import pandas as pd
import pytest

from pairs_trading import external_data as ed

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'external')

DAILY = {
    'F-F_Research_Data_5_Factors_2x3_daily_CSV': 'F-F_Research_Data_5_Factors_2x3_daily.csv',
    'F-F_Momentum_Factor_daily_CSV': 'F-F_Momentum_Factor_daily.csv',
    'F-F_ST_Reversal_Factor_daily_CSV': 'F-F_ST_Reversal_Factor_daily.csv',
    'F-F_LT_Reversal_Factor_daily_CSV': 'F-F_LT_Reversal_Factor_Daily.csv',
}


def _text(name):
    with open(os.path.join(FIX, name), newline='') as f:
        return f.read()


def _zip(name, text=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(name, text if text is not None else _text(name))
    return buf.getvalue()


def _french_cache(tmp_path, overrides=None):
    """A data/external cache holding the four fixture zips (no fingerprint sidecars)."""
    d = tmp_path / 'french'
    d.mkdir(parents=True)
    for stem, csv_name in DAILY.items():
        text = (overrides or {}).get(stem)
        (d / f'{stem}.zip').write_bytes(_zip(csv_name, text))
    return str(tmp_path)


def test_daily_parser_reads_percent_as_decimals_and_stops_at_trailer():
    frame, vintage = ed.parse_french_csv(_text('F-F_Research_Data_5_Factors_2x3_daily.csv'))
    assert vintage == '202608'
    assert list(frame.columns) == ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA', 'RF']
    assert list(frame.index) == list(pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04',
                                                     '2024-01-05', '2024-01-08']))
    assert frame.loc['2024-01-02', 'Mkt-RF'] == pytest.approx(-0.0071)
    assert frame.loc['2024-01-08', 'CMA'] == pytest.approx(-0.0067)
    assert frame['RF'].eq(0.0002).all()


def test_header_whitespace_and_missing_codes():
    frame, _ = ed.parse_french_csv(_text('F-F_Momentum_Factor_daily.csv'))
    assert list(frame.columns) == ['Mom']                   # ',Mom   ' in older vintages
    assert np.isnan(frame.loc['2024-01-03', 'Mom'])         # -99.99 is missing, not -99.99%
    assert frame['Mom'].notna().sum() == 5


def test_monthly_file_ignores_annual_block_and_reads_old_vintage_line():
    frame, vintage = ed.parse_french_csv(_text('F-F_Research_Data_Factors_monthly.csv'))
    assert vintage == '201912'                              # 'created by CMPT_ME_BEME_RETS using the ...'
    assert list(frame.index) == list(pd.to_datetime(['2019-10-01', '2019-11-01', '2019-12-01']))
    assert frame.loc['2019-11-01', 'Mkt-RF'] == pytest.approx(0.0387)
    assert np.isnan(frame.loc['2019-12-01', 'RF'])
    assert len(frame) == 3                                  # the 2018/2019 annual rows are not data


def test_only_the_first_block_of_a_multi_block_file_is_read():
    # e.g. 49_Industry_Portfolios: value-weighted, then equal-weighted returns, same dates
    text = _text('F-F_Research_Data_Factors_monthly.csv')
    first, annual = text.split(' Annual Factors: January-December ')
    second = first.split('\r\n\r\n', 1)[1].replace('2.06', '9.99')
    frame, _ = ed.parse_french_csv(first + '  Average Equal Weighted Returns -- Monthly\r\n' + second)
    assert len(frame) == 3 and frame.loc['2019-10-01', 'Mkt-RF'] == pytest.approx(0.0206)


def test_parser_rejects_a_file_without_data():
    with pytest.raises(ValueError, match='no data block'):
        ed.parse_french_csv('This file was created by using the 202608 CRSP database.\r\n\r\nCopyright\r\n')


def test_merged_factors_offline_from_cache(tmp_path):
    cache = _french_cache(tmp_path)
    factors, fp = ed.french_daily_factors(cache_dir=cache, offline=True)
    assert list(factors.columns) == list(ed.FACTOR_COLUMNS)
    # inner join: LT_Rev ends on 2024-01-05 and Mom starts a day early
    assert list(factors.index) == list(pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05']))
    assert factors.loc['2024-01-04', 'LT_Rev'] == pytest.approx(-0.0015)
    assert factors.loc['2024-01-05', 'ST_Rev'] == pytest.approx(0.0036)
    assert fp['vintage'] == '202608'
    assert fp['first_date'] == '2024-01-02' and fp['last_date'] == '2024-01-05'
    zpath = os.path.join(cache, 'french', 'F-F_Momentum_Factor_daily_CSV.zip')
    with open(zpath, 'rb') as f:
        assert fp['files']['F-F_Momentum_Factor_daily_CSV']['sha256'] == hashlib.sha256(f.read()).hexdigest()
    assert fp['files']['F-F_Momentum_Factor_daily_CSV']['url'] == ed.FRENCH_BASE_URL + 'F-F_Momentum_Factor_daily_CSV.zip'


def test_mixed_vintages_are_refused(tmp_path):
    text = _text('F-F_LT_Reversal_Factor_Daily.csv').replace('202608', '202607')
    cache = _french_cache(tmp_path, {'F-F_LT_Reversal_Factor_daily_CSV': text})
    with pytest.raises(ValueError, match='different CRSP vintages'):
        ed.french_daily_factors(cache_dir=cache, offline=True)


def test_offline_without_cache_fails_clearly(tmp_path):
    with pytest.raises(FileNotFoundError, match='offline mode') as err:
        ed.french_daily_factors(cache_dir=str(tmp_path), offline=True)
    assert ed.FRENCH_BASE_URL in str(err.value)
    with pytest.raises(FileNotFoundError, match='fredgraph.csv\\?id=DTB3'):
        ed.fred_series('DTB3', cache_dir=str(tmp_path), offline=True)


def test_cache_is_written_once_and_pinned(tmp_path, monkeypatch):
    calls = []
    blob = _zip('F-F_ST_Reversal_Factor_daily.csv')

    def fake_get(url, headers=None, **kw):
        calls.append(url)
        return blob

    monkeypatch.setattr(ed, 'http_get', fake_get)
    path = str(tmp_path / 'french' / 'x.zip')
    got, meta = ed.cached_download('https://example.org/x.zip', path, vintage_of=ed._french_vintage)
    assert got == blob and len(calls) == 1
    with open(path + '.json') as f:
        side = json.load(f)
    assert side['sha256'] == hashlib.sha256(blob).hexdigest() and side['vintage'] == '202608'
    assert side['url'] == 'https://example.org/x.zip' and side['fetched_at']
    got2, meta2 = ed.cached_download('https://example.org/x.zip', path, vintage_of=ed._french_vintage)
    assert got2 == blob and len(calls) == 1                 # served from the cache
    assert meta2['fetched_at'] == meta['fetched_at']
    ed.cached_download('https://example.org/x.zip', path, refresh=True, offline=True)
    assert len(calls) == 1                                  # offline wins over refresh
    ed.cached_download('https://example.org/x.zip', path, refresh=True)
    assert len(calls) == 2
    with pytest.raises(FileNotFoundError):
        ed.cached_download('https://example.org/y.zip', str(tmp_path / 'y.zip'), offline=True)


def test_corrupted_cache_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, 'http_get', lambda url, headers=None, **kw: b'original bytes')
    path = str(tmp_path / 'fred' / 'DTB3.csv')
    ed.cached_download('https://example.org/DTB3', path)
    with open(path, 'wb') as f:
        f.write(b'edited bytes')
    with pytest.raises(ValueError, match='does not match its fingerprint'):
        ed.cached_download('https://example.org/DTB3', path, offline=True)


def test_fred_parser_missing_values_and_units():
    s = ed.parse_fred_csv(_text('fredgraph_DTB3.csv'), 'DTB3')
    assert s.name == 'DTB3' and s.dtype == float
    assert np.isnan(s.loc['2024-01-15'])                    # holiday: empty string
    assert s.loc['2024-01-16'] == pytest.approx(5.23)       # percent per annum, as published
    legacy = ed.parse_fred_csv(_text('fredgraph_EFFR_legacy.csv'), 'EFFR')
    assert np.isnan(legacy.loc['2024-01-15'])               # '.' in older downloads
    assert legacy.notna().sum() == 2
    with pytest.raises(ValueError, match='unexpected FRED CSV columns'):
        ed.parse_fred_csv(_text('fredgraph_DTB3.csv'), 'EFFR')


def test_fred_series_offline_with_fingerprint(tmp_path):
    d = tmp_path / 'fred'
    d.mkdir()
    blob = _text('fredgraph_DTB3.csv').encode()
    (d / 'DTB3.csv').write_bytes(blob)
    (d / 'DTB3.csv.json').write_text(json.dumps({'url': ed.FRED_URL.format(series_id='DTB3'),
                                                 'sha256': hashlib.sha256(blob).hexdigest(),
                                                 'fetched_at': '2026-10-20T12:00:00+00:00'}))
    s, fp = ed.fred_series('DTB3', cache_dir=str(tmp_path), offline=True)
    assert len(s) == 4 and fp['vintage'] == '2026-10-20' and fp['last_observation'] == '2024-01-16'
    assert fp['series_id'] == 'DTB3' and fp['sha256'] == hashlib.sha256(blob).hexdigest()
    with pytest.raises(ValueError, match='not a FRED series id'):
        ed.fred_series('DTB3&cosd=2026', cache_dir=str(tmp_path), offline=True)


def test_sec_user_agent_default_and_override(monkeypatch):
    monkeypatch.delenv('SEC_USER_AGENT', raising=False)
    assert ed.sec_user_agent() == ed.SEC_USER_AGENT_DEFAULT
    monkeypatch.setenv('SEC_USER_AGENT', 'lab bot ops@example.org')
    assert ed.sec_user_agent() == 'lab bot ops@example.org'
