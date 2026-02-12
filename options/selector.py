"""
Select optimal option contract: filter by DTE/delta, rank by liquidity and bid-ask spread.
"""
import logging
from typing import Any, Optional

from config.settings import (
    OPTIONS_DELTA_MAX,
    OPTIONS_DELTA_MIN,
    OPTIONS_DTE_MAX,
    OPTIONS_DTE_MIN,
    OPTIONS_MIN_OPEN_INTEREST,
)
from data.options_data import get_options_chain_in_dte_range

logger = logging.getLogger(__name__)


def _option_type_from_signal(signal: str) -> str:
    """BUY_CALL -> call, BUY_PUT -> put."""
    return "call" if signal == "BUY_CALL" else "put"


def _spread_score(row: Any) -> float:
    """Lower bid-ask spread is better. Return spread as fraction of mid, or 1 if missing."""
    try:
        bid = float(row.get("bid", 0) or 0)
        ask = float(row.get("ask", 0) or 0)
        if ask <= 0:
            return 1.0
        mid = (bid + ask) / 2
        if mid <= 0:
            return 1.0
        return (ask - bid) / mid
    except Exception:
        return 1.0


def _liquidity_score(row: Any) -> float:
    """Higher open interest and volume = better. Normalize for ranking."""
    oi = int(row.get("openInterest", 0) or 0)
    vol = int(row.get("volume", 0) or 0)
    return oi + (vol * 2)


def select_option(
    symbol: str,
    signal_type: str,
    account_value: float,
) -> Optional[dict]:
    """
    Pick best option contract for the signal. Filters calls/puts, DTE 14-30, delta 0.30-0.45,
    min open interest; ranks by liquidity and tight spread.
    Returns: {symbol (option), strike, expiration, estimated_cost, greeks} or None.
    """
    if signal_type not in ("BUY_CALL", "BUY_PUT"):
        return None
    option_type = _option_type_from_signal(signal_type)
    try:
        chain = get_options_chain_in_dte_range(
            symbol,
            option_type=option_type,
            dte_range=(OPTIONS_DTE_MIN, OPTIONS_DTE_MAX),
            delta_range=(OPTIONS_DELTA_MIN, OPTIONS_DELTA_MAX),
            min_open_interest=OPTIONS_MIN_OPEN_INTEREST,
        )
        if chain is None or chain.empty:
            logger.debug("No contracts in DTE/delta range for %s %s", symbol, option_type)
            return None
        # Rank: liquidity (OI + volume) desc, spread asc
        chain = chain.copy()
        chain["_liq"] = chain.apply(_liquidity_score, axis=1)
        chain["_spread"] = chain.apply(_spread_score, axis=1)
        chain = chain.sort_values(by=["_liq", "_spread"], ascending=[False, True])
        best = chain.iloc[0]
        contract_symbol = best.get("contractSymbol") or best.get("contract_symbol")
        strike = best.get("strike")
        expiration = best.get("expiration", "")
        ask = float(best.get("ask", 0) or 0)
        bid = float(best.get("bid", 0) or 0)
        est_cost = ask if ask > 0 else (bid if bid > 0 else 0)
        greeks = {
            "delta": best.get("delta"),
            "gamma": best.get("gamma"),
            "theta": best.get("theta"),
            "vega": best.get("vega"),
            "iv": best.get("impliedVolatility"),
        }
        return {
            "symbol": contract_symbol,
            "underlying": symbol,
            "strike": strike,
            "expiration": expiration,
            "option_type": option_type,
            "estimated_cost": est_cost,
            "bid": bid,
            "ask": ask,
            "greeks": greeks,
            "open_interest": best.get("openInterest"),
        }
    except Exception as e:
        logger.warning("select_option %s %s failed: %s", symbol, signal_type, e)
        return None
