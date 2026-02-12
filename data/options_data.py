"""
Fetch options chains and contract info via yfinance.
Uses whatever Greeks/IV yfinance provides.
# TODO: integrate Polygon.io for better Greeks (delta, gamma, theta, vega).
"""
import logging
from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from config.settings import (
    OPTIONS_DELTA_MAX,
    OPTIONS_DELTA_MIN,
    OPTIONS_DTE_MAX,
    OPTIONS_DTE_MIN,
    OPTIONS_MIN_OPEN_INTEREST,
)

logger = logging.getLogger(__name__)


def get_options_chain(symbol: str, expiration: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """
    Get options chain for symbol. Returns (calls_df, puts_df, list of expiration dates).
    If expiration is None, uses the first available expiration; otherwise uses the given date (YYYY-MM-DD).
    """
    try:
        ticker = yf.Ticker(symbol)
        expirations = list(ticker.options) if hasattr(ticker, "options") and ticker.options else []
        if not expirations:
            logger.warning("No options expirations for %s", symbol)
            return pd.DataFrame(), pd.DataFrame(), []

        if expiration is None:
            expiration = expirations[0]
        if expiration not in expirations:
            expiration = expirations[0]

        chain = ticker.option_chain(expiration)
        calls = chain.calls if chain.calls is not None else pd.DataFrame()
        puts = chain.puts if chain.puts is not None else pd.DataFrame()
        return calls, puts, expirations
    except Exception as e:
        logger.warning("get_options_chain %s failed: %s", symbol, e)
        return pd.DataFrame(), pd.DataFrame(), []


def _dte(expiration_str: str) -> int:
    """Days to expiration from expiration date string (e.g. YYYY-MM-DD or MMM DD, YYYY)."""
    try:
        for fmt in ("%Y-%m-%d", "%b %d, %Y"):
            try:
                exp_d = datetime.strptime(expiration_str.strip()[:10], fmt[:10].replace("%b %d, %Y", "%Y-%m-%d"))
                if fmt == "%b %d, %Y":
                    exp_d = datetime.strptime(expiration_str.strip(), fmt)
                else:
                    exp_d = datetime.strptime(expiration_str.strip()[:10], "%Y-%m-%d")
                return (exp_d.date() - datetime.now().date()).days
            except ValueError:
                continue
    except Exception:
        pass
    return 0


def filter_options(
    chain: pd.DataFrame,
    option_type: str,
    dte_range: Tuple[int, int] = (OPTIONS_DTE_MIN, OPTIONS_DTE_MAX),
    delta_range: Optional[Tuple[float, float]] = (OPTIONS_DELTA_MIN, OPTIONS_DELTA_MAX),
    min_open_interest: int = OPTIONS_MIN_OPEN_INTEREST,
    expiration_str: Optional[str] = None,
) -> pd.DataFrame:
    """
    Narrow chain to viable contracts: DTE in range, optional delta (if available), min open interest.
    chain: DataFrame from get_options_chain (calls or puts).
    option_type: 'call' or 'put'.
    """
    if chain is None or chain.empty:
        return pd.DataFrame()
    df = chain.copy()
    # DTE filter (if we have expiration)
    if expiration_str:
        dte = _dte(expiration_str)
        if dte < dte_range[0] or dte > dte_range[1]:
            return pd.DataFrame()
    # Open interest
    if "openInterest" in df.columns:
        df = df[df["openInterest"].fillna(0).astype(int) >= min_open_interest]
    else:
        logger.debug("No openInterest column; skipping OI filter")
    # Delta: yfinance option_chain often does not include delta. TODO: integrate Polygon.io for better Greeks.
    if delta_range and "delta" in df.columns:
        df = df[(df["delta"] >= delta_range[0]) & (df["delta"] <= delta_range[1])]
    return df


def get_greeks(contract: Any) -> dict:
    """
    Get Greeks/IV for a specific contract (row from options chain or dict with contractSymbol).
    Uses whatever yfinance provides; may not include delta/gamma/theta/vega.
    # TODO: integrate Polygon.io for better Greeks.
    """
    result = {"delta": None, "gamma": None, "theta": None, "vega": None, "iv": None}
    if contract is None:
        return result
    if hasattr(contract, "get"):
        row = contract
    else:
        row = contract
    if isinstance(row, dict):
        result["iv"] = row.get("impliedVolatility")
        result["delta"] = row.get("delta")
        result["gamma"] = row.get("gamma")
        result["theta"] = row.get("theta")
        result["vega"] = row.get("vega")
    elif hasattr(row, "impliedVolatility"):
        result["iv"] = getattr(row, "impliedVolatility", None)
        result["delta"] = getattr(row, "delta", None)
        result["gamma"] = getattr(row, "gamma", None)
        result["theta"] = getattr(row, "theta", None)
        result["vega"] = getattr(row, "vega", None)
    return result


def get_options_chain_in_dte_range(
    symbol: str,
    option_type: str,
    dte_range: Tuple[int, int] = (OPTIONS_DTE_MIN, OPTIONS_DTE_MAX),
    delta_range: Optional[Tuple[float, float]] = (OPTIONS_DELTA_MIN, OPTIONS_DELTA_MAX),
    min_open_interest: int = OPTIONS_MIN_OPEN_INTEREST,
) -> pd.DataFrame:
    """
    Get all expirations, filter by DTE and other params, return single DataFrame of viable contracts.
    option_type: 'call' or 'put'.
    """
    try:
        ticker = yf.Ticker(symbol)
        expirations = list(ticker.options) if hasattr(ticker, "options") and ticker.options else []
        if not expirations:
            return pd.DataFrame()
        today = datetime.now().date()
        out = []
        for exp_str in expirations:
            try:
                exp_d = datetime.strptime(exp_str[:10], "%Y-%m-%d").date()
                dte = (exp_d - today).days
                if dte < dte_range[0] or dte > dte_range[1]:
                    continue
            except Exception:
                continue
            chain = ticker.option_chain(exp_str)
            if option_type == "call":
                df = chain.calls
            else:
                df = chain.puts
            if df is None or df.empty:
                continue
            df = df.copy()
            df["expiration"] = exp_str
            df["dte"] = dte
            filtered = filter_options(
                df,
                option_type,
                dte_range=dte_range,
                delta_range=delta_range,
                min_open_interest=min_open_interest,
                expiration_str=exp_str,
            )
            if not filtered.empty:
                out.append(filtered)
        if not out:
            return pd.DataFrame()
        return pd.concat(out, ignore_index=True)
    except Exception as e:
        logger.warning("get_options_chain_in_dte_range %s %s failed: %s", symbol, option_type, e)
        return pd.DataFrame()
