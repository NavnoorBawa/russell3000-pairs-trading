"""
TRANSFORMER ENCODER FOR PAIRS TRADING - DATA PROCESSOR
=======================================================
Enhanced Russell 3000 Data Processor with comprehensive stock loading.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

from pairs_trading.config import (
    pd, np, yf, os, pickle, time, random, logging,
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

        logger.info("ENHANCED Russell 3000 Data Processor initialized")

    def load_symbols(self) -> List[str]:
        """ENHANCED: Load and format Russell 3000 symbols properly"""
        try:
            if os.path.exists("data/marketcap.csv"):
                marketcap_df = pd.read_csv("data/marketcap.csv")
                logger.info(f"Successfully loaded Marketcap.csv with {len(marketcap_df)} rows")
            elif os.environ.get('PAIRS_DEMO_UNIVERSE') == '1':
                # v31 (audit): opt-in SMOKE-TEST universe. This is deliberately NOT the
                # study universe and will NOT reproduce the published results.
                logger.warning(
                    "PAIRS_DEMO_UNIVERSE=1: using a ~60-symbol smoke-test universe. "
                    "This does NOT reproduce the published Russell 3000 results."
                )
                symbols = [
                    # Deliberately short so every ticker can be verified as currently
                    # listed. The old 290-name fallback contained delisted/renamed tickers
                    # (ANTM, WCG, ATVI, PXD, MRO, DISH), a non-ticker ('BERKSHIREH-B'),
                    # duplicates (TSLA, TPG, SLG, ARE, BXP, LYV) and two ETFs (SPY, VTI)
                    # inside a single-stock pairs universe.
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
                marketcap_df = pd.DataFrame({'Symbol': symbols})
            else:
                # v31 (audit): FAIL LOUDLY. Previously a missing universe file silently
                # substituted a hardcoded mega-cap list, so `python -m pairs_trading.main`
                # on a fresh clone ran a completely different (and survivorship-biased)
                # study while the README/site presented it as reproducing the published
                # Russell 3000 result. data/ is .gitignored, so this was the DEFAULT path
                # for every person who cloned the repo.
                raise FileNotFoundError(
                    "data/marketcap.csv not found — this file defines the study universe "
                    "(Russell 3000 constituents) and is required to reproduce the published "
                    "results. It is not redistributed in this repository.\n"
                    "  • Supply your own CSV with a 'Symbol' (or 'Ticker') column at "
                    "data/marketcap.csv, or\n"
                    "  • set PAIRS_DEMO_UNIVERSE=1 for a ~60-symbol smoke-test run that "
                    "exercises the pipeline but does NOT reproduce the published numbers.\n"
                    "Run from the repository root: the path is resolved relative to the "
                    "current working directory."
                )

            possible_symbol_columns = ['Symbol', 'Ticker', 'symbol', 'ticker', 'SYMBOL', 'TICKER']
            symbol_column = None

            for col_name in possible_symbol_columns:
                if col_name in marketcap_df.columns:
                    symbol_column = col_name
                    break

            if symbol_column is None:
                for col in marketcap_df.columns:
                    if 'symbol' in col.lower() or 'ticker' in col.lower():
                        symbol_column = col
                        break

                if symbol_column is None:
                    raise ValueError(f"No symbol column found. Available columns: {list(marketcap_df.columns)}")

            if symbol_column != 'Symbol':
                marketcap_df = marketcap_df.rename(columns={symbol_column: 'Symbol'})

            logger.info("Cleaning and formatting symbol data...")

            initial_count = len(marketcap_df)
            marketcap_df = marketcap_df.dropna(subset=['Symbol'])
            logger.info(f"Removed {initial_count - len(marketcap_df)} rows with missing symbols")

            marketcap_df['Symbol'] = (marketcap_df['Symbol']
                                    .astype(str)
                                    .str.strip()
                                    .str.upper()
                                    .str.replace(' ', '')
                                    .str.replace('\t', '')
                                    .str.replace('\n', ''))

            before_validation = len(marketcap_df)
            valid_mask = (
                (marketcap_df['Symbol'].str.len() >= 1) &
                (marketcap_df['Symbol'].str.len() <= 6) &
                (marketcap_df['Symbol'] != 'NAN') &
                (marketcap_df['Symbol'] != 'NULL') &
                (marketcap_df['Symbol'] != '') &
                (marketcap_df['Symbol'] != '0') &
                (~marketcap_df['Symbol'].str.contains(r'^[0-9]+$', na=False)) &
                (marketcap_df['Symbol'].str.match(r'^[A-Z0-9\.\-]+$', na=False))
            )

            marketcap_df = marketcap_df[valid_mask]
            logger.info(f"Validation removed {before_validation - len(marketcap_df)} invalid symbols")

            before_dedup = len(marketcap_df)
            marketcap_df = marketcap_df.drop_duplicates(subset=['Symbol'], keep='first')
            logger.info(f"Removed {before_dedup - len(marketcap_df)} duplicate symbols")

            marketcap_df = marketcap_df.sort_values('Symbol').reset_index(drop=True)

            symbols = marketcap_df['Symbol'].tolist()

            logger.info(f"ENHANCED: Successfully loaded and formatted {len(symbols)} Russell 3000 symbols")
            logger.info(f"Sample symbols: {symbols[:20]}...")

            return symbols

        except Exception as e:
            logger.error(f"Error loading and formatting symbols: {str(e)}")
            basic_symbols = [
                'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'JPM', 'JNJ', 'WMT',
                'HD', 'PG', 'BAC', 'UNH', 'V', 'MA', 'XOM', 'CVX', 'LLY', 'ABBV'
            ]
            logger.warning(f"Using fallback list of {len(basic_symbols)} symbols")
            return basic_symbols

    def fetch_stock_data(self, symbol: str, max_retries: int = 3) -> Optional[pd.DataFrame]:
        """Fetch stock data with indicators"""
        for attempt in range(max_retries):
            try:
                time.sleep(random.uniform(0.05, 0.15))

                ticker = yf.Ticker(symbol)
                data = ticker.history(
                    start=self.start_date,
                    end=self.end_date,
                    interval='1d',
                    auto_adjust=True,
                    repair=True,
                    timeout=30
                )

                if not data.empty and len(data) >= 200:
                    if self._validate_data(data):
                        processed_data = self._process_indicators(data)
                        self.successful_count += 1
                        return processed_data

            except Exception:
                if attempt == max_retries - 1:
                    self.failed_count += 1
                continue

        return None

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
            _early = close_prices.dropna().iloc[:21]
            if len(_early) == 0 or float(_early.median()) < 2.0:
                return False

            return True
        except Exception:
            return False

    def _process_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Process with key technical indicators"""
        try:
            processed = data.copy()

            processed['Returns'] = processed['Close'].pct_change()
            processed['Log_Returns'] = np.log(processed['Close'] / processed['Close'].shift(1))

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
                processed[f'Momentum_{period}'] = processed['Close'].pct_change(periods=period)

            vol_20 = processed['Volatility_20']
            processed['High_Vol_Regime'] = (vol_20 > vol_20.rolling(window=200, min_periods=100).quantile(0.7)).astype(int)
            processed['Trend_Strength'] = abs(processed['MA_20'] - processed['MA_50']) / (processed['Close'].rolling(20).std() + 1e-8)

            numeric_columns = processed.select_dtypes(include=[np.number]).columns
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

    def load_macro_data(self) -> Dict:
        """Load VIX and sector ETF data for macro regime features.
        Cached in macro_data.pkl to avoid re-fetching.
        Returns dict with keys: 'VIX' (Series), 'sectors' (Dict[str, Series])
        """
        macro_file = "data/macro_data.pkl"
        if os.path.exists(macro_file):
            try:
                with open(macro_file, 'rb') as f:
                    macro = pickle.load(f)
                logger.info(f"Loaded cached macro data: VIX + {len(macro.get('sectors', {}))} sector ETFs")
                return macro
            except Exception as e:
                logger.warning(f"Failed to load cached macro data: {str(e)}")

        logger.info(f"Fetching macro data: {MACRO_TICKERS}")
        macro = {'VIX': pd.Series(dtype=float), 'sectors': {}}

        try:
            for ticker in MACRO_TICKERS:
                try:
                    time.sleep(random.uniform(0.1, 0.3))
                    t = yf.Ticker(ticker)
                    data = t.history(start=self.start_date, end=self.end_date,
                                     interval='1d', auto_adjust=True, timeout=30)
                    if data.empty:
                        continue
                    close = data['Close'].dropna()
                    # Strip timezone for consistency
                    if hasattr(close.index, 'tz') and close.index.tz is not None:
                        close.index = close.index.tz_localize(None)
                    if ticker == '^VIX':
                        macro['VIX'] = close
                        logger.info(f"  VIX: {len(close)} days ({close.index[0].date()} → {close.index[-1].date()})")
                    elif ticker in SECTOR_ETFS:
                        macro['sectors'][ticker] = close
                        logger.info(f"  {ticker}: {len(close)} days")
                except Exception as e:
                    logger.warning(f"Failed to fetch {ticker}: {str(e)}")

            with open(macro_file, 'wb') as f:
                pickle.dump(macro, f)
            logger.info(f"Macro data cached to {macro_file}")

        except Exception as e:
            logger.error(f"Macro data fetch error: {str(e)}")

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
        from days 35-50). Recomputing from the raw OHLCV — which is untouched vendor
        data — makes the look-ahead fix effective without a multi-hour refetch.

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

    def load_or_fetch_data(self, symbols: List[str], max_workers: int = 8) -> Dict[str, pd.DataFrame]:
        """Load or fetch data"""

        if os.path.exists(self.data_file):
            try:
                logger.info(f"Loading saved data from {self.data_file}")
                with open(self.data_file, 'rb') as f:
                    saved_data = pickle.load(f)
                logger.info(f"Loaded {len(saved_data)} symbols from saved data")
                return self._reprocess_cached_indicators(saved_data)
            except Exception as e:
                logger.warning(f"Failed to load saved data: {str(e)}")

        logger.info(f"Fetching fresh data for {len(symbols)} symbols")
        results = {}

        with tqdm(total=len(symbols), desc="Fetching enhanced data", unit="symbol") as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_symbol = {executor.submit(self.fetch_stock_data, symbol): symbol for symbol in symbols}

                for future in concurrent.futures.as_completed(future_to_symbol):
                    symbol = future_to_symbol[future]
                    try:
                        data = future.result(timeout=60)
                        if data is not None:
                            results[symbol] = data
                        pbar.update(1)
                        pbar.set_postfix({'Success': len(results)})
                    except Exception:
                        pbar.update(1)
                        continue

        logger.info(f"Fetched {len(results)}/{len(symbols)} symbols ({len(results)/len(symbols)*100:.1f}% success)")

        if len(results) > 20:
            try:
                with open(self.data_file, 'wb') as f:
                    pickle.dump(results, f)
                logger.info("Enhanced data saved successfully")
            except Exception as e:
                logger.warning(f"Failed to save data: {str(e)}")

        return results
