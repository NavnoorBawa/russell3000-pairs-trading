"""
AVELLANEDA-LEE SECTOR-ETF RESIDUAL MEAN REVERSION
=================================================
A second, independent strategy family for the study: the ETF variant of Avellaneda &
Lee (2010), "Statistical Arbitrage in the U.S. Equities Market", Quantitative Finance
10(7):761-782, with the published parameters verbatim. Section and equation numbers
refer to the authors' free draft of 15 June 2009
(https://math.nyu.edu/~avellane/AvellanedaLeeStatArb20090616.pdf).

Model (Sec. 2.3, Sec. 3 eqs. 11-14, Appendix). Every stock is assigned one sector SPDR.
Every day, for every stock with 60 daily returns, on those 60 returns:
    R_S,n   = beta_0 + beta R_I,n + eps_n,         n = 1..60   (OLS with intercept)
    X_k     = eps_1 + ... + eps_k,                 k = 1..60   (so X_60 = 0)
    X_{n+1} = a + b X_n + zeta_{n+1},              n = 1..59   (AR(1) by OLS)
    kappa = -ln(b) x 252,  m = a / (1 - b),  sigma_eq = sqrt(Var(zeta) / (1 - b^2))  (eq. 21)
Var(zeta) is the sample variance of the 59 AR(1) residuals (ddof = 1). The model is
accepted only if 0 < b < 1 and kappa > 252/30, a mean-reversion time below half the
estimation window (Sec. 4; "0 < b < 0.9672" in the Appendix).

Variant implemented: the "pure mean-reversion" s-score of Sec. 4.1, eq. (15), evaluated
at X_60 = 0 with the cross-sectionally centred mean of Sec. 5.1 eq. (18) / Appendix
eq. (22):
    s_i = -(m_i - <m>) / sigma_eq,i
where <m> averages m over the day's universe members whose model is accepted ("brackets
denote averaging over different stocks"; rejected models are left out because
m = a / (1 - b) is unbounded as b -> 1). NOT implemented: the drift-adjusted "modified
s-score" of Sec. 4.2 eq. (17), which A&L do not back-test; the trading-time (volume)
returns of Sec. 6; the PCA factors of Sec. 2.1.

Trading rule (Sec. 4.1, eq. 16, cut-offs s_bo = s_so = 1.25, s_bc = 0.75, s_sc = 0.50):
    open long  if s < -1.25          close long  if s > -0.50
    open short if s > +1.25          close short if s < +0.75
When a held stock's model is rejected (b outside (0, 1) or kappa <= 252/30) the position
is closed (Sec. 5: "we reject the model and (i) do not open trades or (ii) close open
trades"). A day on which a stock has no estimate at all (fewer than 60 returns in the
window, or a degenerate regression) leaves its state unchanged. Returns are taken
between consecutive real bars only, so one missing bar removes two returns (into and
out of the gap) and leaves the stock without an estimate on that row and the 60 after
it; a position held through such a gap can then neither exit by signal nor be rejected
until estimates resume. Only universe members open positions; held positions are
managed by the same rule after leaving the universe.

Book (Sec. 4.1, Sec. 5). Opening a position buys (sells) a notional of position_frac x
current equity of the stock and sells (buys) beta times that notional of its sector ETF.
The "bang-bang" position is then held unchanged until it closes (A&L footnote 9: sizing
is applied to new positions only). The ETF hedges of all positions are netted: on each
day only the net change of each ETF position is traded.

Execution and accounting follow the pairs engine (trading_system.py): the signal uses
data through the close of day t; the order fills at the close of t+1 with the share count
fixed from the day-t close (an entry needs a real bar on t+1; an exit without one fills at
the last real close); every leg is marked to market daily on adjusted closes, so dividends
are in the P&L as in A&L's equation for E_t; costs are booked on fill days; positions still
open when the data ends close at the last bar (exit_reason 'end_of_data').

Costs: the cost model of the pairs arm S1 (study_config profile v33, s1_cost_model). Each
stock execution pays its one-way leg cost (transaction_costs.calculate_leg_cost: per-share
commission on point-in-time shares, half-spread by 20-day dollar-ADV bucket, square-root
impact on the stock's 20-day dollar ADV and daily volatility, both as of the fill day, as
the pairs engine reads them); a short stock leg pays the profile's borrow fee (0.38%/yr)
over its calendar holding period, booked at the exit fill. The net ETF trade
of each day is costed with the same function at an effectively unlimited ADV
(ETF_ASSUMED_ADV_DOLLARS): the half-spread falls in the model's top bucket (0.75 bp; the
sector SPDRs quote a one-cent spread, 0.3-2.5 bp of a $40-$300 price) and impact is below
0.1 bp for any hedge trade here. The ETF closes carry no split record, so ETF share
counts, and the per-share commission on them, are in the closes' adjusted units: an ETF
split inside the data inflates the pre-split count (twofold for a 2:1 split), which
overstates a cost component of a few tenths of a bp of ETF notional. A net short ETF
position accrues the same borrow fee daily. No prime-broker financing spread (S1's
profile sets it to zero; s1_cost_model refuses one) and no interest on cash are modelled.

Universe: S1's rule (LiquidityUniverse). On each ranking day d (the first signal day and
every universe_rebalance_days-th trading day after it) the candidates are the
point-in-time Russell 3000 members, the holdings of the IWV snapshot in force on d (as
trading_system._formation_members reads them at S1's formations), with price history.
Each candidate's bars dated in (d - universe_window_days, d], S1's formation window
(1095 calendar days, pair_selector.formation_window), go through S1's symbol screen
(pair_selector.screen_symbols: >= 300 bars, mean point-in-time close >= $5, mean
point-in-time dollar volume >= $10M, annualised volatility between 5% and 80%, < 10%
missing closes), and the universe_size (500, S1's max_universe) most liquid by that mean
dollar volume form the universe until the next ranking day: on a day S1 re-forms, the
names S1 screens. A screened name without a sector ETF cannot be hedged and is passed
over for the next one; each ranking records how many of S1's own 500 that replaced. A
name outside the snapshot in force can never enter, and neither can a member the price
cache has no history for (the survivorship gap, reported per snapshot by the run
script). As for S1, a snapshot is in force from its report-period date although N-PORT
reports are filed 53-62 days later: it stands in for the index membership FTSE Russell
had already published. S1 re-forms every 126 trading days, this arm every 21. Without a
membership callable the ranking runs over every name of the price dict (the synthetic
tests; a price dict built from a current constituent list omits names delisted before
it, survivorship that flatters mean reversion).

Deviations from A&L, each declared before any run: t+1 fills (A&L fill on the signal
close); the repository cost model instead of a flat 5 bp per side; the 11 SPDR sector
ETFs (A&L's Table 3 has 15 sector ETFs); the universe above (A&L trade all US stocks
above $1bn market cap); a fixed position_frac rather than A&L's leverage target
(Lambda_t = 2/100 for "2+2" leverage). The first development run ranked the names of
data/marketcap.csv and paid v32's 0.25% borrow fee; the point-in-time universe and S1's
fee replaced them afterwards because the pre-registration requires S1's universe rule and
cost model for this arm, not because of that run's result. The next version shared only
S1's membership source and size: it ranked on 252-day dollar volume with a $5 floor on
the ranking day's close and none of S1's history, $10M or volatility screens. A review
found 7-10% of its names failing S1's screens on every ranking day, most of them above
S1's 80% volatility cap, and measured their P&L in both directions: +$1.07M of the
rehearsal's $1.77M net, -$0.63M gross over development. S1's screens replaced that rule
because the pre-registration states the same universe rule as S1 and compares this arm
with the baselines of S1's screened universe, whichever way those names cut.

The stock -> ETF map is an argument. Two readers are provided: ff49_sector_etf_map (SIC
-> Fama-French 49 industry -> SPDR, reference/industry_ff49.csv, the committed map the
study runs use; universe.sector_etf_map reads the same file) and nasdaq_sector_etf_map
(the Nasdaq 'Sector' column of data/marketcap.csv).
"""

