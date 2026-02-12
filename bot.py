"""
Main bot runner: scheduling, scan loop, position tracking, Friday close, daily summary.
All times US Eastern (America/New_York).
"""
import logging
import logging.handlers
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import (
    CORE_WATCHLIST,
    FRIDAY_CLOSE_HOUR,
    LOG_BACKUP_COUNT,
    LOG_FILE,
    LOG_WHEN,
    LOG_DIR,
    MARKET_OPEN_SCAN_TIME,
    PREMARKET_SCAN_TIME,
    SCAN_INTERVAL_MIN,
    POSITION_TRACK_INTERVAL_MIN,
    DAILY_SUMMARY_TIME,
    TIMEZONE,
)
from data.market_data import get_account_info, get_daily_bars, get_4hr_bars
from options.selector import select_option
from risk.manager import can_open_position, calculate_position_size
from scanner.premarket_scanner import build_daily_watchlist
from strategy.momentum import calculate_signals
from trading.order_manager import place_option_order
from trading.position_tracker import get_portfolio_summary, register_position_opened, track_positions
from notifications.daily_summary import record_signal, record_scanner_picks, record_trade

# ----- Logging -----
LOG_DIR.mkdir(parents=True, exist_ok=True)
_file_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_FILE, when=LOG_WHEN, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().setLevel(logging.INFO)
logging.getLogger().addHandler(_file_handler)
logging.getLogger().addHandler(_console)
logger = logging.getLogger("bot")

# In-memory daily watchlist (set at pre-market, used rest of day)
_daily_watchlist: list = list(CORE_WATCHLIST)
_tz = ZoneInfo(TIMEZONE)


def _now_et() -> datetime:
    return datetime.now(_tz)


def _is_friday() -> bool:
    return _now_et().weekday() == 4


def boot() -> bool:
    """Load config, connect to Alpaca, verify account."""
    try:
        from config import settings
        if not settings.APCA_API_KEY_ID or not settings.APCA_API_SECRET_KEY:
            logger.error("Missing Alpaca API keys in .env")
            return False
        info = get_account_info()
        if not info:
            logger.error("Could not connect to Alpaca or get account")
            return False
        logger.info("Connected. Portfolio value=%.2f buying_power=%.2f", info.get("portfolio_value", 0), info.get("buying_power", 0))
        return True
    except Exception as e:
        logger.exception("Boot failed: %s", e)
        return False


def run_premarket_scan() -> None:
    """9:00 AM ET: run scanner, build daily watchlist."""
    global _daily_watchlist
    logger.info("Running pre-market scan...")
    try:
        _daily_watchlist = build_daily_watchlist()
        # Record only the movers the scanner added (for daily summary), not the full watchlist
        movers = [s for s in _daily_watchlist if s not in CORE_WATCHLIST]
        record_scanner_picks(movers)
    except Exception as e:
        logger.exception("Pre-market scan failed: %s", e)
        _daily_watchlist = list(CORE_WATCHLIST)


