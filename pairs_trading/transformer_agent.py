"""
TRANSFORMER ENCODER FOR PAIRS TRADING - TRANSFORMER AGENT
==========================================================
Transformer Enhanced Trading Agent for Financial Signal Prediction.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

from pairs_trading.config import (
    torch, nn, optim, np, logging
)
from pairs_trading.transformer_encoder import FinancialTransformerEncoder

logger = logging.getLogger(__name__)


class TransformerEnhancedTradingAgent:
    """Transformer Encoder for Financial Signal Prediction"""

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
        self.signal_predictions = []

        logger.info("TRANSFORMER-ENHANCED TRADING AGENT INITIALIZED")

    def predict_signal_quality(self, features: np.ndarray) -> float:
        """Use Transformer to predict signal quality"""
        self.transformer.eval()
        with torch.no_grad():
            if isinstance(features, np.ndarray):
                features = torch.FloatTensor(features).to(self.device)

            if len(features.shape) == 1:
                features = features.unsqueeze(0)

            output = self.transformer(features)
            quality_score = torch.sigmoid(output).item()

        return quality_score

    def train_on_batch(self, features_batch: np.ndarray, targets_batch: np.ndarray,
                       pos_weight: float = None):
        """Train Transformer on a batch of data.

        v26.1: optional pos_weight (= n_neg/n_pos) up-weights the rare class so an
        imbalanced label set trains a real model instead of collapsing to the prior.
        """
        self.transformer.train()

        features = torch.FloatTensor(features_batch).to(self.device)
        targets = torch.FloatTensor(targets_batch).to(self.device)

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
        """Extract attention weights for interpretability"""
        self.transformer.eval()
        with torch.no_grad():
            features = torch.FloatTensor(features).unsqueeze(0).to(self.device)
            _, attention_weights = self.transformer(features, return_attention=True)
        return attention_weights