from dataclasses import asdict, dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from pairs_trading.config import pd, np, logging
from pairs_trading.json_export import calculate_max_drawdown_from_returns
from pairs_trading.pair_selector import MIN_DOLLAR_VOLUME, formation_window, screen_symbols
from pairs_trading.significance import (
    annualized_sharpe, block_bootstrap_sharpe_ci, hac_tstat_mean, probabilistic_sharpe_ratio,
)
from pairs_trading.study_config import PROFILES, _hash
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
S1_PROFILE = 'v33'          # the pairs arm whose universe rule and cost model this arm shares

# Nasdaq-screener sector (data/marketcap.csv 'Sector') -> SPDR sector ETF. The Nasdaq
# taxonomy is not GICS: 'Telecommunications' also holds network-equipment makers (CSCO,
# ANET) that GICS puts in Information Technology, and 'Miscellaneous' (28 names, mostly
# industrial machinery and multi-sector firms) and missing sectors (e.g. BRK-A/BRK-B) are
# left unmapped, so those names are not traded. The SIC-based map of ff49_sector_etf_map
# has the same interface (symbol -> ETF ticker) and is preferred when its file exists.
NASDAQ_SECTOR_TO_SPDR = {
    'Technology': 'XLK',
    'Telecommunications': 'XLC',
    'Finance': 'XLF',
    'Health Care': 'XLV',
    'Consumer Discretionary': 'XLY',
    'Consumer Staples': 'XLP',
    'Energy': 'XLE',
    'Industrials': 'XLI',
    'Basic Materials': 'XLB',
    'Utilities': 'XLU',
    'Real Estate': 'XLRE',
}

# Dollar ADV passed to the cost model for the sector SPDRs: effectively unlimited, so
# the model's top spread bucket applies and square-root impact vanishes (a $5M hedge
# trade at a 1.2% daily volatility costs 0.3 x 1.2% x sqrt(5e6 / 1e12) = 0.08 bp).
ETF_ASSUMED_ADV_DOLLARS = 1e12

# Net ETF share changes smaller than this are floating-point residue of offsetting
# hedges, not trades.
_SHARE_EPS = 1e-6

# The price-frame columns pair_selector.screen_symbols reads.
_SCREEN_COLUMNS = ('Close', 'Close_PIT', 'Volume', 'Volume_PIT', 'Returns')


@dataclass(frozen=True)
class ResidualStatArbParams:
    """Strategy parameters: A&L's published values (Sec. 4, 4.1) and declared settings.

    None was chosen on the study data; position_frac and the universe settings were
    declared before the first run, and the universe's size and window are S1's (profile
    v33: max_universe, formation_calendar_days). The registered arm runs the defaults,
    whose hash is study_config.RESIDUAL_PARAMS_HASH.
    """
    window: int = 60                     # Sec. 4: estimation window T1 = 60 days
    kappa_min: float = 252.0 / 30.0      # Sec. 4: kappa > 252/30 = 8.4
    s_open: float = 1.25                 # Sec. 4.1: s_bo = s_so
    s_close_short: float = 0.75          # Sec. 4.1: s_bc (close short when s < +0.75)
    s_close_long: float = 0.50           # Sec. 4.1: s_sc (close long when s > -0.50)
    position_frac: float = 0.005         # stock notional of one position / current equity
    universe_size: int = 500             # S1's max_universe
    universe_rebalance_days: int = 21
    universe_window_days: int = 1095     # S1's formation window, calendar days
    adv_days: int = 20                   # cost-model ADV and volatility window (as data_processor)
    initial_capital: float = 100_000_000.0

    def config_hash(self) -> str:
        """Fingerprint of the parameters, as study_config hashes a profile: the registered
        arm runs ResidualStatArbParams(), and its exports carry this hash."""
        return _hash(asdict(self))


def s1_cost_model() -> EnhancedPrimeFundTransactionCostModel:
    """The cost model of the pairs arm S1: its profile's borrow fee and prime-broker spread.

    The residual book charges no financing carry, so a profile with a non-zero
    prime-broker spread (v32's 0.5%/yr) is refused rather than silently undercharged.
    """
    profile = PROFILES[S1_PROFILE]
    if profile.pb_financing_spread:
        raise ValueError(f"profile {S1_PROFILE} charges a prime-broker spread of "
                         f"{profile.pb_financing_spread}; the residual book does not model financing")
    return EnhancedPrimeFundTransactionCostModel(borrow_rate=profile.borrow_rate,
                                                 pb_financing_spread=profile.pb_financing_spread)


def nasdaq_sector_etf_map(path: str = 'data/marketcap.csv') -> Dict[str, str]:
    """{symbol: sector ETF} from the universe file's Nasdaq 'Sector' column.

    Symbols are normalised to the price cache's Yahoo style as data_processor.load_symbols
    does (upper case, no whitespace, '.' -> '-' for class shares). Sectors outside
    NASDAQ_SECTOR_TO_SPDR are left out.
    """
    df = pd.read_csv(path)
    etfs = df['Sector'].map(NASDAQ_SECTOR_TO_SPDR)
    keep = etfs.notna()
    return dict(zip(_normalise_symbols(df['Symbol'])[keep], etfs[keep]))


def ff49_sector_etf_map(path: str = 'reference/industry_ff49.csv') -> Dict[str, str]:
    """{symbol: sector ETF} from the 'sector_etf' column of the SIC-based industry file.

    The file (written by scripts/build_reference_data.py: ticker, cik, sic, ff49,
    ff49_name, sector_etf, ...) assigns each ticker's SEC SIC code a Fama-French 49
    industry and that industry a Select Sector SPDR, with SIC-range overrides (e.g. REITs,
    SIC 6798 -> XLRE). Tickers with a blank sector_etf (no CIK or SIC, or the FF49
    'Other' industry) are left out. Symbols are normalised as in nasdaq_sector_etf_map.
    """
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    etfs = df['sector_etf'].str.strip().str.upper()
    keep = etfs != ''
    return dict(zip(_normalise_symbols(df['ticker'])[keep], etfs[keep]))


def _normalise_symbols(symbols: pd.Series) -> pd.Series:
    """Upper case, no whitespace, '.' and '/' -> '-' for class shares (BRK.B -> BRK-B)."""
    return (symbols.astype(str).str.strip().str.upper().str.replace(r'\s+', '', regex=True)
            .str.replace('.', '-', regex=False).str.replace('/', '-', regex=False))


def _naive_dates(index) -> pd.DatetimeIndex:
    """Wall-clock trading dates (tz dropped, time removed) of a DatetimeIndex."""
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def _rolling(values: np.ndarray, window: int, min_periods: int, how: str) -> np.ndarray:
    """Trailing (causal) rolling mean/std down the rows of a T x N array, NaN-aware."""
    frame = pd.DataFrame(values).rolling(window, min_periods=min_periods)
    return (frame.mean() if how == 'mean' else frame.std()).to_numpy()


