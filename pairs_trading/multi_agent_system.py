"""
PAIRS TRADING - LEARNED SIGNAL-QUALITY RANKER
=============================================
Feature assembly for a candidate pair-day and a transformer-encoder classifier that
scores P(trade is profitable). The score is used for opportunity RANKING only — it never
opens or blocks a trade on its own (v19-v21 evidence: quality gating degraded OOS).

This is NOT reinforcement learning: there is no policy, value function or environment
loop. v32 removed the 1000-episode "multi-agent training" loop that used to run here —
it applied a fixed rule, computed shaped "rewards" and updated no parameters at all —
together with the never-populated actor/critic loss plots it produced.
"""

import os
import warnings

from pairs_trading.config import (
    pd, np, stats, logging, Dict, List, SECTOR_MAP, SECTOR_ETFS
)
from sklearn.preprocessing import RobustScaler

logger = logging.getLogger(__name__)


def roc_auc(y: np.ndarray, score: np.ndarray):
    """Mann-Whitney ROC AUC with tie handling; None if only one class is present."""
    y = np.asarray(y, dtype=float) > 0.5
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = stats.rankdata(np.asarray(score, dtype=float))
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def classifier_skill(y: np.ndarray, p: np.ndarray, prior: float = None) -> Dict:
    """AUC, Brier score vs the constant-prior Brier score, and calibration in the large."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    prior = float(y.mean()) if prior is None else float(prior)
    return {
        'n': int(len(y)),
        'hit_rate': float(y.mean()) if len(y) else None,
        'mean_predicted': float(p.mean()) if len(p) else None,
        'brier': float(np.mean((p - y) ** 2)) if len(y) else None,
        'brier_base_rate': float(np.mean((prior - y) ** 2)) if len(y) else None,
        'auc': roc_auc(y, p),
    }


class FixedTransformerMultiAgentSystem:
    """Feature extractor + transformer signal-quality ranker (class name kept for API compatibility)."""

    MIN_SAMPLES = 400

    # v32: the feature vector has 30 entries. It used to be zero-padded to 38 ("38
    # features" in the README), so inputs 30-37 were constant zeros.
    N_FEATURES = 30

    def __init__(self, state_dim: int = N_FEATURES):
        self.state_dim = state_dim
        self.scaler = RobustScaler()
        self.scaler_fitted = False
        # Stays None until train_on_samples() trains it; while None the ranking score is
        # 1.0 for every candidate. PAIRS_USE_TRANSFORMER=0 skips training entirely, which
        # gives the classical-only system on the same code path (the ML ablation).
        self.signal_transformer = None
        self.use_signal_transformer = os.environ.get("PAIRS_USE_TRANSFORMER", "1") != "0"
        # Real pair statistics injected by the system after selection, so the pair-level
        # features match between training and inference.
        self.pair_statistics: Dict = {}
        self.training_summary: Dict = {}
        logger.info("Signal-quality ranker initialised")

    def extract_advanced_features(self, spread_data: pd.Series, pair_stats: Dict,
                                 stock1_data: pd.DataFrame, stock2_data: pd.DataFrame,
                                 macro_data: Dict = None, symbol1: str = None, symbol2: str = None) -> np.ndarray:
        """FIXED: More robust feature extraction"""
        try:
            if len(spread_data) < 20:
                return np.zeros(self.state_dim)

            features = []

            current_spread = spread_data.iloc[-1]
            spread_mean = spread_data.mean()
            spread_std = spread_data.std() + 1e-8

            zscore = (current_spread - spread_mean) / spread_std
            features.extend([
                zscore,
                abs(zscore),
                np.clip(zscore, -4, 4),
                zscore ** 2,
            ])

            # v17: diff() not pct_change() — Kalman spread crosses zero; pct_change()
            # divides by near-zero values → inf, clamped to ±3.0 by nan_to_num, making
            # the momentum features permanently saturated and _assess_feature_quality
            # always passing the 0.005 threshold spuriously.
            spread_returns = spread_data.diff().dropna()
            if len(spread_returns) >= 5:
                features.extend([
                    spread_returns.iloc[-1] if len(spread_returns) > 0 else 0,
                    spread_returns.rolling(5, min_periods=3).mean().iloc[-1] if len(spread_returns) >= 3 else 0,
                    spread_returns.rolling(10, min_periods=5).mean().iloc[-1] if len(spread_returns) >= 5 else 0,
                    spread_returns.rolling(5, min_periods=3).std().iloc[-1] if len(spread_returns) >= 3 else 0.01,
                ])
            else:
                features.extend([0, 0, 0, 0.01])

            if len(spread_data) >= 10:
                ma_5 = spread_data.rolling(5, min_periods=3).mean().iloc[-1] if len(spread_data) >= 3 else current_spread
                ma_20 = spread_data.rolling(20, min_periods=10).mean().iloc[-1] if len(spread_data) >= 10 else current_spread
                features.extend([
                    (current_spread - ma_5) / spread_std,
                    (current_spread - ma_20) / spread_std,
                ])
            else:
                features.extend([0, 0])

            # v31 (audit): LOOK-AHEAD FIX. Callers pass the FULL price history for each
            # leg (trading_system.py passes self.processed_data[symbol] unsliced) while
            # `spread_data` is correctly truncated to the decision date. Taking
            # common_dates[-1] therefore read RSI_14 / Momentum_5 / High_Vol_Regime — and
            # the day-of-week feature below — from the LAST DAY OF THE ENTIRE STUDY on
            # every single backtest date. Anchor to the spread's last observation, which
            # is the decision date; the macro block at the bottom of this function already
            # uses exactly this reference (`ref_date = spread_data.index[-1]`).
            _as_of = spread_data.index[-1]
            try:
                stock1_data = stock1_data.loc[:_as_of]
                stock2_data = stock2_data.loc[:_as_of]
            except (TypeError, KeyError):
                # v32: never fall back to the unsliced frames (that re-opens the v31
                # terminal-date look-ahead); use neutral per-stock features instead.
                logger.warning("extract_advanced_features: could not align stock data to "
                               f"as-of {_as_of}; using neutral per-stock features")
                stock1_data = stock2_data = pd.DataFrame()

            common_dates = stock1_data.index.intersection(stock2_data.index)
            if len(common_dates) > 0:
                latest_date = common_dates[-1]

                for i, stock_data in enumerate([stock1_data, stock2_data]):
                    if latest_date in stock_data.index:
                        row = stock_data.loc[latest_date]
                        rsi = row.get('RSI_14', 50) / 100
                        momentum_5 = row.get('Momentum_5', 0)
                        vol_regime = row.get('High_Vol_Regime', 0)
                        features.extend([rsi, momentum_5, vol_regime])
                    else:
                        features.extend([0.5, 0, 0])
            else:
                features.extend([0.5, 0, 0] * 2)

            correlation = pair_stats.get('correlation', 0)
            half_life = min(pair_stats.get('half_life', 50), 100) / 100
            quality_score = pair_stats.get('quality_score', 0.5)

            features.extend([
                correlation,
                half_life,
                quality_score,
            ])

            if len(common_dates) > 0:
                latest_date = common_dates[-1]
                day_of_week = latest_date.weekday() / 6
                features.append(day_of_week)
            else:
                features.append(0)

            if len(spread_returns) >= 10:
                recent_vol = spread_returns.rolling(10, min_periods=5).std().iloc[-1]
                momentum_20 = spread_data.iloc[-1] - spread_data.iloc[-min(21, len(spread_data))] if len(spread_data) > 10 else 0
                features.extend([recent_vol, momentum_20 / spread_std])
            else:
                features.extend([0.02, 0])

            # --- MACRO REGIME FEATURES (8 features, indices 22-29) ---
            # 22: VIX level / 30 (>1.0 = stressed)      23: VIX 20-trading-day momentum
            # 24: VIX regime bucket (0 / 0.5 / 1.0)     25-26: 20-day return of each leg's sector ETF
            # 27: sector divergence (25 - 26)           28: breadth (mean 20d sector return)
            # 29: cross-sector flag: 1.0 different sectors, 0.5 same, 0.75 unknown (a leg
            #     is not in SECTOR_MAP — v32: unknowns used to count as "same sector")
            if macro_data is not None and not macro_data.get('VIX', pd.Series()).empty:
                try:
                    # Determine reference date from spread
                    ref_date = spread_data.index[-1]
                    if hasattr(ref_date, 'tz') and ref_date.tz is not None:
                        ref_date = ref_date.tz_localize(None)

                    vix = macro_data['VIX']
                    vix_at = vix.asof(ref_date) if not vix.empty else 20.0
                    vix_20d_ago = vix.asof(ref_date - pd.Timedelta(days=28)) if not vix.empty else 20.0
                    vix_level = float(vix_at) / 30.0
                    vix_mom = (float(vix_at) - float(vix_20d_ago)) / (float(vix_20d_ago) + 1e-8)
                    vix_val = float(vix_at)
                    vix_regime = 0.0 if vix_val < 15 else (0.5 if vix_val < 25 else 1.0)

                    sectors = macro_data.get('sectors', {})
                    s1_etf = SECTOR_MAP.get(symbol1) if symbol1 else None
                    s2_etf = SECTOR_MAP.get(symbol2) if symbol2 else None

                    def sector_20d_return(etf):
                        s = sectors.get(etf, pd.Series(dtype=float)) if etf else pd.Series(dtype=float)
                        if s.empty:
                            return 0.0
                        v_now = s.asof(ref_date)
                        v_ago = s.asof(ref_date - pd.Timedelta(days=28))
                        if v_ago and v_ago > 0:
                            return float((v_now - v_ago) / v_ago)
                        return 0.0

                    s1_mom = sector_20d_return(s1_etf)
                    s2_mom = sector_20d_return(s2_etf)
                    breadth = float(np.mean([sector_20d_return(e) for e in SECTOR_ETFS if e in sectors])) if sectors else 0.0
                    if s1_etf is None or s2_etf is None:
                        cross_sector = 0.75
                    else:
                        cross_sector = 0.5 if s1_etf == s2_etf else 1.0

                    features.extend([vix_level, vix_mom, vix_regime, s1_mom, s2_mom,
                                      s1_mom - s2_mom, breadth, cross_sector])
                except Exception:
                    features.extend([0.67, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.5])
            else:
                features.extend([0.67, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.5])

            if len(features) != self.N_FEATURES:
                raise ValueError(f"feature vector has {len(features)} entries, expected {self.N_FEATURES}")
            features_array = np.array(features, dtype=np.float32)

            features_array = np.nan_to_num(features_array, nan=0.0, posinf=3.0, neginf=-3.0)
            features_array = np.clip(features_array, -5, 5)

            return features_array

        except Exception as e:
            logger.debug(f"Feature extraction error: {str(e)}")
            return np.zeros(self.state_dim)

    def train_on_samples(self, X_raw: np.ndarray, y: np.ndarray, epochs: int = 3,
                         batch_size: int = 256) -> bool:
        """Fit the feature scaler and train the transformer on (raw features, labels).

        X_raw/y come from CompleteFixedRussell3000TradingSystem.build_outcome_samples:
        one row per pair-day on which the real entry rule fired, features extracted with
        the same function, stock data and macro data as at inference, label = whether the
        trade the engine would have opened made money. Returns True if a model was trained.
        """
        self.training_summary = {'n_samples': 0 if X_raw is None else int(len(X_raw))}
        if not self.use_signal_transformer:
            logger.info("Ranker: PAIRS_USE_TRANSFORMER=0 — not trained (quality = 1.0)")
            return False
        if X_raw is None or y is None or len(X_raw) < self.MIN_SAMPLES:
            logger.info(f"Ranker: {self.training_summary['n_samples']} samples < {self.MIN_SAMPLES} — "
                        "not trained (quality = 1.0)")
            return False
        y = np.asarray(y, dtype=np.float32)
        base_rate = float(y.mean())
        self.training_summary['base_rate'] = base_rate
        if base_rate < 0.02 or base_rate > 0.98:
            logger.info(f"Ranker: degenerate labels (base rate {base_rate:.1%}) — not trained")
            return False
        self.fit_scaler(list(np.asarray(X_raw, dtype=np.float32)))
        X = self.scaler.transform(np.asarray(X_raw, dtype=np.float32)).astype(np.float32)
        self._train_signal_transformer(X, y, epochs=epochs, batch_size=batch_size)
        return self.signal_transformer is not None

    def _train_signal_transformer(self, X: np.ndarray, y: np.ndarray,
                                  epochs: int = 3, batch_size: int = 256):
        """BCE-train the transformer to predict P(profitable) at entry.

        Class-balanced via pos_weight = n_neg / n_pos, so an imbalanced label set still
        trains a real model instead of collapsing to the prior; the induced shift in the
        log-odds is removed at inference (logit_offset), so scores stay probabilities.
        """
        from pairs_trading.transformer_agent import TransformerEnhancedTradingAgent
        agent = TransformerEnhancedTradingAgent(state_dim=X.shape[1])
        n_pos = float((y > 0.5).sum())
        n_neg = float((y <= 0.5).sum())
        pos_weight = (n_neg / n_pos) if n_pos > 0 else 1.0
        n = len(X)
        idx = np.arange(n)
        epoch_losses = []
        for ep in range(epochs):
            np.random.shuffle(idx)
            losses = []
            for i in range(0, n, batch_size):
                b = idx[i:i + batch_size]
                losses.append(agent.train_on_batch(X[b], y[b], pos_weight=pos_weight))
            epoch_losses.append(float(np.mean(losses)))
            logger.info(f"Ranker epoch {ep + 1}/{epochs}: BCE loss {epoch_losses[-1]:.4f} "
                        f"({n} samples, base rate {y.mean():.1%}, pos_weight {pos_weight:.2f})")
        # Prior correction for the class weighting (King & Zeng 2001): with positives
        # weighted by w the loss is minimised at log-odds + log(w), so subtracting log(w)
        # restores an estimate of P(profitable) at the training base rate.
        agent.logit_offset = -float(np.log(pos_weight)) if pos_weight > 0 else 0.0
        self.training_summary.update({'epochs': epochs, 'epoch_losses': epoch_losses,
                                      'pos_weight': pos_weight,
                                      'logit_offset': agent.logit_offset})
        self.signal_transformer = agent

    def score_signal_quality(self, state: np.ndarray) -> float:
        """Transformer P(profitable) for a scaled feature vector — RANKING only.

        Returns 1.0 when no transformer is trained (classical-only / ablation path), so
        ranking degrades to signal_strength x pair_quality. If a trained model fails on a
        vector, the training base rate is returned: a neutral prior, not the top score
        (through v31 a failure returned 1.0 and outranked every correctly scored signal).
        """
        if self.signal_transformer is None:
            return 1.0
        try:
            return float(self.signal_transformer.predict_signal_quality(state))
        except Exception as e:
            prior = float(self.training_summary.get('base_rate', 0.5))
            logger.debug(f"Ranker scoring failed ({e}); using the base rate {prior:.3f}")
            return prior

    def evaluate(self, X_raw: np.ndarray, y: np.ndarray) -> Dict:
        """Out-of-sample skill of the trained scorer on (raw features, labels).

        Reports ROC AUC (0.5 = no ranking skill), the Brier score next to the Brier score
        of always predicting the training base rate, and the mean predicted probability
        against the realised hit rate (calibration in the large). Nothing here feeds back
        into trading; it measures whether the ranker carries information at all.
        """
        p = self.predict_raw(X_raw)
        if p is None:
            return {'n': 0 if X_raw is None else int(len(X_raw)),
                    'trained': self.signal_transformer is not None}
        return {'trained': True, **classifier_skill(y, p, self.training_summary.get('base_rate'))}

    def predict_raw(self, X_raw: np.ndarray):
        """P(profitable) for a batch of RAW feature vectors, or None if untrained/empty."""
        if self.signal_transformer is None or X_raw is None or len(X_raw) == 0:
            return None
        X = np.asarray(X_raw, dtype=np.float32)
        if self.scaler_fitted:
            X = self.scaler.transform(X).astype(np.float32)
        return self.signal_transformer.predict_proba(X)

    def get_pair_stats(self, pair_key):
        """Get pair statistics — uses real stored stats when available (v27 fix).
        Falls back to neutral defaults only when stats haven't been injected yet
        (e.g. before pair selection runs). Eliminates the training/serving skew
        where features[17-19] (correlation, half_life, quality_score) were always
        0.5/0.3/0.8 during transformer training but real values at inference time.
        """
        if isinstance(pair_key, tuple):
            pair_string = f"{pair_key[0]}-{pair_key[1]}"
        else:
            pair_string = str(pair_key)

        stored = self.pair_statistics.get(pair_string)
        if stored:
            return {
                'correlation':          stored.get('correlation', 0.5),
                'half_life':            stored.get('half_life', 30),
                'cointegration_pvalue': stored.get('cointegration_pvalue', 0.05),
                'quality_score':        stored.get('quality_score', 0.8),
            }
        return {
            'correlation': 0.5,
            'half_life': 30,
            'cointegration_pvalue': 0.05,
            'quality_score': 0.8
        }

    def fit_scaler(self, features_list: List[np.ndarray]):
        """Fit the RobustScaler, excluding rows with any |z| >= 3 feature when enough remain."""
        try:
            if len(features_list) > 0:
                all_features = np.vstack(features_list)
                # constant columns (e.g. a macro input that never moves) are expected here
                with np.errstate(invalid='ignore', divide='ignore'), warnings.catch_warnings():
                    warnings.simplefilter('ignore', RuntimeWarning)
                    z_scores = np.abs(stats.zscore(all_features, axis=0, nan_policy='omit'))
                z_scores = np.nan_to_num(z_scores, nan=0.0)   # constant columns -> not outliers
                mask = (z_scores < 3).all(axis=1)
                clean_features = all_features[mask]
                if len(clean_features) > 20:
                    self.scaler.fit(clean_features)
                else:
                    self.scaler.fit(all_features)
                self.scaler_fitted = True
                logger.info(f"Feature scaler fitted on {int(mask.sum())}/{len(all_features)} "
                            "rows after outlier removal")
        except Exception as e:
            logger.error(f"Scaler fitting error: {str(e)}")
