# Swing Trading Options Bot

Automated swing trading bot that uses momentum/directional signals to trade stock options. Built for **Alpaca paper trading** (US options); switch to live by changing config and API keys.

## Setup

1. **Python 3.11+** (3.12 recommended).

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   - Copy `config/.env.example` to `config/.env` (or create `.env` in project root).
   - Set your Alpaca **paper** API keys:
     - `APCA_API_KEY_ID`
     - `APCA_API_SECRET_KEY`
     - `APCA_API_BASE_URL=https://paper-api.alpaca.markets`
   - For daily email summary: set `NOTIFICATION_EMAIL_FROM`, `NOTIFICATION_EMAIL_APP_PASSWORD`, `NOTIFICATION_EMAIL_TO` (Gmail app password).

4. **Run the bot:**
   ```bash
   python bot.py
   ```
   All times are **US Eastern** (America/New_York). The scheduler runs:
   - **9:00 AM ET** – Pre-market scan (movers + core watchlist).
   - **9:45 AM ET** – First signal scan after open.
   - **Every 30 min** (10:00–15:30 ET) – Signal scan and position checks.
   - **Every 15 min** – Exit checks (stop loss, take profit, max hold).
   - **Friday 3:00 PM ET** – Close all positions.
   - **4:15 PM ET** – Daily summary email.

## Project layout

- `config/settings.py` – Strategy, risk, and options parameters; load from `.env`.
- `data/market_data.py` – Alpaca bars, price, account.
- `data/options_data.py` – yfinance options chains (Greeks/IV as provided; TODO: Polygon).
- `scanner/premarket_scanner.py` – Pre-market movers + fallback universe.
- `strategy/momentum.py` – RSI, MACD, EMA, volume; composite signal (BUY_CALL / BUY_PUT).
- `options/selector.py` – Filter/rank option contracts (DTE, delta, liquidity).
- `risk/manager.py` – Position size, stop loss, take profit, max hold.
- `trading/order_manager.py` – Alpaca option orders; `position_tracker.py` – exits.
- `notifications/daily_summary.py` – End-of-day email summary.
- `bot.py` – Main runner and scheduling.
- Logs: `logs/bot.log` (daily rotation, 14 days).

## Going live

- Set `PAPER_TRADING=false` (or in `.env`).
- Use live Alpaca API keys and `APCA_API_BASE_URL=https://api.alpaca.markets`.
- Ensure your Alpaca account has **options trading** enabled (Level 2+ for buy call/put).

## Risk parameters (config/settings.py)

| Parameter            | Default   |
|----------------------|-----------|
| Max position size    | 20%       |
| Max open positions   | 4         |
| Stop loss            | 25%       |
| Take profit          | 40%       |
| Max hold             | 5 days    |
| Options DTE          | 14–30     |
| Options delta        | 0.30–0.45 |
