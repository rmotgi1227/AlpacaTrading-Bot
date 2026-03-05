"""Tests for bot.py — capital pre-flight check in boot()."""
import logging
from unittest.mock import patch

from bot import boot


class TestCapitalPreflight:
    @patch("bot.get_account_info")
    def test_underfunded_logs_error(self, mock_info, caplog):
        """$100 account should log ERROR about being underfunded."""
        mock_info.return_value = {
            "portfolio_value": 100.0,
            "buying_power": 100.0,
            "positions": [],
        }
        with caplog.at_level(logging.ERROR):
            result = boot()
        assert result is True  # bot still starts
        assert any("underfunded" in r.message.lower() for r in caplog.records)

    @patch("bot.get_account_info")
    def test_low_capital_logs_warning(self, mock_info, caplog):
        """$600 account (below min*3=$1500) should log WARNING."""
        mock_info.return_value = {
            "portfolio_value": 600.0,
            "buying_power": 600.0,
            "positions": [],
        }
        with caplog.at_level(logging.WARNING):
            result = boot()
        assert result is True
        assert any("low capital" in r.message.lower() for r in caplog.records)

    @patch("bot.get_account_info")
    def test_adequate_capital_no_warning(self, mock_info, caplog):
        """$5000 account should have no capital warnings."""
        mock_info.return_value = {
            "portfolio_value": 5000.0,
            "buying_power": 5000.0,
            "positions": [],
        }
        with caplog.at_level(logging.WARNING):
            result = boot()
        assert result is True
        warning_records = [r for r in caplog.records
                          if r.levelno >= logging.WARNING
                          and ("underfunded" in r.message.lower() or "low capital" in r.message.lower())]
        assert len(warning_records) == 0

    @patch("bot.get_account_info")
    def test_boot_still_returns_true_when_underfunded(self, mock_info):
        """bot should NOT block startup even with $0 (it monitors existing positions)."""
        mock_info.return_value = {
            "portfolio_value": 0.0,
            "buying_power": 0.0,
            "positions": [],
        }
        result = boot()
        assert result is True

    @patch("bot.get_account_info")
    def test_no_account_returns_false(self, mock_info):
        """If Alpaca connection fails, boot should return False."""
        mock_info.return_value = None
        result = boot()
        assert result is False
