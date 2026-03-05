"""Tests for bot.py — real-time price re-fetch gate in run_signal_scan()."""
import logging
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from bot import run_signal_scan


def _make_account_info(value=10000):
    return {
        "portfolio_value": value,
        "buying_power": value,
        "positions": [],
    }


def _make_signal(signal="BUY_CALL", score=2):
    return {"signal": signal, "score": score}


def _make_contract(symbol="AAPL240119C00100000", ask=2.50):
    return {
        "symbol": symbol,
        "underlying": "AAPL",
        "strike": 100,
        "expiration": "2024-01-19",
        "option_type": "call",
        "estimated_cost": ask,
        "bid": ask - 0.10,
        "ask": ask,
        "greeks": {},
        "open_interest": 500,
    }


@pytest.fixture
def scan_patches():
    """Common patches for run_signal_scan. Returns dict of mocks."""
    with (
        patch("bot._is_market_day", return_value=True),
        patch("bot._last_premarket_scan_date", new=None),
        patch("bot.run_premarket_scan"),
        patch("bot.get_account_info") as mock_info,
        patch("bot.get_daily_bars") as mock_daily,
        patch("bot.get_4hr_bars") as mock_4hr,
        patch("bot.calculate_signals") as mock_signals,
        patch("bot.record_signal"),
        patch("bot.llm_filter_signal") as mock_llm,
        patch("bot.can_open_position", return_value=True),
        patch("bot.select_option") as mock_select,
        patch("bot.calculate_position_size", return_value=1),
        patch("bot.place_option_order") as mock_place,
        patch("bot.get_option_quote") as mock_quote,
        patch("bot.track_positions"),
        patch("bot.register_position_opened"),
        patch("bot.record_trade"),
        patch("bot._daily_watchlist", new=["AAPL"]),
    ):
        mock_info.return_value = _make_account_info()
        mock_daily.return_value = pd.DataFrame()
        mock_4hr.return_value = pd.DataFrame()
        mock_signals.return_value = _make_signal()
        mock_llm.return_value = {"approved": True, "reasoning": "test"}
        mock_select.return_value = _make_contract()
        mock_place.return_value = {"id": "order1", "status": "accepted"}

        yield {
            "info": mock_info,
            "select": mock_select,
            "place": mock_place,
            "quote": mock_quote,
        }


class TestPriceRefetch:
    def test_deviation_aborts_trade(self, scan_patches, caplog):
        """If RT price deviates > 3% from stale, trade should be aborted."""
        scan_patches["quote"].return_value = {
            "bid": 3.00, "ask": 3.10, "mid": 3.05,
            "spread": 0.10, "spread_pct": 0.03, "timestamp": None,
        }
        # stale cost = 2.50, rt ask = 3.10 => deviation = 24% > 3%
        with caplog.at_level(logging.INFO):
            run_signal_scan()
        scan_patches["place"].assert_not_called()
        assert any("ABORT" in r.message and "deviation" in r.message for r in caplog.records)

    def test_spread_aborts_trade(self, scan_patches, caplog):
        """If RT spread > MAX_SPREAD_PCT, trade should be aborted."""
        scan_patches["quote"].return_value = {
            "bid": 2.00, "ask": 2.80, "mid": 2.40,
            "spread": 0.80, "spread_pct": 0.333, "timestamp": None,
        }
        with caplog.at_level(logging.INFO):
            run_signal_scan()
        scan_patches["place"].assert_not_called()
        assert any("ABORT" in r.message and "spread" in r.message for r in caplog.records)

    def test_none_quote_falls_back_to_stale(self, scan_patches, caplog):
        """If RT quote fails, should use stale price and place order."""
        scan_patches["quote"].return_value = None

        with caplog.at_level(logging.WARNING):
            run_signal_scan()
        scan_patches["place"].assert_called_once()
        # Verify the stale price was used
        call_kwargs = scan_patches["place"].call_args
        assert call_kwargs.kwargs.get("limit_price") == 2.50 or call_kwargs[1].get("limit_price") == 2.50

    def test_valid_quote_uses_rt_ask(self, scan_patches):
        """If RT quote is valid and passes gates, should use RT ask as limit price."""
        scan_patches["quote"].return_value = {
            "bid": 2.45, "ask": 2.55, "mid": 2.50,
            "spread": 0.10, "spread_pct": 0.04, "timestamp": None,
        }
        run_signal_scan()
        scan_patches["place"].assert_called_once()
        call_kwargs = scan_patches["place"].call_args
        limit = call_kwargs.kwargs.get("limit_price") or call_kwargs[1].get("limit_price")
        assert limit == 2.55  # RT ask, not stale 2.50
