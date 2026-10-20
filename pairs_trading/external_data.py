"""
PAIRS TRADING - EXTERNAL DATA
=============================
Free reference series for the evidence layer: Kenneth French's daily factor returns and
FRED interest rates. Each source file is downloaded once, cached under data/external/
next to a fingerprint (URL, SHA-256, fetch time, vintage), and read from the cache
afterwards, so an attribution reproduces against the same vintage. Offline mode never
touches the network and stops with a clear message when a file is not cached.

Also home to the polite HTTP helper the data-building scripts share (retries with
backoff, rate limiting, the SEC's declared User-Agent).
"""

import hashlib
import io
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

DEFAULT_CACHE_DIR = os.path.join('data', 'external')

FRENCH_BASE_URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/'
# Daily files and the columns each contributes: FF5 (Fama-French 2015, 2x3 sorts),
# momentum (Carhart 1997), short- and long-term reversal. Gatev, Goetzmann and
# Rouwenhorst (2006, RFS 19(3), section 4.2, Table 4) attribute pairs returns to the
# Fama-French factors plus momentum and reversal.
FRENCH_DAILY_FILES = {
    'F-F_Research_Data_5_Factors_2x3_daily_CSV': ('Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA', 'RF'),
    'F-F_Momentum_Factor_daily_CSV': ('Mom',),
    'F-F_ST_Reversal_Factor_daily_CSV': ('ST_Rev',),
    'F-F_LT_Reversal_Factor_daily_CSV': ('LT_Rev',),
}
FACTOR_COLUMNS = tuple(c for cols in FRENCH_DAILY_FILES.values() for c in cols)

FRED_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'

SEC_USER_AGENT_DEFAULT = 'russell3000-pairs-trading research bot admin@example.org'

# French's files: 'This file was created by using the 202608 CRSP database.' (older files:
# 'created by CMPT_ME_BEME_RETS using the 201912 CRSP database').
_VINTAGE = re.compile(r'using\s+the\s+(\d{6})\s+CRSP\s+database', re.I)
# Missing-value codes in the French library.
_FRENCH_MISSING = (-99.99, -999.0)


def sec_user_agent() -> str:
    """The User-Agent declared to SEC EDGAR (env SEC_USER_AGENT, else a role address).

    EDGAR's fair-access policy asks automated clients to identify themselves and stay
    under 10 requests per second; no personal address is ever sent by default.
    """
    return os.environ.get('SEC_USER_AGENT') or SEC_USER_AGENT_DEFAULT


class RateLimiter:
    """Spaces calls at least `min_interval` seconds apart (thread-safe)."""

    def __init__(self, min_interval: float):
        self.min_interval = float(min_interval)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.min_interval
        if delay > 0:
            time.sleep(delay)