@dataclass
class ResidualMarket:
    """Calendar-aligned arrays the strategy reads: T dates x N stocks, T x J ETFs."""
    dates: pd.DatetimeIndex
    symbols: List[str]
    close: np.ndarray            # adjusted close; NaN on days without a real bar
    close_ff: np.ndarray         # last real adjusted close (NaN before the first bar)
    close_pit: np.ndarray        # point-in-time (split-unadjusted) close; NaN without a bar
    dollar_volume: np.ndarray    # point-in-time close x point-in-time shares; NaN without a bar
    adv_dollars: np.ndarray      # trailing adv_days mean dollar volume
    daily_vol: np.ndarray        # trailing adv_days std of daily returns
    etfs: List[str]
    etf_close: np.ndarray        # T x J, forward-filled
    etf_daily_vol: np.ndarray    # T x J
    etf_of: np.ndarray           # N: column of each stock's ETF in etf_close

    @classmethod
    def from_prices(cls, prices: Mapping[str, pd.DataFrame], sector_closes: Mapping[str, pd.Series],
                    sector_map: Mapping[str, str], adv_days: int = 20) -> 'ResidualMarket':
        """Align the price dict and the sector ETF closes on the ETFs' trading calendar.

        prices        : {symbol: DataFrame} as in the price cache (adjusted 'Close'; 'Close_PIT'
                        and 'Volume_PIT' when present, else 'Close' and 'Volume').
        sector_closes : {ETF: Series of adjusted closes} (macro_data['sectors']).
        sector_map    : {symbol: ETF}; symbols without a mapped ETF that has closes are dropped.
        """
        etfs = sorted({e for e in sector_map.values() if e in sector_closes})
        etf_frame = pd.DataFrame({e: pd.Series(sector_closes[e].to_numpy(dtype=float),
                                               index=_naive_dates(sector_closes[e].index))
                                  for e in etfs})
        etf_frame = etf_frame[~etf_frame.index.duplicated(keep='last')].sort_index()
        dates = etf_frame.index
        etf_close = etf_frame.ffill().to_numpy(dtype=float)
        etf_ret = etf_close[1:] / etf_close[:-1] - 1.0
        etf_ret = np.vstack([np.full((1, len(etfs)), np.nan), etf_ret])
        etf_vol = _rolling(etf_ret, adv_days, max(2, int(adv_days * 0.7)), 'std')

        symbols = sorted(s for s in prices if sector_map.get(s) in etfs and 'Close' in prices[s].columns)
        T, N = len(dates), len(symbols)
        close = np.full((T, N), np.nan)
        close_pit = np.full((T, N), np.nan)
        shares_pit = np.full((T, N), np.nan)
        for i, sym in enumerate(symbols):
            df = prices[sym]
            df = df.set_axis(_naive_dates(df.index))
            df = df[~df.index.duplicated(keep='last')]
            c = df['Close'].where(df['Close'] > 0)
            pit = df['Close_PIT'].where(df['Close_PIT'] > 0) if 'Close_PIT' in df.columns else c
            vol = df['Volume_PIT'] if 'Volume_PIT' in df.columns else df.get('Volume')
            close[:, i] = c.reindex(dates).to_numpy(dtype=float)
            close_pit[:, i] = pit.where(c.notna()).reindex(dates).to_numpy(dtype=float)
            if vol is not None:
                shares_pit[:, i] = vol.where(c.notna()).reindex(dates).to_numpy(dtype=float)
        close_ff = pd.DataFrame(close).ffill().to_numpy()
        dollar_volume = close_pit * shares_pit
        returns = close_ff[1:] / close_ff[:-1] - 1.0
        returns = np.vstack([np.full((1, N), np.nan), returns])
        minp = max(2, int(adv_days * 0.7))
        index = {e: j for j, e in enumerate(etfs)}
        return cls(dates=dates, symbols=symbols, close=close, close_ff=close_ff, close_pit=close_pit,
                   dollar_volume=dollar_volume,
                   adv_dollars=_rolling(dollar_volume, adv_days, minp, 'mean'),
                   daily_vol=_rolling(returns, adv_days, minp, 'std'),
                   etfs=etfs, etf_close=etf_close, etf_daily_vol=etf_vol,
                   etf_of=np.array([index[sector_map[s]] for s in symbols], dtype=int))

    def stock_returns(self) -> np.ndarray:
        """Daily simple returns between consecutive real bars (NaN if either bar is missing)."""
        r = self.close[1:] / self.close[:-1] - 1.0
        return np.vstack([np.full((1, len(self.symbols)), np.nan), r])

    def etf_returns(self) -> np.ndarray:
        """Daily simple returns of the ETF closes (T x J)."""
        r = self.etf_close[1:] / self.etf_close[:-1] - 1.0
        return np.vstack([np.full((1, len(self.etfs)), np.nan), r])


