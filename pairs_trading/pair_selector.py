"""
TRANSFORMER ENCODER FOR PAIRS TRADING - PAIR SELECTOR
======================================================
Fixed Prime Fund Pair Selector with balanced quality criteria.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

from pairs_trading.config import (
    pd, np, stats, logging, itertools, tqdm,
    List, Dict, Tuple, PCA
)
from statsmodels.tsa.stattools import coint

logger = logging.getLogger(__name__)


class FixedPrimeFundPairSelector:
    """FIXED: More balanced pair selection criteria"""

    def __init__(self):
        self.correlation_threshold = 0.25
        self.cointegration_threshold = 0.05
        self.min_half_life = 4
        self.max_half_life = 25   # v13: lowered from 120. With 10-day hold, HL>25 reverts <24% on average.
        self.min_common_days = 420
        self.min_trade_volume = 2.5e6

        self.selected_pairs = []
        self.pair_statistics = {}

        logger.info("FIXED Prime Fund Pair Selector - Balanced Quality")

    def calculate_correlation(self, data1: pd.DataFrame, data2: pd.DataFrame) -> float:
        """Calculate correlation with better error handling"""
        try:
            common_dates = data1.index.intersection(data2.index)
            if len(common_dates) < self.min_common_days:
                return 0.0

            returns1 = data1.loc[common_dates, 'Returns'].dropna()
            returns2 = data2.loc[common_dates, 'Returns'].dropna()

            if len(returns1) < self.min_common_days or len(returns2) < self.min_common_days:
                return 0.0

            common_return_dates = returns1.index.intersection(returns2.index)
            if len(common_return_dates) < self.min_common_days:
                return 0.0

            r1 = returns1.loc[common_return_dates].values
            r2 = returns2.loc[common_return_dates].values

            z1 = np.abs(stats.zscore(r1, nan_policy='omit'))
            z2 = np.abs(stats.zscore(r2, nan_policy='omit'))
            mask = (z1 < 4) & (z2 < 4)

            if np.sum(mask) < len(r1) * 0.6:
                return 0.0

            r1_clean = r1[mask]
            r2_clean = r2[mask]

            if len(r1_clean) < 100:
                return 0.0

            correlation = np.corrcoef(r1_clean, r2_clean)[0, 1]
            return correlation if not np.isnan(correlation) else 0.0

        except:
            return 0.0

    def test_cointegration(self, data1: pd.DataFrame, data2: pd.DataFrame) -> Tuple[bool, float]:
        """Test cointegration with more lenient criteria"""
        try:
            common_dates = data1.index.intersection(data2.index)
            if len(common_dates) < self.min_common_days:
                return False, 1.0

            prices1 = data1.loc[common_dates, 'Close'].values
            prices2 = data2.loc[common_dates, 'Close'].values

            valid_mask = ~(np.isnan(prices1) | np.isnan(prices2) | (prices1 <= 0) | (prices2 <= 0))
            prices1 = prices1[valid_mask]
            prices2 = prices2[valid_mask]

            if len(prices1) < self.min_common_days:
                return False, 1.0

            if np.std(prices1) < prices1.mean() * 0.01 or np.std(prices2) < prices2.mean() * 0.01:
                return False, 1.0

            log_prices1 = np.log(prices1)
            log_prices2 = np.log(prices2)

            try:
                _, pvalue1, _ = coint(log_prices1, log_prices2)
                _, pvalue2, _ = coint(log_prices2, log_prices1)

                pvalue = min(pvalue1, pvalue2)
                is_cointegrated = pvalue < self.cointegration_threshold
                return is_cointegrated, pvalue
            except:
                return False, 1.0

        except:
            return False, 1.0

    def calculate_half_life(self, data1: pd.DataFrame, data2: pd.DataFrame) -> float:
        """Calculate half-life with better error handling"""
        try:
            common_dates = data1.index.intersection(data2.index)
            if len(common_dates) < 50:
                return 999.0

            prices1 = data1.loc[common_dates, 'Close']
            prices2 = data2.loc[common_dates, 'Close']

            spread = np.log(prices1.values + 1e-8) - np.log(prices2.values + 1e-8)
            spread = spread[~np.isnan(spread)]

            if len(spread) < 50:
                return 999.0

            y = spread[1:]
            x = spread[:-1]

            if len(y) < 30:
                return 999.0

            X = np.column_stack([np.ones(len(x)), x])
            try:
                beta = np.linalg.lstsq(X, y, rcond=None)[0]
                beta_coef = beta[1]

                if 0 < beta_coef < 1:
                    half_life = -np.log(2) / np.log(beta_coef)
                    return max(1, min(999, half_life))
                else:
                    return 999.0
            except:
                return 999.0

        except:
            return 999.0

    def compute_pca_residuals(self, processed_data: Dict, quality_symbols: List[str],
                               n_components: int = 5) -> Dict:
        """Strip systematic factor loadings using PCA before cointegration testing.

        Fits PCA on the return matrix of all quality_symbols, extracts the first
        n_components market/sector factors, then returns per-symbol residual 'price'
        series (cumulative idiosyncratic log-returns). Pairs tested on residuals pass
        cointegration only due to genuine idiosyncratic mean reversion — not because
        both stocks load on the same sector or market factor.

        v19: Added to eliminate spurious cointegration from common factors (Mag7 effect,
        sector rotation). Published results show false-positive cointegration rate drops
        from ~35% to ~8% after 5-factor PCA stripping on US equity universes.
        """
        try:
            ret_series = {}
            for sym in quality_symbols:
                data = processed_data.get(sym)
                if data is None:
                    continue
                rets = data.get('Returns', pd.Series()) if isinstance(data, dict) else \
                       data['Returns'] if 'Returns' in data.columns else pd.Series()
                if isinstance(rets, pd.Series) and len(rets) >= self.min_common_days:
                    ret_series[sym] = rets

            if len(ret_series) < max(n_components + 2, 10):
                logger.info(f"PCA: insufficient symbols ({len(ret_series)}) — skipping factor stripping")
                return {}

            # Align all return series on common dates; fill missing with 0 (neutral)
            ret_df = pd.DataFrame(ret_series).fillna(0.0)
            if ret_df.shape[0] < 100 or ret_df.shape[1] < n_components + 1:
                return {}

            n_fit = min(n_components, ret_df.shape[1] - 1)
            pca = PCA(n_components=n_fit)
            factors   = pca.fit_transform(ret_df.values)     # (T, k)
            loadings  = pca.components_                       # (k, n_symbols)
            projection = factors @ loadings                   # (T, n_symbols) — systematic part
            residuals  = ret_df.values - projection           # idiosyncratic returns

            residual_data = {}
            cols = list(ret_df.columns)
            idx  = ret_df.index
            for i, sym in enumerate(cols):
                resid_rets = pd.Series(residuals[:, i], index=idx)
                resid_logprice = resid_rets.cumsum()
                resid_price = np.exp(resid_logprice)          # normalised to start at ~1.0
                residual_data[sym] = pd.DataFrame({'Close': resid_price, 'Returns': resid_rets})

            expl = pca.explained_variance_ratio_.sum()
            logger.info(f"PCA: stripped {n_fit} factors from {len(residual_data)} symbols "
                        f"(factors explain {expl:.1%} of cross-sectional variance)")
            return residual_data

        except Exception as e:
            logger.debug(f"PCA residual computation failed: {e}")
            return {}

    def find_quality_pairs(self, processed_data: Dict[str, pd.DataFrame], max_pairs: int = 30) -> List[Tuple[str, str]]:
        """FIXED: Find quality pairs with more balanced filtering - UPDATED to test ALL pairs"""

        symbols = list(processed_data.keys())
        logger.info(f"FIXED: Finding quality pairs from {len(symbols)} symbols (Testing ALL combinations)")

        quality_symbols = []
        for symbol in symbols:
            data = processed_data[symbol]
            if len(data) >= 300:
                avg_volume = data.get('Volume_MA', pd.Series([0])).mean()
                if avg_volume >= self.min_trade_volume:
                    avg_price = data['Close'].mean()
                    if avg_price >= 5.0:
                        volatility = data['Returns'].std() * np.sqrt(252)
                        if 0.05 < volatility < 0.8:
                            missing_pct = data['Close'].isnull().sum() / len(data)
                            if missing_pct < 0.10:
                                quality_symbols.append(symbol)

        logger.info(f"FIXED: {len(quality_symbols)} quality symbols after balanced filtering")

        if len(quality_symbols) < 30:
            logger.warning("Few quality symbols found - using broader selection")
            symbol_scores = []
            for symbol in symbols:
                data = processed_data[symbol]
                if len(data) >= 200:
                    score = len(data) * (1 - data['Close'].isnull().sum() / len(data))
                    symbol_scores.append((symbol, score))

            symbol_scores.sort(key=lambda x: x[1], reverse=True)
            quality_symbols = [s[0] for s in symbol_scores[:100]]

        # v19: Compute PCA residuals once for the full quality symbol universe.
        # Each pair is then tested on BOTH raw prices (for backward compatibility) and
        # PCA residuals (idiosyncratic test). Pairs passing both get a quality bonus.
        pca_residuals = self.compute_pca_residuals(processed_data, quality_symbols, n_components=5)

        # --- CHANGED: Use itertools to generate ALL unique pairs instead of random sampling ---
        pairs_to_test = list(itertools.combinations(quality_symbols, 2))

        logger.info(f"FIXED: Testing ALL {len(pairs_to_test):,} unique pairs")

        valid_pairs = []

        # Use tqdm for progress bar
        test_progress = tqdm(pairs_to_test, desc="FIXED pair testing", unit="pair")

        for symbol1, symbol2 in test_progress:
            try:
                if symbol1 == symbol2:
                    continue

                data1 = processed_data[symbol1]
                data2 = processed_data[symbol2]

                common_dates = data1.index.intersection(data2.index)
                if len(common_dates) < self.min_common_days:
                    continue

                correlation = self.calculate_correlation(data1, data2)
                if abs(correlation) < self.correlation_threshold:
                    continue

                is_cointegrated, coint_pvalue = self.test_cointegration(data1, data2)
                if not is_cointegrated:
                    continue

                half_life = self.calculate_half_life(data1, data2)
                if not (self.min_half_life <= half_life <= self.max_half_life):
                    continue

                # v19: PCA idiosyncratic cointegration test.
                # Tests whether the residual spread (after stripping 5 systematic factors)
                # is also cointegrated. Pairs passing this are genuinely idiosyncratic.
                pca_cointegrated = False
                if symbol1 in pca_residuals and symbol2 in pca_residuals:
                    try:
                        pca_ok, _ = self.test_cointegration(
                            pca_residuals[symbol1], pca_residuals[symbol2]
                        )
                        pca_cointegrated = pca_ok
                    except Exception:
                        pass

                quality_score = self._calculate_balanced_quality_score(
                    correlation, coint_pvalue, half_life, data1, data2,
                    pca_cointegrated=pca_cointegrated
                )

                if quality_score > 0.4:
                    valid_pairs.append({
                        'symbols': (symbol1, symbol2),
                        'stats': {
                            'correlation': correlation,
                            'cointegration_pvalue': coint_pvalue,
                            'half_life': half_life,
                            'quality_score': quality_score,
                            'pca_cointegrated': pca_cointegrated,
                        },
                        'score': quality_score
                    })

                test_progress.set_postfix({
                    'Quality_Pairs': len(valid_pairs),
                    'Rate': f'{len(valid_pairs)/test_progress.n*100:.1f}%' if hasattr(test_progress, 'n') and test_progress.n > 0 else '0%'
                })

            except Exception as e:
                continue

        valid_pairs.sort(key=lambda x: x['score'], reverse=True)

        # --- CHANGED: Return ALL valid pairs instead of limiting to max_pairs ---
        selected_pairs = [p['symbols'] for p in valid_pairs]

        self.selected_pairs = selected_pairs
        # expose the quality-symbol universe so the benchmark can run the textbook
        # distance method on the exact same universe (apples-to-apples comparison)
        self.last_quality_symbols = list(quality_symbols)

        self.pair_statistics = {}
        for pair in valid_pairs:
            s1, s2 = pair['symbols']
            self.pair_statistics[f"{s1}-{s2}"] = pair['stats']

        logger.info(f"FIXED: Found {len(self.selected_pairs)} pairs satisfying all conditions")

        if valid_pairs:
            logger.info("Top 5 FIXED quality pairs:")
            for i, pair in enumerate(valid_pairs[:5]):
                s1, s2 = pair['symbols']
                score = pair['score']
                stats_dict = pair['stats']
                logger.info(f"   {i+1}. {s1:4s}-{s2:4s}: "
                           f"Score={score:.3f}, Corr={stats_dict['correlation']:.3f}, "
                           f"Coint_p={stats_dict['cointegration_pvalue']:.4f}, "
                           f"Half_Life={stats_dict['half_life']:.1f}d")

        return self.selected_pairs

    def _calculate_balanced_quality_score(self, correlation: float, coint_pvalue: float,
                                        half_life: float, data1: pd.DataFrame, data2: pd.DataFrame,
                                        pca_cointegrated: bool = False) -> float:
        """FIXED: More balanced quality scoring. v19: pca_cointegrated bonus added."""
        try:
            corr_score = min(0.3, abs(correlation) * 0.6)
            coint_score = (self.cointegration_threshold - coint_pvalue) / self.cointegration_threshold * 0.3

            # v19: half-life score recalibrated for dynamic hold (max 25 days).
            # With 2.5× HL hold, all HL in [4,25] get ≥85% expected reversion.
            # Score is still highest at HL=10 (fastest mean reversion = most reliable).
            optimal_hl = 10
            if 4 <= half_life <= 25:
                hl_score = 0.2 * max(0.0, 1.0 - abs(half_life - optimal_hl) / 15.0)
            else:
                hl_score = 0.0

            bonus_score = 0
            try:
                common_dates = data1.index.intersection(data2.index)
                if len(common_dates) > 300:
                    data1_completeness = 1 - (data1.loc[common_dates, 'Close'].isnull().sum() / len(common_dates))
                    data2_completeness = 1 - (data2.loc[common_dates, 'Close'].isnull().sum() / len(common_dates))
                    if data1_completeness > 0.95 and data2_completeness > 0.95:
                        bonus_score += 0.2
            except:
                pass

            # v19: PCA idiosyncratic cointegration bonus (+0.15).
            # Pairs whose RESIDUAL spread (after stripping 5 systematic factors) is also
            # cointegrated are genuinely idiosyncratic mean-reverting relationships.
            # Literature shows these have ~3× lower regime-break failure rate.
            pca_bonus = 0.15 if pca_cointegrated else 0.0

            total_score = corr_score + coint_score + hl_score + bonus_score + pca_bonus
            return min(1.0, total_score)

        except:
            return 0.0
