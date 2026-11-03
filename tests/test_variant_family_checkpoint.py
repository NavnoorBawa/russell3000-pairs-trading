"""The variant family's checkpoints: a resumed run reads back exactly what the first run wrote."""
import importlib.util
import pathlib

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location('variant_family', ROOT / 'scripts' / 'variant_family.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_checkpoint_round_trips_its_row_and_series(tmp_path):
    vf = _load()
    row = {'name': 'grid entry=2.0 exit=0.5 stop=3.0', 'sharpe': -0.1234, 'trades': 211}
    dates = ['2023-07-03', '2023-07-05', '2023-07-06']
    returns = [0.001, -0.0025, 1.5e-11]
    vf._write_checkpoint(tmp_path, row['name'], row, dates, returns)
    back_row, back = vf._read_checkpoint(tmp_path, row['name'])
    assert back_row == row
    pd.testing.assert_series_equal(back, pd.Series(returns, index=pd.to_datetime(dates)))
    assert not list(tmp_path.glob('*.tmp'))               # written atomically


def test_checkpoint_names_are_distinct_and_checked(tmp_path):
    vf = _load()
    names = ['ranker_gbm', 'open_fills', 'grid entry=2.0 exit=0.5 stop=3.0', 'grid entry=2.0 exit=0.5 stop=3.5']
    assert len({vf._checkpoint(tmp_path, n).name for n in names}) == len(names)
    vf._write_checkpoint(tmp_path, 'open_fills', {'name': 'open_fills'}, ['2023-07-03'], [0.0])
    vf._checkpoint(tmp_path, 'open_fills').rename(vf._checkpoint(tmp_path, 'ranker_gbm'))
    with pytest.raises(ValueError, match='not'):
        vf._read_checkpoint(tmp_path, 'ranker_gbm')
