"""Tests for trading/order_manager.py — close_position_limit() step-down strategy."""
import pytest
from unittest.mock import patch, MagicMock, call

from trading.order_manager import close_position_limit, _wait_for_fill


class TestWaitForFill:
    @patch("trading.order_manager.time.sleep")
    @patch("trading.order_manager._get_api")
    def test_filled_immediately(self, mock_api_fn, mock_sleep):
        mock_api = MagicMock()
        mock_order = MagicMock()
        mock_order.status = "filled"
        mock_api.get_order.return_value = mock_order
        mock_api_fn.return_value = mock_api

        result = _wait_for_fill("order123", timeout_sec=30)
        assert result == "filled"

    @patch("trading.order_manager.time.sleep")
    @patch("trading.order_manager._get_api")
    def test_timeout(self, mock_api_fn, mock_sleep):
        mock_api = MagicMock()
        mock_order = MagicMock()
        mock_order.status = "new"  # never fills
        mock_api.get_order.return_value = mock_order
        mock_api_fn.return_value = mock_api

        result = _wait_for_fill("order123", timeout_sec=10)
        assert result == "timeout"

    @patch("trading.order_manager.time.sleep")
    @patch("trading.order_manager._get_api")
    def test_cancelled_normalized(self, mock_api_fn, mock_sleep):
        mock_api = MagicMock()
        mock_order = MagicMock()
        mock_order.status = "cancelled"  # British spelling from API
        mock_api.get_order.return_value = mock_order
        mock_api_fn.return_value = mock_api

        result = _wait_for_fill("order123", timeout_sec=30)
        assert result == "canceled"  # normalized to American spelling


class TestClosePositionLimit:
    @patch("trading.order_manager.close_position")
    @patch("trading.order_manager._wait_for_fill")
    @patch("trading.order_manager._get_api")
    @patch("trading.order_manager._get_position_qty")
    @patch("data.alpaca_options_client.get_option_quote")
    def test_fill_on_first_attempt(self, mock_quote, mock_qty, mock_api_fn, mock_wait, mock_close):
        mock_quote.return_value = {"bid": 2.50, "ask": 2.60}
        mock_qty.return_value = 3
        mock_api = MagicMock()
        mock_order = MagicMock()
        mock_order.id = "order1"
        mock_api.submit_order.return_value = mock_order
        mock_api_fn.return_value = mock_api
        mock_wait.return_value = "filled"

        position = {"symbol": "AAPL240119C00100000"}
        result = close_position_limit(position)

        assert result is True
        mock_close.assert_not_called()
        mock_api.submit_order.assert_called_once()
        submit_kwargs = mock_api.submit_order.call_args
        assert submit_kwargs.kwargs["type"] == "limit"
        assert submit_kwargs.kwargs["side"] == "sell"

    @patch("trading.order_manager.close_position")
    @patch("trading.order_manager.cancel_order")
    @patch("trading.order_manager._wait_for_fill")
    @patch("trading.order_manager._get_api")
    @patch("trading.order_manager._get_position_qty")
    @patch("data.alpaca_options_client.get_option_quote")
    def test_timeout_then_fill_on_step_down(self, mock_quote, mock_qty, mock_api_fn,
                                             mock_wait, mock_cancel, mock_close):
        mock_quote.return_value = {"bid": 2.50, "ask": 2.60}
        mock_qty.return_value = 1
        mock_api = MagicMock()
        mock_order = MagicMock()
        mock_order.id = "order1"
        mock_api.submit_order.return_value = mock_order
        mock_api_fn.return_value = mock_api
        # First attempt times out, second fills
        mock_wait.side_effect = ["timeout", "filled"]
        mock_cancel.return_value = True

        result = close_position_limit({"symbol": "SYM123456789"})

        assert result is True
        assert mock_api.submit_order.call_count == 2
        mock_cancel.assert_called_once_with("order1")
        mock_close.assert_not_called()

    @patch("trading.order_manager.close_position")
    @patch("trading.order_manager.cancel_order")
    @patch("trading.order_manager._wait_for_fill")
    @patch("trading.order_manager._get_api")
    @patch("trading.order_manager._get_position_qty")
    @patch("data.alpaca_options_client.get_option_quote")
    def test_all_steps_fail_market_fallback(self, mock_quote, mock_qty, mock_api_fn,
                                             mock_wait, mock_cancel, mock_close):
        mock_quote.return_value = {"bid": 2.50, "ask": 2.60}
        mock_qty.return_value = 1
        mock_api = MagicMock()
        mock_order = MagicMock()
        mock_order.id = "order1"
        mock_api.submit_order.return_value = mock_order
        mock_api_fn.return_value = mock_api
        # All attempts time out (initial + EXIT_MAX_STEP_DOWNS = 3 total)
        mock_wait.return_value = "timeout"
        mock_cancel.return_value = True
        mock_close.return_value = True

        result = close_position_limit({"symbol": "SYM123456789"})

        assert result is True
        mock_close.assert_called_once()  # market fallback triggered
        assert mock_api.submit_order.call_count == 3  # 1 initial + 2 step-downs

    @patch("trading.order_manager.close_position")
    @patch("trading.order_manager._get_position_qty")
    @patch("data.alpaca_options_client.get_option_quote")
    def test_no_bid_immediate_market_fallback(self, mock_quote, mock_qty, mock_close):
        mock_quote.return_value = None  # no RT quote available
        mock_qty.return_value = 1
        mock_close.return_value = True

        result = close_position_limit({"symbol": "SYM123456789"})

        assert result is True
        mock_close.assert_called_once()

    @patch("trading.order_manager.close_position")
    @patch("trading.order_manager.cancel_order")
    @patch("trading.order_manager._wait_for_fill")
    @patch("trading.order_manager._get_api")
    @patch("trading.order_manager._get_position_qty")
    @patch("data.alpaca_options_client.get_option_quote")
    def test_cancel_called_on_unfilled(self, mock_quote, mock_qty, mock_api_fn,
                                       mock_wait, mock_cancel, mock_close):
        mock_quote.return_value = {"bid": 1.00, "ask": 1.10}
        mock_qty.return_value = 2
        mock_api = MagicMock()
        mock_order = MagicMock()
        mock_order.id = "order_abc"
        mock_api.submit_order.return_value = mock_order
        mock_api_fn.return_value = mock_api
        mock_wait.return_value = "timeout"
        mock_cancel.return_value = True
        mock_close.return_value = True

        close_position_limit({"symbol": "SYM123456789"})

        # cancel should be called for each timed-out attempt
        assert mock_cancel.call_count == 3  # 1 initial + 2 step-downs, all timeout

    def test_no_symbol_returns_false(self):
        result = close_position_limit({})
        assert result is False


# Patch get_option_quote at module level for close_position_limit
@pytest.fixture(autouse=True)
def patch_get_option_quote():
    """Ensure close_position_limit can import get_option_quote."""
    with patch.dict("sys.modules", {}):
        yield
