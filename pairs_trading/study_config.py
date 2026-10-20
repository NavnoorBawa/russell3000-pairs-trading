"""
PAIRS TRADING - STUDY CONFIGURATION
===================================
Every design choice that differs between study versions, in one frozen object.

A run is (profile, calendar):

  profile   WHAT is traded and how: universe source, pair-candidate rule, re-selection
            scheme, regime gate, ranking model, financing/borrow assumptions.
            `v32` reproduces the published v32 study exactly (tests/test_study_config.py
            pins it against a golden fingerprint of the v32 code); `v33` is the design
            pre-registered in docs/PREREGISTRATION.md.
  calendar  WHEN: price history, formation cutoff, ranker training end, first entry
            date. `dev` is the 2020-2025 study period every version so far was designed
            on; `holdout2026` is the sealed out-of-sample period, used once.

Why each v33 choice differs from v32 is stated next to the profile below; none was
chosen by its effect on 2020-2025 results (docs/PREREGISTRATION.md).

The profile and calendar come from the CLI (--profile/--calendar), else the environment
(PAIRS_PROFILE/PAIRS_CALENDAR), else the defaults below. The older switches
PAIRS_RESELECT and PAIRS_USE_TRANSFORMER still override the profile's re-selection and
ranker, and are reported as non-default switches in every export.

The seal is in code, not only in procedure: data dated on or after SEALED_FROM (prices,
macro series, the 2026 N-PORT holdings) is fetched only when PAIRS_UNSEAL names the
commit that added docs/PREREGISTRATION.md (assert_unsealed), which scripts/run_holdout.sh
sets after its checks.
"""

import dataclasses
import hashlib
import json
import os
import pathlib
import subprocess
from dataclasses import dataclass
from typing import Optional

DEFAULT_PROFILE = 'v33'
DEFAULT_CALENDAR = 'dev'
SEALED_FROM = '2026-01-01'                 # first date of the sealed holdout period
PREREGISTRATION = 'docs/PREREGISTRATION.md'
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Profile:
    """Strategy design: the knobs that changed between study versions."""

    name: str
    universe: str                  # 'marketcap': data/marketcap.csv (membership as of its
    #                                download date); 'pit_iwv': point-in-time Russell 3000
    #                                membership from IWV's SEC N-PORT holdings (universe.py)
    max_universe: int              # most liquid screened names whose pairs are tested
    same_industry: bool            # test only pairs within one Fama-French 49 industry
    reselect: str                  # 'pool': re-test the initial pairs; 'full': re-run selection
    reselect_every: int            # trading days between re-selections
    formation_calendar_days: int   # trailing window each re-selection uses
    regime_gate: bool              # VIX / sector-dispersion position scaling and entry block
    ranker: str                    # 'transformer' | 'gbm' (scikit-learn) | 'none' (classical)
    borrow_rate: float             # annual stock-borrow fee on short notional
    pb_financing_spread: float     # annual carry on the short half of gross notional

    def config_hash(self) -> str:
        return _hash(dataclasses.asdict(self))


@dataclass(frozen=True)
class Calendar:
    """Study dates. All are inclusive calendar dates (YYYY-MM-DD)."""

    name: str
    data_start: str                # first price date loaded
    data_end: str                  # last price date loaded
    selection_cutoff: str          # the initial pair universe uses data <= this date
    model_train_end: str           # ranking-model labels complete by this date
    backtest_start: str            # first entry date of the main backtest
    walk_forward: bool             # run the walk-forward validation on this calendar
    price_cache: str               # price cache file (one per calendar: the dev cache is
    #                                never extended into the holdout period)
    macro_cache: str               # VIX / sector-ETF cache file, likewise per calendar

    def config_hash(self) -> str:
        return _hash(dataclasses.asdict(self))


PROFILES = {
    'v32': Profile(
        name='v32', universe='marketcap', max_universe=300, same_industry=False,
        reselect='pool', reselect_every=90, formation_calendar_days=730,
        regime_gate=True, ranker='transformer',
        borrow_rate=0.0025, pb_financing_spread=0.005),
    'v33': Profile(
        name='v33',
        # Point-in-time membership: no look-ahead inclusion of names that only later grew
        # into the index, no closed-end funds or BDCs, no domicile filter error.
        universe='pit_iwv',
        # The ~500 largest/most liquid names, the universe of Avellaneda & Lee (2010) and
        # Li & Papanicolaou (2024); same-industry pairs keep the test count below v32's.
        max_universe=500,
        # Do & Faff (2010): pairs from the same refined industry are the economically
        # motivated ones; the restriction cuts the multiple-testing family ~10x.
        same_industry=True,
        # Full re-formation every 126 trading days (Gatev et al.'s six-month trading
        # period) on the trailing three years, the length of the initial formation
        # window: no stale 2022 pool shrinking towards noise-level pass rates.
        reselect='full', reselect_every=126, formation_calendar_days=1095,
        # The gate's thresholds were fitted on walk-forward windows that now lie inside
        # the test period (docs/PROGRESS.md, v10/v11).
        regime_gate=False,
        # The learned ranker had no out-of-sample skill (AUC 0.51); it is an ablation arm,
        # not part of the primary design.
        ranker='none',
        # One buy-side borrow fee, the median indicative fee of Muravyev, Pearson & Pollet
        # (2025, Table 1: 0.38%/yr). v32 charged a 25 bp GC fee AND a 50 bp prime-broker
        # spread on the short half — the same short rebate haircut counted twice; the book
        # never runs leverage, so there is no long-side debit to finance.
        borrow_rate=0.0038, pb_financing_spread=0.0),
}

