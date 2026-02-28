"""
Strategy params, watchlist, risk and options thresholds.
All times are US Eastern (America/New_York).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from config/ or project root
_env_path = Path(__file__).resolve().parent / ".env"
if not _env_path.exists():
    _env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# ----- Trading mode -----
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() in ("true", "1", "yes")

# ----- Alpaca (from .env) -----
APCA_API_KEY_ID = os.getenv("APCA_API_KEY_ID", "")
APCA_API_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY", "")
# Base URL must NOT include /v2 — the SDK adds it (e.g. /v2/account)
_raw_base = os.getenv(
    "APCA_API_BASE_URL",
    "https://paper-api.alpaca.markets" if PAPER_TRADING else "https://api.alpaca.markets",
)
APCA_API_BASE_URL = _raw_base.rstrip("/").removesuffix("/v2") if _raw_base else _raw_base
APCA_API_DATA_URL = os.getenv("APCA_API_DATA_URL", "https://data.alpaca.markets")

# ----- Core watchlist -----
CORE_WATCHLIST = [
    "TSLA",
    "SPY",
    "QQQ",
    "NVDA",
    "AAPL",
    "AMD",
    "META",
    "AMZN",
    "MSFT",
    "GOOGL",
    "NFLX",
    "CRM",
    "AVGO",
    "SHOP",
    "COIN",
    "PLTR",
    "SOFI",
    "MARA",
    "ARM",
    "SMCI",
]

# ----- Fallback universe for pre-market scanner (when API returns nothing useful) -----
# ~50 liquid tech/ETF symbols
SCANNER_FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "UNH",
    "JNJ", "JPM", "V", "PG", "XOM", "MA", "HD", "CVX", "MRK", "ABBV",
    "PEP", "KO", "COST", "AVGO", "WMT", "MCD", "CSCO", "ACN", "ABT", "TMO",
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "ARKK", "XLF", "XLK", "XLE",
    "AMD", "INTC", "CRM", "ORCL", "ADBE", "NFLX", "PYPL", "UBER", "SHOP", "SQ",
]

# ----- Strategy: technical indicators -----
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_FAST = 9
EMA_SLOW = 21
VOLUME_MA_DAYS = 20
VOLUME_CONFIRM_MULTIPLIER = 1.5  # signal confirmed when volume > this * 20d avg
SIGNAL_THRESHOLD = 1  # need |score| >= 1 for BUY_CALL / BUY_PUT (LLM filter handles quality)

# ----- Risk -----
MAX_POSITION_PCT = 10  # max 10% of portfolio per position
MAX_OPEN_POSITIONS = 4
STOP_LOSS_PCT = 15    # exit if position down 15% from entry
TAKE_PROFIT_PCT = 20  # exit if position up 20% from entry
MAX_HOLD_DAYS = 5     # close if held > 5 trading days
FRIDAY_CLOSE_HOUR = 15  # 3:00 PM ET - close all positions

# ----- Options -----
OPTIONS_DTE_MIN = 14
OPTIONS_DTE_MAX = 60
OPTIONS_DELTA_MIN = 0.25
OPTIONS_DELTA_MAX = 0.60
OPTIONS_MIN_OPEN_INTEREST = 100

# ----- Scanner -----
PREMARKET_SCAN_TOP_N = 5   # add top N movers to daily watchlist
SCAN_START_OFFSET_MIN = 15  # first scan 15 min after open (9:45 AM ET)
SCAN_INTERVAL_MIN = 30     # scan every 30 min
POSITION_TRACK_INTERVAL_MIN = 5   # check exits every 5 min

# ----- Scheduling (Eastern) -----
TIMEZONE = "America/New_York"
PREMARKET_SCAN_TIME = "09:00"   # 9:00 AM ET
PREMARKET_MISFIRE_GRACE_SEC = 3600  # allow up to 60 min late execution after downtime/sleep
MARKET_OPEN_SCAN_TIME = "09:45" # 9:45 AM ET
MARKET_CLOSE_HOUR = 16         # 4:00 PM ET
DAILY_SUMMARY_TIME = "16:15"   # 4:15 PM ET

# ----- Notifications -----
NOTIFICATION_EMAIL_FROM = os.getenv("NOTIFICATION_EMAIL_FROM", "")
NOTIFICATION_EMAIL_APP_PASSWORD = os.getenv("NOTIFICATION_EMAIL_APP_PASSWORD", "")
NOTIFICATION_EMAIL_TO = os.getenv("NOTIFICATION_EMAIL_TO", "")
NOTIFICATION_SMS_ENABLED = False  # Twilio stubbed; set True when configured

# ----- LLM signal filter -----
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_ENABLED = os.getenv("LLM_ENABLED", "true").lower() in ("true", "1", "yes")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "256"))
LLM_TIMEOUT_SEC = int(os.getenv("LLM_TIMEOUT_SEC", "10"))

# ----- Logging -----
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "bot.log"
LOG_WHEN = "midnight"   # TimedRotatingFileHandler
LOG_BACKUP_COUNT = 14   # keep 14 days
