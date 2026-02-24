"""
Momentum strategy: RSI, MACD, EMA crossover, volume confirmation.
Composite signal: BUY_CALL when score >= 2, BUY_PUT when score <= -2.
"""
import logging
from typing import Any, List

import pandas as pd
import pandas_ta as ta

from config.settings import (
    EMA_FAST,
    EMA_SLOW,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD,
    SIGNAL_THRESHOLD,
    VOLUME_CONFIRM_MULTIPLIER,
    VOLUME_MA_DAYS,
)

logger = logging.getLogger(__name__)


def _ensure_close_column(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column name to 'close' (Alpaca may use 'c' in raw)."""
    if df is None or df.empty:
        return df
    if "close" not in df.columns and "c" in df.columns:
        df = df.rename(columns={"c": "close"})
    return df


def _rsi_signal(df: pd.DataFrame) -> tuple:
    """RSI: +1 bullish (cross above oversold), -1 bearish (cross below overbought), 0 neutral."""
    if df is None or len(df) < RSI_PERIOD + 2:
        return 0, []
    df = _ensure_close_column(df)
    close = df["close"]
    rsi = ta.rsi(close, length=RSI_PERIOD)
    if rsi is None or len(rsi) < 2:
        return 0, []
    curr = float(rsi.iloc[-1])
    prev = float(rsi.iloc[-2])
    if prev <= RSI_OVERSOLD < curr:
        return 1, [f"RSI crossed above {RSI_OVERSOLD} (bullish)"]
    if prev >= RSI_OVERBOUGHT > curr:
        return -1, [f"RSI crossed below {RSI_OVERBOUGHT} (bearish)"]
    if curr > RSI_OVERSOLD and curr < RSI_OVERBOUGHT:
        return 0, []
    if curr <= RSI_OVERSOLD:
        return 1, [f"RSI at oversold {curr:.1f} (bullish)"]
    return -1, [f"RSI at overbought {curr:.1f} (bearish)"]


def _macd_signal(df: pd.DataFrame) -> tuple:
    """MACD: +1 when MACD crosses above signal, -1 when crosses below, 0 neutral."""
    if df is None or len(df) < MACD_SLOW + MACD_SIGNAL + 2:
        return 0, []
    df = _ensure_close_column(df)
    close = df["close"]
    macd_df = ta.macd(close, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    if macd_df is None or macd_df.empty or len(macd_df) < 2:
        return 0, []
    # Column names: MACD_12_26_9, MACDs_12_26_9, MACDh_12_26_9 or similar
    macd_col = [c for c in macd_df.columns if "MACD_" in c and "h" not in c.lower() and "s" not in c.lower()]
    sig_col = [c for c in macd_df.columns if "MACD" in c and ("s_" in c or "signal" in c.lower())]
    if not macd_col or not sig_col:
        macd_col = [c for c in macd_df.columns if c.startswith("MACD") and not c.endswith("_h") and not c.endswith("_s")]
        sig_col = [c for c in macd_df.columns if "MACD" in c and c != macd_col[0]]
    if not macd_col or not sig_col:
        return 0, []
    macd_line = macd_df[macd_col[0]]
    signal_line = macd_df[sig_col[0]]
    curr_m = float(macd_line.iloc[-1])
    curr_s = float(signal_line.iloc[-1])
    prev_m = float(macd_line.iloc[-2])
    prev_s = float(signal_line.iloc[-2])
    if prev_m <= prev_s and curr_m > curr_s:
        return 1, ["MACD crossed above signal (bullish)"]
    if prev_m >= prev_s and curr_m < curr_s:
        return -1, ["MACD crossed below signal (bearish)"]
    return 0, []


def _ema_signal(df: pd.DataFrame) -> tuple:
    """EMA crossover: +1 when fast crosses above slow, -1 when crosses below."""
    if df is None or len(df) < EMA_SLOW + 2:
        return 0, []
    df = _ensure_close_column(df)
    close = df["close"]
    ema_f = ta.ema(close, length=EMA_FAST)
    ema_s = ta.ema(close, length=EMA_SLOW)
    if ema_f is None or ema_s is None or len(ema_f) < 2 or len(ema_s) < 2:
        return 0, []
    f_curr, f_prev = float(ema_f.iloc[-1]), float(ema_f.iloc[-2])
    s_curr, s_prev = float(ema_s.iloc[-1]), float(ema_s.iloc[-2])
    if f_prev <= s_prev and f_curr > s_curr:
        return 1, [f"EMA{EMA_FAST} crossed above EMA{EMA_SLOW} (bullish)"]
    if f_prev >= s_prev and f_curr < s_curr:
        return -1, [f"EMA{EMA_FAST} crossed below EMA{EMA_SLOW} (bearish)"]
    return 0, []


def _volume_confirmed(df: pd.DataFrame) -> bool:
    """True when current volume > VOLUME_CONFIRM_MULTIPLIER * 20-day average volume."""
    if df is None or "volume" not in df.columns or len(df) < VOLUME_MA_DAYS + 1:
        return False
    vol = df["volume"].astype(float)
    current = vol.iloc[-1]
    avg = vol.iloc[-VOLUME_MA_DAYS - 1 : -1].mean()
    if avg <= 0:
        return True
    return current >= (VOLUME_CONFIRM_MULTIPLIER * avg)


def calculate_signals(
    symbol: str,
    daily_bars: pd.DataFrame,
    four_hr_bars: pd.DataFrame,
) -> dict:
    """
    Composite momentum signal from daily and 4h bars.
    Returns: {"symbol": str, "signal": "BUY_CALL" | "BUY_PUT" | "NO_TRADE", "score": int, "reasons": [str]}.
    """
    reasons: List[str] = []
    scores: List[int] = []
    # Prefer 4h for responsiveness; fallback to daily
    primary = four_hr_bars if four_hr_bars is not None and len(four_hr_bars) >= 20 else daily_bars
    if primary is None or len(primary) < 10:
        return {
            "symbol": symbol,
            "signal": "NO_TRADE",
            "score": 0,
            "reasons": ["Insufficient bar data"],
        }
    vol_ok = _volume_confirmed(primary)
    rsi_v, rsi_r = _rsi_signal(primary)
    macd_v, macd_r = _macd_signal(primary)
    ema_v, ema_r = _ema_signal(primary)
    reasons.extend(rsi_r + macd_r + ema_r)
    scores.extend([rsi_v, macd_v, ema_v])
    if not vol_ok:
        reasons.append("Volume below confirmation threshold (signal not blocked)")
    score = sum(scores)
    if score >= SIGNAL_THRESHOLD:
        signal = "BUY_CALL"
    elif score <= -SIGNAL_THRESHOLD:
        signal = "BUY_PUT"
    else:
        signal = "NO_TRADE"
    return {
        "symbol": symbol,
        "signal": signal,
        "score": score,
        "reasons": reasons,
    }
