"""
PAIRS TRADING - PAIR SELECTION
==============================
Symbol screens, correlation filter, two-direction Engle-Granger cointegration
(Bonferroni), half-life of the cointegrating spread, PCA idiosyncratic check, quality
score, and the Benjamini-Hochberg FDR diagnostic.
"""

import os

from joblib import Parallel, delayed
from threadpoolctl import threadpool_limits

from pairs_trading.config import (
    pd, np, stats, logging, itertools, tqdm,
    List, Dict, Optional, Tuple, PCA
)
from pairs_trading.fast_coint import engle_granger

logger = logging.getLogger(__name__)

# Every column the per-pair tests read; the all-pairs search ships only these to workers.
PAIR_TEST_COLUMNS = ('Close', 'Returns')
# The all-pairs search runs in worker processes (joblib's default loky backend), not in
# threads: the per-pair tests are pandas- and Python-bound and hold the GIL. On the 4,950
# pairs of the 100 most liquid symbols (formation data 2020-2022, 4 CPUs), 4 processes
# took 9 s, 4 threads 75 s and one process 24 s.
# The search is split into rectangular blocks of the pair matrix: about 8 tasks per
# worker, so the pool stays busy to the end, and at least 250 pairs per task, so the
# ~10 ms cost of sending a task (its symbols' columns, not the whole universe) stays
# below 1% of the ~5 ms of tests per pair.
_TASKS_PER_JOB = 8
_MIN_PAIRS_PER_TASK = 250


def resolve_n_jobs() -> int:
    """PAIRS_N_JOBS as a positive int (default min(4, CPU count)); a malformed value is an error."""
    raw = os.environ.get('PAIRS_N_JOBS')
    if raw is None:
        return min(4, os.cpu_count() or 1)
    try:
        n_jobs = int(raw)
    except ValueError:
        n_jobs = 0
    if n_jobs < 1:
        raise ValueError(f"PAIRS_N_JOBS must be a positive integer, got {raw!r}")
    return n_jobs


def pair_blocks(n_symbols: int, n_jobs: int) -> List[List[Tuple[int, int]]]:
    """Partition of the pairs (i, j), i < j < n_symbols, into tasks of the all-pairs search.

    The symbol list is cut into B contiguous groups and each task is one group pair
    (a <= b): the pairs with i in group a and j in group b, in itertools.combinations
    order. A task needs only the two groups' data. B is the largest value that keeps
    >= _MIN_PAIRS_PER_TASK pairs per task, stopping once there are
    _TASKS_PER_JOB * n_jobs tasks.
    """
    n_pairs = n_symbols * (n_symbols - 1) // 2
    n_groups = 1
    while n_groups < n_symbols:
        n_tasks = (n_groups + 1) * (n_groups + 2) // 2
        if n_pairs < _MIN_PAIRS_PER_TASK * n_tasks:
            break
        n_groups += 1
        if n_tasks >= _TASKS_PER_JOB * n_jobs:
            break
    edges = np.linspace(0, n_symbols, n_groups + 1).round().astype(int)
    blocks = []
    for a in range(n_groups):
        for b in range(a, n_groups):
            block = [(i, j) for i in range(edges[a], edges[a + 1])
                     for j in range(max(i + 1, edges[b]), edges[b + 1])]
            if block:
                blocks.append(block)
    return blocks


def _test_pair_block(selector: 'FixedPrimeFundPairSelector', frames: Dict[str, pd.DataFrame],
                     pca_frames: Dict[str, pd.DataFrame], pairs: List[Tuple[str, str]]) -> List:
    """[(pair, selector._test_pair(...))] for the pairs of one task, BLAS single-threaded.

    One BLAS thread in every task, in this process or in a worker, so a pair's floating-
    point results cannot depend on how many threads the linear algebra was given.
    """
    with threadpool_limits(limits=1):
        return [((s1, s2), selector._test_pair(frames[s1], frames[s2], pca_frames.get(s1), pca_frames.get(s2)))
                for s1, s2 in pairs]


