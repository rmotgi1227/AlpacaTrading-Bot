"""Tests for data/alpaca_options_client.py — real-time options quote fetching."""
import pytest
from unittest.mock import patch, MagicMock

from data.alpaca_options_client import get_option_quote, get_option_quotes_batch, _parse_quote


# --- _parse_quote ---

class TestParseQuote:
    def test_normal_quote(self):
        raw = {"bp": 1.50, "ap": 1.60, "bs": 10, "as": 20, "t": "2024-01-01T10:00:00Z"}
        result = _parse_quote("AAPL240119C00100000", raw)
        assert result["symbol"] == "AAPL240119C00100000"
        assert result["bid"] == 1.50
        assert result["ask"] == 1.60
        assert result["bid_size"] == 10
        assert result["ask_size"] == 20
        assert result["mid"] == pytest.approx(1.55)
        assert result["spread"] == pytest.approx(0.10)
        assert result["spread_pct"] == pytest.approx(0.10 / 1.55)
        assert result["timestamp"] == "2024-01-01T10:00:00Z"

    def test_zero_mid_returns_sentinel_spread(self):
        raw = {"bp": 0, "ap": 0, "bs": 0, "as": 0, "t": None}
        result = _parse_quote("SYM", raw)
        assert result["mid"] == 0.0
        assert result["spread_pct"] == 999.0

    def test_missing_fields_default_to_zero(self):
        raw = {}
        result = _parse_quote("SYM", raw)
        assert result["bid"] == 0.0
        assert result["ask"] == 0.0
        assert result["bid_size"] == 0
        assert result["ask_size"] == 0

    def test_none_values_treated_as_zero(self):
        raw = {"bp": None, "ap": None, "bs": None, "as": None}
        result = _parse_quote("SYM", raw)
        assert result["bid"] == 0.0
        assert result["ask"] == 0.0


# --- get_option_quote ---

class TestGetOptionQuote:
    @patch("data.alpaca_options_client.requests.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "quotes": {
                "AAPL240119C00100000": {
                    "bp": 2.00, "ap": 2.20, "bs": 5, "as": 10, "t": "2024-01-01T10:00:00Z"
                }
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_option_quote("AAPL240119C00100000")
        assert result is not None
        assert result["bid"] == 2.00
        assert result["ask"] == 2.20
        assert result["mid"] == pytest.approx(2.10)
        assert result["spread_pct"] == pytest.approx(0.20 / 2.10)

    @patch("data.alpaca_options_client.requests.get")
    def test_missing_symbol_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"quotes": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_option_quote("MISSING_SYM")
        assert result is None

    @patch("data.alpaca_options_client.requests.get")
    def test_http_error_returns_none(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.HTTPError("500 Server Error")

        result = get_option_quote("SYM")
        assert result is None

    @patch("data.alpaca_options_client.requests.get")
    def test_timeout_returns_none(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("timed out")

        result = get_option_quote("SYM")
        assert result is None

    @patch("data.alpaca_options_client.requests.get")
    def test_connection_error_returns_none(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        result = get_option_quote("SYM")
        assert result is None


# --- get_option_quotes_batch ---

class TestGetOptionQuotesBatch:
    @patch("data.alpaca_options_client.requests.get")
    def test_batch_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "quotes": {
                "SYM1": {"bp": 1.0, "ap": 1.1, "bs": 5, "as": 5, "t": None},
                "SYM2": {"bp": 2.0, "ap": 2.2, "bs": 10, "as": 10, "t": None},
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_option_quotes_batch(["SYM1", "SYM2", "SYM3"])
        assert "SYM1" in result
        assert "SYM2" in result
        assert "SYM3" not in result  # omitted — not in response
        assert result["SYM1"]["bid"] == 1.0
        assert result["SYM2"]["ask"] == 2.2

    @patch("data.alpaca_options_client.requests.get")
    def test_batch_empty_list(self, mock_get):
        result = get_option_quotes_batch([])
        assert result == {}
        mock_get.assert_not_called()

    @patch("data.alpaca_options_client.requests.get")
    def test_batch_timeout_returns_empty(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("timed out")

        result = get_option_quotes_batch(["SYM1"])
        assert result == {}