CALENDARS = {
    'dev': Calendar(
        name='dev', data_start='2020-01-01', data_end='2025-12-31',
        selection_cutoff='2022-12-31', model_train_end='2023-06-30',
        backtest_start='2023-07-01', walk_forward=True,
        price_cache='data/enhanced_russell_3000_data.pkl', macro_cache='data/macro_data.pkl'),
    # Sealed until docs/PREREGISTRATION.md is committed: same formation length (three
    # years) as dev, trading from the first session of 2026 to the last close before the
    # pre-registration date. Too short for the 252/63-day walk-forward grid.
    'holdout2026': Calendar(
        name='holdout2026', data_start='2023-01-01', data_end='2026-10-19',
        selection_cutoff='2025-12-31', model_train_end='2025-12-31',
        backtest_start='2026-01-02', walk_forward=False,
        price_cache='data/holdout2026_prices.pkl', macro_cache='data/holdout2026_macro.pkl'),
    # The holdout calendar shifted one year back, inside the development period: the
    # dress rehearsal of scripts/run_holdout.sh (fresh cache, both profiles, the residual
    # arm, evaluation, publishing) before the one real run. It sees no 2026 data.
    'rehearsal2025': Calendar(
        name='rehearsal2025', data_start='2022-01-01', data_end='2025-10-17',
        selection_cutoff='2024-12-31', model_train_end='2024-12-31',
        backtest_start='2025-01-02', walk_forward=False,
        price_cache='data/rehearsal2025_prices.pkl', macro_cache='data/rehearsal2025_macro.pkl'),
}


def _hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]


def get_profile(name: Optional[str] = None) -> Profile:
    """The named profile (default: PAIRS_PROFILE, else DEFAULT_PROFILE), with the legacy
    PAIRS_RESELECT / PAIRS_USE_TRANSFORMER overrides applied."""
    name = name or os.environ.get('PAIRS_PROFILE') or DEFAULT_PROFILE
    if name not in PROFILES:
        raise ValueError(f"Unknown profile {name!r}; choose one of {sorted(PROFILES)}")
    profile = PROFILES[name]
    reselect = os.environ.get('PAIRS_RESELECT')
    if reselect:
        if reselect.lower() not in ('pool', 'full'):
            raise ValueError(f"PAIRS_RESELECT={reselect!r}: use 'pool' or 'full'")
        profile = dataclasses.replace(profile, reselect=reselect.lower())
    if os.environ.get('PAIRS_USE_TRANSFORMER') == '0':
        profile = dataclasses.replace(profile, ranker='none')
    ranker = os.environ.get('PAIRS_RANKER')
    if ranker:
        if ranker not in ('transformer', 'gbm', 'none'):
            raise ValueError(f"PAIRS_RANKER={ranker!r}: use 'transformer', 'gbm' or 'none'")
        profile = dataclasses.replace(profile, ranker=ranker)
    return profile


def get_calendar(name: Optional[str] = None) -> Calendar:
    """The named calendar (default: PAIRS_CALENDAR, else DEFAULT_CALENDAR)."""
    name = name or os.environ.get('PAIRS_CALENDAR') or DEFAULT_CALENDAR
    if name not in CALENDARS:
        raise ValueError(f"Unknown calendar {name!r}; choose one of {sorted(CALENDARS)}")
    return CALENDARS[name]


class SealedError(RuntimeError):
    """Data of the sealed holdout period was requested before the pre-registration."""


def _git(repo, *args) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None


def preregistration_commit(repo=None) -> Optional[str]:
    """The one commit that added docs/PREREGISTRATION.md, when HEAD descends from it.

    Renames are not followed (a file moved into place is not 'added'), and a history with
    more than one adding commit (deleted and re-added) has no unambiguous answer: None.
    """
    repo = repo or REPO_ROOT
    out = _git(repo, '-c', 'log.follow=false', 'log', '--no-renames', '--diff-filter=A',
               '--format=%H', '--', PREREGISTRATION)
    commits = out.stdout.split() if out is not None and out.returncode == 0 else []
    if len(commits) != 1:
        return None
    ancestor = _git(repo, 'merge-base', '--is-ancestor', commits[0], 'HEAD')
    return commits[0] if ancestor is not None and ancestor.returncode == 0 else None


_UNSEALED = set()          # (repo, PAIRS_UNSEAL) already checked in this process


def assert_unsealed(end_date: str, repo=None) -> None:
    """Refuse data dated on or after SEALED_FROM unless the holdout has been unsealed.

    Unsealed means PAIRS_UNSEAL equals the commit that added docs/PREREGISTRATION.md, an
    ancestor of HEAD; scripts/run_holdout.sh sets it after checking that commit. Every
    fetch of prices, macro series or N-PORT holdings for such a period goes through here
    (once per symbol: a passed check is remembered for the process).
    """
    if str(end_date)[:10] < SEALED_FROM:
        return
    key = (str(repo or REPO_ROOT), os.environ.get('PAIRS_UNSEAL'))
    if key in _UNSEALED:
        return
    commit = preregistration_commit(repo)
    if commit is None or key[1] != commit:
        raise SealedError(
            f"data up to {str(end_date)[:10]} lies in the sealed holdout (from {SEALED_FROM}). It is "
            f"fetched only by scripts/run_holdout.sh, after {PREREGISTRATION} is committed "
            f"(pre-registration commit: {commit or 'none'}).")
    _UNSEALED.add(key)


def describe(profile: Profile, calendar: Calendar) -> dict:
    """JSON-ready record of a run's design, for the provenance block."""
    return {'profile': dataclasses.asdict(profile), 'calendar': dataclasses.asdict(calendar),
            'profile_hash': profile.config_hash(), 'calendar_hash': calendar.config_hash()}