class LiquidityUniverse:
    """S1's universe rule, re-applied every `rebalance_every` trading days.

    On a ranking day d (the anchor and every rebalance_every-th trading day before or
    after it) the candidates are the members on d (`members(d)`, the point-in-time
    membership in force on d; every symbol of `prices` when None) with a price frame.
    Each candidate's bars dated in (d - window_days, d] (pair_selector.formation_window,
    S1's formation window) go through S1's symbol screen (pair_selector.screen_symbols),
    and the `size` most liquid screened names with a sector ETF (in market.symbols) form
    the universe. Only data dated <= d is used. A query for date t returns the universe
    of the latest ranking day <= t (empty before the first one). `log` records each
    ranking day used: its date, the members, those with prices, those that pass the
    screen ('screened') and those of them with a sector ETF ('eligible'), the selected
    count, and how many of S1's own `size` names (the most liquid screened ones, with or
    without an ETF) have no sector ETF ('s1_without_sector_etf'), each replaced here by
    the next most liquid name.
    """

    def __init__(self, market: ResidualMarket, prices: Mapping[str, pd.DataFrame], size: int = 500,
                 rebalance_every: int = 21, window_days: int = 1095, anchor=None,
                 members: Optional[Callable[[pd.Timestamp], Iterable[str]]] = None,
                 min_dollar_volume: float = MIN_DOLLAR_VOLUME):
        self.market = market
        self.size = int(size)
        self.rebalance_every = int(rebalance_every)
        self.window_days = int(window_days)
        self.min_dollar_volume = float(min_dollar_volume)
        self.members = members
        # The columns the screen reads. 'Returns' as the price cache carries it
        # (data_processor: returns of the forward-filled close); a raw OHLCV frame gets it.
        self.prices = {}
        for sym, df in prices.items():
            if not len(df.index) or 'Close' not in df.columns:
                continue
            if 'Returns' not in df.columns:
                df = df.assign(Returns=df['Close'].ffill().pct_change(fill_method=None))
            self.prices[sym] = df[[c for c in _SCREEN_COLUMNS if c in df.columns]]
        self.tradable = set(market.symbols)
        anchor_ts = market.dates[0] if anchor is None else pd.Timestamp(anchor)
        self.anchor_k = int(market.dates.searchsorted(anchor_ts, side='left'))
        self._members: Dict[int, List[str]] = {}
        self.log: Dict[int, Dict] = {}

    def ranking_day(self, date) -> int:
        """Calendar row of the latest ranking day <= `date` (-1 if there is none)."""
        k = int(self.market.dates.searchsorted(pd.Timestamp(date), side='right')) - 1
        if k < 0:
            return -1
        r = self.anchor_k + self.rebalance_every * ((k - self.anchor_k) // self.rebalance_every)
        return r if r >= 0 else -1

    def members_at(self, r: int) -> List[str]:
        """Membership ranked on calendar row r."""
        if r not in self._members:
            day = self.market.dates[r]
            if self.members is None:
                n_members, pool = len(self.prices), sorted(self.prices)
            else:
                member = set(self.members(day))
                n_members, pool = len(member), sorted(member & set(self.prices))
            window = {s: formation_window(self.prices[s], day, self.window_days) for s in pool}
            screened = [s for s, _ in screen_symbols(window, self.min_dollar_volume)]
            eligible = [s for s in screened if s in self.tradable]
            self._members[r] = sorted(eligible[:self.size])
            self.log[r] = {'date': str(day.date()), 'members': n_members, 'with_prices': len(pool),
                           'screened': len(screened), 'eligible': len(eligible),
                           'selected': len(self._members[r]),
                           's1_without_sector_etf': sum(s not in self.tradable for s in screened[:self.size])}
        return self._members[r]

    def __call__(self, date) -> List[str]:
        r = self.ranking_day(date)
        return self.members_at(r) if r >= 0 else []


# ──────────────────────────────────────────────────────────────────────────────
# Estimation (A&L Appendix)
# ──────────────────────────────────────────────────────────────────────────────

def ou_from_ar1(a, b, var_zeta, periods: int = TRADING_DAYS_PER_YEAR) -> Dict[str, np.ndarray]:
    """OU parameters from the AR(1) X_{n+1} = a + b X_n + zeta (A&L Appendix eq. 21).

    kappa = -ln(b) x periods, m = a / (1 - b), sigma_eq = sqrt(Var(zeta) / (1 - b^2));
    NaN wherever 0 < b < 1 fails (the OU mapping is undefined there).
    """
    a, b, var_zeta = (np.asarray(x, dtype=float) for x in (a, b, var_zeta))
    ok = (b > 0) & (b < 1)
    bb = np.where(ok, b, 0.5)
    kappa = np.where(ok, -np.log(bb) * periods, np.nan)
    m = np.where(ok, a / (1.0 - bb), np.nan)
    sigma_eq = np.where(ok, np.sqrt(np.maximum(var_zeta, 0.0) / (1.0 - bb * bb)), np.nan)
    return {'kappa': kappa, 'm': m, 'sigma_eq': sigma_eq}


def ou_residual_fit(stock_returns, etf_returns, periods: int = TRADING_DAYS_PER_YEAR) -> Dict[str, np.ndarray]:
    """A&L Appendix estimation on the LAST axis of the inputs (one estimation window).

    Inputs: arrays (..., W) of stock and ETF daily returns, oldest first. Returns arrays
    of shape (...): beta0, beta (OLS of stock on ETF returns with intercept), a, b and
    var_zeta (OLS AR(1) of the cumulative residual X_1..X_W, sample variance of its W - 1
    residuals with ddof = 1), kappa, m, sigma_eq (eq. 21) and `estimable` (every return
    finite and neither regression degenerate). kappa, m and sigma_eq are NaN unless
    0 < b < 1.
    """
    r = np.asarray(stock_returns, dtype=float)
    e = np.asarray(etf_returns, dtype=float)
    w = r.shape[-1]
    finite = np.isfinite(r).all(-1) & np.isfinite(e).all(-1)
    r = np.where(np.isfinite(r), r, 0.0)
    e = np.where(np.isfinite(e), e, 0.0)
    de = e - e.mean(-1, keepdims=True)
    dr = r - r.mean(-1, keepdims=True)
    see = (de * de).sum(-1)
    with np.errstate(invalid='ignore', divide='ignore'):
        beta = np.where(see > 0, (de * dr).sum(-1) / np.where(see > 0, see, 1.0), np.nan)
        beta0 = r.mean(-1) - beta * e.mean(-1)
        x_all = np.cumsum(dr - beta[..., None] * de, axis=-1)
        x, y = x_all[..., :-1], x_all[..., 1:]
        dx = x - x.mean(-1, keepdims=True)
        dy = y - y.mean(-1, keepdims=True)
        sxx = (dx * dx).sum(-1)
        b = np.where(sxx > 0, (dx * dy).sum(-1) / np.where(sxx > 0, sxx, 1.0), np.nan)
        a = y.mean(-1) - b * x.mean(-1)
        zeta = dy - b[..., None] * dx
        var_zeta = (zeta * zeta).sum(-1) / (w - 2)
    estimable = finite & (see > 0) & (sxx > 0)
    nan = np.full(estimable.shape, np.nan)
    out = {'beta0': beta0, 'beta': beta, 'a': a, 'b': b, 'var_zeta': var_zeta}
    out.update(ou_from_ar1(a, b, var_zeta, periods))
    out = {k: np.where(estimable, v, nan) for k, v in out.items()}
    out['estimable'] = estimable
    return out


def rolling_ou_fits(stock_returns: np.ndarray, etf_returns: np.ndarray, window: int = 60,
                    rows: Optional[Sequence[int]] = None, chunk: int = 32) -> Dict[str, np.ndarray]:
    """ou_residual_fit on the trailing `window` returns ending at each row of T x N matrices.

    Row t uses returns t - window + 1 .. t only. `etf_returns` is aligned with the stocks
    (column i = the return of stock i's ETF). Only `rows` are estimated (all rows with a
    full window by default); other entries are NaN (estimable False). Vectorised over
    stocks and days with a strided window view, processed `chunk` rows at a time.
    """
    T, N = stock_returns.shape
    keys = ('beta0', 'beta', 'a', 'b', 'var_zeta', 'kappa', 'm', 'sigma_eq')
    out = {k: np.full((T, N), np.nan) for k in keys}
    out['estimable'] = np.zeros((T, N), dtype=bool)
    rows = np.arange(window - 1, T) if rows is None else np.asarray(sorted(rows), dtype=int)
    rows = rows[rows >= window - 1]
    if rows.size == 0 or N == 0:
        return out
    view_r = np.lib.stride_tricks.sliding_window_view(stock_returns, window, axis=0)
    view_e = np.lib.stride_tricks.sliding_window_view(etf_returns, window, axis=0)
    for lo in range(0, rows.size, chunk):
        rr = rows[lo:lo + chunk]
        fit = ou_residual_fit(view_r[rr - window + 1], view_e[rr - window + 1])
        for k, v in fit.items():
            out[k][rr] = v
    return out


def centred_s_scores(m: np.ndarray, sigma_eq: np.ndarray, accepted: np.ndarray,
                     in_universe: np.ndarray) -> np.ndarray:
    """s = -(m - <m>) / sigma_eq (A&L Sec. 5.1 eq. 18, Appendix eq. 22), row by row.

    <m> is the mean of m over the row's universe members with an accepted model; s is
    NaN where the model is not accepted or the row has no such member.
    """
    pool = accepted & in_universe
    count = pool.sum(axis=1)
    total = np.where(pool, m, 0.0).sum(axis=1)
    mean_m = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    with np.errstate(invalid='ignore', divide='ignore'):
        s = -(m - mean_m[:, None]) / sigma_eq
    return np.where(accepted, s, np.nan)


@dataclass
class ResidualSignals:
    """Per-day, per-stock signal inputs of the simulation (T x N arrays)."""
    s: np.ndarray
    beta: np.ndarray
    kappa: np.ndarray
    m: np.ndarray
    sigma_eq: np.ndarray
    estimable: np.ndarray
    accepted: np.ndarray
    in_universe: np.ndarray


def compute_signals(market: ResidualMarket, in_universe: np.ndarray,
                    params: ResidualStatArbParams = ResidualStatArbParams(),
                    rows: Optional[Sequence[int]] = None) -> ResidualSignals:
    """Daily A&L fits and centred s-scores for the stocks that are ever in the universe.

    Columns never in `in_universe` are not estimated (they cannot be traded). A model is
    accepted when it is estimable, 0 < b < 1 and kappa > kappa_min.
    """
    T, N = market.close.shape
    cols = np.flatnonzero(in_universe.any(axis=0))
    stock_r = market.stock_returns()[:, cols]
    etf_r = market.etf_returns()[:, market.etf_of[cols]]
    fit = rolling_ou_fits(stock_r, etf_r, params.window, rows)

    def full(v, fill):
        a = np.full((T, N), fill, dtype=v.dtype)
        a[:, cols] = v
        return a

    est = full(fit['estimable'], False)
    kappa = full(fit['kappa'], np.nan)
    with np.errstate(invalid='ignore'):
        accepted = est & (kappa > params.kappa_min)
    m = full(fit['m'], np.nan)
    sigma_eq = full(fit['sigma_eq'], np.nan)
    return ResidualSignals(s=centred_s_scores(m, sigma_eq, accepted, in_universe),
                           beta=full(fit['beta'], np.nan), kappa=kappa, m=m, sigma_eq=sigma_eq,
                           estimable=est, accepted=accepted, in_universe=in_universe)


# ──────────────────────────────────────────────────────────────────────────────
# Simulation
# ──────────────────────────────────────────────────────────────────────────────

def _leg_cost(cost_model, shares: float, price: float, adv_dollars: float, daily_vol: float,
              pit_price: float) -> Dict[str, float]:
    """One-way cost of one execution (calculate_leg_cost with ADV in the price's share units)."""
    adv_shares = adv_dollars / price if np.isfinite(adv_dollars) and adv_dollars > 0 else None
    return cost_model.calculate_leg_cost(shares, price, daily_volume_shares=adv_shares,
                                         daily_volatility=daily_vol, point_in_time_price=pit_price)


def simulate_residual_book(market: ResidualMarket, signals: ResidualSignals,
                           params: ResidualStatArbParams = ResidualStatArbParams(),
                           first_k: int = 0, last_entry_k: Optional[int] = None,
                           cost_model: Optional[EnhancedPrimeFundTransactionCostModel] = None) -> Dict:
    """Daily event loop: signals at the close of day k, fills at the close of k + 1.

    first_k      : first signal day (calendar row); the daily series starts there.
    last_entry_k : last day on which a new position may be signalled; positions open after
                   it run off under the exit rule until the data ends.
    Returns the raw result dict (see run_residual_statarb).
    """
    cost_model = cost_model or s1_cost_model()
    T, N = market.close.shape
    J = len(market.etfs)
    last_entry_k = T - 1 if last_entry_k is None else int(last_entry_k)
    dates = market.dates
    cff, ecl = market.close_ff, market.etf_close
    has_bar = np.isfinite(market.close)
    pit_ratio = pd.DataFrame(market.close_pit / market.close).ffill().to_numpy()

    side = np.zeros(N, dtype=int)
    shares = np.zeros(N)
    hedge = np.zeros(N)                       # ETF shares of each stock's own hedge
    etf_pos = np.zeros(J)                     # netted ETF shares held
    open_trades: Dict[int, Dict] = {}
    pending: Dict[int, Dict] = {}
    trades: List[Dict] = []
    stock_costs = dict.fromkeys(('commission', 'bid_ask', 'market_impact', 'borrow'), 0.0)
    etf_costs = dict.fromkeys(('commission', 'bid_ask', 'market_impact', 'borrow'), 0.0)
    traded = {'stock': 0.0, 'etf_net': 0.0, 'etf_unnetted': 0.0}
    rejects = {'no_fill_bar': 0}
    daily = {key: [] for key in ('dates', 'returns', 'gross_returns', 'gross_pnl', 'costs', 'equity',
                                 'gross_exposure', 'stock_gross_exposure', 'etf_gross_exposure',
                                 'open_positions', 'long_positions', 'short_positions')}
    equity = float(params.initial_capital)

    for k in range(first_k, T):
        equity_prev = equity
        gross_pnl = 0.0
        day_cost = 0.0
        if k > first_k:
            held = shares != 0
            gross_pnl += float(np.dot(shares[held], cff[k, held] - cff[k - 1, held]))
            gross_pnl += float(np.dot(etf_pos, ecl[k] - ecl[k - 1]))
            cal_days = int((dates[k] - dates[k - 1]).days)
            for j in np.flatnonzero(etf_pos < -_SHARE_EPS):
                fee = cost_model.calculate_borrow_cost(-etf_pos[j] * ecl[k - 1, j], market.etfs[j], cal_days)
                etf_costs['borrow'] += fee
                day_cost += fee

        # Fills at today's close: orders signalled yesterday; at the last bar, close everything.
        orders, pending = pending, {}
        if k == T - 1:
            for i in open_trades:
                orders.setdefault(i, {'kind': 'close', 'signal_k': k, 'reason': 'end_of_data'})
        for i, order in sorted(orders.items(), key=lambda kv: (kv[1]['kind'] != 'close', kv[0])):
            j = market.etf_of[i]
            if order['kind'] == 'close':
                t = open_trades.pop(i)
                price = float(cff[k, i])
                c = _leg_cost(cost_model, t['shares'], price, market.adv_dollars[k, i],
                              market.daily_vol[k, i], price * pit_ratio[k, i])
                cal_days = max(1, int((dates[k] - dates[t['entry_k']]).days))
                borrow = (cost_model.calculate_borrow_cost(abs(t['shares']) * t['entry_price'],
                                                           market.symbols[i], cal_days)
                          if t['shares'] < 0 else 0.0)
                stock_pnl = t['shares'] * (price - t['entry_price'])
                hedge_pnl = t['etf_shares'] * (ecl[k, j] - t['etf_entry_price'])
                costs = {key: t['entry_costs'][key] + c[key]
                         for key in ('commission', 'bid_ask', 'market_impact')}
                costs['borrow'] = borrow
                costs['total'] = sum(costs.values())
                for key in ('commission', 'bid_ask', 'market_impact'):
                    stock_costs[key] += c[key]
                stock_costs['borrow'] += borrow
                day_cost += c['total'] + borrow
                traded['stock'] += abs(t['shares']) * price
                traded['etf_unnetted'] += abs(t['etf_shares']) * ecl[k, j]
                gross = stock_pnl + hedge_pnl
                t.update({'exit_signal_k': order['signal_k'], 'exit_k': k, 'exit_reason': order['reason'],
                          's_exit': order.get('s'), 'exit_price': price, 'exit_price_real': bool(has_bar[k, i]),
                          'etf_exit_price': float(ecl[k, j]), 'stock_pnl': stock_pnl, 'hedge_pnl': hedge_pnl,
                          'gross_pnl': gross, 'costs': costs, 'net_pnl': gross - costs['total'],
                          'calendar_days': cal_days, 'trading_days_held': k - t['entry_k']})
                trades.append(t)
                side[i], shares[i], hedge[i] = 0, 0.0, 0.0
            else:
                if not has_bar[k, i]:
                    rejects['no_fill_bar'] += 1
                    continue
                price = float(market.close[k, i])
                c = _leg_cost(cost_model, order['shares'], price, market.adv_dollars[k, i],
                              market.daily_vol[k, i], price * pit_ratio[k, i])
                for key in ('commission', 'bid_ask', 'market_impact'):
                    stock_costs[key] += c[key]
                day_cost += c['total']
                traded['stock'] += abs(order['shares']) * price
                traded['etf_unnetted'] += abs(order['etf_shares']) * ecl[k, j]
                side[i] = 1 if order['shares'] > 0 else -1
                shares[i], hedge[i] = order['shares'], order['etf_shares']
                open_trades[i] = {
                    'symbol': market.symbols[i], 'etf': market.etfs[j],
                    'side': 'long' if side[i] > 0 else 'short',
                    'signal_k': order['signal_k'], 'entry_k': k,
                    's_entry': order['s'], 'kappa': order['kappa'], 'beta': order['beta'],
                    'm': order['m'], 'sigma_eq': order['sigma_eq'], 'notional': order['notional'],
                    'shares': order['shares'], 'etf_shares': order['etf_shares'],
                    'entry_price': price, 'etf_entry_price': float(ecl[k, j]),
                    'entry_costs': {key: c[key] for key in ('commission', 'bid_ask', 'market_impact')},
                }

        # One net trade per ETF: the change of the summed hedges.
        target = np.bincount(market.etf_of, weights=hedge, minlength=J) if N else np.zeros(J)
        for j in np.flatnonzero(np.abs(target - etf_pos) > _SHARE_EPS):
            delta = float(target[j] - etf_pos[j])
            c = cost_model.calculate_leg_cost(delta, float(ecl[k, j]),
                                              daily_volume_shares=ETF_ASSUMED_ADV_DOLLARS / ecl[k, j],
                                              daily_volatility=float(market.etf_daily_vol[k, j]),
                                              point_in_time_price=float(ecl[k, j]))
            for key in ('commission', 'bid_ask', 'market_impact'):
                etf_costs[key] += c[key]
            day_cost += c['total']
            traded['etf_net'] += abs(delta) * ecl[k, j]
        etf_pos = target

        equity = equity_prev + gross_pnl - day_cost
        held = shares != 0
        stock_gross = float(np.abs(shares[held] * cff[k, held]).sum())
        etf_gross = float(np.abs(etf_pos * ecl[k]).sum())
        daily['dates'].append(dates[k])
        daily['returns'].append((gross_pnl - day_cost) / equity_prev if equity_prev > 0 else 0.0)
        daily['gross_returns'].append(gross_pnl / equity_prev if equity_prev > 0 else 0.0)
        daily['gross_pnl'].append(gross_pnl)
        daily['costs'].append(day_cost)
        daily['equity'].append(equity)
        daily['stock_gross_exposure'].append(stock_gross / equity if equity > 0 else 0.0)
        daily['etf_gross_exposure'].append(etf_gross / equity if equity > 0 else 0.0)
        daily['gross_exposure'].append((stock_gross + etf_gross) / equity if equity > 0 else 0.0)
        daily['open_positions'].append(int(held.sum()))
        daily['long_positions'].append(int((side > 0).sum()))
        daily['short_positions'].append(int((side < 0).sum()))

        if k == T - 1:
            break
        # Signals at today's close, for fills at the next close.
        s = signals.s[k]
        for i in np.flatnonzero(side != 0):
            if not signals.estimable[k, i]:
                continue
            if not signals.accepted[k, i]:
                pending[i] = {'kind': 'close', 'signal_k': k, 'reason': 'model_rejected', 's': None}
            elif (side[i] > 0 and s[i] > -params.s_close_long) or (side[i] < 0 and s[i] < params.s_close_short):
                pending[i] = {'kind': 'close', 'signal_k': k, 'reason': 'signal', 's': float(s[i])}
        if k <= last_entry_k and k + 1 < T - 1:
            with np.errstate(invalid='ignore'):
                go = (side == 0) & signals.in_universe[k] & signals.accepted[k] & np.isfinite(signals.beta[k]) \
                    & ((s < -params.s_open) | (s > params.s_open))
            notional = params.position_frac * equity
            for i in np.flatnonzero(go):
                direction = 1.0 if s[i] < 0 else -1.0
                j = market.etf_of[i]
                pending[i] = {'kind': 'open', 'signal_k': k, 's': float(s[i]),
                              'kappa': float(signals.kappa[k, i]), 'beta': float(signals.beta[k, i]),
                              'm': float(signals.m[k, i]), 'sigma_eq': float(signals.sigma_eq[k, i]),
                              'notional': notional, 'shares': direction * notional / cff[k, i],
                              'etf_shares': -direction * signals.beta[k, i] * notional / ecl[k, j]}
        if k >= last_entry_k and not open_trades and not pending:
            break

    return {'trades': trades, 'daily': daily, 'stock_costs': stock_costs, 'etf_costs': etf_costs,
            'traded_notional': traded, 'rejects': rejects, 'initial_capital': float(params.initial_capital)}


# ──────────────────────────────────────────────────────────────────────────────
# Results
# ──────────────────────────────────────────────────────────────────────────────

def _per_trade_bp(values: np.ndarray) -> Dict[str, Optional[float]]:
    """Mean, standard error and t of per-trade values given in bp (trades treated as independent)."""
    n = int(values.size)
    if n == 0:
        return {'mean': None, 'se': None, 't': None, 'n': 0}
    if n < 2:
        return {'mean': float(values.mean()), 'se': None, 't': None, 'n': n}
    se = float(values.std(ddof=1) / np.sqrt(n))
    return {'mean': float(values.mean()), 'se': se, 't': float(values.mean() / se) if se > 0 else None,
            'n': n}


def summarise_residual_book(raw: Dict, dates: pd.DatetimeIndex) -> Dict:
    """Trade records, cost totals, turnover and summary metrics from simulate_residual_book.

    `dates` is the full calendar the simulation ran on (trades carry calendar rows).
    Per-trade bp (gross_bp, net_bp, cost_bp) are of the position's stock notional, the
    dollar amount A&L's P&L equation invests per stock; a trade's P&L includes its own
    hedge leg, while ETF execution and borrow costs are booked on the netted ETF book
    and reported in aggregate (summary etf_cost_bp_per_trade: ETF costs / summed entry
    notional). The per-trade t treats trades as independent; hac_t_* use the daily series.
    """
    daily = raw['daily']
    r = np.asarray(daily['returns'], dtype=float)
    g = np.asarray(daily['gross_returns'], dtype=float)
    n_days = int(r.size)
    capital = raw['initial_capital']
    final_equity = daily['equity'][-1] if daily['equity'] else capital
    total_return = final_equity / capital - 1.0

    records = []
    for t in sorted(raw['trades'], key=lambda t: (t['entry_k'], t['symbol'])):
        notional = t['notional']
        records.append({
            'symbol': t['symbol'], 'etf': t['etf'], 'side': t['side'],
            'signal_date': str(dates[t['signal_k']].date()), 'entry_date': str(dates[t['entry_k']].date()),
            'exit_signal_date': str(dates[t['exit_signal_k']].date()), 'exit_date': str(dates[t['exit_k']].date()),
            'exit_reason': t['exit_reason'], 's_entry': t['s_entry'], 's_exit': t['s_exit'],
            'kappa': t['kappa'], 'half_life_days': float(np.log(2) / t['kappa'] * TRADING_DAYS_PER_YEAR),
            'beta': t['beta'], 'm': t['m'], 'sigma_eq': t['sigma_eq'],
            'notional': notional, 'shares': t['shares'], 'etf_shares': t['etf_shares'],
            'entry_price': t['entry_price'], 'exit_price': t['exit_price'], 'exit_price_real': t['exit_price_real'],
            'etf_entry_price': t['etf_entry_price'], 'etf_exit_price': t['etf_exit_price'],
            'holding_days': t['trading_days_held'], 'calendar_days': t['calendar_days'],
            'stock_pnl': t['stock_pnl'], 'hedge_pnl': t['hedge_pnl'], 'gross_pnl': t['gross_pnl'],
            'net_pnl': t['net_pnl'], 'costs': dict(t['costs']),
            'gross_bp': t['gross_pnl'] / notional * 1e4, 'net_bp': t['net_pnl'] / notional * 1e4,
            'cost_bp': t['costs']['total'] / notional * 1e4,
        })

    stock_total = float(sum(raw['stock_costs'].values()))
    etf_total = float(sum(raw['etf_costs'].values()))
    gross_pnl = float(np.sum(daily['gross_pnl']))
    entry_notional = float(sum(t['notional'] for t in records))
    gross_bp = np.array([t['gross_bp'] for t in records], dtype=float)
    net_bp = np.array([t['net_bp'] for t in records], dtype=float)
    cost_bp = np.array([t['cost_bp'] for t in records], dtype=float)
    exit_reasons: Dict[str, int] = {}
    for t in records:
        exit_reasons[t['exit_reason']] = exit_reasons.get(t['exit_reason'], 0) + 1
    avg_equity = float(np.mean(daily['equity'])) if daily['equity'] else capital
    traded = raw['traded_notional']
    per_year = TRADING_DAYS_PER_YEAR / n_days if n_days else 0.0
    gross_exposure = np.asarray(daily['gross_exposure'], dtype=float)
    hac_net, hac_gross = hac_tstat_mean(r), hac_tstat_mean(g)
    etf_bp = etf_total / entry_notional * 1e4 if entry_notional > 0 else None

    summary = {
        'start': str(daily['dates'][0].date()) if n_days else None,
        'end': str(daily['dates'][-1].date()) if n_days else None,
        'days': n_days,
        'total_return': total_return,
        'annualized_return': (float((1.0 + total_return) ** per_year - 1.0)
                              if n_days and total_return > -1.0 else None),
        'sharpe': annualized_sharpe(r),
        'gross_sharpe': annualized_sharpe(g),
        'volatility': float(r.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)) if n_days > 1 else 0.0,
        'max_drawdown': -calculate_max_drawdown_from_returns(r),      # <= 0, as the pairs engine
        'hac_t_net': hac_net['tstat'], 'hac_p_net': hac_net['pvalue'],
        'hac_t_gross': hac_gross['tstat'], 'hac_p_gross': hac_gross['pvalue'],
        'final_equity': final_equity,
        'gross_pnl': gross_pnl,
        'total_costs': stock_total + etf_total,
        'trades': len(records),
        'trades_long': sum(1 for t in records if t['side'] == 'long'),
        'trades_short': sum(1 for t in records if t['side'] == 'short'),
        'win_rate': float(np.mean(net_bp > 0)) if records else None,
        'gross_bp_per_trade': _per_trade_bp(gross_bp),
        'net_bp_per_trade': _per_trade_bp(net_bp),
        'stock_cost_bp_per_trade': float(cost_bp.mean()) if records else None,
        'etf_cost_bp_per_trade': etf_bp,
        'cost_bp_per_trade': (float(cost_bp.mean()) + etf_bp) if records and etf_bp is not None else None,
        'avg_holding_days': float(np.mean([t['holding_days'] for t in records])) if records else None,
        'median_holding_days': float(np.median([t['holding_days'] for t in records])) if records else None,
        'avg_gross_exposure': float(gross_exposure.mean()) if n_days else 0.0,
        'max_gross_exposure': float(gross_exposure.max()) if n_days else 0.0,
        'avg_open_positions': float(np.mean(daily['open_positions'])) if n_days else 0.0,
        'max_open_positions': int(np.max(daily['open_positions'])) if n_days else 0,
        'exit_reasons': dict(sorted(exit_reasons.items())),
    }
    costs = {
        'stock': dict(raw['stock_costs'], total=stock_total),
        'etf': dict(raw['etf_costs'], total=etf_total),
        'total': stock_total + etf_total,
    }
    turnover = {
        'stock_traded_notional': traded['stock'],
        'etf_traded_notional': traded['etf_net'],
        'etf_traded_notional_unnetted': traded['etf_unnetted'],
        'annual_turnover': (traded['stock'] + traded['etf_net']) / avg_equity * per_year,
        'annual_stock_turnover': traded['stock'] / avg_equity * per_year,
        'annual_etf_turnover': traded['etf_net'] / avg_equity * per_year,
    }
    # The pairs headline's significance battery (significance_report), on the net series.
    ci = block_bootstrap_sharpe_ci(r, periods=TRADING_DAYS_PER_YEAR) if n_days > 1 else {}
    significance = {
        'ann_sharpe': summary['sharpe'], 'hac_t': hac_net['tstat'], 'hac_p': hac_net['pvalue'],
        'psr': probabilistic_sharpe_ratio(r, 0.0, TRADING_DAYS_PER_YEAR)['psr'] if n_days > 1 else None,
        'boot_lo': ci.get('lo'), 'boot_hi': ci.get('hi'),
    }
    return {
        'daily_dates': [str(d.date()) for d in daily['dates']],
        'daily_net_returns': list(r),
        'daily_returns': list(r),                  # the same net series, the pairs engine's key
        'daily_gross_returns': list(g),
        'daily_gross_pnl': list(daily['gross_pnl']),
        'daily_costs': list(daily['costs']),
        'daily_equity': list(daily['equity']),
        'daily_gross_exposure': list(daily['gross_exposure']),
        'daily_stock_gross_exposure': list(daily['stock_gross_exposure']),
        'daily_etf_gross_exposure': list(daily['etf_gross_exposure']),
        'daily_open_positions': list(daily['open_positions']),
        'daily_long_positions': list(daily['long_positions']),
        'daily_short_positions': list(daily['short_positions']),
        'trades': records,
        'total_trades': len(records),
        'costs': costs,
        'turnover': turnover,
        'summary': summary,
        'significance': significance,
        'rejects': dict(raw['rejects']),
    }


