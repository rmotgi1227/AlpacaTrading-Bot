"""Tests for options/selector.py — spread filter behavior."""
import pytest
from unittest.mock import patch, MagicMock

import pandas as pd

from options.selector import select_option


def _make_chain(rows):
    """Build a DataFrame matching get_options_chain_in_dte_range output."""
    return pd.DataFrame(rows)


class TestSpreadFilter:
    @patch("options.selector.get_options_chain_in_dte_range")
    def test_wide_spreads_filtered_out(self, mock_chain):
        mock_chain.return_value = _make_chain([
            {"contractSymbol": "WIDE1", "strike": 100, "expiration": "2024-03-01",
             "bid": 1.0, "ask": 1.5, "openInterest": 500, "volume": 100,
             "delta": 0.35, "gamma": 0.01, "theta": -0.02, "vega": 0.05, "impliedVolatility": 0.30},
            {"contractSymbol": "TIGHT1", "strike": 105, "expiration": "2024-03-01",
             "bid": 2.0, "ask": 2.10, "openInterest": 1000, "volume": 200,
             "delta": 0.40, "gamma": 0.01, "theta": -0.02, "vega": 0.05, "impliedVolatility": 0.28},
        ])
        result = select_option("AAPL", "BUY_CALL", 10000)
        assert result is not None
        # WIDE1 spread = 0.50/1.25 = 40% > 10%, should be filtered
        # TIGHT1 spread = 0.10/2.05 ≈ 4.9% < 10%, should pass
        assert result["symbol"] == "TIGHT1"

    @patch("options.selector.get_options_chain_in_dte_range")
    def test_all_wide_returns_none(self, mock_chain):
        mock_chain.return_value = _make_chain([
            {"contractSymbol": "WIDE1", "strike": 100, "expiration": "2024-03-01",
             "bid": 1.0, "ask": 2.0, "openInterest": 500, "volume": 100,
             "delta": 0.35, "gamma": 0.01, "theta": -0.02, "vega": 0.05, "impliedVolatility": 0.30},
            {"contractSymbol": "WIDE2", "strike": 105, "expiration": "2024-03-01",
             "bid": 0.5, "ask": 1.0, "openInterest": 300, "volume": 50,
             "delta": 0.40, "gamma": 0.01, "theta": -0.02, "vega": 0.05, "impliedVolatility": 0.35},
        ])
        result = select_option("AAPL", "BUY_CALL", 10000)
        # Both have spread > 10%: WIDE1 = 66%, WIDE2 = 66%
        assert result is None

    @patch("options.selector.get_options_chain_in_dte_range")
    def test_best_by_liquidity_when_multiple_pass(self, mock_chain):
        mock_chain.return_value = _make_chain([
            {"contractSymbol": "LOW_LIQ", "strike": 100, "expiration": "2024-03-01",
             "bid": 2.0, "ask": 2.10, "openInterest": 200, "volume": 50,
             "delta": 0.35, "gamma": 0.01, "theta": -0.02, "vega": 0.05, "impliedVolatility": 0.30},
            {"contractSymbol": "HIGH_LIQ", "strike": 105, "expiration": "2024-03-01",
             "bid": 3.0, "ask": 3.15, "openInterest": 2000, "volume": 500,
             "delta": 0.40, "gamma": 0.01, "theta": -0.02, "vega": 0.05, "impliedVolatility": 0.28},
        ])
        result = select_option("AAPL", "BUY_CALL", 10000)
        assert result is not None
        # Both pass spread filter, HIGH_LIQ has higher OI+volume
        assert result["symbol"] == "HIGH_LIQ"

    @patch("options.selector.get_options_chain_in_dte_range")
    def test_empty_chain_returns_none(self, mock_chain):
        mock_chain.return_value = pd.DataFrame()
        result = select_option("AAPL", "BUY_CALL", 10000)
        assert result is None

    def test_invalid_signal_returns_none(self):
        result = select_option("AAPL", "HOLD", 10000)
        assert result is None
