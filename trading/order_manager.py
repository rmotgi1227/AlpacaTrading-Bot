"""
Place/cancel orders and close positions via Alpaca.
Uses options-specific symbol (OCC format) for option orders.
"""
import logging
import time
from typing import Any, List, Optional

from config.settings import APCA_API_BASE_URL, APCA_API_KEY_ID, APCA_API_SECRET_KEY

logger = logging.getLogger(__name__)

try:
    import alpaca_trade_api as tradeapi
except ImportError:
    tradeapi = None

MAX_RETRIES = 3
RETRY_DELAY = 2


def _get_api() -> "tradeapi.REST":
    if tradeapi is None:
        raise RuntimeError("alpaca-trade-api is not installed")
    return tradeapi.REST(
        key_id=APCA_API_KEY_ID,
        secret_key=APCA_API_SECRET_KEY,
        base_url=APCA_API_BASE_URL,
    )


def _to_occ_symbol(contract: dict) -> Optional[str]:
    """
    Ensure we have an OCC-style option symbol for Alpaca.
    yfinance contractSymbol is often like AAPL240119C00100000; Alpaca uses same format.
    If contract has 'symbol' use it; else try to build or return None.
    """
    sym = contract.get("symbol") or contract.get("contractSymbol")
    if sym and isinstance(sym, str) and len(sym) >= 10:
        return sym
    return None


def place_option_order(
    contract: dict,
    quantity: int,
    order_type: str = "limit",
    limit_price: Optional[float] = None,
) -> Optional[dict]:
    """
    Submit buy order for option. quantity = number of contracts.
    For options Alpaca requires: time_in_force='day', qty whole number, no notional.
    Returns order dict with id, status, etc. or None on failure.
    """
    if quantity < 1:
        return None
    symbol = _to_occ_symbol(contract)
    if not symbol:
        logger.error("No OCC symbol in contract: %s", contract)
        return None
    price = limit_price if limit_price is not None else (contract.get("estimated_cost") or contract.get("ask") or 0)
    for attempt in range(MAX_RETRIES):
        try:
            api = _get_api()
            if order_type == "market":
                order = api.submit_order(
                    symbol=symbol,
                    qty=int(quantity),
                    side="buy",
                    type="market",
                    time_in_force="day",
                )
            else:
                order = api.submit_order(
                    symbol=symbol,
                    qty=int(quantity),
                    side="buy",
                    type="limit",
                    time_in_force="day",
                    limit_price=str(round(price, 2)),
                )
            raw = getattr(order, "_raw", order) if order else None
            if raw is None and order is not None:
                raw = {
                    "id": getattr(order, "id", None),
                    "status": getattr(order, "status", None),
                    "symbol": getattr(order, "symbol", None),
                }
            logger.info("Order submitted: %s qty=%s %s", symbol, quantity, raw)
            return raw
        except Exception as e:
            logger.warning("place_option_order attempt %s failed: %s", attempt + 1, e)
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    return None


def close_position(position: Any) -> bool:
    """Sell to close. position: Alpaca position object or dict with 'symbol'."""
    sym = getattr(position, "symbol", None) or (position.get("symbol") if isinstance(position, dict) else None)
    if not sym:
        logger.error("close_position: no symbol")
        return False
    for attempt in range(MAX_RETRIES):
        try:
            api = _get_api()
            api.close_position(sym)
            logger.info("Closed position: %s", sym)
            return True
        except Exception as e:
            logger.warning("close_position %s attempt %s failed: %s", sym, attempt + 1, e)
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    return False


def cancel_order(order_id: str) -> bool:
    """Cancel pending order."""
    try:
        api = _get_api()
        api.cancel_order(order_id)
        logger.info("Cancelled order: %s", order_id)
        return True
    except Exception as e:
        logger.warning("cancel_order %s failed: %s", order_id, e)
        return False


def get_open_orders(symbol: Optional[str] = None) -> List[dict]:
    """List open (pending) orders. Optionally filter by symbol."""
    try:
        api = _get_api()
        params = {"status": "open"}
        if symbol:
            params["symbols"] = symbol
        orders = api.list_orders(**params)
        if orders is None:
            return []
        out = []
        for o in orders:
            raw = getattr(o, "_raw", o)
            if isinstance(o, dict):
                out.append(o)
            elif raw is not None:
                out.append(raw)
            else:
                out.append({"id": getattr(o, "id", None), "symbol": getattr(o, "symbol", None), "status": getattr(o, "status", None)})
        return out
    except Exception as e:
        logger.warning("get_open_orders failed: %s", e)
        return []