SPEC = {
    'strategy': 'Avellaneda & Lee (2010) sector-ETF residual mean reversion',
    'reference': 'Avellaneda, M. and Lee, J.-H. (2010), Statistical Arbitrage in the U.S. Equities '
                 'Market, Quantitative Finance 10(7):761-782; equation numbers of the 15 June 2009 draft',
    'signal': 'pure mean-reversion s-score, Sec. 4.1 eq. (15), s = -(m - <m>)/sigma_eq with the '
              'cross-sectionally centred mean of Sec. 5.1 eq. (18) / Appendix eq. (22); <m> over the '
              "day's universe members with an accepted model. Not the drift-adjusted eq. (17).",
    'estimation': '60-day OLS of stock on sector-ETF returns with intercept; AR(1) by OLS on the '
                  'cumulative residual; kappa = -ln(b)*252, m = a/(1-b), sigma_eq = sqrt(Var(zeta)/(1-b^2)) '
                  '(Appendix eq. 21); accepted iff 0 < b < 1 and kappa > 252/30',
    'rules': 'open long s < -1.25, open short s > 1.25, close long s > -0.50, close short s < 0.75 '
             '(Sec. 4.1 eq. 16); close when a held model is rejected (Sec. 5); no estimate: keep state',
    'execution': 'signal at the close of t, fill at the close of t+1, shares fixed from the t close; '
                 'stock notional position_frac x equity hedged with -beta x notional of the sector ETF, '
                 'ETF hedges netted daily',
    'costs': "S1's cost model (profile v33): transaction_costs.calculate_leg_cost per stock execution "
             '(20-day dollar ADV and volatility at the fill) + borrow on short stock legs; net ETF trades '
             'through the same function at ETF_ASSUMED_ADV_DOLLARS (top spread bucket, impact ~0) + borrow on '
             'net short ETF positions',
    'universe': "S1's rule: on each ranking day (the first signal day, then every universe_rebalance_days) the "
                'point-in-time members in force that day (the IWV snapshot) with price history, screened as S1 '
                'screens a formation on the trailing universe_window_days (pair_selector.screen_symbols: >= 300 '
                'bars, mean point-in-time close >= $5 and dollar volume >= $10M, annualised volatility 5-80%, '
                '< 10% missing closes); the universe_size most liquid screened names with a sector ETF; without a '
                'membership source, every name of the price dict',
}


