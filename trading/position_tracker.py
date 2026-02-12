"""
Monitor open positions and trigger exits via risk manager.
Runs every 15 min during market hours.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from data.market_data import get_account_info
from risk.manager import should_exit
from trading.order_manager import close_position

logger = logging.getLogger(__name__)

# Optional: persist position open dates when we place orders (keyed by symbol)
_position_open_dates: Dict[str, datetime] = {}


def register_position_opened(symbol: str, opened_at: Optional[datetime] = None) -> None:
    """Call when we open a position so we can enforce max hold. Bot should call this after place_option_order."""
    _position_open_dates[symbol] = opened_at or datetime.utcnow()


def get_position_open_date(symbol: str) -> Optional[datetime]:
    return _position_open_dates.get(symbol)


def track_positions() -> List[dict]:
    """
    For each open position: run risk_manager.should_exit; if exit triggered, close and log.
    Returns list of actions taken: [{"symbol": ..., "action": "close", "reason": ...}].
    """
    actions = []
    try:
        info = get_account_info()
        if not info or not info.get("positions"):
            return actions
        positions = info["positions"]
        for p in positions:
            sym = p.get("symbol") or getattr(p, "symbol", None)
            if not sym:
                continue
            current_price = p.get("current_price") or getattr(p, "current_price", None)
            if current_price is not None:
                current_price = float(current_price)
            open_date = get_position_open_date(sym)
            if open_date is None and hasattr(p, "opened_at"):
                open_date = getattr(p, "opened_at", None)
            if open_date is None and isinstance(p, dict) and p.get("opened_at"):
                try:
                    open_date = datetime.fromisoformat(str(p["opened_at"]).replace("Z", "+00:00"))
                except Exception:
                    pass
            do_exit, reason = should_exit(p, current_price=current_price, open_date=open_date)
            if do_exit and reason:
                logger.info("Exit triggered for %s: %s", sym, reason)
                if close_position(p):
                    actions.append({"symbol": sym, "action": "close", "reason": reason})
                    _position_open_dates.pop(sym, None)
                    try:
                        from notifications.daily_summary import record_trade
                        pl = p.get("unrealized_pl") or getattr(p, "unrealized_pl", None)
                        record_trade({"symbol": sym, "side": "sell", "reason": reason, "unrealized_pl": pl, "type": "exit"})
                    except Exception:
                        pass
    except Exception as e:
        logger.error("track_positions failed: %s", e)
    return actions


def get_portfolio_summary() -> dict:
    """Current positions, P&L, exposure from account info."""
    try:
        info = get_account_info()
        if not info:
            return {"portfolio_value": 0, "buying_power": 0, "positions": [], "unrealized_pl": 0}
        positions = []
        total_unrealized = 0.0
        for p in info.get("positions", []):
            sym = p.get("symbol") or getattr(p, "symbol", "")
            mv = p.get("market_value") or getattr(p, "market_value", 0)
            pl = p.get("unrealized_pl") or getattr(p, "unrealized_pl", 0)
            try:
                total_unrealized += float(pl or 0)
            except (TypeError, ValueError):
                pass
            positions.append({
                "symbol": sym,
                "market_value": mv,
                "unrealized_pl": pl,
                "qty": p.get("qty") or getattr(p, "qty", 0),
            })
        return {
            "portfolio_value": info.get("portfolio_value", 0),
            "buying_power": info.get("buying_power", 0),
            "cash": info.get("cash", 0),
            "positions": positions,
            "unrealized_pl": total_unrealized,
        }
    except Exception as e:
        logger.error("get_portfolio_summary failed: %s", e)
        return {"portfolio_value": 0, "buying_power": 0, "positions": [], "unrealized_pl": 0}
