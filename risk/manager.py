"""
Position sizing, stop loss, take profit, max hold time.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, List, Optional

from config.settings import (
    MAX_HOLD_DAYS,
    MAX_OPEN_POSITIONS,
    MAX_POSITION_PCT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
)

logger = logging.getLogger(__name__)


def can_open_position(account_value: float, current_positions: List[Any]) -> bool:
    """True if we have room for another trade (under max open positions)."""
    if account_value <= 0:
        return False
    count = len(current_positions) if current_positions else 0
    return count < MAX_OPEN_POSITIONS


def calculate_position_size(account_value: float, option_price: float) -> int:
    """
    Max contracts to buy so position is <= MAX_POSITION_PCT of portfolio.
    option_price is per-contract (e.g. premium * 100 for standard options).
    Returns integer number of contracts (minimum 0, at least 1 if we can afford one).
    """
    if account_value <= 0 or option_price <= 0:
        return 0
    max_dollars = account_value * (MAX_POSITION_PCT / 100.0)
    # Option cost per contract = premium * 100 (standard multiplier)
    cost_per_contract = option_price * 100
    if cost_per_contract <= 0:
        return 0
    contracts = int(max_dollars / cost_per_contract)
    return max(0, contracts)


def _position_entry_value(position: Any) -> float:
    """Cost basis (entry value) for the position."""
    cost = getattr(position, "cost_basis", None) or position.get("cost_basis") if isinstance(position, dict) else None
    if cost is not None:
        return float(cost)
    return 0.0


def _position_current_value(position: Any) -> float:
    """Current market value of the position."""
    val = getattr(position, "market_value", None) or (position.get("market_value") if isinstance(position, dict) else None)
    if val is not None:
        return float(val)
    return 0.0


def _is_option_symbol(symbol: str) -> bool:
    """OCC option symbols are long and contain strike/expiry (e.g. AAPL240119C00100000)."""
    s = str(symbol or "")
    return len(s) > 12 and ("C" in s or "P" in s)


def _position_entry_price(position: Any) -> float:
    """Average entry price per share/contract (for options, this is the option premium level)."""
    cost = _position_entry_value(position)
    qty = abs(float(getattr(position, "qty", 0) or position.get("qty", 0)))
    if qty <= 0:
        return 0.0
    sym = str(getattr(position, "symbol", position.get("symbol", "")) if hasattr(position, "symbol") or isinstance(position, dict) else "")
    if _is_option_symbol(sym):
        return cost / (qty * 100)
    return cost / qty


def _position_current_price(position: Any) -> float:
    """Current price from position or passed current_price."""
    p = getattr(position, "current_price", None) or (position.get("current_price") if isinstance(position, dict) else None)
    if p is not None:
        return float(p)
    return 0.0


def check_stop_loss(position: Any, current_price: Optional[float] = None) -> bool:
    """True if position is down >= STOP_LOSS_PCT from entry (exit)."""
    entry = _position_entry_price(position)
    if entry <= 0:
        return False
    current = current_price if current_price is not None else _position_current_price(position)
    if current <= 0:
        return False
    pct_change = 100.0 * (current - entry) / entry
    return pct_change <= -STOP_LOSS_PCT


def check_take_profit(position: Any, current_price: Optional[float] = None) -> bool:
    """True if position is up >= TAKE_PROFIT_PCT from entry (exit)."""
    entry = _position_entry_price(position)
    if entry <= 0:
        return False
    current = current_price if current_price is not None else _position_current_price(position)
    if current <= 0:
        return False
    pct_change = 100.0 * (current - entry) / entry
    return pct_change >= TAKE_PROFIT_PCT


def check_max_hold_time(position: Any, open_date: Optional[datetime] = None) -> bool:
    """True if position has been held > MAX_HOLD_DAYS trading days."""
    opened = open_date
    if opened is None:
        # Alpaca position may have opened_at or we track elsewhere
        opened = getattr(position, "opened_at", None) or position.get("opened_at") if isinstance(position, dict) else None
        if isinstance(opened, str):
            try:
                opened = datetime.fromisoformat(opened.replace("Z", "+00:00"))
            except Exception:
                return False
        if opened is None:
            return False
    if isinstance(opened, datetime) and opened.tzinfo:
        opened = opened.replace(tzinfo=None)
    elif isinstance(opened, datetime):
        pass
    else:
        return False
    days = (datetime.utcnow() - opened).days
    return days >= MAX_HOLD_DAYS


def should_exit(
    position: Any,
    current_price: Optional[float] = None,
    open_date: Optional[datetime] = None,
) -> tuple:
    """
    Combines all exit checks. Returns (should_exit: bool, reason: str).
    """
    if check_stop_loss(position, current_price):
        return True, "stop_loss"
    if check_take_profit(position, current_price):
        return True, "take_profit"
    if check_max_hold_time(position, open_date):
        return True, "max_hold_time"
    return False, ""