def http_get(url: str, headers: Optional[Dict[str, str]] = None, data: Optional[bytes] = None,
             timeout: float = 60.0, retries: int = 5, limiter: Optional[RateLimiter] = None) -> bytes:
    """Fetch `url` (POST when `data` is given) and return the body.

    HTTP 429 and 5xx responses and network errors are retried with exponential backoff
    and jitter, honouring a Retry-After or ratelimit-reset header; any other 4xx is
    raised at once, since retrying cannot fix it. `limiter` spaces every attempt.
    """
    rng = random.Random(hash(url) & 0xFFFFFFFF)
    for attempt in range(retries):
        if limiter is not None:
            limiter.wait()
        req = urllib.request.Request(url, data=data, headers=dict(headers or {}))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            if attempt == retries - 1:
                raise
            hinted = e.headers.get('Retry-After') or e.headers.get('ratelimit-reset')
            wait = float(hinted) if hinted and hinted.strip().isdigit() else min(60.0, 2.0 ** (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries - 1:
                raise
            wait = min(60.0, 2.0 ** (attempt + 1))
        time.sleep(wait + rng.uniform(0.0, 1.0))
    raise RuntimeError(f'unreachable: {url}')


# EDGAR's fair-access limit is 10 requests per second per client.
SEC_LIMITER = RateLimiter(1 / 8)


def sec_get(url: str) -> bytes:
    """Fetch an EDGAR URL with the declared User-Agent, at most 8 requests per second."""
    return http_get(url, headers={'User-Agent': sec_user_agent(), 'Accept-Encoding': 'identity'},
                    limiter=SEC_LIMITER)


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def write_atomic(path, data) -> None:
    """Write bytes (or text, UTF-8) to `path` via a temp file in the same directory and os.replace."""
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = f'{path}.tmp-{os.getpid()}'
    with open(tmp, 'wb') as f:
        f.write(data if isinstance(data, bytes) else data.encode())
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def cached_download(url: str, path: str, offline: bool = False, refresh: bool = False,
                    vintage_of=None, headers: Optional[Dict[str, str]] = None) -> Tuple[bytes, Dict]:
    """Return (bytes, fingerprint) for `url`, cached at `path` with a `path + '.json'` sidecar.

    A cached file is used as is (the vintage stays pinned) unless `refresh` is set.
    `offline` never touches the network (it overrides `refresh`) and raises
    FileNotFoundError when the file is not cached. `vintage_of(bytes)` names the data
    vintage recorded in the fingerprint; the cached bytes are checked against the
    recorded SHA-256 on every read.
    """
    meta_path = path + '.json'
    if os.path.exists(path) and (offline or not refresh):
        with open(path, 'rb') as f:
            blob = f.read()
        meta = {}
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)
        digest = _sha256(blob)
        if meta.get('sha256') and meta['sha256'] != digest:
            raise ValueError(f'{path}: SHA-256 {digest} does not match its fingerprint '
                             f"{meta['sha256']} ({meta_path}); delete both and fetch again")
        meta.setdefault('url', url)
        meta['sha256'] = digest
        if 'vintage' not in meta:
            meta['vintage'] = vintage_of(blob) if vintage_of else None
        return blob, meta
    if offline:
        raise FileNotFoundError(
            f'{path} is not cached and offline mode was requested. Run once with network '
            f'access (offline=False) to download {url}, or place that file at {path}.')
    blob = http_get(url, headers=headers or {'User-Agent': 'Mozilla/5.0 (research; pairs-trading)'})
    meta = {'url': url, 'sha256': _sha256(blob), 'bytes': len(blob),
            'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'vintage': vintage_of(blob) if vintage_of else None}
    write_atomic(path, blob)
    write_atomic(meta_path, json.dumps(meta, indent=1))
    return blob, meta


# ---------------------------------------------------------------------------------------
# Kenneth French data library
# ---------------------------------------------------------------------------------------

def parse_french_csv(text: str) -> Tuple[pd.DataFrame, Optional[str]]:
    """Parse one French-library CSV into (returns in decimals, CRSP vintage 'YYYYMM').

    The files open with free-text notes (one names the CRSP vintage), then a header row
    starting with ',' and one row per period (YYYYMMDD for daily files, YYYYMM for
    monthly ones) in percent. Monthly files continue with annual blocks under their own
    header; only the first block is read, and it ends at the first row that is not a
    period of the same frequency (a blank line, the copyright line or an annual block).
    Missing-value codes (-99.99, -999) become NaN.
    """
    vintage = _VINTAGE.search(text)
    lines = text.splitlines()
    rows, header, width = [], None, None
    for line in lines:
        cells = [c.strip() for c in line.split(',')]
        if header is None:
            if len(cells) > 1 and cells[0] == '' and all(cells[1:]):
                header = cells[1:]
            continue
        key = cells[0]
        if width is None and key.isdigit() and len(key) in (6, 8):
            width = len(key)
        if width is None or not (key.isdigit() and len(key) == width) or len(cells) != len(header) + 1:
            if rows:
                break
            continue
        rows.append(cells)
    if header is None or not rows:
        raise ValueError('no data block found in French-library CSV')
    fmt = '%Y%m%d' if width == 8 else '%Y%m'
    index = pd.to_datetime([r[0] for r in rows], format=fmt)
    values = np.array([[float(x) for x in r[1:]] for r in rows])
    values[np.isin(values, _FRENCH_MISSING)] = np.nan
    frame = pd.DataFrame(values / 100.0, index=index, columns=header)
    frame.index.name = 'date'
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError('French-library CSV dates are not strictly increasing')
    return frame, vintage.group(1) if vintage else None


def _french_zip_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith('.csv')]
        if len(names) != 1:
            raise ValueError(f'expected one CSV in the French-library zip, found {names}')
        return zf.read(names[0]).decode('latin-1')


def _french_vintage(blob: bytes) -> Optional[str]:
    match = _VINTAGE.search(_french_zip_text(blob))
    return match.group(1) if match else None


def read_french_zip(blob: bytes) -> Tuple[pd.DataFrame, Optional[str]]:
    """Parse the single CSV inside a French-library zip (see parse_french_csv)."""
    return parse_french_csv(_french_zip_text(blob))


def french_daily_factors(cache_dir: str = DEFAULT_CACHE_DIR, offline: bool = False,
                         refresh: bool = False) -> Tuple[pd.DataFrame, Dict]:
    """Daily factor returns (decimals): Mkt-RF, SMB, HML, RMW, CMA, RF, Mom, ST_Rev, LT_Rev.

    Inner-joined on the dates all four files cover. The fingerprint lists each file's
    URL, SHA-256, fetch time and CRSP vintage; French revises factor history at every
    update ('Noisy Factors', Akey, Robertson and Simutin), so the vintage belongs in
    the provenance of any attribution. Mixed vintages across the four files raise.
    """
    frames, files = [], {}
    for stem, cols in FRENCH_DAILY_FILES.items():
        url = f'{FRENCH_BASE_URL}{stem}.zip'
        blob, meta = cached_download(url, os.path.join(cache_dir, 'french', f'{stem}.zip'),
                                     offline=offline, refresh=refresh,
                                     vintage_of=_french_vintage)
        frame, vintage = read_french_zip(blob)
        missing = [c for c in cols if c not in frame.columns]
        if missing:
            raise ValueError(f'{stem}: columns {missing} not found (have {list(frame.columns)})')
        frames.append(frame[list(cols)])
        files[stem] = dict(meta, vintage=vintage)
    vintages = {m['vintage'] for m in files.values()}
    if len(vintages) != 1:
        raise ValueError(f'French-library files come from different CRSP vintages: {sorted(map(str, vintages))}; '
                         f'refresh all of them together')
    factors = pd.concat(frames, axis=1, join='inner').sort_index()
    fingerprint = {'source': 'Kenneth R. French Data Library', 'vintage': vintages.pop(),
                   'first_date': factors.index[0].date().isoformat(),
                   'last_date': factors.index[-1].date().isoformat(), 'files': files}
    return factors[list(FACTOR_COLUMNS)], fingerprint


# ---------------------------------------------------------------------------------------
# FRED
# ---------------------------------------------------------------------------------------

def parse_fred_csv(text: str, series_id: str) -> pd.Series:
    """Parse a fredgraph.csv download into a float Series named `series_id`.

    The first column is the date ('observation_date', or 'DATE' in older downloads).
    Holidays appear as empty values ('2020-01-20,') or '.', and become NaN; values stay
    in FRED's published units (percent per annum for DTB3 and EFFR).
    """
    frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    if frame.shape[1] != 2 or frame.columns[1].strip() != series_id:
        raise ValueError(f'unexpected FRED CSV columns {list(frame.columns)} for {series_id}')
    values = frame.iloc[:, 1].str.strip()
    values = values.where(~values.isin(['', '.']))
    series = pd.Series(pd.to_numeric(values, errors='raise').to_numpy(dtype=float),
                       index=pd.to_datetime(frame.iloc[:, 0], format='%Y-%m-%d'), name=series_id)
    series.index.name = 'date'
    if not series.index.is_monotonic_increasing or series.index.has_duplicates:
        raise ValueError(f'FRED {series_id}: dates are not strictly increasing')
    return series


def fred_series(series_id: str, cache_dir: str = DEFAULT_CACHE_DIR, offline: bool = False,
                refresh: bool = False) -> Tuple[pd.Series, Dict]:
    """A FRED series (e.g. 'DTB3', 'EFFR') and its fingerprint.

    FRED revises some series after publication; the cached download is the vintage
    (its fetch date is recorded as `vintage`), so re-runs read the same numbers until
    `refresh` is requested.
    """
    if not re.fullmatch(r'[A-Z0-9_]+', series_id):
        raise ValueError(f'not a FRED series id: {series_id!r}')
    url = FRED_URL.format(series_id=series_id)
    blob, meta = cached_download(url, os.path.join(cache_dir, 'fred', f'{series_id}.csv'),
                                 offline=offline, refresh=refresh)
    series = parse_fred_csv(blob.decode('utf-8'), series_id)
    fetched = meta.get('fetched_at')
    fingerprint = dict(meta, source='FRED, Federal Reserve Bank of St. Louis', series_id=series_id,
                       vintage=fetched[:10] if fetched else None,
                       last_observation=series.dropna().index[-1].date().isoformat() if series.notna().any() else None)
    return series, fingerprint