def run_residual_statarb(prices: Mapping[str, pd.DataFrame], sector_closes: Mapping[str, pd.Series],
                         sector_map: Mapping[str, str], start, end,
                         universe: Optional[Callable[[pd.Timestamp], Sequence[str]]] = None,
                         params: ResidualStatArbParams = ResidualStatArbParams(),
                         cost_model: Optional[EnhancedPrimeFundTransactionCostModel] = None,
                         members: Optional[Callable[[pd.Timestamp], Iterable[str]]] = None) -> Dict:
    """Backtest the A&L ETF residual strategy; new positions are signalled on [start, end].

    The daily series starts on the first trading day >= start with a zero return (orders
    signalled at that close fill at the next one) and runs until the last position has
    closed, at the latest the last bar of the data.

    prices        : processed price dict {symbol: DataFrame} (adjusted 'Close'; 'Close_PIT',
                    'Volume_PIT' for the dollar-volume screen and the cost inputs).
    sector_closes : {ETF: Series of closes}, e.g. macro_data['sectors'].
    sector_map    : {symbol: ETF} (e.g. ff49_sector_etf_map()).
    universe      : callable date -> eligible symbols, using data up to that date only;
                    default LiquidityUniverse (S1's rule over `prices`) anchored at `start`.
    cost_model    : default s1_cost_model().
    members       : callable date -> point-in-time members in force on that date (e.g.
                    universe.PITUniverse(...).members_asof), the default universe's gate on
                    each ranking day; None ranks every name. Not combinable with `universe`.
    Returns a dict with daily_dates, daily_net_returns (also as daily_returns),
    daily_gross_returns, daily exposures and position counts, trades and total_trades,
    costs (by type, stock and ETF), turnover, summary metrics and the significance
    battery, universe and signal diagnostics, the parameters and their hash, and the
    strategy spec.
    """
    if universe is not None and members is not None:
        raise ValueError('pass a membership source for the default universe, or a universe, not both')
    cost_model = cost_model or s1_cost_model()
    market = ResidualMarket.from_prices(prices, sector_closes, sector_map, adv_days=params.adv_days)
    dates = market.dates
    T = len(dates)
    first_k = int(dates.searchsorted(pd.Timestamp(start), side='left'))
    last_entry_k = int(dates.searchsorted(pd.Timestamp(end), side='right')) - 1
    if first_k >= T or last_entry_k < first_k:
        raise ValueError(f'no trading days between {start} and {end} in the ETF calendar')
    if universe is None:
        universe = LiquidityUniverse(market, prices, size=params.universe_size,
                                     rebalance_every=params.universe_rebalance_days,
                                     window_days=params.universe_window_days, anchor=dates[first_k],
                                     members=members)
    col = {s: i for i, s in enumerate(market.symbols)}
    in_universe = np.zeros(market.close.shape, dtype=bool)
    unknown = set()
    for k in range(first_k, T):
        for sym in universe(dates[k]):
            i = col.get(sym)
            if i is None:
                unknown.add(sym)
            else:
                in_universe[k, i] = True
    if unknown:
        logger.info(f'Residual stat-arb: {len(unknown)} universe symbols have no prices or no sector ETF '
                    f'and are skipped')
    signals = compute_signals(market, in_universe, params, rows=range(first_k, T))
    logger.info(f'Residual stat-arb: {len(market.symbols)} mapped symbols, '
                f'{int(in_universe.any(axis=0).sum())} ever in the universe, '
                f'{len(dates[first_k:last_entry_k + 1])} signal days')
    raw = simulate_residual_book(market, signals, params, first_k, last_entry_k, cost_model)
    out = summarise_residual_book(raw, dates)

    rows = slice(first_k, first_k + len(out['daily_dates']))
    n_members = in_universe[rows].sum(axis=1)
    accepted = (signals.accepted & in_universe)[rows].sum(axis=1)
    estimable = (signals.estimable & in_universe)[rows].sum(axis=1)
    with np.errstate(invalid='ignore'):
        kappa_u = np.where(signals.accepted & in_universe, signals.kappa, np.nan)[rows]
    out['universe'] = {
        'mapped_symbols': len(market.symbols),
        'symbols_ever_in_universe': int(in_universe.any(axis=0).sum()),
        'unknown_symbols_skipped': len(unknown),
        'mean_members': float(n_members.mean()) if n_members.size else 0.0,
        'etfs': list(market.etfs),
        'point_in_time': members is not None,
        'rankings': [universe.log[r] for r in sorted(getattr(universe, 'log', {}))
                     if first_k <= r < rows.stop],
    }
    out['signal_diagnostics'] = {
        'mean_estimable_fraction': float(np.mean(estimable / np.maximum(n_members, 1))) if n_members.size else None,
        'mean_accepted_fraction': float(np.mean(accepted / np.maximum(n_members, 1))) if n_members.size else None,
        'median_kappa_accepted': float(np.nanmedian(kappa_u)) if np.isfinite(kappa_u).any() else None,
    }
    out['params'] = asdict(params)
    out['params_hash'] = params.config_hash()
    out['spec'] = dict(SPEC, etf_assumed_adv_dollars=ETF_ASSUMED_ADV_DOLLARS,
                       borrow_rate=float(cost_model.gc_borrow_rate),
                       pb_financing_spread=float(cost_model.pb_financing_spread))
    out['signals'] = signals
    out['market'] = market
    return out
