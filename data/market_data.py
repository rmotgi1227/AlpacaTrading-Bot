"""
Fetch price/candle data and account info from Alpaca.
Uses alpaca-trade-api REST for stocks (equity bars and account).
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

try:
    import alpaca_trade_api as tradeapi
    from alpaca_trade_api.rest import TimeFrame, TimeFrameUnit
except ImportError:
    tradeapi = None
    TimeFrame = None
    TimeFrameUnit = None

from config.settings import (
    APCA_API_BASE_URL,
    APCA_API_DATA_URL,
    APCA_API_KEY_ID,
    APCA_API_SECRET_KEY,
)

logger = logging.getLogger(__name__)

# Optional: point data requests to data URL (env may override)
import os
_data_url = os.environ.get("APCA_API_DATA_URL", APCA_API_DATA_URL)


def _get_api() -> "tradeapi.REST":
    if tradeapi is None:
        raise RuntimeError("alpaca-trade-api is not installed")
    return tradeapi.REST(
        key_id=APCA_API_KEY_ID,
        secret_key=APCA_API_SECRET_KEY,
        base_url=APCA_API_BASE_URL,
    )


def _get_data_api():
    """REST client used for data (bars); uses data URL."""
    if tradeapi is None:
        raise RuntimeError("alpaca-trade-api is not installed")
    return tradeapi.REST(
        key_id=APCA_API_KEY_ID,
        secret_key=APCA_API_SECRET_KEY,
        base_url=APCA_API_BASE_URL,
        api_version="v2",
    )


def _bar_to_row(b) -> dict:
    """Extract t,o,h,l,c,v from a bar entity or dict."""
    if isinstance(b, dict):
        return {k: b.get(k) for k in ("t", "o", "h", "l", "c", "v")}
    return {
        "t": getattr(b, "t", None),
        "o": getattr(b, "o", None),
        "h": getattr(b, "h", None),
        "l": getattr(b, "l", None),
        "c": getattr(b, "c", None),
        "v": getattr(b, "v", 0),
    }


def _to_df(bars) -> pd.DataFrame:
    """Convert Alpaca bars (BarsV2 or list of bar dicts) to DataFrame with OHLCV."""
    if bars is None or (hasattr(bars, "__len__") and len(bars) == 0):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    if hasattr(bars, "df") and bars.df is not None:
        return bars.df
    data = []
    if hasattr(bars, "__iter__") and not isinstance(bars, (dict, str)):
        for b in bars:
            row = _bar_to_row(getattr(b, "_raw", b))
            if row.get("t") is not None or row.get("c") is not None:
                data.append(row)
    elif isinstance(bars, dict) and "bars" in bars:
        for b in bars.get("bars", []):
            row = _bar_to_row(b)
            if row.get("t") is not None or row.get("c") is not None:
                data.append(row)
    if not data:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(data)
    df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
    return df[["open", "high", "low", "close", "volume"]]


def get_daily_bars(symbol: str, lookback: int = 60) -> pd.DataFrame:
    """Fetch daily OHLCV bars for symbol. lookback = number of daily bars."""
    try:
        api = _get_data_api()
        end = datetime.utcnow()
        start = end - timedelta(days=lookback + 10)
        start_s = start.strftime("%Y-%m-%d")
        end_s = end.strftime("%Y-%m-%d")
        bars = api.get_bars(symbol, TimeFrame.Day, start=start_s, end=end_s, limit=lookback, adjustment="split", feed="iex")
        df = _to_df(bars)
        if df.empty or len(df) > lookback:
            df = df.tail(lookback)
        return df
    except Exception as e:
        logger.warning("get_daily_bars %s failed: %s", symbol, e)
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def get_4hr_bars(symbol: str, lookback: int = 30) -> pd.DataFrame:
    """Fetch 4-hour OHLCV bars. lookback = number of 4hr bars."""
    try:
        api = _get_data_api()
        end = datetime.utcnow()
        # ~6 bars per day, so lookback days * 6
        start = end - timedelta(days=max(lookback // 6 + 5, 10))
        start_s = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_s = end.strftime("%Y-%m-%dT%H:%M:%SZ")
        tf = TimeFrame(4, TimeFrameUnit.Hour)
        bars = api.get_bars(symbol, tf, start=start_s, end=end_s, limit=lookback, adjustment="split", feed="iex")
        df = _to_df(bars)
        if not df.empty and len(df) > lookback:
            df = df.tail(lookback)
        return df
    except Exception as e:
        logger.warning("get_4hr_bars %s failed: %s", symbol, e)
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def get_current_price(symbol: str) -> Optional[float]:
    """Real-time (or latest) price for symbol. Uses latest trade or quote."""
    try:
        api = _get_data_api()
        # Latest quote is more representative for options underlying
        q = api.get_latest_quote(symbol)
        if q and getattr(q, "ap", None) and getattr(q, "bp", None):
            return (float(q.ap) + float(q.bp)) / 2.0
        t = api.get_latest_trade(symbol)
        if t and getattr(t, "p", None):
            return float(t.p)
        return None
    except Exception as e:
        logger.warning("get_current_price %s failed: %s", symbol, e)
        return None


def get_account_info() -> Optional[dict]:
    """Portfolio value, buying power, and list of positions (equity + options)."""
    try:
        api = _get_api()
        acc = api.get_account()
        if acc is None:
            return None
        positions = api.list_positions()
        positions_list = []
        for p in positions or []:
            positions_list.append({
                "symbol": getattr(p, "symbol", None),
                "qty": getattr(p, "qty", None),
                "side": getattr(p, "side", None),
                "market_value": getattr(p, "market_value", None),
                "cost_basis": getattr(p, "cost_basis", None),
                "unrealized_pl": getattr(p, "unrealized_pl", None),
                "current_price": getattr(p, "current_price", None),
            })
        return {
            "portfolio_value": float(getattr(acc, "portfolio_value", 0) or 0),
            "buying_power": float(getattr(acc, "buying_power", 0) or 0),
            "cash": float(getattr(acc, "cash", 0) or 0),
            "positions": positions_list,
            "status": getattr(acc, "status", None),
        }
    except Exception as e:
        logger.error("get_account_info failed: %s", e)
        return None
