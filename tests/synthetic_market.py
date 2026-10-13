"""Re-export of pairs_trading.synthetic (the synthetic market moved into the package in
v32 so scripts/synthetic_validation.py can use it without importing the test suite)."""
from pairs_trading.synthetic import (SECTOR_ETFS, _ohlcv, build_system, make_market, perturb_after,
                                     perturb_macro_after)

__all__ = ['SECTOR_ETFS', '_ohlcv', 'build_system', 'make_market', 'perturb_after', 'perturb_macro_after']
