"""Bit-reproducibility: the same inputs give the same results in a fresh process.

The hermetic synthetic study (selection, main backtest, walk-forward, benchmarks, exports)
runs in two separate interpreters that differ in everything that should not matter — the
str hash seed (set iteration order) and the BLAS/OpenMP thread count — and must produce
byte-identical trade lists and daily return series. Sets are sorted before they reach any
decision or export, and every random draw comes from a seeded generator; this test is the
end-to-end proof.
"""
import hashlib
import json
import os
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = textwrap.dedent("""
    import json, os, pickle, sys, tempfile, hashlib
    import pandas as pd
    sys.path.insert(0, {root!r})
    from tests.synthetic_market import make_market
    root = tempfile.mkdtemp()
    frames, macro, _ = make_market(n_pairs=4, n_noise=4, seed=17)
    os.makedirs(os.path.join(root, 'data'))
    pickle.dump(frames, open(os.path.join(root, 'data', 'enhanced_russell_3000_data.pkl'), 'wb'))
    pickle.dump(macro, open(os.path.join(root, 'data', 'macro_data.pkl'), 'wb'))
    pd.DataFrame({{'Symbol': sorted(frames)}}).to_csv(os.path.join(root, 'data', 'marketcap.csv'), index=False)
    os.chdir(root)
    from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem
    r = CompleteFixedRussell3000TradingSystem(profile='v32').run_complete_system()
    trades = [[t['pair'], str(t['date']), str(t['exit_date']), t['exit_reason'], repr(t['net_pnl_pct'])]
              for t in r['trades']]
    parts = {{'trades': trades, 'daily': [repr(x) for x in r['daily_returns']],
             'wf': r['walk_forward'].get('stitched_total_return_pct'),
             'gatev': [repr(x) for x in r['benchmarks']['distance_method']['daily_returns']]}}
    payload = json.dumps(parts)
    json.dump(parts, open(sys.argv[1], 'w'))
    print(hashlib.sha256(payload.encode()).hexdigest(), len(trades))
""")


def _run(hash_seed: str, threads: str, dump: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith('PAIRS_')}
    env.update({'PYTHONHASHSEED': hash_seed, 'OMP_NUM_THREADS': threads, 'MKL_NUM_THREADS': threads,
                'OPENBLAS_NUM_THREADS': threads, 'PAIRS_USE_TRANSFORMER': '0', 'MPLBACKEND': 'Agg',
                'TQDM_DISABLE': '1'})
    out = subprocess.run([sys.executable, '-c', SCRIPT.format(root=ROOT), dump], env=env, cwd=ROOT,
                         capture_output=True, text=True, timeout=900)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip().splitlines()[-1]


def _first_differences(x: dict, y: dict) -> list:
    """Per component, the first index (or the value) where two runs' payloads differ."""
    out = []
    for key in x:
        u, v = x[key], y[key]
        if u == v:
            continue
        if isinstance(u, list) and isinstance(v, list):
            i = next((k for k, (p, q) in enumerate(zip(u, v)) if p != q), min(len(u), len(v)))
            out.append(f"{key}: lengths {len(u)}/{len(v)}, first difference at {i}: "
                       f"{u[i] if i < len(u) else None!r} vs {v[i] if i < len(v) else None!r}")
        else:
            out.append(f"{key}: {u!r} vs {v!r}")
    return out


def test_full_pipeline_is_bit_reproducible_across_processes(tmp_path):
    a = _run('0', '1', str(tmp_path / 'a.json'))
    b = _run('12345', '2', str(tmp_path / 'b.json'))
    digest, n_trades = a.split()
    assert int(n_trades) > 10
    if a != b:
        diffs = _first_differences(json.loads((tmp_path / 'a.json').read_text()),
                                   json.loads((tmp_path / 'b.json').read_text()))
        raise AssertionError(f"{a} != {b}:\n  " + '\n  '.join(diffs))
    assert len(digest) == 64 and digest != hashlib.sha256(b'').hexdigest()
