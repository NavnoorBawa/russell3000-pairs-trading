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
            else:
                logger.warning("Marketcap.csv not found, using comprehensive Russell 3000 fallback")
                symbols = [
                    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO', 'ORCL',
                    'CRM', 'ADBE', 'NOW', 'INTC', 'AMD', 'QCOM', 'TXN', 'MU', 'AMAT', 'LRCX',
                    'MRVL', 'ADI', 'KLAC', 'CDNS', 'SNPS', 'FTNT', 'TEAM', 'WDAY', 'DDOG', 'CRWD',
                    'ZS', 'NET', 'SNOW', 'PLTR', 'OKTA', 'ZM', 'DOCU', 'TWLO', 'SHOP', 'SQ',
                    'JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'AXP', 'BLK', 'SCHW', 'SPGI',
                    'MCO', 'CME', 'ICE', 'NDAQ', 'CBOE', 'COF', 'DFS', 'SYF', 'TROW', 'BEN',
                    'PNC', 'USB', 'TFC', 'MTB', 'FITB', 'HBAN', 'RF', 'KEY', 'CFG', 'ZION',
                    'WRB', 'AON', 'MMC', 'AJG', 'BRO', 'PGR', 'TRV', 'ALL', 'AIG', 'MET',
                    'UNH', 'JNJ', 'PFE', 'ABT', 'TMO', 'DHR', 'MRK', 'ABBV', 'LLY', 'BMY',
                    'AMGN', 'GILD', 'VRTX', 'REGN', 'BIIB', 'ILMN', 'MRNA', 'BNTX', 'ZTS', 'ELV',
                    'CVS', 'CI', 'HUM', 'ANTM', 'CNC', 'MOH', 'WCG', 'VEEV', 'ISRG', 'SYK',
                    'BSX', 'MDT', 'EW', 'HOLX', 'RMD', 'IQV', 'DXCM', 'ALGN', 'IDXX', 'MTD',
                    'WMT', 'HD', 'COST', 'TGT', 'LOW', 'TJX', 'SBUX', 'MCD', 'NKE', 'LULU',
                    'EBAY', 'ETSY', 'W', 'CHWY', 'PETS', 'BBY', 'GPS', 'M', 'KSS', 'JWN',
                    'DG', 'DLTR', 'ROST', 'ULTA', 'TPG', 'F', 'GM', 'TSLA', 'RIVN', 'LCID',
                    'DIS', 'NFLX', 'CMCSA', 'WBD', 'PARA', 'LYV', 'ROKU', 'SPOT', 'MTCH', 'BMBL',
                    'XOM', 'CVX', 'COP', 'EOG', 'SLB', 'MPC', 'VLO', 'PSX', 'OXY', 'DVN',
                    'PXD', 'FANG', 'MRO', 'APA', 'HES', 'HAL', 'BKR', 'NOV', 'KMI', 'OKE',
                    'NEE', 'DUK', 'SO', 'D', 'AEP', 'EXC', 'XEL', 'PEG', 'SRE', 'ES',
                    'WEC', 'ETR', 'AWK', 'ATO', 'CNP', 'CMS', 'EVRG', 'FE', 'NI', 'PNW',
                    'CAT', 'BA', 'GE', 'HON', 'UPS', 'RTX', 'LMT', 'NOC', 'GD', 'MMM',
                    'EMR', 'ETN', 'PH', 'ITW', 'CMI', 'DE', 'FDX', 'CSX', 'UNP', 'NSC',
                    'WM', 'RSG', 'PCAR', 'IR', 'OTIS', 'CARR', 'TDG', 'LHX', 'HWM', 'AOS',
                    'DHI', 'LEN', 'NVR', 'PHM', 'KBH', 'TOL', 'TPG', 'BLD', 'BLDR', 'SSD',
                    'LIN', 'APD', 'ECL', 'SHW', 'DD', 'DOW', 'PPG', 'NEM', 'FCX', 'GOLD',
                    'ALB', 'CE', 'FMC', 'IFF', 'MLM', 'VMC', 'NUE', 'STLD', 'RS', 'X',
                    'AA', 'CENX', 'WY', 'IP', 'PKG', 'CCK', 'BALL', 'SLG', 'BXP', 'ARE',
                    'PLD', 'AMT', 'CCI', 'EQIX', 'PSA', 'EXR', 'AVB', 'EQR', 'DLR', 'WELL',
                    'SPG', 'O', 'CBRE', 'VTR', 'ESS', 'MAA', 'UDR', 'CPT', 'FRT', 'BXP',
                    'HST', 'SLG', 'KRC', 'HIW', 'ARE', 'COLD', 'CUZ', 'FR', 'KIM', 'REG',
                    'VZ', 'T', 'TMUS', 'CHTR', 'LYV', 'NWSA', 'NYT', 'DISH', 'SIRI', 'IPG',
                    'OMC', 'TTWO', 'EA', 'ATVI', 'RBLX', 'U', 'PATH', 'BILL', 'PYPL', 'V',
                    'MA', 'KO', 'PEP', 'PM', 'MO', 'BRK-B', 'BERKSHIREH-B', 'VTI', 'SPY'
                ]
                marketcap_df = pd.DataFrame({'Symbol': symbols})

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

            if close_prices.min() < 2.0:
                return False

            return True
        except:
            return False

    def _process_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Process with key technical indicators"""
        try:
            processed = data.copy()

            processed['Returns'] = processed['Close'].pct_change()
            processed['Log_Returns'] = np.log(processed['Close'] / processed['Close'].shift(1))

            for period in [5, 10, 20, 50]:
                processed[f'MA_{period}'] = processed['Close'].rolling(window=period, min_periods=int(period*0.7)).mean()
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
                if processed[col].isnull().sum() > len(processed) * 0.5:
                    if 'RSI' in col:
                        processed[col] = 50
                    elif 'Volatility' in col:
                        processed[col] = 0.2
                    elif 'BB_Position' in col:
                        processed[col] = 0.5
                    else:
                        processed[col] = 0
                else:
                    processed[col] = processed[col].ffill().bfill().fillna(0)

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
        except:
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

    def load_or_fetch_data(self, symbols: List[str], max_workers: int = 8) -> Dict[str, pd.DataFrame]:
        """Load or fetch data"""

        if os.path.exists(self.data_file):
            try:
                logger.info(f"Loading saved data from {self.data_file}")
                with open(self.data_file, 'rb') as f:
                    saved_data = pickle.load(f)
                logger.info(f"Loaded {len(saved_data)} symbols from saved data")
                return saved_data
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
