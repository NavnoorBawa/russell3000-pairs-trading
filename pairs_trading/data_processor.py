"""
PAIRS TRADING - DATA
====================
Universe loading, price/macro fetching and caching (yfinance), point-in-time price
reconstruction, and causal technical indicators.
"""

from pairs_trading.config import (
    pd, np, yf, os, json, pickle, time, random, logging,
    concurrent, tqdm, List, Dict, Optional,
    MACRO_TICKERS, SECTOR_ETFS
)

logger = logging.getLogger(__name__)


class EnhancedRussell3000DataProcessor:
    """ENHANCED: Russell 3000 data processor with comprehensive stock loading"""

    def __init__(self, start_date: str = "2020-01-01", end_date: str = "2025-12-31"):
        self.start_date = start_date
        self.end_date = end_date
        self.data_file = "data/enhanced_russell_3000_data.pkl"
        self.successful_count = 0
        self.failed_count = 0
        self.fetch_manifest: Dict[str, str] = {}
        # Fraction of the universe the price data covers (None: a pre-v32 cache without a
        # fetch manifest, coverage unknown). Recorded in every export's run_config.
        self.universe_coverage: Optional[float] = None
        self.universe_cached_fraction: Optional[float] = None   # cached symbols / universe

        logger.info("ENHANCED Russell 3000 Data Processor initialized")

    DEMO_UNIVERSE = [
        # Deliberately short so every ticker can be verified as currently listed. NOT the
        # study universe: it exercises the pipeline but does not reproduce the results.
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'AVGO', 'ORCL',
        'CRM', 'ADBE', 'INTC', 'AMD', 'QCOM', 'TXN', 'MU', 'AMAT',
        'JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'AXP', 'BLK', 'SCHW', 'PNC',
        'UNH', 'JNJ', 'PFE', 'ABT', 'TMO', 'MRK', 'ABBV', 'LLY', 'BMY', 'AMGN',
        'WMT', 'HD', 'COST', 'TGT', 'LOW', 'TJX', 'SBUX', 'MCD', 'NKE',
        'XOM', 'CVX', 'COP', 'EOG', 'SLB', 'MPC', 'VLO', 'PSX',
        'NEE', 'DUK', 'SO', 'AEP', 'CAT', 'BA', 'HON', 'UPS', 'RTX', 'LMT',
        'LIN', 'APD', 'SHW', 'NEM', 'FCX', 'NUE',
        'PLD', 'AMT', 'EQIX', 'PSA', 'SPG', 'O',
        'VZ', 'T', 'TMUS', 'DIS', 'NFLX', 'CMCSA', 'V', 'MA', 'KO', 'PEP',
    ]

    def load_symbols(self) -> List[str]:
        """Load the study universe from data/marketcap.csv ('Symbol' or 'Ticker' column).

        Fails loudly if the file is missing or unusable. v32: the v31 "fail loudly" error
        was raised INSIDE this method's own try-block, whose catch-all handler logged it
        and returned a hardcoded 20-mega-cap fallback — so a fresh clone silently ran a
        different, survivorship-biased study. There is no silent fallback any more;
        PAIRS_DEMO_UNIVERSE=1 is the explicit, opt-in smoke-test universe.
        """
        path = "data/marketcap.csv"
        if os.path.exists(path):
            marketcap_df = pd.read_csv(path)
            logger.info(f"Loaded {path} with {len(marketcap_df)} rows")
        elif os.environ.get('PAIRS_DEMO_UNIVERSE') == '1':
            logger.warning("PAIRS_DEMO_UNIVERSE=1: using a ~85-symbol smoke-test universe. "
                           "This does NOT reproduce the published Russell 3000 results.")
            marketcap_df = pd.DataFrame({'Symbol': self.DEMO_UNIVERSE})
        else:
            raise FileNotFoundError(
                "data/marketcap.csv not found — this file defines the study universe "
                "(Russell 3000 constituents) and is required to reproduce the published "
                "results. It is not redistributed in this repository.\n"
                "  - Supply your own CSV with a 'Symbol' (or 'Ticker') column at "
                "data/marketcap.csv, or\n"
                "  - set PAIRS_DEMO_UNIVERSE=1 for a smoke-test run that exercises the "
                "pipeline but does NOT reproduce the published numbers.\n"
                "Run from the repository root: the path is resolved relative to the "
                "current working directory."
            )

        symbol_column = next((c for c in ['Symbol', 'Ticker', 'symbol', 'ticker', 'SYMBOL', 'TICKER']
                              if c in marketcap_df.columns), None)
        if symbol_column is None:
            symbol_column = next((c for c in marketcap_df.columns
                                  if 'symbol' in c.lower() or 'ticker' in c.lower()), None)
        if symbol_column is None:
            raise ValueError(f"No symbol column in {path}. Available columns: {list(marketcap_df.columns)}")
        if symbol_column != 'Symbol':
            marketcap_df = marketcap_df.rename(columns={symbol_column: 'Symbol'})

        initial_count = len(marketcap_df)
        marketcap_df = marketcap_df.dropna(subset=['Symbol'])
        # Class shares: exchanges/index files write BRK.B, Yahoo serves BRK-B.
        marketcap_df['Symbol'] = (marketcap_df['Symbol'].astype(str).str.strip().str.upper()
                                  .str.replace(r'\s+', '', regex=True).str.replace('.', '-', regex=False))
        valid_mask = (
            marketcap_df['Symbol'].str.len().between(1, 6) &
            ~marketcap_df['Symbol'].isin(['NAN', 'NULL', '0']) &
            ~marketcap_df['Symbol'].str.fullmatch(r'[0-9]+', na=False) &
            marketcap_df['Symbol'].str.fullmatch(r'[A-Z0-9.\-]+', na=False)
        )
        marketcap_df = marketcap_df[valid_mask].drop_duplicates(subset=['Symbol'], keep='first')
        symbols = sorted(marketcap_df['Symbol'].tolist())
        if not symbols:
            raise ValueError(f"{path} contains no valid symbols")
        logger.info(f"Universe: {len(symbols)} symbols ({initial_count - len(symbols)} rows removed "
                    f"as missing/invalid/duplicate); sample {symbols[:10]}")
        return symbols

    def fetch_stock_data(self, symbol: str, max_retries: int = 4) -> Optional[pd.DataFrame]:
        """Fetch one symbol's daily OHLCV (auto-adjusted) and compute its indicators.

        v32: exponential backoff with jitter between attempts (Yahoo rate-limit windows
        last seconds to minutes; the old 0.05-0.15 s jitter burned all retries at once),
        a private RNG for the jitter (worker threads no longer consume the seeded global
        RNG), and the outcome recorded per symbol in `self.fetch_manifest`.
        """
        rng = random.Random(hash(symbol) & 0xFFFFFFFF)
        status = 'error'
        for attempt in range(max_retries):
            try:
                if attempt:
                    time.sleep(min(60.0, 2.0 ** attempt) + rng.uniform(0.0, 1.0))
                data = self._download_history(symbol)
                if data.empty:
                    status = 'empty'
                    continue
                if len(data) < 200:
                    status = 'short'
                    break
                if not self._validate_data(data):
                    status = 'invalid'
                    break
                self.successful_count += 1
                self.fetch_manifest[symbol] = 'ok'
                return self._process_indicators(data)
            except Exception as e:
                status = f'error:{type(e).__name__}'
                continue
        self.failed_count += 1
        self.fetch_manifest[symbol] = status
        return None

    CHART_URL = 'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}'

    def _download_history(self, symbol: str) -> pd.DataFrame:
        """Daily history from Yahoo's chart API, shaped like yfinance's
        Ticker.history(auto_adjust=True): Open/High/Low/Close adjusted for splits and
        dividends, Volume split-adjusted, 'Dividends' and 'Stock Splits' event columns, and
        a tz-aware date index in the exchange's timezone (midnight local).

        v32: called directly. yfinance reads this same endpoint but first performs a
        cookie/crumb handshake that Yahoo now rate-limits (HTTP 429 on every call from a
        shared IP), so a full-universe fetch through yfinance failed on every symbol.
        yfinance's optional price repair (repair=True) is not reproduced.
        """
        import requests
        start = int(pd.Timestamp(self.start_date, tz='UTC').timestamp())
        end = int(pd.Timestamp(self._fetch_end(), tz='UTC').timestamp())       # exclusive
        r = requests.get(self.CHART_URL.format(symbol=requests.utils.quote(symbol, safe='')),
                         params={'period1': start, 'period2': end, 'interval': '1d',
                                 'events': 'div,splits', 'includeAdjustedClose': 'true'},
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        if r.status_code == 404:
            return pd.DataFrame()
        r.raise_for_status()
        result = (r.json().get('chart') or {}).get('result') or []
        if not result or not result[0].get('timestamp'):
            return pd.DataFrame()
        res = result[0]
        tz = (res.get('meta') or {}).get('exchangeTimezoneName') or 'America/New_York'
        idx = pd.to_datetime(res['timestamp'], unit='s', utc=True).tz_convert(tz).normalize()
        q = res['indicators']['quote'][0]
        df = pd.DataFrame({c.capitalize(): pd.to_numeric(pd.Series(q.get(c)), errors='coerce').to_numpy()
                           for c in ('open', 'high', 'low', 'close', 'volume')}, index=idx)
        adj = (res['indicators'].get('adjclose') or [{}])[0].get('adjclose')
        if adj is not None:
            adj = pd.to_numeric(pd.Series(adj), errors='coerce').to_numpy()
            ratio = adj / df['Close'].to_numpy()
            for c in ('Open', 'High', 'Low'):
                df[c] = df[c].to_numpy() * ratio
            df['Close'] = adj
        df['Dividends'] = 0.0
        df['Stock Splits'] = 0.0
        events = res.get('events') or {}
        for ev in (events.get('dividends') or {}).values():
            d = pd.Timestamp(ev['date'], unit='s', tz='UTC').tz_convert(tz).normalize()
            if d in df.index:
                df.loc[d, 'Dividends'] = float(ev.get('amount') or 0.0)
        for ev in (events.get('splits') or {}).values():
            d = pd.Timestamp(ev['date'], unit='s', tz='UTC').tz_convert(tz).normalize()
            num, den = float(ev.get('numerator') or 0), float(ev.get('denominator') or 0)
            if d in df.index and num > 0 and den > 0:
                df.loc[d, 'Stock Splits'] = num / den
        df = df[~df.index.duplicated(keep='last')]
        has_price = df[['Open', 'High', 'Low', 'Close']].notna().any(axis=1)
        has_event = (df['Dividends'] != 0) | (df['Stock Splits'] != 0)
        df = df[has_price | has_event]
        df['Volume'] = df['Volume'].fillna(0.0)
        df.index.name = 'Date'
        return df

    def _fetch_end(self) -> str:
        """yfinance treats `end` as EXCLUSIVE; fetch through end_date inclusive."""
        return str((pd.Timestamp(self.end_date) + pd.Timedelta(days=1)).date())

    @staticmethod
    def future_split_factor(data: pd.DataFrame) -> pd.Series:
        """Product of split ratios strictly AFTER each date (1.0 if no later split).

        yfinance back-adjusts every earlier bar for a split, so for dates before a 10:1
        split the cached Close is the traded price / 10 and Volume is traded shares x 10.
        Multiplying Close (dividing Volume) by this factor recovers the point-in-time
        values a trader actually saw. Splits after the fetched date range are not in the
        data and cannot be undone here (documented limitation). Dividends are NOT undone:
        with auto_adjust=True the cached closes are also dividend-adjusted, so a
        "point-in-time" price is still lowered by the cumulative yield of later dividends
        (a few percent a year for high-yield names) — a small, disclosed residual in the
        $5 price and dollar-volume screens.
        """
        if 'Stock Splits' not in data.columns or len(data) == 0:
            return pd.Series(1.0, index=data.index)
        ratio = pd.to_numeric(data['Stock Splits'], errors='coerce').fillna(0.0)
        ratio = ratio.where(ratio > 0, 1.0)
        after = ratio.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)
        return after

    def _validate_data(self, data: pd.DataFrame) -> bool:
        """Validate data quality with more lenient criteria"""
        try:
            if 'Close' not in data.columns:
                return False

            close_prices = data['Close']

            if (close_prices <= 0).any() or close_prices.isnull().sum() > len(data) * 0.15:
                return False

            # v31 (audit): SURVIVORSHIP FIX. This was `close_prices.min() < 2.0` over the
            # ENTIRE 2020-2025 sample, so a symbol that fell below $2 at any point — a
            # 2024 collapse, say — was deleted from the universe retroactively, including
            # for 2020-2022 when it was a perfectly ordinary stock. That removes future
            # losers from past pair selection, which flatters every backtest that selects
            # on this universe.
            # A penny-stock screen is legitimate, but it must use information available at
            # selection time. Screen on the START of the series instead of its minimum.
            # v32: on the POINT-IN-TIME price. Back-adjusted prices divide pre-split history by
            # later split ratios, so a $19 stock that split 10:1 in 2024 showed ~$1.90 in 2020
            # and was screened out because of a future corporate action.
            _pit = (close_prices * self.future_split_factor(data)).dropna()
            _early = _pit.iloc[:21]
            if len(_early) == 0 or float(_early.median()) < 2.0:
                return False

            return True
        except Exception:
            return False

    def _process_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Process with key technical indicators"""
        try:
            processed = data.copy()

            _f = self.future_split_factor(processed)
            processed['Close_PIT'] = processed['Close'] * _f
            if 'Volume' in processed.columns:
                processed['Volume_PIT'] = processed['Volume'] / _f
            # Return-type columns are computed on a LOCAL forward-filled close, so a missing
            # close gives a 0 return on the gap day and the true move across the gap on the
            # next valid day (the raw Close column itself stays unfilled). Computing them on
            # the raw close left NaNs that the derived-column ffill below then replaced with
            # copies of the previous day's return, inventing moves.
            _close = processed['Close'].ffill()
            processed['Returns'] = _close.pct_change(fill_method=None)
            processed['Log_Returns'] = np.log(_close / _close.shift(1))

            for period in [5, 10, 20, 50]:
                # v31 (audit): min_periods=1 so the warm-up is a CAUSAL partial average
                # (the mean of however many bars exist so far) rather than NaN. With the
                # old min_periods=int(period*0.7) the head was NaN and then got .bfill()ed
                # with a future value; simply dropping the bfill would instead leave a
                # price-level column filled with the neutral 0, which blows up derived
                # terms like Trend_Strength = |MA_20 - MA_50| / std. A partial average is
                # both leak-free and dimensionally correct.
                processed[f'MA_{period}'] = processed['Close'].rolling(window=period, min_periods=1).mean()
                processed[f'EMA_{period}'] = processed['Close'].ewm(span=period).mean()

            for period in [14, 21]:
                processed[f'RSI_{period}'] = self._calculate_rsi(processed['Close'], period)

            sma_20 = processed['Close'].rolling(window=20, min_periods=14).mean()
            std_20 = processed['Close'].rolling(window=20, min_periods=14).std()
            processed['BB_Upper'] = sma_20 + (std_20 * 2)
            processed['BB_Lower'] = sma_20 - (std_20 * 2)
            processed['BB_Position'] = (processed['Close'] - processed['BB_Lower']) / (processed['BB_Upper'] - processed['BB_Lower'] + 1e-8)

            for period in [10, 20, 50]:
                processed[f'Volatility_{period}'] = processed['Returns'].rolling(window=period, min_periods=int(period*0.7)).std() * np.sqrt(252)

            if 'Volume' in processed.columns:
                processed['Volume_MA'] = processed['Volume'].rolling(window=20, min_periods=14).mean()
                processed['Volume_Ratio'] = processed['Volume'] / (processed['Volume_MA'] + 1e-8)
            else:
                processed['Volume_MA'] = 1e6
                processed['Volume_Ratio'] = 1

            for period in [1, 5, 10, 20]:
                processed[f'Momentum_{period}'] = _close.pct_change(periods=period, fill_method=None)

            vol_20 = processed['Volatility_20']
            processed['High_Vol_Regime'] = (vol_20 > vol_20.rolling(window=200, min_periods=100).quantile(0.7)).astype(int)
            processed['Trend_Strength'] = abs(processed['MA_20'] - processed['MA_50']) / (processed['Close'].rolling(20).std() + 1e-8)

            # v32: fill only DERIVED indicator columns. Through v31 this loop also rewrote the
            # raw OHLCV columns: a leading missing Close became 0 and gaps became stale
            # prices, contradicting the "untouched vendor data" premise of the reprocess path.
            protected = set(self._RAW_COLUMNS) | {'Close_PIT', 'Volume_PIT'}
            numeric_columns = [c for c in processed.select_dtypes(include=[np.number]).columns
                               if c not in protected]
            for col in numeric_columns:
                # Neutral prior for this indicator family, used for the warm-up region
                # where the rolling window genuinely has no information yet.
                if 'RSI' in col:
                    _neutral = 50
                elif 'Volatility' in col:
                    _neutral = 0.2
                elif 'BB_Position' in col:
                    _neutral = 0.5
                else:
                    _neutral = 0

                if processed[col].isnull().sum() > len(processed) * 0.5:
                    processed[col] = _neutral
                else:
                    # v31 (audit): LOOK-AHEAD FIX — dropped `.bfill()`. Back-filling copies
                    # the first VALID indicator value backwards over the whole warm-up
                    # region, so e.g. MA_50's first 34 rows were filled with a mean
                    # computed from days 35-50 — future data at those timestamps. Every
                    # rolling indicator here (MA/EMA/RSI/Volatility/BB/Trend) had a
                    # future-contaminated head, and the walk-forward windows that start
                    # earliest are the ones most affected. Forward-fill only, then seed
                    # the remaining leading gap with a neutral constant.
                    processed[col] = processed[col].ffill().fillna(_neutral)

            return processed

        except Exception as e:
            logger.debug(f"Error processing indicators: {str(e)}")
            return data

    def _calculate_rsi(self, prices: pd.Series, window: int = 14) -> pd.Series:
        """Calculate RSI with better error handling"""
        try:
            delta = prices.diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)

            avg_gain = gain.rolling(window=window, min_periods=int(window*0.7)).mean()
            avg_loss = loss.rolling(window=window, min_periods=int(window*0.7)).mean()

            rs = avg_gain / (avg_loss + 1e-10)
            rsi = 100 - (100 / (1 + rs))

            return rsi.fillna(50)
        except Exception:
            return pd.Series(50, index=prices.index)

    @staticmethod
    def _atomic_pickle(obj, path: str) -> None:
        """Write a pickle atomically (temp file in the same directory, then os.replace)."""
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        tmp = f"{path}.tmp-{os.getpid()}"
        with open(tmp, 'wb') as f:
            pickle.dump(obj, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    @staticmethod
    def _load_pickle_or_raise(path: str):
        """Load a cache file, failing LOUDLY rather than silently refetching over it.

        v32: an unreadable cache used to fall through to a fresh fetch that then wrote
        over the same path — destroying a study cache that cannot be rebuilt (it holds
        names Yahoo no longer serves and a fixed adjustment vintage). Only local caches
        you created yourself should ever be loaded: pickle can execute code (SECURITY.md).
        """
        try:
            with open(path, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            raise RuntimeError(
                f"Could not read the cache {path} ({type(e).__name__}: {e}). It was NOT "
                "overwritten. If it was written by a different pandas/numpy version, load it "
                "with that environment (see requirements.txt); to rebuild from Yahoo "
                "instead, move the file aside and re-run.") from e

    def load_macro_data(self) -> Dict:
        """VIX and sector-ETF closes for the regime gate and macro features.

        Returns {'VIX': Series, 'sectors': {etf: Series}} with tz-naive indexes, cached in
        data/macro_data.pkl. v32: the cache is written only when VIX and every sector ETF
        were fetched — a failed fetch used to be cached permanently as empty, which
        silently switched the regime gate off (missing VIX defaults to "calm").
        """
        macro_file = "data/macro_data.pkl"
        if os.path.exists(macro_file):
            macro = self._load_pickle_or_raise(macro_file)
            n_sec = len(macro.get('sectors', {}))
            logger.info(f"Loaded cached macro data: VIX ({len(macro.get('VIX', []))} days) + "
                        f"{n_sec} sector ETFs")
            missing = [e for e in SECTOR_ETFS if e not in macro.get('sectors', {})]
            if macro.get('VIX') is None or len(macro.get('VIX', [])) == 0 or missing:
                logger.warning(f"Macro cache is incomplete (VIX present: "
                               f"{len(macro.get('VIX', [])) > 0}; missing sector ETFs: {missing}). "
                               "The regime gate treats missing days as calm.")
            return macro

        logger.info(f"Fetching macro data: {MACRO_TICKERS}")
        macro = {'VIX': pd.Series(dtype=float), 'sectors': {}}
        rng = random.Random(0)
        for ticker in MACRO_TICKERS:
            for attempt in range(4):
                try:
                    if attempt:
                        time.sleep(min(60.0, 2.0 ** attempt) + rng.uniform(0.0, 1.0))
                    data = self._download_history(ticker)
                    if data.empty:
                        continue
                    close = data['Close'].dropna()
                    if getattr(close.index, 'tz', None) is not None:
                        close.index = close.index.tz_localize(None)
                    if ticker == '^VIX':
                        macro['VIX'] = close
                    else:
                        macro['sectors'][ticker] = close
                    logger.info(f"  {ticker}: {len(close)} days ({close.index[0].date()} -> {close.index[-1].date()})")
                    break
                except Exception as e:
                    logger.warning(f"Fetch {ticker} attempt {attempt + 1} failed: {e}")
        missing = [e for e in SECTOR_ETFS if e not in macro['sectors']]
        if len(macro['VIX']) and not missing:
            self._atomic_pickle(macro, macro_file)
            logger.info(f"Macro data cached to {macro_file}")
        else:
            logger.error(f"Macro fetch incomplete (VIX: {len(macro['VIX'])} days; missing: {missing}) — "
                         "NOT cached; the regime gate will treat missing days as calm for this run.")
        return macro

    # Columns that come straight from the data vendor. Everything else in a cached frame
    # is derived by _process_indicators and can be safely recomputed from these.
    _RAW_COLUMNS = ('Open', 'High', 'Low', 'Close', 'Volume',
                    'Dividends', 'Stock Splits', 'Repaired?')

    def _reprocess_cached_indicators(self, saved_data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """Recompute derived indicators from the cached raw OHLCV.

        v31 (audit): the price cache stores *processed* frames, so indicator columns
        written by an older, buggy `_process_indicators` persist across runs — a fix to
        that function would otherwise be silently inert for anyone with a warm cache.
        Concretely: the shipped cache was built when `_process_indicators` ended with
        `.ffill().bfill()`, which back-filled future values across every rolling
        indicator's warm-up region (cached MA_50 begins with 34 identical rows computed
        from days 35-50). Recomputing from the raw OHLCV makes the look-ahead fix effective
        without a multi-hour refetch. Caveat: in a cache built before v32 the raw OHLCV is
        NOT untouched vendor data — the old fill loop also forward-filled prices on rows
        where the vendor returned none — and those rows remain until the cache is re-fetched.

        Set PAIRS_SKIP_REPROCESS=1 to load the cache verbatim (e.g. to reproduce an
        older published run bit-for-bit).
        """
        if os.environ.get('PAIRS_SKIP_REPROCESS') == '1':
            logger.warning("PAIRS_SKIP_REPROCESS=1: using cached indicator columns as-is "
                           "(these may carry the pre-v31 bfill look-ahead)")
            return saved_data

        out, reprocessed, skipped = {}, 0, 0
        for sym, df in saved_data.items():
            try:
                raw_cols = [c for c in self._RAW_COLUMNS if c in df.columns]
                if 'Close' not in raw_cols:
                    out[sym] = df
                    skipped += 1
                    continue
                out[sym] = self._process_indicators(df[raw_cols].copy())
                reprocessed += 1
            except Exception:
                out[sym] = df
                skipped += 1
        logger.info(f"Recomputed indicators from cached OHLCV for {reprocessed} symbols "
                    f"({skipped} left as-is) — removes the pre-v31 bfill look-ahead")
        return out

    MIN_FETCH_COVERAGE = 0.90

    MIN_PRE_V32_CACHED_FRACTION = 0.5

    def _check_cache_coverage(self, wanted, cached) -> None:
        """Apply the fetch-coverage rule to a cache that is being LOADED, not only fetched.

        A partial fetch accepted once with PAIRS_ALLOW_PARTIAL_FETCH=1 (or a demo-universe
        fetch) is written to the cache; without this check every later run would reuse it
        silently, with no switch set and nothing in its provenance. Coverage comes from the
        fetch manifest written together with the cache: a universe symbol counts as covered
        if its fetch succeeded and it is in the cache, or if it was deliberately excluded
        ('short' history / 'invalid' data). A manifest that does not describe this cache
        (a different symbol set) is ignored with a warning.

        A cache without a manifest predates v32: its coverage in this sense is unknown,
        because v31 also dropped symbols on purpose. The fraction of the universe it holds is
        recorded as provenance, and only a cache holding less than half the universe (e.g.
        an old demo-universe cache) is refused.
        """
        allow = os.environ.get('PAIRS_ALLOW_PARTIAL_FETCH') == '1'
        cached = set(cached)
        wanted = set(wanted)
        self.universe_cached_fraction = len(cached & wanted) / len(wanted) if wanted else None
        manifest_path = self.data_file.replace('.pkl', '_manifest.json')
        present = os.path.exists(manifest_path)
        manifest = None
        if present:
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
            except (OSError, ValueError):
                manifest = None                # present but unreadable: rejected below
            cs = manifest.get('cached_symbols') if isinstance(manifest, dict) else None
            if not (isinstance(manifest, dict) and isinstance(manifest.get('outcomes', {}), dict)
                    and (cs is None or (isinstance(cs, list) and all(isinstance(x, str) for x in cs)))):
                # fail closed with a clear message: ignoring it would drop to the weaker
                # pre-v32 rule and could accept a partial cache
                raise RuntimeError(
                    f"{manifest_path} is not a fetch manifest written by this system. Delete the "
                    "cache and its manifest to re-fetch, or delete only the manifest to load the "
                    "cache as a pre-v32 cache (coverage unknown).")
        outcomes = (manifest.get('outcomes') or None) if present else None
        if outcomes is not None:
            described = set(manifest.get('cached_symbols') or
                            [k for k, v in outcomes.items() if v == 'ok'])
            if described != cached:
                logger.warning(f"{manifest_path} does not describe this cache ({len(described)} "
                               f"symbols vs {len(cached)} cached); ignoring it — coverage unknown")
                outcomes = None
        if outcomes is None or not wanted:
            self.universe_coverage = None
            frac = self.universe_cached_fraction
            logger.info(f"Price cache coverage unknown (no usable fetch manifest); it holds "
                        f"{frac:.1%} of the universe file" if frac is not None else
                        "Price cache coverage unknown (no usable fetch manifest)")
            if frac is not None and frac < self.MIN_PRE_V32_CACHED_FRACTION and not allow:
                raise RuntimeError(
                    f"The price cache holds only {frac:.1%} of the universe file and has no fetch "
                    "manifest: it cannot be the study cache (an old demo-universe or partial "
                    "cache?). Delete it to re-fetch, or set PAIRS_ALLOW_PARTIAL_FETCH=1 to run "
                    "on it as a sensitivity variant.")
            return
        bad = sum(1 for s in wanted
                  if outcomes.get(s) not in ('short', 'invalid')
                  and not (outcomes.get(s) == 'ok' and s in cached))
        self.universe_coverage = 1.0 - bad / len(wanted)
        if self.universe_coverage < self.MIN_FETCH_COVERAGE and not allow:
            raise RuntimeError(
                f"According to its fetch manifest ({manifest_path}), the price cache covers only "
                f"{self.universe_coverage:.1%} of the universe file (threshold "
                f"{self.MIN_FETCH_COVERAGE:.0%}): it was built from a partial or demo-universe "
                "fetch. Delete the cache and its manifest to re-fetch, or set "
                "PAIRS_ALLOW_PARTIAL_FETCH=1 to run on it as a sensitivity variant.")

    def load_or_fetch_data(self, symbols: List[str], max_workers: int = 4) -> Dict[str, pd.DataFrame]:
        """Load the price cache (restricted to `symbols`), or fetch and cache it.

        Symbols are returned in sorted order, so pair orientation and every downstream
        iteration are deterministic (a fetched dict used to follow thread-completion order).
        """
        if os.path.exists(self.data_file):
            logger.info(f"Loading saved data from {self.data_file}")
            saved_data = self._load_pickle_or_raise(self.data_file)
            logger.info(f"Loaded {len(saved_data)} symbols from saved data")
            # v32: the universe file defines the universe. Through v31 a cache was used
            # verbatim and `symbols` was ignored, so marketcap.csv had no effect at all
            # whenever the cache existed.
            wanted = set(symbols)
            subset = {s: saved_data[s] for s in sorted(saved_data) if s in wanted}
            if len(subset) < len(saved_data):
                logger.info(f"Restricted the cache to the universe file: {len(subset)} of "
                            f"{len(saved_data)} cached symbols are in the universe")
            if len(wanted) > len(subset):
                logger.info(f"{len(wanted) - len(subset)} universe symbols have no cached prices "
                            "(failed or never fetched) and are excluded")
            self._check_cache_coverage(wanted, saved_data.keys())
            return self._reprocess_cached_indicators(subset)

        logger.info(f"Fetching fresh data for {len(symbols)} symbols")
        results = {}
        with tqdm(total=len(symbols), desc="Fetching data", unit="symbol") as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_symbol = {executor.submit(self.fetch_stock_data, s): s for s in symbols}
                for future in concurrent.futures.as_completed(future_to_symbol):
                    symbol = future_to_symbol[future]
                    try:
                        data = future.result()
                        if data is not None:
                            results[symbol] = data
                    except Exception as e:
                        self.fetch_manifest[symbol] = f'error:{type(e).__name__}'
                    pbar.update(1)
                    pbar.set_postfix({'ok': len(results)})
        results = dict(sorted(results.items()))
        attempted = len(symbols)
        errors = sum(1 for v in self.fetch_manifest.values() if v.startswith('error') or v == 'empty')
        coverage = 1.0 - errors / attempted if attempted else 0.0
        self.universe_coverage = coverage
        logger.info(f"Fetched {len(results)}/{attempted} symbols; {errors} fetch errors/empties "
                    f"({coverage:.1%} fetch coverage); manifest outcome counts: "
                    f"{dict(pd.Series(list(self.fetch_manifest.values())).value_counts()) if self.fetch_manifest else {}}")
        manifest_path = self.data_file.replace('.pkl', '_manifest.json')
        manifest = {'start': self.start_date, 'end': self.end_date,
                    'fetched_at': pd.Timestamp.now(tz='UTC').isoformat(),
                    'yfinance_version': getattr(yf, '__version__', 'unknown'),
                    'cached_symbols': sorted(results),
                    'outcomes': dict(sorted(self.fetch_manifest.items()))}
        if coverage < self.MIN_FETCH_COVERAGE and os.environ.get('PAIRS_ALLOW_PARTIAL_FETCH') != '1':
            if os.path.exists(manifest_path):
                os.remove(manifest_path)       # no cache exists, so any manifest here is stale
            raise RuntimeError(
                f"Only {coverage:.1%} of symbols fetched without error (threshold "
                f"{self.MIN_FETCH_COVERAGE:.0%}) — most likely Yahoo rate limiting. The partial "
                "data was NOT cached, because a partial universe silently changes the study. "
                "Re-run later, or set PAIRS_ALLOW_PARTIAL_FETCH=1 to accept it.")
        if results:
            # the manifest describes exactly this cache: staged first, renamed after the cache
            os.makedirs(os.path.dirname(manifest_path) or '.', exist_ok=True)
            tmp_manifest = f"{manifest_path}.tmp-{os.getpid()}"
            with open(tmp_manifest, 'w') as f:
                json.dump(manifest, f, indent=1)
            self._atomic_pickle(results, self.data_file)
            os.replace(tmp_manifest, manifest_path)
            logger.info(f"Price cache written to {self.data_file} (manifest: {manifest_path})")
            self.universe_cached_fraction = len(results) / attempted if attempted else None
        return results
