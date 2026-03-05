"""
Place/cancel orders and close positions via Alpaca.
Uses options-specific symbol (OCC format) for option orders.
"""
import logging
import time
from typing import Any, List, Optional

from config.settings import (
    APCA_API_BASE_URL,
    APCA_API_KEY_ID,
    APCA_API_SECRET_KEY,
    EXIT_LIMIT_TIMEOUT_SEC,
    EXIT_MAX_STEP_DOWNS,
    EXIT_PRICE_STEP_DOWN_PCT,
    EXIT_USE_MARKET_FALLBACK,
)

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


def _get_position_qty(sym: str) -> Optional[int]:
    """Get current quantity for an open position."""
    try:
        api = _get_api()
        pos = api.get_position(sym)
        qty = getattr(pos, "qty", None)
        if qty is not None:
            return abs(int(qty))
        return None
    except Exception as e:
        logger.warning("_get_position_qty %s failed: %s", sym, e)
        return None


_FILL_POLL_INTERVAL = 5  # seconds between fill checks


def _wait_for_fill(order_id: str, timeout_sec: int) -> str:
    """
    Poll order status until filled, cancelled, expired, rejected, or timeout.
    Returns status string: "filled", "canceled", "expired", "rejected", or "timeout".
    """
    api = _get_api()
    elapsed = 0
    while elapsed < timeout_sec:
        try:
            order = api.get_order(order_id)
            status = getattr(order, "status", None) or (order.get("status") if isinstance(order, dict) else None)
            if status in ("filled", "canceled", "cancelled", "expired", "rejected"):
                return "canceled" if status == "cancelled" else status
        except Exception as e:
            logger.warning("_wait_for_fill poll error for %s: %s", order_id, e)
        time.sleep(_FILL_POLL_INTERVAL)
        elapsed += _FILL_POLL_INTERVAL
    return "timeout"


def close_position_limit(position: Any, bid_price: Optional[float] = None) -> bool:
    """
    Close position using limit sell orders with step-down strategy.

    1. Place limit sell at bid price
    2. If not filled after EXIT_LIMIT_TIMEOUT_SEC, cancel and step price down
    3. After EXIT_MAX_STEP_DOWNS failures, fall back to market order

    Args:
        position: Alpaca position object or dict with 'symbol' and 'qty'
        bid_price: Override bid price (if already fetched). Otherwise fetches real-time.

    Returns:
        True if position was closed, False otherwise.
    """
    sym = getattr(position, "symbol", None) or (position.get("symbol") if isinstance(position, dict) else None)
    if not sym:
        logger.error("close_position_limit: no symbol")
        return False

    qty = _get_position_qty(sym)
    if qty is None or qty <= 0:
        logger.warning("close_position_limit: could not get qty for %s, falling back to market", sym)
        return close_position(position)

    # Get bid price from real-time quote if not provided
    current_bid = bid_price
    if current_bid is None:
        try:
            from data.alpaca_options_client import get_option_quote
            rt_quote = get_option_quote(sym)
            if rt_quote is not None:
                current_bid = rt_quote["bid"]
        except Exception as e:
            logger.warning("Failed to get RT quote for exit %s: %s", sym, e)

    if current_bid is None or current_bid <= 0:
        logger.warning("No bid available for %s; falling back to market order", sym)
        return close_position(position)

    # Step-down limit order strategy
    limit_price = current_bid
    for step in range(EXIT_MAX_STEP_DOWNS + 1):
        try:
            api = _get_api()
            order = api.submit_order(
                symbol=sym,
                qty=int(qty),
                side="sell",
                type="limit",
                time_in_force="day",
                limit_price=str(round(limit_price, 2)),
            )
            order_id = getattr(order, "id", None) or (order.get("id") if isinstance(order, dict) else None)
            if not order_id:
                logger.warning("close_position_limit: no order ID returned for %s", sym)
                break

            logger.info("Limit sell submitted for %s: qty=%d price=$%.2f (step %d/%d)",
                        sym, qty, limit_price, step, EXIT_MAX_STEP_DOWNS)

            status = _wait_for_fill(order_id, EXIT_LIMIT_TIMEOUT_SEC)
            if status == "filled":
                logger.info("Limit sell filled for %s at $%.2f (step %d)", sym, limit_price, step)
                return True

            # Not filled — cancel and step down
            if status == "timeout":
                cancel_order(order_id)
                logger.info("Limit sell timed out for %s at $%.2f, stepping down", sym, limit_price)
            elif status in ("canceled", "expired"):
                logger.info("Limit sell %s for %s at $%.2f", status, sym, limit_price)
            elif status == "rejected":
                logger.warning("Limit sell rejected for %s at $%.2f", sym, limit_price)
                break

            # Step down price for next attempt
            if step < EXIT_MAX_STEP_DOWNS:
                limit_price = round(limit_price * (1 - EXIT_PRICE_STEP_DOWN_PCT), 2)
                if limit_price <= 0:
                    logger.warning("Stepped price to $0 for %s; falling back to market", sym)
                    break
        except Exception as e:
            logger.warning("close_position_limit step %d for %s failed: %s", step, sym, e)
            break

    # All limit attempts exhausted — market fallback
    if EXIT_USE_MARKET_FALLBACK:
        logger.info("All limit attempts exhausted for %s; falling back to market order", sym)
        return close_position(position)
    logger.warning("All limit attempts exhausted for %s and market fallback disabled", sym)
    return False