class FixedPrimeFundPairSelector:
    """Formation-period pair selection: screens, correlation, cointegration, half-life, quality."""

    def __init__(self):
        # v32: a POSITIVE return correlation is required. abs() used to admit negatively
        # correlated pairs, whose cointegrating slope is negative — the engine cannot
        # trade those (hedge ratios outside [0.25, 4] are skipped), so they only diluted
        # the universe and the FDR count. 0.25 is a light pre-screen, not a similarity
        # requirement; there is no same-industry restriction (see README limitations).
        self.correlation_threshold = 0.25
        self.cointegration_threshold = 0.05
        # Half-life band, trading days. The time stop is clamp(2.5 x HL, 10, 25) days, and
        # an OU spread closes 1 - 2^(-hold/HL) of its gap over a hold: ~82% for HL <= 10,
        # falling to 63% at HL = 18 and 50% at HL = 25 (where the 25-day cap binds).
        self.min_half_life = 4
        self.max_half_life = 25
        self.min_common_days = 420
        # v32: liquidity is screened on point-in-time DOLLAR volume (close x shares). The
        # former 2.5M-SHARE floor favoured low-priced names and excluded liquid high-priced
        # ones (a $400 stock trading 1M shares a day is $400M of daily liquidity). Every
        # symbol must clear the floor; if more than max_universe do, the most liquid
        # max_universe are kept, which keeps the all-pairs search (n^2/2 tests) bounded.
        self.min_dollar_volume = 10e6
        self.max_universe = 300
        # The all-pairs search runs in n_jobs worker processes (PAIRS_N_JOBS; 1 = in this
        # process). The selection does not depend on it: see find_quality_pairs.
        self.n_jobs = resolve_n_jobs()

        self.selected_pairs = []
        self.pair_statistics = {}

        logger.info("Pair selector initialised")

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

        except Exception:
            return 0.0

    @staticmethod
    def cointegration_pvalue(log_prices1: np.ndarray, log_prices2: np.ndarray) -> float:
        """Two-direction Engle-Granger p-value, Bonferroni-combined: min(1, 2*min(p12, p21)).

        v31 (audit): min() of the two Engle-Granger directions is NOT a p-value — the two
        regressions are separate (correlated) tests, and taking the smaller inflates the
        false-positive rate (~1.5-2x effective size at alpha=0.05). Bonferroni over the 2
        tests restores a valid, conservative p-value while keeping the "test both
        directions" intent. v32: factored out so every caller (initial selection, the
        quarterly re-test and its recent-window check) uses the same definition.

        Each direction is statsmodels' coint(y0, y1) (trend='c', autolag='aic') computed by
        pairs_trading.fast_coint.engle_granger: the same statistic to rounding (~1e-13),
        13-30x faster; degenerate inputs are handed to statsmodels itself.
        """
        try:
            _, p12 = engle_granger(log_prices1, log_prices2)
            _, p21 = engle_granger(log_prices2, log_prices1)
        except Exception:
            return 1.0
        if not (np.isfinite(p12) and np.isfinite(p21)):
            return 1.0
        return float(min(1.0, 2.0 * min(p12, p21)))

    @staticmethod
    def _aligned_log_prices(data1: pd.DataFrame, data2: pd.DataFrame):
        """Log closes of both legs on their common dates with real, positive prices."""
        common = data1.index.intersection(data2.index)
        p1 = data1.loc[common, 'Close'].to_numpy(dtype=float)
        p2 = data2.loc[common, 'Close'].to_numpy(dtype=float)
        ok = np.isfinite(p1) & np.isfinite(p2) & (p1 > 0) & (p2 > 0)
        return np.log(p1[ok]), np.log(p2[ok])

    def test_cointegration(self, data1: pd.DataFrame, data2: pd.DataFrame) -> Tuple[bool, float]:
        """Engle-Granger cointegration of log prices on common dates (Bonferroni p, see above)."""
        try:
            common_dates = data1.index.intersection(data2.index)
            if len(common_dates) < self.min_common_days:
                return False, 1.0
            log_prices1, log_prices2 = self._aligned_log_prices(data1, data2)
            if len(log_prices1) < self.min_common_days:
                return False, 1.0
            p1, p2 = np.exp(log_prices1), np.exp(log_prices2)
            if np.std(p1) < p1.mean() * 0.01 or np.std(p2) < p2.mean() * 0.01:
                return False, 1.0
            pvalue = self.cointegration_pvalue(log_prices1, log_prices2)
            return pvalue < self.cointegration_threshold, pvalue
        except Exception:
            return False, 1.0

    def calculate_half_life(self, data1: pd.DataFrame, data2: pd.DataFrame) -> float:
        """Mean-reversion half-life (days) of the cointegrating spread.

        Step 1 (as in Engle-Granger): OLS hedge regression log p1 = a + b log p2 on the
        pair's common dates. Step 2: AR(1) with intercept on that residual spread,
        s_t = c + phi s_{t-1} + e_t; half-life = -ln 2 / ln phi for 0 < phi < 1.

        v32: through v31 this used the beta = 1 spread log p1 - log p2 — not the spread
        that was tested for cointegration nor the one traded — so a genuinely
        cointegrated pair with hedge ratio far from 1 got a meaningless (often 999)
        half-life; and the AR(1) ran on the gap-compressed series, so lags straddled gaps
        (now only true one-step pairs enter the regression).
        """
        try:
            # Gap-aware: align on the union of dates so a day missing from either leg is a
            # NaN in the spread, and fit the AR(1) only on genuine one-step pairs (a
            # compressed series would regress across gaps and bias phi down).
            idx = data1.index.union(data2.index)
            p1 = data1['Close'].reindex(idx).to_numpy(dtype=float)
            p2 = data2['Close'].reindex(idx).to_numpy(dtype=float)
            ok = np.isfinite(p1) & np.isfinite(p2) & (p1 > 0) & (p2 > 0)
            if ok.sum() < 50:
                return 999.0
            lp1 = np.full(len(idx), np.nan)
            lp2 = np.full(len(idx), np.nan)
            lp1[ok], lp2[ok] = np.log(p1[ok]), np.log(p2[ok])
            if np.std(lp2[ok]) < 1e-12:
                return 999.0
            b, a = np.polyfit(lp2[ok], lp1[ok], 1)
            spread = lp1 - (a + b * lp2)
            y, x = spread[1:], spread[:-1]
            m = np.isfinite(y) & np.isfinite(x)
            if m.sum() < 30:
                return 999.0
            X = np.column_stack([np.ones(int(m.sum())), x[m]])
            phi = float(np.linalg.lstsq(X, y[m], rcond=None)[0][1])
            if 0.0 < phi < 1.0:
                return float(max(1.0, min(999.0, -np.log(2.0) / np.log(phi))))
            return 999.0
        except Exception:
            return 999.0

    def compute_pca_residuals(self, processed_data: Dict, quality_symbols: List[str],
                               n_components: int = 5) -> Dict:
        """Strip systematic factor loadings using PCA before cointegration testing.

        Fits PCA on the return matrix of all quality_symbols, extracts the first
        n_components market/sector factors, then returns per-symbol residual 'price'
        series (cumulative idiosyncratic log-returns). Pairs tested on residuals pass
        cointegration only due to genuine idiosyncratic mean reversion — not because
        both stocks load on the same sector or market factor.

        v19: added to discount cointegration that only reflects shared factor exposure
        (market, sector rotation). The residuals feed a quality-score bonus only; pairs
        are selected and traded on raw prices. (v32 removed an unsourced claim that
        5-factor stripping cuts the false-positive cointegration rate from ~35% to ~8%.)
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

            # v31 (audit): was `pd.DataFrame(ret_series).fillna(0.0)`. Assembling the
            # series produces a UNION index, so any symbol with a shorter history or
            # trading gaps received fabricated 0.0 "returns" on every date it did not
            # actually trade — up to ~43% of a column for late-listing symbols. Zeros are
            # not neutral here: a long run of them is a perfectly mean-reverting, zero-
            # variance stretch, which both distorts the PCA factor structure and makes the
            # resulting residual series look spuriously stationary — earning a residual-
            # cointegration quality BONUS for the symbols with the worst data.
            # Drop thin columns, then restrict to genuinely common dates.
            ret_df = pd.DataFrame(ret_series)
            _coverage = ret_df.notna().mean()
            _keep = _coverage[_coverage >= 0.90].index
            _dropped = len(ret_df.columns) - len(_keep)
            ret_df = ret_df[_keep].dropna(how='any')
            if _dropped:
                logger.info(f"PCA: dropped {_dropped} symbol(s) with <90% return coverage; "
                            f"{ret_df.shape[1]} symbols on {ret_df.shape[0]} common dates")
            if ret_df.shape[0] < 100 or ret_df.shape[1] < n_components + 1:
                logger.info("PCA: insufficient common history after coverage filter — skipping")
                return {}

            n_fit = min(n_components, ret_df.shape[1] - 1)
            pca = PCA(n_components=n_fit)
            factors   = pca.fit_transform(ret_df.values)     # (T, k)
            loadings  = pca.components_                       # (k, n_symbols)
            projection = factors @ loadings                   # (T, n_symbols) — systematic part
            # v32: sklearn centres the data before projecting, so X - projection still
            # contains each symbol's mean return; cumulating it put a deterministic drift
            # into every residual "price" that a constant-only Engle-Granger test cannot
            # absorb. Remove the column means: residuals are the idiosyncratic part only.
            residuals  = ret_df.values - pca.mean_ - projection

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

    def find_quality_pairs(self, processed_data: Dict[str, pd.DataFrame]) -> List[Tuple[str, str]]:
        """Screen symbols, then test every pair of screened symbols; return all that pass.

        Symbol screen (formation data only): >= 300 bars, mean point-in-time price >= $5,
        mean point-in-time dollar volume >= min_dollar_volume (the max_universe most
        liquid names are kept if more pass), annualised volatility 5-80%, < 10% missing
        closes. Pair tests: return correlation >= +0.25, two-direction Engle-Granger
        p < 0.05 (Bonferroni), half-life 4-25 days, quality score > 0.4. All passing
        pairs are returned, ranked by quality score. Symbols are processed in sorted
        order, so the traded orientation of every pair (which leg is regressed on which)
        is deterministic. The pair tests run over n_jobs worker processes
        (_test_all_pairs); the result is identical for any n_jobs.
        """

        # A new search starts without the previous one's outputs (the selector itself is
        # sent to the pair-test workers).
        self.selected_pairs, self.pair_statistics, self.fdr_diagnostic = [], {}, {}
        symbols = sorted(processed_data)
        logger.info(f"Pair selection: screening {len(symbols)} symbols")

        screened = []
        for symbol in symbols:
            data = processed_data[symbol]
            if len(data) < 300:
                continue
            # v32: point-in-time (split-unadjusted) price and volume. The adjusted series
            # divide pre-split prices (and multiply pre-split volumes) by LATER split
            # ratios, so these level screens used to depend on future corporate actions.
            price = data['Close_PIT'] if 'Close_PIT' in data.columns else data['Close']
            shares = data['Volume_PIT'] if 'Volume_PIT' in data.columns else data['Volume']
            if price.mean() < 5.0:
                continue
            dollar_volume = float((price * shares).mean())
            if not np.isfinite(dollar_volume) or dollar_volume < self.min_dollar_volume:
                continue
            volatility = data['Returns'].std() * np.sqrt(252)
            if not (0.05 < volatility < 0.8):
                continue
            if data['Close'].isnull().sum() / len(data) >= 0.10:
                continue
            screened.append((symbol, dollar_volume))

        screened.sort(key=lambda kv: (-kv[1], kv[0]))
        quality_symbols = sorted(sym for sym, _ in screened[:self.max_universe])
        logger.info(f"Pair selection: {len(screened)} symbols pass the screens; testing the "
                    f"{len(quality_symbols)} most liquid")
        # v32: no silent fallback. Through v31, fewer than 30 passing symbols switched to
        # the 100 longest histories with NO liquidity, price or volatility screen at all.
        if len(quality_symbols) < 30:
            logger.warning(f"Only {len(quality_symbols)} symbols pass the screens; the pair "
                           "universe is small")
        if len(quality_symbols) < 2:
            self.last_quality_symbols = list(quality_symbols)
            return []

        # v19: Compute PCA residuals once for the full quality symbol universe.
        # Each pair is then tested on BOTH raw prices (for backward compatibility) and
        # PCA residuals (idiosyncratic test). Pairs passing both get a quality bonus.
        pca_residuals = self.compute_pca_residuals(processed_data, quality_symbols, n_components=5)

        n_pairs = len(quality_symbols) * (len(quality_symbols) - 1) // 2
        logger.info(f"Pair selection: testing all {n_pairs:,} unique pairs "
                    f"({self.n_jobs} worker{'s' if self.n_jobs > 1 else ''})")
        outcomes = self._test_all_pairs(processed_data, quality_symbols, pca_residuals)

        # Collected in itertools.combinations order, whatever order the tasks finished in.
        valid_pairs = []
        _all_coint_pvalues = []   # every correlation-passing pair's coint p-value (for FDR)
        for pair in itertools.combinations(quality_symbols, 2):
            coint_pvalue, pair_stats = outcomes[pair]
            if coint_pvalue is not None:
                _all_coint_pvalues.append(coint_pvalue)
            if pair_stats is not None:
                valid_pairs.append({'symbols': pair, 'stats': pair_stats,
                                    'score': pair_stats['quality_score']})

        valid_pairs.sort(key=lambda x: x['score'], reverse=True)

        selected_pairs = [p['symbols'] for p in valid_pairs]

        self.selected_pairs = selected_pairs
        # expose the quality-symbol universe so the benchmark can run the textbook
        # distance method on the exact same universe (apples-to-apples comparison)
        self.last_quality_symbols = list(quality_symbols)

        self.pair_statistics = {}
        for pair in valid_pairs:
            s1, s2 = pair['symbols']
            self.pair_statistics[f"{s1}-{s2}"] = pair['stats']

        # ── Multiple-testing (FDR) diagnostic ────────────────────────────────────
        # Testing tens of thousands of pairs at raw p<0.05 yields many false positives
        # by chance. Benjamini-Hochberg controls the false-discovery rate; this reports
        # how many correlation-passing pairs survive BH. "Expected false positives" is
        # 0.05 x pairs tested, an UPPER bound (it assumes every tested pair is null), and
        # it describes the cointegration step alone: the later half-life, quality and
        # quarterly re-tests remove some false positives as well as true ones. Diagnostic
        # only — it does not change which pairs are selected.
        self.fdr_diagnostic = {}
        try:
            from statsmodels.stats.multitest import multipletests
            pvals = np.asarray(_all_coint_pvalues, dtype=float)
            n_tested = int(pvals.size)
            if n_tested > 0:
                n_raw_sig = int((pvals < 0.05).sum())
                exp_false_pos = 0.05 * n_tested        # upper bound: all tested pairs null
                bh05 = int(multipletests(pvals, alpha=0.05, method='fdr_bh')[0].sum())
                bh10 = int(multipletests(pvals, alpha=0.10, method='fdr_bh')[0].sum())
                self.fdr_diagnostic = {
                    'pairs_tested': n_tested,
                    'significant_raw_p05': n_raw_sig,
                    'expected_false_positives_at_p05': round(exp_false_pos, 1),
                    'survive_bh_fdr_q05': bh05,
                    'survive_bh_fdr_q10': bh10,
                    'final_selected_pairs': len(self.selected_pairs),
                }
                logger.info("FDR diagnostic (Benjamini-Hochberg on cointegration p-values):")
                logger.info(f"  tested {n_tested:,} pairs | raw p<0.05: {n_raw_sig:,} "
                            f"(<= {exp_false_pos:,.0f} expected false positives if all were null)")
                logger.info(f"  survive BH-FDR q<0.05: {bh05:,} | q<0.10: {bh10:,} | "
                            f"final selected (after half-life/quality/PCA): {len(self.selected_pairs):,}")
        except Exception as e:
            logger.debug(f"FDR diagnostic skipped: {e}")

        logger.info(f"Pair selection: {len(self.selected_pairs)} pairs satisfy all conditions")

        if valid_pairs:
            logger.info("Top 5 pairs by quality score:")
            for i, pair in enumerate(valid_pairs[:5]):
                s1, s2 = pair['symbols']
                score = pair['score']
                stats_dict = pair['stats']
                logger.info(f"   {i+1}. {s1:4s}-{s2:4s}: "
                           f"Score={score:.3f}, Corr={stats_dict['correlation']:.3f}, "
                           f"Coint_p={stats_dict['cointegration_pvalue']:.4f}, "
                           f"Half_Life={stats_dict['half_life']:.1f}d")

        return self.selected_pairs

    def _pair_tasks(self, processed_data: Dict[str, pd.DataFrame], quality_symbols: List[str],
                    pca_residuals: Dict[str, pd.DataFrame]) -> List[Tuple[Dict, Dict, List]]:
        """The all-pairs search as tasks (frames, pca_frames, pairs), one per pair_blocks block.

        A task carries its pairs and, for only the symbols in them, the PAIR_TEST_COLUMNS
        and the PCA residuals: the universe is never sent whole, nor a pair's data per pair.
        """
        frames = {s: processed_data[s][[c for c in PAIR_TEST_COLUMNS if c in processed_data[s].columns]]
                  for s in quality_symbols}
        tasks = []
        for block in pair_blocks(len(quality_symbols), self.n_jobs):
            pairs = [(quality_symbols[i], quality_symbols[j]) for i, j in block]
            names = sorted({s for pair in pairs for s in pair})
            tasks.append(({s: frames[s] for s in names},
                          {s: pca_residuals[s] for s in names if s in pca_residuals}, pairs))
        return tasks

    def _test_all_pairs(self, processed_data: Dict[str, pd.DataFrame], quality_symbols: List[str],
                        pca_residuals: Dict[str, pd.DataFrame]) -> Dict[Tuple[str, str], Tuple]:
        """{pair: _test_pair outcome} for every pair of quality_symbols, over n_jobs processes.

        Every task (see _pair_tasks) runs the same function on the same values with one
        BLAS thread, so each pair's outcome, and with it the selection, its order,
        pair_statistics and the FDR p-values, is identical for any n_jobs. With n_jobs = 1
        or a single task, the tasks run in this process.
        """
        tasks = self._pair_tasks(processed_data, quality_symbols, pca_residuals)
        if self.n_jobs > 1 and len(tasks) > 1:
            results = Parallel(n_jobs=self.n_jobs, return_as='generator_unordered')(
                delayed(_test_pair_block)(self, *task) for task in tasks)
        else:
            results = (_test_pair_block(self, *task) for task in tasks)

        outcomes, n_quality = {}, 0
        with tqdm(total=sum(len(task[2]) for task in tasks), desc="Pair testing", unit="pair") as progress:
            for block_outcomes in results:
                outcomes.update(block_outcomes)
                n_quality += sum(1 for _, (_, pair_stats) in block_outcomes if pair_stats is not None)
                progress.update(len(block_outcomes))
                progress.set_postfix({'Quality_Pairs': n_quality})
        return outcomes

    def _test_pair(self, data1: pd.DataFrame, data2: pd.DataFrame, pca1: Optional[pd.DataFrame] = None,
                   pca2: Optional[pd.DataFrame] = None) -> Tuple[Optional[float], Optional[Dict]]:
        """The pair tests of find_quality_pairs for one pair, in order.

        Returns (p, stats). p is the Bonferroni cointegration p-value when the pair reached
        the cointegration test (common dates and correlation passed) and p is finite, else
        None: it enters the FDR diagnostic. stats is the pair's statistics dict when every
        test passes, else None. pca1 / pca2 are the legs' PCA-residual frames (None when a
        leg has none). An exception ends the pair's tests; a p-value already obtained is kept.
        """
        pvalue = None
        try:
            common_dates = data1.index.intersection(data2.index)
            if len(common_dates) < self.min_common_days:
                return None, None

            correlation = self.calculate_correlation(data1, data2)
            if correlation < self.correlation_threshold:
                return None, None

            is_cointegrated, coint_pvalue = self.test_cointegration(data1, data2)
            if coint_pvalue is not None and np.isfinite(coint_pvalue):
                pvalue = coint_pvalue
            if not is_cointegrated:
                return pvalue, None

            half_life = self.calculate_half_life(data1, data2)
            if not (self.min_half_life <= half_life <= self.max_half_life):
                return pvalue, None

            # v19: PCA idiosyncratic cointegration test.
            # Tests whether the residual spread (after stripping 5 systematic factors)
            # is also cointegrated. Pairs passing this are genuinely idiosyncratic.
            pca_cointegrated = False
            if pca1 is not None and pca2 is not None:
                try:
                    pca_cointegrated, _ = self.test_cointegration(pca1, pca2)
                except Exception:
                    pass

            quality_score = self._calculate_balanced_quality_score(
                correlation, coint_pvalue, half_life, data1, data2,
                pca_cointegrated=pca_cointegrated
            )
            if quality_score > 0.4:
                return pvalue, {
                    'correlation': correlation,
                    'cointegration_pvalue': coint_pvalue,
                    'half_life': half_life,
                    'quality_score': quality_score,
                    'pca_cointegrated': pca_cointegrated,
                }
        except Exception:
            pass
        return pvalue, None

    def _calculate_balanced_quality_score(self, correlation: float, coint_pvalue: float,
                                        half_life: float, data1: pd.DataFrame, data2: pd.DataFrame,
                                        pca_cointegrated: bool = False) -> float:
        """Heuristic quality score in [0, 1] used for ranking, the 0.4 selection cut-off,
        the engine's 0.55 trading floor and position sizing.

        Components: correlation (<= 0.3), cointegration strength (<= 0.3), half-life
        closeness to 10 days (<= 0.2), data completeness (0.2) and PCA-residual
        cointegration (0.15). The weights are hand-set, not estimated. Note that the
        completeness bonus is effectively a constant: the symbol screen already
        requires < 10% missing closes and missing closes are rare in the cache, so
        almost every pair receives the 0.2 — the 0.4 / 0.55 cut-offs are really
        0.2 / 0.35 on the other four components.
        """
        try:
            corr_score = min(0.3, max(0.0, correlation) * 0.6)
            coint_score = (self.cointegration_threshold - coint_pvalue) / self.cointegration_threshold * 0.3

            # Highest at HL = 10, where the time stop (2.5 x HL = 25 days) still allows
            # ~82% expected reversion; see the half-life band in __init__.
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
            except Exception:
                pass

            # v19: PCA bonus (+0.15) when the two legs' factor-stripped residual "prices"
            # are also cointegrated. A heuristic: the residual series is not what is
            # traded, and no out-of-sample evidence that the bonus improves pair
            # survival has been produced for this project. (v32 removed an unsourced
            # "~3x lower regime-break failure rate" claim.)
            pca_bonus = 0.15 if pca_cointegrated else 0.0

            total_score = corr_score + coint_score + hl_score + bonus_score + pca_bonus
            return min(1.0, total_score)

        except Exception:
            return 0.0
