"""
End-of-day summary: trades, positions, P&L, portfolio, signals, scanner picks.
Delivers via email (Gmail app password). Twilio SMS stubbed for v1.
"""
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List

from config.settings import (
    NOTIFICATION_EMAIL_APP_PASSWORD,
    NOTIFICATION_EMAIL_FROM,
    NOTIFICATION_EMAIL_TO,
    NOTIFICATION_SMS_ENABLED,
)
from trading.position_tracker import get_portfolio_summary

logger = logging.getLogger(__name__)

# In-memory log of today's signals and scanner picks (bot writes these)
_today_signals: List[dict] = []
_today_scanner_picks: List[str] = []
_today_trades: List[dict] = []


def record_signal(signal_result: dict) -> None:
    """Call from bot when a signal is generated (for daily summary)."""
    _today_signals.append({**signal_result, "at": datetime.utcnow().isoformat()})


def record_scanner_picks(picks: List[str]) -> None:
    """Call from bot after pre-market scan."""
    _today_scanner_picks.clear()
    _today_scanner_picks.extend(picks)


def record_trade(entry_or_exit: dict) -> None:
    """Call when placing or closing a trade (symbol, side, qty, price, PnL if exit)."""
    _today_trades.append({**entry_or_exit, "at": datetime.utcnow().isoformat()})


def generate_daily_summary() -> dict:
    """
    Compile: trades today, open positions, daily P&L, portfolio snapshot, signals, scanner picks.
    """
    summary = get_portfolio_summary()
    summary["generated_at"] = datetime.utcnow().isoformat()
    summary["trades_today"] = list(_today_trades)
    summary["signals_today"] = list(_today_signals)
    summary["scanner_picks"] = list(_today_scanner_picks)
    return summary


def _summary_to_text(summary: dict) -> str:
    """Plain text body for email."""
    lines = [
        "Swing Options Bot – Daily Summary",
        "Generated: " + summary.get("generated_at", ""),
        "",
        "--- Portfolio ---",
        "Portfolio value: ${:.2f}".format(float(summary.get("portfolio_value", 0) or 0)),
        "Buying power:   ${:.2f}".format(float(summary.get("buying_power", 0) or 0)),
        "Unrealized P&L: ${:.2f}".format(float(summary.get("unrealized_pl", 0) or 0)),
        "",
        "--- Open Positions ---",
    ]
    for p in summary.get("positions", []) or []:
        lines.append("  {}  qty={}  mv=${}  P&L=${}".format(
            p.get("symbol", ""),
            p.get("qty", ""),
            p.get("market_value", ""),
            p.get("unrealized_pl", ""),
        ))
    lines.append("")
    lines.append("--- Trades Today ---")
    for t in summary.get("trades_today", []) or []:
        lines.append("  {}  {}".format(t.get("at", ""), t))
    lines.append("")
    lines.append("--- Signals Today ---")
    for s in summary.get("signals_today", []) or []:
        lines.append("  {}  {}  score={}".format(s.get("symbol", ""), s.get("signal", ""), s.get("score", "")))
    lines.append("")
    lines.append("--- Scanner Picks (Pre-market) ---")
    lines.append("  " + ", ".join(summary.get("scanner_picks", []) or []))
    return "\n".join(lines)


def send_summary(summary: dict) -> bool:
    """
    Send daily summary. Primary: email (Gmail app password). Optional: Twilio SMS (stubbed).
    """
    body = _summary_to_text(summary)
    sent = False
    if NOTIFICATION_EMAIL_FROM and NOTIFICATION_EMAIL_APP_PASSWORD and NOTIFICATION_EMAIL_TO:
        try:
            msg = MIMEMultipart()
            msg["Subject"] = "Swing Options Bot – Daily Summary"
            msg["From"] = NOTIFICATION_EMAIL_FROM
            msg["To"] = NOTIFICATION_EMAIL_TO
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(NOTIFICATION_EMAIL_FROM, NOTIFICATION_EMAIL_APP_PASSWORD)
                server.sendmail(NOTIFICATION_EMAIL_FROM, NOTIFICATION_EMAIL_TO, msg.as_string())
            logger.info("Daily summary email sent to %s", NOTIFICATION_EMAIL_TO)
            sent = True
        except Exception as e:
            logger.warning("Failed to send summary email: %s", e)
    else:
        logger.debug("Email not configured; skipping send")
    if NOTIFICATION_SMS_ENABLED:
        # TODO: Twilio SMS – stub for v1
        logger.debug("SMS disabled in v1")
    return sent
