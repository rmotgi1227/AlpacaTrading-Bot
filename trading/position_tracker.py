"""
Monitor open positions and trigger exits via risk manager.
Runs every 15 min during market hours.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from data.market_data import get_account_info
from config.settings import TIMEZONE
from risk.manager import should_exit
from trading.order_manager import close_position

_tz = ZoneInfo(TIMEZONE)

logger = logging.getLogger(__name__)

_POSITIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "positions.json"
_position_open_dates: Dict[str, datetime] = {}


def _load_positions() -> None:
    """Load persisted position open dates from disk."""
    global _position_open_dates
    try:
        if _POSITIONS_FILE.exists():
            raw = json.loads(_POSITIONS_FILE.read_text())
            _position_open_dates = {
                sym: datetime.fromisoformat(ts) for sym, ts in raw.items()
            }
            logger.info("Loaded %d position open dates from %s", len(_position_open_dates), _POSITIONS_FILE)
    except Exception as e:
        logger.warning("Failed to load positions file: %s", e)
        _position_open_dates = {}


def _save_positions() -> None:
    """Persist position open dates to disk."""
    try:
        _POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        raw = {sym: dt.isoformat() for sym, dt in _position_open_dates.items()}
        _POSITIONS_FILE.write_text(json.dumps(raw, indent=2))
    except Exception as e:
        logger.warning("Failed to save positions file: %s", e)


# Load on import so bot restart recovers state
_load_positions()


def register_position_opened(symbol: str, opened_at: Optional[datetime] = None) -> None:
    """Call when we open a position so we can enforce max hold. Bot should call this after place_option_order."""
    _position_open_dates[symbol] = opened_at or datetime.utcnow()
    _save_positions()


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
            # Skip stop-loss/take-profit on same day as entry to avoid PDT
            if open_date is not None:
                today = datetime.now(_tz).date()
                opened_date = open_date.date() if hasattr(open_date, 'date') else today
                if opened_date == today:
                    logger.debug("Skipping exit check for %s (opened today, PDT guard)", sym)
                    continue
            do_exit, reason = should_exit(p, current_price=current_price, open_date=open_date)
            if do_exit and reason:
                logger.info("Exit triggered for %s: %s", sym, reason)
                if close_position(p):
                    actions.append({"symbol": sym, "action": "close", "reason": reason})
                    _position_open_dates.pop(sym, None)
                    _save_positions()
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
