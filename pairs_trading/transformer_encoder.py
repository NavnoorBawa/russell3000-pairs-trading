"""
TRANSFORMER ENCODER FOR PAIRS TRADING - TRANSFORMER ARCHITECTURE
=================================================================
Positional Encoding, Transformer Encoder Layer, and Financial Transformer Encoder.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

from pairs_trading.config import (
    torch, nn, math, logging, np
)

logger = logging.getLogger(__name__)


class PositionalEncoding(nn.Module):
    """Positional Encoding for Transformer to handle time series sequences"""

    def __init__(self, d_model: int, max_len: int = 5000, dropout: float = 0.1):
        super(PositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))

        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)

        self.register_buffer('pe', pe)

    def forward(self, x):
        x = x + self.pe[:, :x.size(1), :]
        return self.dropout(x)


class TransformerEncoderLayer(nn.Module):
    """Single Transformer Encoder Layer with Multi-Head Attention"""

    def __init__(self, d_model: int, nhead: int, dim_feedforward: int = 2048,
                 dropout: float = 0.1):
        super(TransformerEncoderLayer, self).__init__()

        self.self_attn = nn.MultiheadAttention(d_model, nhead, dropout=dropout, batch_first=True)

        self.linear1 = nn.Linear(d_model, dim_feedforward)
        self.dropout = nn.Dropout(dropout)
        self.linear2 = nn.Linear(dim_feedforward, d_model)

        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)

        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)

        self.activation = nn.GELU()

    def forward(self, src, src_mask=None, src_key_padding_mask=None):
        src2, attention_weights = self.self_attn(src, src, src,
                                                 attn_mask=src_mask,
                                                 key_padding_mask=src_key_padding_mask)
        src = src + self.dropout1(src2)
        src = self.norm1(src)

        src2 = self.linear2(self.dropout(self.activation(self.linear1(src))))
        src = src + self.dropout2(src2)
        src = self.norm2(src)

        return src, attention_weights


class FinancialTransformerEncoder(nn.Module):
    """Complete Transformer Encoder for Financial Time Series"""

    def __init__(self, input_dim: int, d_model: int = 128, nhead: int = 8,
                 num_layers: int = 4, dim_feedforward: int = 512,
                 dropout: float = 0.1, output_dim: int = 3):
        super(FinancialTransformerEncoder, self).__init__()

        self.input_dim = input_dim
        self.d_model = d_model
        self.nhead = nhead
        self.num_layers = num_layers

        self.input_projection = nn.Linear(input_dim, d_model)
        self.positional_encoding = PositionalEncoding(d_model, dropout=dropout)

        self.encoder_layers = nn.ModuleList([
            TransformerEncoderLayer(d_model, nhead, dim_feedforward, dropout)
            for _ in range(num_layers)
        ])

        self.global_pool = nn.AdaptiveAvgPool1d(1)
        self.fc1 = nn.Linear(d_model, d_model // 2)
        self.fc2 = nn.Linear(d_model // 2, output_dim)

        self.dropout = nn.Dropout(dropout)
        self.activation = nn.GELU()
        self.norm = nn.LayerNorm(d_model)

        self._init_weights()

        logger.info(f"Initialized Transformer Encoder: d_model={d_model}, nhead={nhead}, "
                   f"num_layers={num_layers}, input_dim={input_dim}")

    def _init_weights(self):
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def forward(self, x, return_attention=False):
        if len(x.shape) == 2:
            x = x.unsqueeze(1)

        batch_size, seq_len, _ = x.shape

        x = self.input_projection(x)
        x = self.positional_encoding(x)

        attention_weights_list = []
        for encoder_layer in self.encoder_layers:
            x, attn_weights = encoder_layer(x)
            if return_attention:
                attention_weights_list.append(attn_weights)

        x = self.norm(x)

        x = x.transpose(1, 2)
        x = self.global_pool(x).squeeze(-1)

        x = self.dropout(x)
        x = self.activation(self.fc1(x))
        x = self.dropout(x)
        output = self.fc2(x)

        if return_attention:
            return output, attention_weights_list
        return output

    def get_embeddings(self, x):
        if len(x.shape) == 2:
            x = x.unsqueeze(1)

        x = self.input_projection(x)
        x = self.positional_encoding(x)

        for encoder_layer in self.encoder_layers:
            x, _ = encoder_layer(x)

        x = self.norm(x)
        x = x.transpose(1, 2)
        x = self.global_pool(x).squeeze(-1)

        return x