def run_signal_scan() -> None:
    """For each watchlist symbol: signals; if strong + risk ok, select option and place order. Then check exits."""
    logger.info("Running signal scan for watchlist: %s", _daily_watchlist)
    try:
        info = get_account_info()
        if not info:
            return
        account_value = float(info.get("portfolio_value", 0) or 0)
        positions = info.get("positions", [])
        if not can_open_position(account_value, positions):
            logger.debug("Max positions reached; skipping new entries")
        for symbol in _daily_watchlist:
            try:
                daily = get_daily_bars(symbol, lookback=60)
                four_hr = get_4hr_bars(symbol, lookback=30)
                sig = calculate_signals(symbol, daily, four_hr)
                record_signal(sig)
                logger.info("Signal %s: %s score=%s", symbol, sig.get("signal"), sig.get("score"))
                if sig.get("signal") not in ("BUY_CALL", "BUY_PUT"):
                    continue
                if not can_open_position(account_value, positions):
                    continue
                contract = select_option(symbol, sig["signal"], account_value)
                if not contract:
                    continue
                cost = contract.get("estimated_cost") or contract.get("ask") or 0
                if cost <= 0:
                    continue
                qty = calculate_position_size(account_value, cost)
                if qty < 1:
                    continue
                order = place_option_order(contract, qty, order_type="limit", limit_price=cost)
                if order:
                    opt_sym = contract.get("symbol") or contract.get("contractSymbol")
                    if opt_sym:
                        register_position_opened(opt_sym)
                    record_trade({"symbol": opt_sym, "side": "buy", "qty": qty, "price": cost, "type": "entry"})
                    positions = (positions or []) + [{"symbol": opt_sym}]
                    account_value -= qty * cost * 100
            except Exception as e:
                logger.warning("Signal scan %s failed: %s", symbol, e)
        track_positions()
    except Exception as e:
        logger.exception("Signal scan failed: %s", e)


def run_position_track() -> None:
    """Every 15 min: check exit conditions on all positions."""
    logger.info("Running position track...")
    try:
        actions = track_positions()
        if actions:
            logger.info("Position actions: %s", actions)
    except Exception as e:
        logger.exception("Position track failed: %s", e)


def run_friday_close() -> None:
    """Friday 3:00 PM ET: close all positions to avoid weekend risk."""
    if not _is_friday():
        return
    logger.info("Friday close: closing all positions...")
    try:
        info = get_account_info()
        for p in info.get("positions", []) or []:
            sym = p.get("symbol") or getattr(p, "symbol", None)
            if sym:
                from trading.order_manager import close_position
                close_position(p)
    except Exception as e:
        logger.exception("Friday close failed: %s", e)


def run_daily_summary() -> None:
    """4:15 PM ET: generate and send daily summary."""
    logger.info("Running daily summary...")
    try:
        from notifications.daily_summary import generate_daily_summary, send_summary
        summary = generate_daily_summary()
        send_summary(summary)
    except Exception as e:
        logger.exception("Daily summary failed: %s", e)


def main() -> None:
    if not boot():
        sys.exit(1)
    run_premarket_scan()
    scheduler = BlockingScheduler(timezone=_tz)
    # Pre-market: 9:00 AM ET
    hour, minute = map(int, PREMARKET_SCAN_TIME.split(":"))
    scheduler.add_job(run_premarket_scan, CronTrigger(hour=hour, minute=minute), id="premarket")
    # First scan: 9:45 AM ET
    hour, minute = map(int, MARKET_OPEN_SCAN_TIME.split(":"))
    scheduler.add_job(run_signal_scan, CronTrigger(hour=hour, minute=minute), id="open_scan")
    # Recurring scan every 30 min from 10:00 to 15:30 ET
    scheduler.add_job(
        run_signal_scan,
        CronTrigger(minute="0,30", hour="10,11,12,13,14,15"),
        id="recurring_scan",
    )
    # Position track every 15 min
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler.add_job(run_position_track, IntervalTrigger(minutes=POSITION_TRACK_INTERVAL_MIN), id="position_track")
    # Friday 3:00 PM ET
    scheduler.add_job(run_friday_close, CronTrigger(day_of_week="fri", hour=FRIDAY_CLOSE_HOUR, minute=0), id="friday_close")
    # Daily summary 4:15 PM ET
    hour, minute = map(int, DAILY_SUMMARY_TIME.split(":"))
    scheduler.add_job(run_daily_summary, CronTrigger(hour=hour, minute=minute), id="daily_summary")
    logger.info("Scheduler started (ET). Pre-market %s, open scan %s, summary %s", PREMARKET_SCAN_TIME, MARKET_OPEN_SCAN_TIME, DAILY_SUMMARY_TIME)
    scheduler.start()


if __name__ == "__main__":
    main()
