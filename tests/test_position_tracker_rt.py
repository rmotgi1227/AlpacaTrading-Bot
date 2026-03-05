"""
Tests for real-time bid price usage in track_positions().
Verifies that exit decisions use the RT bid (actual sellable price)
instead of the stale mark price from the position object.
"""
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is importable
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from trading.position_tracker import track_positions


def _make_position(symbol: str, current_price: float, cost_basis: float, qty: int = 1):
    """Helper: dict mimicking an Alpaca position object."""
    return {
        "symbol": symbol,
        "current_price": str(current_price),
        "cost_basis": str(cost_basis),
        "market_value": str(current_price * qty * 100),
        "unrealized_pl": str((current_price - cost_basis / (qty * 100)) * qty * 100),
        "qty": str(qty),
    }


# Patch targets
_ACCOUNT = "trading.position_tracker.get_account_info"
_QUOTES = "trading.position_tracker.get_option_quotes_batch"
_SHOULD_EXIT = "trading.position_tracker.should_exit"
_CLOSE = "trading.position_tracker.close_position_limit"
_OPEN_DATE = "trading.position_tracker.get_position_open_date"


@patch(_OPEN_DATE, return_value=datetime.utcnow() - timedelta(days=2))
@patch(_CLOSE, return_value=True)
@patch(_SHOULD_EXIT)
@patch(_QUOTES)
@patch(_ACCOUNT)
def test_exit_triggered_using_rt_bid(mock_account, mock_quotes, mock_exit, mock_close, mock_open_date):
    """Exit decision should use the RT bid, not the stale position price."""
    pos = _make_position("AAPL250321C00200000", current_price=5.00, cost_basis=300.0)

    mock_account.return_value = {
        "positions": [pos],
        "portfolio_value": 10000,
        "buying_power": 5000,
        "cash": 5000,
    }
    # RT bid is $6.50 — different from stale $5.00
    mock_quotes.return_value = {
        "AAPL250321C00200000": {"bid": 6.50, "ask": 7.00, "mid": 6.75},
    }
    mock_exit.return_value = (True, "take_profit")

    actions = track_positions()

    # should_exit must have been called with the RT bid ($6.50), not position price ($5.00)
    mock_exit.assert_called_once()
    call_kwargs = mock_exit.call_args
    assert call_kwargs[1]["current_price"] == 6.50


@patch(_OPEN_DATE, return_value=datetime.utcnow() - timedelta(days=2))
@patch(_CLOSE, return_value=True)
@patch(_SHOULD_EXIT)
@patch(_QUOTES)
@patch(_ACCOUNT)
def test_rt_bid_below_tp_prevents_exit(mock_account, mock_quotes, mock_exit, mock_close, mock_open_date):
    """If stale price says +20% but RT bid says only +10%, should_exit gets the lower bid
    and (assuming threshold is 20%) won't trigger take-profit."""
    pos = _make_position("AAPL250321C00200000", current_price=3.60, cost_basis=300.0)

    mock_account.return_value = {"positions": [pos], "portfolio_value": 10000, "buying_power": 5000, "cash": 5000}
    # RT bid is only $3.20 — below the stale $3.60
    mock_quotes.return_value = {
        "AAPL250321C00200000": {"bid": 3.20, "ask": 3.50, "mid": 3.35},
    }
    mock_exit.return_value = (False, "")

    actions = track_positions()

    # should_exit called with the lower RT bid
    mock_exit.assert_called_once()
    assert mock_exit.call_args[1]["current_price"] == 3.20
    # No exit → close_position_limit should NOT be called
    mock_close.assert_not_called()
    assert actions == []


@patch(_OPEN_DATE, return_value=datetime.utcnow() - timedelta(days=2))
@patch(_CLOSE, return_value=True)
@patch(_SHOULD_EXIT)
@patch(_QUOTES)
@patch(_ACCOUNT)
def test_fallback_to_position_price_when_no_rt_quote(mock_account, mock_quotes, mock_exit, mock_close, mock_open_date):
    """When RT quote is missing for a symbol, fall back to position's current_price."""
    pos = _make_position("AAPL250321C00200000", current_price=4.00, cost_basis=300.0)

    mock_account.return_value = {"positions": [pos], "portfolio_value": 10000, "buying_power": 5000, "cash": 5000}
    # No RT quote for this symbol
    mock_quotes.return_value = {}
    mock_exit.return_value = (True, "stop_loss")

    actions = track_positions()

    # should_exit called with the fallback position price ($4.00)
    mock_exit.assert_called_once()
    assert mock_exit.call_args[1]["current_price"] == 4.00
    assert len(actions) == 1


@patch(_OPEN_DATE, return_value=datetime.utcnow() - timedelta(days=2))
@patch(_CLOSE, return_value=True)
@patch(_SHOULD_EXIT)
@patch(_QUOTES)
@patch(_ACCOUNT)
def test_bid_price_passed_to_close_position_limit(mock_account, mock_quotes, mock_exit, mock_close, mock_open_date):
    """The RT bid should be forwarded to close_position_limit so it doesn't re-fetch."""
    pos = _make_position("AAPL250321C00200000", current_price=5.00, cost_basis=300.0)

    mock_account.return_value = {"positions": [pos], "portfolio_value": 10000, "buying_power": 5000, "cash": 5000}
    mock_quotes.return_value = {
        "AAPL250321C00200000": {"bid": 6.50, "ask": 7.00, "mid": 6.75},
    }
    mock_exit.return_value = (True, "take_profit")

    actions = track_positions()

    mock_close.assert_called_once()
    call_kwargs = mock_close.call_args
    assert call_kwargs[1]["bid_price"] == 6.50
    assert len(actions) == 1
