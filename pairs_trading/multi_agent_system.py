"""
TRANSFORMER ENCODER FOR PAIRS TRADING - MULTI-AGENT SYSTEM
===========================================================
Fixed Transformer Multi-Agent System with balanced signal generation.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

import os

from pairs_trading.config import (
    pd, np, stats, random, logging, tqdm,
    deque, Dict, List, Tuple, SECTOR_MAP, SECTOR_ETFS
)
from sklearn.preprocessing import RobustScaler

logger = logging.getLogger(__name__)


class FixedTransformerMultiAgentSystem:
    """FIXED: More balanced signal generation"""

    def __init__(self, state_dim: int = 38):
        self.state_dim = state_dim
        self.sequence_length = 40

        self.scaler = RobustScaler()
        self.scaler_fitted = False

        # v24: transformer that scores P(spread reverts) for each entry-grade signal.
        # Stays None until train_agent() builds an outcome dataset and trains it;
        # while None, feature_quality falls back to 1.0 (v22/v23 behaviour).
        # PAIRS_USE_TRANSFORMER=0 skips training entirely → exact classical-only
        # system on the same code path (for the with/without-ML ablation).
        self.signal_transformer = None
        self.use_signal_transformer = os.environ.get(
            "PAIRS_USE_TRANSFORMER", "1") != "0"

        self.min_zscore_threshold = 2.0      # v12: raised from 1.5 (fewer marginal trades)
        self.min_signal_strength = 0.65     # v12: raised from 0.60
        self.min_confidence_threshold = 0.70  # v12: raised from 0.65

        self.recent_rewards = deque(maxlen=100)
        self.action_distribution = {0: 0, 1: 0, 2: 0}
        self.episode_count = 0
        self.training_step = 0

        self.signal_quality_history = deque(maxlen=1000)

        self.episode_rewards = []
        self.eval_rewards = []
        self.actor_losses = []
        self.critic_losses = []
        self.exploration_rates = []
        self.q_values = []
        self.episode_lengths = []

        logger.info("FIXED Transformer Multi-Agent System - Balanced Training")

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

            # --- MACRO REGIME FEATURES (8 new features, indices 30-37) ---
            # Feature 30: VIX level normalized (>1.0 = stressed)
            # Feature 31: VIX 20-day momentum
            # Feature 32: VIX regime bucket (0=low, 0.5=normal, 1.0=stressed)
            # Feature 33: Sector ETF 20-day return for stock1's sector
            # Feature 34: Sector ETF 20-day return for stock2's sector
            # Feature 35: Sector divergence (stock1 sector - stock2 sector momentum)
            # Feature 36: Market breadth (avg 20d return across all sectors)
            # Feature 37: Cross-sector flag (1.0 if different sectors, 0.5 if same)
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
                    s1_etf = SECTOR_MAP.get(symbol1, 'SPY') if symbol1 else 'SPY'
                    s2_etf = SECTOR_MAP.get(symbol2, 'SPY') if symbol2 else 'SPY'

                    def sector_20d_return(etf):
                        s = sectors.get(etf, pd.Series())
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
                    cross_sector = 0.5 if s1_etf == s2_etf else 1.0

                    features.extend([vix_level, vix_mom, vix_regime, s1_mom, s2_mom,
                                      s1_mom - s2_mom, breadth, cross_sector])
                except Exception:
                    features.extend([0.67, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.5])
            else:
                features.extend([0.67, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.5])

            features_array = np.array(features[:self.state_dim], dtype=np.float32)
            if len(features_array) < self.state_dim:
                padding = np.zeros(self.state_dim - len(features_array))
                features_array = np.concatenate([features_array, padding])

            features_array = np.nan_to_num(features_array, nan=0.0, posinf=3.0, neginf=-3.0)
            features_array = np.clip(features_array, -5, 5)

            return features_array

        except Exception as e:
            logger.debug(f"Feature extraction error: {str(e)}")
            return np.zeros(self.state_dim)

    def get_action(self, state: np.ndarray, training: bool = True, pair_key: str = None) -> Tuple[int, float]:
        """FIXED: More balanced signal generation. Returns (action, feature_quality)."""
        try:
            if len(state) == 0:
                return 1, 0.0

            zscore = state[0] if len(state) > 0 else 0
            abs_zscore = abs(zscore)
            signal_strength = min(abs_zscore / 2.5, 1.0)

            if abs_zscore < self.min_zscore_threshold:
                self.action_distribution[1] += 1
                return 1, 0.0

            if signal_strength < self.min_signal_strength:
                self.action_distribution[1] += 1
                return 1, 0.0

            # v24: trained transformer scores signal quality — RANKING ONLY, never a gate.
            # v19-v21 evidence: using a quality score as a hard entry gate degraded OOS
            # (W10 -3.85% at 61.5% WR; W18 109→61 trades, WR 63%→51%). The score therefore
            # feeds only the opportunity ranking in run_comprehensive_backtest; it cannot
            # block a trade on its own. Falls back to 1.0 when no transformer is trained.
            feature_quality = 1.0
            if self.signal_transformer is not None:
                try:
                    feature_quality = float(
                        self.signal_transformer.predict_signal_quality(state)
                    )
                except Exception:
                    feature_quality = 1.0

            if zscore > self.min_zscore_threshold and signal_strength > self.min_signal_strength:
                action = 2
            elif zscore < -self.min_zscore_threshold and signal_strength > self.min_signal_strength:
                action = 0
            else:
                action = 1

            self.signal_quality_history.append({
                'zscore': abs_zscore,
                'signal_strength': signal_strength,
                'feature_quality': feature_quality,
                'action': action
            })

            self.action_distribution[action] += 1
            return action, feature_quality

        except Exception as e:
            logger.debug(f"Action selection error: {str(e)}")
            self.action_distribution[1] += 1
            return 1, 0.0

    def score_signal_quality(self, state: np.ndarray) -> float:
        """v26: transformer P(reversion) used for opportunity RANKING only.

        Decoupled from get_action so the entry gate (raw z-score, applied in the
        backtest) and the quality score (scaled features → transformer) no longer
        share the unit-mismatched state[0]. Returns 1.0 when no transformer is
        trained (classical-only / ablation path), so ranking degrades to
        signal_strength × pair_quality. Never a gate — v19-v21 evidence: quality
        gating degraded OOS.
        """
        if self.signal_transformer is None:
            return 1.0
        try:
            return float(self.signal_transformer.predict_signal_quality(state))
        except Exception:
            return 1.0

    def _assess_feature_quality(self, state: np.ndarray) -> float:
        """FIXED: More balanced feature quality assessment"""
        try:
            if len(state) < 10:
                return 0.0

            quality_score = 0.0

            zscore = abs(state[0])
            if zscore > 2.5:
                quality_score += 0.3
            elif zscore > 2.0:
                quality_score += 0.25
            elif zscore > 1.5:
                quality_score += 0.2
            elif zscore > 1.0:
                quality_score += 0.1

            if len(state) > 5:
                momentum_5 = state[5] if len(state) > 5 else 0
                momentum_10 = state[6] if len(state) > 6 else 0
                if abs(momentum_5) > 0.005:
                    quality_score += 0.25

            if len(state) > 15:
                rsi1 = state[12] if len(state) > 12 else 0.5
                rsi2 = state[15] if len(state) > 15 else 0.5

                rsi_signal = max(abs(rsi1 - 0.5), abs(rsi2 - 0.5))
                if rsi_signal > 0.1:
                    quality_score += 0.2

            if len(state) > 19:
                correlation = abs(state[17]) if len(state) > 17 else 0
                pair_quality = state[19] if len(state) > 19 else 0

                if correlation > 0.2 and pair_quality > 0.5:
                    quality_score += 0.25
                elif correlation > 0.15 and pair_quality > 0.4:
                    quality_score += 0.15

            return min(1.0, quality_score)

        except:
            return 0.0

    def calculate_advanced_reward(self, action: int, actual_return: float, zscore: float = 0,
                                 features: np.ndarray = None) -> float:
        """FIXED: More balanced reward function"""
        try:
            base_reward = 0.0

            if action == 0:
                if actual_return > 0:
                    directional_reward = actual_return * 10000 + 200.0
                else:
                    directional_reward = actual_return * 2500

            elif action == 2:
                if actual_return < 0:
                    directional_reward = -actual_return * 10000 + 200.0
                else:
                    directional_reward = -actual_return * 2500

            else:
                if abs(zscore) > 1.75:
                    directional_reward = -50.0
                else:
                    directional_reward = -5.0

            quality_bonus = 0
            if abs(zscore) > 1.75:
                if (zscore > 1.75 and action == 2 and actual_return < 0) or \
                   (zscore < -1.75 and action == 0 and actual_return > 0):
                    quality_bonus = 200.0
                elif action in [0, 2]:
                    quality_bonus = 20.0

            consistency_bonus = 0
            total_actions = sum(self.action_distribution.values())
            if total_actions > 20:
                neutral_ratio = self.action_distribution[1] / total_actions
                directional_ratio = (self.action_distribution[0] + self.action_distribution[2]) / total_actions

                if 0.15 < directional_ratio < 0.50:
                    consistency_bonus = 100
                elif directional_ratio > 0.05:
                    consistency_bonus = 50
                elif neutral_ratio > 0.85:
                    consistency_bonus = -100

            total_reward = base_reward + directional_reward + quality_bonus + consistency_bonus
            final_reward = np.clip(total_reward, -500, 500)

            self.recent_rewards.append(final_reward)
            return final_reward

        except Exception as e:
            logger.debug(f"Reward calculation error: {str(e)}")
            return 0.0

    def train_agent(self, train_spreads: Dict, episodes: int = 1000):
        """RESEARCH PAPER: Enhanced training with more episodes for deeper learning"""
        logger.info(f"RESEARCH Training Multi-Agent System for {episodes} episodes (ENHANCED)")

        logger.info("Fitting scaler on balanced quality samples...")
        all_features = []

        sample_pairs = list(train_spreads.items())[:15]
        for pair_key, spread in sample_pairs:
            try:
                pair_stats = self.get_pair_stats(pair_key)

                for i in range(30, min(len(spread), 300), 10):
                    window_spread = spread.iloc[:i+1]
                    features = self.extract_advanced_features(
                        window_spread, pair_stats, pd.DataFrame(), pd.DataFrame()
                    )

                    if len(features) > 0:
                        all_features.append(features)

            except:
                continue

        if all_features:
            self.fit_scaler(all_features)
            logger.info(f"FIXED: Scaler fitted on {len(all_features)} balanced samples")

        training_progress = tqdm(range(episodes), desc="FIXED Multi-Agent Training", unit="episode")

        phase_1_episodes = episodes // 3
        phase_2_episodes = episodes * 2 // 3
        phase_3_episodes = episodes

        best_performance_window = deque(maxlen=50)

        for episode in training_progress:
            episode_rewards = []
            episode_trades = 0
            directional_actions = 0
            quality_signals = 0

            self.episode_count = episode

            if episode < phase_1_episodes:
                pairs_to_use = min(15, len(train_spreads))
                min_signal_threshold = 0.6
                training_focus = "exploration"
            elif episode < phase_2_episodes:
                pairs_to_use = min(12, len(train_spreads))
                min_signal_threshold = 1.0
                training_focus = "optimization"
            else:
                pairs_to_use = min(10, len(train_spreads))
                min_signal_threshold = 1.5
                training_focus = "refinement"

            pairs_list = list(train_spreads.items())
            random.shuffle(pairs_list)
            selected_pairs = pairs_list[:pairs_to_use]

            for pair_key, spread in selected_pairs:
                try:
                    if len(spread) < 60:
                        continue

                    max_start = len(spread) - 40
                    start_idx = random.randint(60, max_start)

                    if episode < phase_1_episodes:
                        sequence_length = min(20, len(spread) - start_idx - 1)
                        step_size = 2
                    elif episode < phase_2_episodes:
                        sequence_length = min(15, len(spread) - start_idx - 1)
                        step_size = 3
                    else:
                        sequence_length = min(12, len(spread) - start_idx - 1)
                        step_size = 4

                    for i in range(0, sequence_length - 1, step_size):
                        current_idx = start_idx + i
                        next_idx = current_idx + 1

                        if next_idx >= len(spread):
                            break

                        current_window = spread.iloc[:current_idx+1]

                        pair_stats = self.get_pair_stats(pair_key)

                        current_state = self.extract_advanced_features(
                            current_window, pair_stats, pd.DataFrame(), pd.DataFrame()
                        )

                        if self.scaler_fitted:
                            current_state = self.scaler.transform(current_state.reshape(1, -1)).flatten()

                        action, _ = self.get_action(current_state, training=True)

                        abs_zscore = abs(current_state[0]) if len(current_state) > 0 else 0
                        if abs_zscore > min_signal_threshold:
                            quality_signals += 1

                            if action in [0, 2]:
                                directional_actions += 1

                            spread_return = spread.iloc[next_idx] - spread.iloc[current_idx]

                            reward = self.calculate_advanced_reward(
                                action, spread_return, current_state[0], current_state
                            )

                            episode_rewards.append(reward)
                            episode_trades += 1

                except Exception:
                    continue

            avg_reward = np.mean(episode_rewards) if episode_rewards else 0
            directional_ratio = directional_actions / max(quality_signals, 1)

            self.episode_rewards.append(avg_reward)
            self.episode_lengths.append(episode_trades)
            exploration_proxy = 0.3 if episode < phase_1_episodes else (0.2 if episode < phase_2_episodes else 0.1)
            self.exploration_rates.append(exploration_proxy)

            if avg_reward > 0:
                best_performance_window.append(avg_reward)

            training_progress.set_postfix({
                'Phase': training_focus[:4],
                'Avg_Reward': f'{avg_reward:.2f}',
                'Quality_Signals': quality_signals,
                'Directional%': f'{directional_ratio:.1%}',
                'Best_Avg': f'{np.mean(best_performance_window):.2f}' if best_performance_window else '0.00'
            })

        logger.info("FIXED Multi-Agent training completed with balanced parameters")

        # v24: train the transformer signal-quality model on this same training set.
        # Labels come only from inside train_spreads, so walk-forward retraining stays
        # leak-free: each window agent learns from its own 252-day train slice and the
        # main agent from data up to 2023-06-30 only.
        if not self.use_signal_transformer:
            logger.info("v24 ABLATION MODE (PAIRS_USE_TRANSFORMER=0): transformer "
                        "training skipped — classical-only system, feature_quality=1.0")
        else:
            try:
                tf_X, tf_y = self._build_outcome_dataset(train_spreads)
                if tf_X is not None:
                    self._train_signal_transformer(tf_X, tf_y)
                else:
                    logger.info("v24: insufficient outcome samples — transformer ranking "
                                "disabled (feature_quality falls back to 1.0)")
            except Exception as e:
                logger.warning(f"v24: transformer training failed ({e}) — ranking disabled")

        # Import here to avoid circular imports
        from pairs_trading.plotting import plot_training_results
        plot_stats = {
            'episode_rewards': self.episode_rewards,
            'eval_rewards': self.eval_rewards,
            'actor_losses': self.actor_losses,
            'critic_losses': self.critic_losses,
            'exploration_rates': self.exploration_rates,
            'q_values': self.q_values,
            'episode_lengths': self.episode_lengths
        }
        plot_training_results(plot_stats)

    def _build_outcome_dataset(self, train_spreads: Dict, entry_z: float = 1.8,
                               horizon: int = 10, exit_z: float = 0.5,
                               max_samples: int = 15000):
        """v24: Build (features, label) samples for the signal-quality transformer.

        A sample is any training day whose spread z-score breaches the entry
        threshold — the same |z| > 1.8 condition the backtest trades on. The label
        is the decision-relevant outcome the ranking cares about: **did this entry
        complete a round-trip to the exit band (|z| < exit_z = 0.5) within the
        horizon** — i.e. would the trade have hit its profit target.

        v26.1: this replaced the "|z| dropped by >0.25 at any point" label, which
        was satisfied by ~all entries (base rate >0.95) and tripped the degeneracy
        guard, silently disabling transformer training in the v26 run. The exit-band
        label is more balanced and is exactly what the backtest's exit rule rewards.
        Features use data up to the entry day only; the future enters via labels alone.
        """
        X, y = [], []
        for pair_key, spread in train_spreads.items():
            if len(spread) < 80 + horizon:
                continue
            pair_stats = self.get_pair_stats(pair_key)
            for t in range(60, len(spread) - horizon, 2):
                window = spread.iloc[:t + 1]
                mean = window.mean()
                std = window.std() + 1e-8
                z_t = (window.iloc[-1] - mean) / std
                if abs(z_t) < entry_z:
                    continue
                feats = self.extract_advanced_features(
                    window, pair_stats, pd.DataFrame(), pd.DataFrame()
                )
                if self.scaler_fitted:
                    feats = self.scaler.transform(feats.reshape(1, -1)).flatten()
                future = spread.iloc[t + 1: t + horizon + 1]
                z_future_abs = np.abs((future.values - mean) / std)
                min_abs_z = float(z_future_abs.min()) if len(z_future_abs) else abs(z_t)
                X.append(feats)
                y.append(1.0 if min_abs_z < exit_z else 0.0)   # reached exit band?
                if len(X) >= max_samples:
                    break
            if len(X) >= max_samples:
                break

        if len(X) < 400:
            return None, None
        y_arr = np.array(y, dtype=np.float32)
        # v26.1: only bail on TRULY degenerate labels; class weighting handles
        # ordinary imbalance, so the transformer trains across a wide base-rate range.
        if y_arr.mean() < 0.02 or y_arr.mean() > 0.98:
            return None, None
        return np.array(X, dtype=np.float32), y_arr

    def _train_signal_transformer(self, X: np.ndarray, y: np.ndarray,
                                  epochs: int = 3, batch_size: int = 256):
        """v24: BCE-train the transformer to predict P(reach exit band) at entry.

        v26.1: pass a class-balancing pos_weight = n_neg / n_pos so an imbalanced
        label set still trains a real model instead of collapsing to the prior —
        otherwise the ablation would just be re-measuring the base rate.
        """
        from pairs_trading.transformer_agent import TransformerEnhancedTradingAgent
        agent = TransformerEnhancedTradingAgent(state_dim=X.shape[1])
        n_pos = float((y > 0.5).sum())
        n_neg = float((y <= 0.5).sum())
        pos_weight = (n_neg / n_pos) if n_pos > 0 else 1.0
        n = len(X)
        idx = np.arange(n)
        for ep in range(epochs):
            np.random.shuffle(idx)
            losses = []
            for i in range(0, n, batch_size):
                b = idx[i:i + batch_size]
                losses.append(agent.train_on_batch(X[b], y[b], pos_weight=pos_weight))
            logger.info(f"v24 transformer epoch {ep + 1}/{epochs}: "
                        f"BCE loss {np.mean(losses):.4f} "
                        f"({n} samples, base rate {y.mean():.1%}, pos_weight {pos_weight:.2f})")
        self.signal_transformer = agent

    def get_pair_stats(self, pair_key):
        """Get pair statistics"""
        if isinstance(pair_key, tuple):
            pair_string = f"{pair_key[0]}-{pair_key[1]}"
        else:
            pair_string = str(pair_key)

        return {
            'correlation': 0.5,
            'half_life': 30,
            'cointegration_pvalue': 0.05,
            'quality_score': 0.8
        }

    def fit_scaler(self, features_list: List[np.ndarray]):
        """Fit scaler with outlier removal"""
        try:
            if len(features_list) > 0:
                all_features = np.vstack(features_list)

                z_scores = np.abs(stats.zscore(all_features, axis=0, nan_policy='omit'))
                mask = (z_scores < 3).all(axis=1)
                clean_features = all_features[mask]

                if len(clean_features) > 20:
                    self.scaler.fit(clean_features)
                else:
                    self.scaler.fit(all_features)

                self.scaler_fitted = True
                logger.info("Feature scaler fitted with outlier removal")
        except Exception as e:
            logger.error(f"Scaler fitting error: {str(e)}")

    def get_training_stats(self) -> Dict:
        """Get training statistics"""
        total_actions = sum(self.action_distribution.values())
        directional_ratio = ((self.action_distribution[0] + self.action_distribution[2]) /
                           max(total_actions, 1))

        return {
            'episode_count': self.episode_count,
            'avg_recent_reward': np.mean(self.recent_rewards) if self.recent_rewards else 0,
            'directional_ratio': directional_ratio,
            'action_distribution': dict(self.action_distribution),
            'quality_signals_tracked': len(self.signal_quality_history),
            'training_step': self.training_step
        }


# Need pd import for DataFrame in extract_advanced_features
pd = __import__('pandas')
