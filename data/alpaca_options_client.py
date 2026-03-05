"""
Real-time options quotes from Alpaca's Options Market Data API.
Uses requests directly since alpaca-trade-api doesn't wrap /v1beta1/options/.
"""
import logging
from typing import Dict, List, Optional

import requests

from config.settings import (
    APCA_API_DATA_URL,
    APCA_API_KEY_ID,
    APCA_API_SECRET_KEY,
    OPTIONS_DATA_FEED,
)

logger = logging.getLogger(__name__)

_BASE_URL = APCA_API_DATA_URL.rstrip("/")
_QUOTES_ENDPOINT = f"{_BASE_URL}/v1beta1/options/quotes/latest"
_TIMEOUT = 10  # seconds
_HEADERS = {
    "APCA-API-KEY-ID": APCA_API_KEY_ID,
    "APCA-API-SECRET-KEY": APCA_API_SECRET_KEY,
}


def _parse_quote(symbol: str, raw: dict) -> dict:
    """Normalize a single Alpaca options quote into a standard dict."""
    bid = float(raw.get("bp", 0) or 0)
    ask = float(raw.get("ap", 0) or 0)
    bid_size = int(raw.get("bs", 0) or 0)
    ask_size = int(raw.get("as", 0) or 0)
    mid = (bid + ask) / 2 if (bid + ask) > 0 else 0.0
    if mid > 0:
        spread_pct = (ask - bid) / mid
    else:
        spread_pct = 999.0  # sentinel for zero-mid edge case
    return {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "mid": mid,
        "spread": ask - bid,
        "spread_pct": spread_pct,
        "timestamp": raw.get("t"),
    }


def get_option_quote(occ_symbol: str) -> Optional[dict]:
    """
    Fetch real-time quote for a single options contract.

    Args:
        occ_symbol: OCC-format symbol (e.g. AAPL240119C00100000)

    Returns:
        Normalized dict with bid/ask/mid/spread/spread_pct, or None on failure.
    """
    try:
        resp = requests.get(
            _QUOTES_ENDPOINT,
            params={"symbols": occ_symbol, "feed": OPTIONS_DATA_FEED},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        quotes = data.get("quotes", {})
        if occ_symbol not in quotes:
            logger.warning("No quote returned for %s", occ_symbol)
            return None
        return _parse_quote(occ_symbol, quotes[occ_symbol])
    except requests.exceptions.Timeout:
        logger.warning("Timeout fetching option quote for %s", occ_symbol)
        return None
    except requests.exceptions.RequestException as e:
        logger.warning("Failed to fetch option quote for %s: %s", occ_symbol, e)
        return None
    except Exception as e:
        logger.warning("Unexpected error fetching option quote for %s: %s", occ_symbol, e)
        return None


def get_option_quotes_batch(occ_symbols: List[str]) -> Dict[str, dict]:
    """
    Fetch real-time quotes for multiple options contracts in one call.

    Args:
        occ_symbols: List of OCC-format symbols.

    Returns:
        Dict mapping symbol -> normalized quote dict. Missing/failed symbols are omitted.
    """
    if not occ_symbols:
        return {}
    try:
        symbols_param = ",".join(occ_symbols)
        resp = requests.get(
            _QUOTES_ENDPOINT,
            params={"symbols": symbols_param, "feed": OPTIONS_DATA_FEED},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        quotes = data.get("quotes", {})
        result = {}
        for sym in occ_symbols:
            if sym in quotes:
                result[sym] = _parse_quote(sym, quotes[sym])
        return result
    except requests.exceptions.Timeout:
        logger.warning("Timeout fetching batch option quotes")
        return {}
    except requests.exceptions.RequestException as e:
        logger.warning("Failed to fetch batch option quotes: %s", e)
        return {}
    except Exception as e:
        logger.warning("Unexpected error fetching batch option quotes: %s", e)
        return {}
