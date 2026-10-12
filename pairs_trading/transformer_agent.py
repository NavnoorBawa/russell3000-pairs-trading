"""
PAIRS TRADING - TRANSFORMER SCORER
==================================
Wraps the transformer encoder as a binary classifier (P(trade profitable)) with a
BCE training step and batched inference. Used for ranking only.

Architecture note (v32): each candidate is ONE 30-feature vector, which the encoder
treats as a sequence of length 1. Self-attention over a single token is a fixed linear
map (every attention weight is 1.0), so the network is functionally a deep residual MLP;
the "transformer" label describes the code, not a capability. get_attention_weights is
kept for completeness and returns those trivial weights.
"""

from pairs_trading.config import (
    torch, nn, np, logging
)
from pairs_trading.transformer_encoder import FinancialTransformerEncoder

logger = logging.getLogger(__name__)


class TransformerEnhancedTradingAgent:
    """Transformer-encoder binary classifier for signal quality."""

    def __init__(self, state_dim: int = 20):
        self.state_dim = state_dim
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        self.transformer = FinancialTransformerEncoder(
            input_dim=state_dim,
            d_model=256,
            nhead=8,
            num_layers=6,
            dim_feedforward=1024,
            dropout=0.1,
            output_dim=1
        ).to(self.device)

        self.optimizer = torch.optim.AdamW(
            self.transformer.parameters(),
            lr=0.0001,
            weight_decay=0.01
        )

        self.training_losses = []
        # v32: weighted BCE (pos_weight = w) moves the fitted log-odds by +log(w). The
        # prior-correction offset -log(w) is set by the trainer and applied at inference
        # so the score is an estimate of P(profitable), not of a re-weighted probability.
        self.logit_offset = 0.0

        logger.info("Transformer signal-quality scorer initialised")

    def _as_batch(self, features) -> 'torch.Tensor':
        x = torch.as_tensor(np.asarray(features, dtype=np.float32), device=self.device)
        return x.unsqueeze(0) if x.dim() == 1 else x

    def predict_logits(self, features: np.ndarray, batch_size: int = 4096) -> np.ndarray:
        """Calibrated logits for one vector (shape [n_features]) or a batch ([n, n_features])."""
        self.transformer.eval()
        x = self._as_batch(features)
        out = []
        with torch.no_grad():
            for i in range(0, x.shape[0], batch_size):
                out.append(self.transformer(x[i:i + batch_size]).reshape(-1).cpu().numpy())
        return np.concatenate(out).astype(float) + self.logit_offset

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """P(profitable) for a batch of scaled feature vectors."""
        return 1.0 / (1.0 + np.exp(-self.predict_logits(features)))

    def predict_signal_quality(self, features: np.ndarray) -> float:
        """P(profitable) for a single scaled feature vector."""
        return float(self.predict_proba(features)[0])

    def train_on_batch(self, features_batch: np.ndarray, targets_batch: np.ndarray,
                       pos_weight: float = None):
        """One AdamW step of (optionally class-weighted) BCE on a batch.

        v26.1: optional pos_weight (= n_neg/n_pos) up-weights the rare class so an
        imbalanced label set trains a real model instead of collapsing to the prior.
        """
        self.transformer.train()

        features = self._as_batch(features_batch)
        targets = torch.as_tensor(np.asarray(targets_batch, dtype=np.float32), device=self.device)

        predictions = self.transformer(features).squeeze(-1)
        pw = torch.tensor(pos_weight, device=self.device) if pos_weight is not None else None
        loss = nn.functional.binary_cross_entropy_with_logits(predictions, targets, pos_weight=pw)

        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.transformer.parameters(), max_norm=1.0)
        self.optimizer.step()

        self.training_losses.append(loss.item())

        return loss.item()

    def get_attention_weights(self, features: np.ndarray):
        """Per-layer attention weights for one vector or a batch (trivial: one token)."""
        self.transformer.eval()
        with torch.no_grad():
            _, attention_weights = self.transformer(self._as_batch(features), return_attention=True)
        return attention_weights
