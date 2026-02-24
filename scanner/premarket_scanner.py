"""
Pre-market scanner: find top movers to add to daily watchlist.
Primary: Alpaca snapshots over a universe; fallback: config fallback universe.
"""
import logging
from typing import Any, List

from config.settings import (
    CORE_WATCHLIST,
    PREMARKET_SCAN_TOP_N,
    SCANNER_FALLBACK_UNIVERSE,
)
from data.market_data import _get_data_api
from data.options_data import get_options_chain

logger = logging.getLogger(__name__)

# Batch size for Alpaca snapshots (API may limit symbols per request)
SNAPSHOT_BATCH = 100


def _has_liquid_options(symbol: str) -> bool:
    """Quick check: symbol has at least one expiration with options."""
    try:
        _, _, exps = get_options_chain(symbol)
        return len(exps) > 0
    except Exception:
        return False


def _extract_pct_from_snap(snap: Any, sym: str) -> tuple:
    """Return (symbol, abs_pct, pct) or (None, 0, 0) if cannot compute."""
    try:
        prev_close = None
        current = None
        if snap is None:
            return (None, 0.0, 0.0)
        # Entity may have _raw
        raw = getattr(snap, "_raw", None) if hasattr(snap, "_raw") else snap
        if isinstance(raw, dict):
            daily = raw.get("dailyBar") or raw.get("DailyBar")
            prev_daily = raw.get("prevDailyBar") or raw.get("PrevDailyBar")
            if daily and isinstance(daily, dict):
                current = daily.get("c") or daily.get("close")
            elif daily and hasattr(daily, "c"):
                current = getattr(daily, "c", None) or getattr(daily, "close", None)
            if prev_daily and isinstance(prev_daily, dict):
                prev_close = prev_daily.get("c") or prev_daily.get("close")
            elif prev_daily and hasattr(prev_daily, "c"):
                prev_close = getattr(prev_daily, "c", None) or getattr(prev_daily, "close", None)
            if not current and raw.get("quote"):
                q = raw["quote"]
                ap = q.get("ap") or q.get("bp")
                bp = q.get("bp") or q.get("ap")
                if ap is not None or bp is not None:
                    current = (float(ap or 0) + float(bp or 0)) / 2
        else:
            if hasattr(snap, "dailyBar") and snap.dailyBar:
                bar = snap.dailyBar
                current = getattr(bar, "c", None) or getattr(bar, "close", None)
            if hasattr(snap, "prevDailyBar") and snap.prevDailyBar:
                prev = snap.prevDailyBar
                prev_close = getattr(prev, "c", None) or getattr(prev, "close", None)
            if not current:
                q = getattr(snap, "quote", None)
                if q:
                    current = (float(getattr(q, "ap", 0) or 0) + float(getattr(q, "bp", 0) or 0)) / 2
            if not prev_close and current:
                prev_close = current
        if prev_close is not None and current is not None and float(prev_close) > 0:
            pct = 100.0 * (float(current) - float(prev_close)) / float(prev_close)
            return (sym, abs(pct), pct)
    except Exception as e:
        logger.debug("_extract_pct_from_snap %s: %s", sym, e)
    return (None, 0.0, 0.0)


def _get_movers_from_snapshots(symbols: List[str], top_n: int) -> List[str]:
    """
    Get snapshots for symbols, compute % change (from previous close to latest),
    return top_n by absolute % move. Uses Alpaca data API snapshots.
    """
    if not symbols:
        return []
    try:
        api = _get_data_api()
        results = []
        for i in range(0, len(symbols), SNAPSHOT_BATCH):
            batch = symbols[i : i + SNAPSHOT_BATCH]
            try:
                snapshots = api.get_snapshots(batch, feed="iex")
            except Exception as e:
                logger.warning("get_snapshots batch failed: %s", e)
                continue
            if not snapshots:
                continue
            # SnapshotsV2: may be wrapper with .snapshots dict or dict-like
            data = getattr(snapshots, "snapshots", snapshots)
            if hasattr(data, "_raw"):
                data = data._raw
            if isinstance(data, dict):
                for sym, snap in data.items():
                    if snap is None:
                        continue
                    tup = _extract_pct_from_snap(snap, sym)
                    if tup[0] is not None:
                        results.append(tup)
            else:
                for sym in batch:
                    snap = getattr(data, sym, None) if hasattr(data, sym) else None
                    if snap is None and isinstance(data, dict):
                        snap = data.get(sym)
                    tup = _extract_pct_from_snap(snap, sym)
                    if tup[0] is not None:
                        results.append(tup)
        if not results:
            logger.warning("No snapshot results from %d symbols — movers will fall back to universe order", len(symbols))
            return []
        results.sort(key=lambda x: x[1], reverse=True)
        top = results[:top_n]
        logger.info("Top movers by abs%% change: %s", [(r[0], f"{r[2]:+.2f}%") for r in top])
        return [r[0] for r in top]
    except Exception as e:
        logger.warning("_get_movers_from_snapshots failed: %s", e)
        return []


def scan_premarket_movers(top_n: int = PREMARKET_SCAN_TOP_N) -> List[str]:
    """
    Run before market open. Primary: Alpaca snapshots on fallback universe for top movers.
    Filter by: has liquid options. Return top_n tickers to add to daily watchlist.
    """
    universe = SCANNER_FALLBACK_UNIVERSE
    movers = _get_movers_from_snapshots(universe, top_n=top_n * 2)
    # Filter by liquid options and take top_n
    out = []
    for sym in movers:
        if _has_liquid_options(sym):
            out.append(sym)
            if len(out) >= top_n:
                break
    if len(out) < top_n:
        for sym in universe:
            if sym not in out and _has_liquid_options(sym):
                out.append(sym)
                if len(out) >= top_n:
                    break
    return out[:top_n]


def build_daily_watchlist() -> List[str]:
    """Merge pre-market scanner picks with core watchlist (dedup)."""
    movers = scan_premarket_movers()
    watchlist = list(dict.fromkeys(CORE_WATCHLIST + movers))
    logger.info("Daily watchlist: %s (movers: %s)", watchlist, movers)
    return watchlist
