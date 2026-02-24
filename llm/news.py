"""Fetch recent news headlines for a symbol using yfinance."""
import logging
from typing import List

import yfinance as yf

logger = logging.getLogger(__name__)


def get_headlines(symbol: str, max_headlines: int = 5) -> List[str]:
    """Return recent headlines as ["headline (publisher)", ...]. Empty list on failure."""
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news or []
        results = []
        for item in news[:max_headlines]:
            title = item.get("title", "")
            publisher = item.get("publisher", "")
            if title:
                results.append(f"{title} ({publisher})" if publisher else title)
        return results
    except Exception as e:
        logger.warning("Failed to fetch news for %s: %s", symbol, e)
        return []
