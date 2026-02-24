"""
LLM signal filter: uses Claude to review momentum signals before trading.
Fail-open — any error returns approved=True so the bot keeps trading.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

import pandas as pd

from config.settings import (
    ANTHROPIC_API_KEY,
    LLM_ENABLED,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_TIMEOUT_SEC,
)
from llm.news import get_headlines

logger = logging.getLogger(__name__)

_client = None

SYSTEM_PROMPT = """\
You are a conservative options trade reviewer for a momentum-based swing trading bot.

You will receive a proposed trade signal along with:
- Technical signal details (type, score, reasons)
- Recent price action (daily and 4-hour OHLCV bars)
- Current portfolio state (value, buying power, open positions)
- Recent news headlines

Your job: decide whether to APPROVE or REJECT the trade.

REJECT if:
- News contradicts the signal direction (e.g., bearish signal on strong earnings beat)
- The signal is weak or conflicting (low score, mixed reasons)
- Portfolio is overexposed to this sector or correlated positions
- Price action shows the move may already be exhausted

APPROVE if the technical signal aligns with price action and news context.

Respond with ONLY valid JSON, no other text:
{"decision": "APPROVE" or "REJECT", "reasoning": "one sentence explanation"}
"""


def _get_client():
    """Lazy singleton Anthropic client."""
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=LLM_TIMEOUT_SEC)
    return _client


def _format_bars(df: Optional[pd.DataFrame], label: str, n: int = 5) -> str:
    """Format last n bars as a compact text table."""
    if df is None or df.empty:
        return f"{label}: no data"
    df = df.tail(n)
    lines = [f"{label} (last {len(df)} bars):"]
    for _, row in df.iterrows():
        o = row.get("open", row.get("o", "?"))
        h = row.get("high", row.get("h", "?"))
        lo = row.get("low", row.get("l", "?"))
        c = row.get("close", row.get("c", "?"))
        v = row.get("volume", row.get("v", "?"))
        lines.append(f"  O={o} H={h} L={lo} C={c} V={v}")
    return "\n".join(lines)


def _build_user_prompt(
    symbol: str,
    signal: Dict[str, Any],
    daily_bars: Optional[pd.DataFrame],
    four_hr_bars: Optional[pd.DataFrame],
    portfolio: Dict[str, Any],
    news: List[str],
) -> str:
    """Assemble the user prompt with all context for the LLM."""
    parts = [
        f"SYMBOL: {symbol}",
        f"SIGNAL: {signal.get('signal')} (score={signal.get('score')})",
        f"REASONS: {', '.join(signal.get('reasons', []))}",
        "",
        _format_bars(daily_bars, "Daily bars"),
        "",
        _format_bars(four_hr_bars, "4-hour bars"),
        "",
        "PORTFOLIO:",
        f"  Value: ${portfolio.get('portfolio_value', 'N/A')}",
        f"  Buying power: ${portfolio.get('buying_power', 'N/A')}",
        f"  Open positions: {len(portfolio.get('positions', []))}",
    ]
    for pos in (portfolio.get("positions") or [])[:5]:
        sym = pos.get("symbol", "?")
        pnl = pos.get("unrealized_pl", "?")
        parts.append(f"    {sym} P&L={pnl}")
    parts.append("")
    if news:
        parts.append("RECENT NEWS:")
        for headline in news:
            parts.append(f"  - {headline}")
    else:
        parts.append("RECENT NEWS: none available")
    return "\n".join(parts)


def _parse_response(text: str) -> Dict[str, Any]:
    """Parse LLM JSON response with regex fallback."""
    # Try direct JSON parse
    try:
        data = json.loads(text.strip())
        decision = data.get("decision", "").upper()
        if decision in ("APPROVE", "REJECT"):
            return {"approved": decision == "APPROVE", "reasoning": data.get("reasoning", "")}
    except (json.JSONDecodeError, AttributeError):
        pass
    # Regex fallback
    decision_match = re.search(r'"decision"\s*:\s*"(APPROVE|REJECT)"', text, re.IGNORECASE)
    reasoning_match = re.search(r'"reasoning"\s*:\s*"([^"]*)"', text)
    if decision_match:
        return {
            "approved": decision_match.group(1).upper() == "APPROVE",
            "reasoning": reasoning_match.group(1) if reasoning_match else "",
        }
    # Can't parse — fail open
    logger.warning("Could not parse LLM response: %s", text[:200])
    return {"approved": True, "reasoning": "LLM response unparseable — fail-open"}


def llm_filter_signal(
    symbol: str,
    signal: Dict[str, Any],
    daily_bars: Optional[pd.DataFrame],
    four_hr_bars: Optional[pd.DataFrame],
    account_info: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Ask Claude whether to approve or reject a trade signal.
    Returns {"approved": bool, "reasoning": str}.
    Fail-open: any error returns approved=True.
    """
    if not LLM_ENABLED:
        return {"approved": True, "reasoning": "LLM filter disabled"}

    try:
        news = get_headlines(symbol)
        prompt = _build_user_prompt(symbol, signal, daily_bars, four_hr_bars, account_info, news)

        client = _get_client()
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text
        result = _parse_response(text)
        return result

    except Exception as e:
        logger.warning("LLM filter failed for %s (fail-open): %s", symbol, e)
        return {"approved": True, "reasoning": f"LLM filter error — fail-open: {e}"}
