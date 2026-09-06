# Real Crypto Trading Robot (Python + ccxt)

A clean, modular **live-capable** trading bot for cryptocurrency using the **RSI Mean-Reversion** strategy.

**This is educational software.**  
Trading cryptocurrencies involves a high risk of losing money. Past performance is not indicative of future results. You are solely responsible for any trades placed with this code.

---

## Features

- **ccxt** unified connector → works with Binance, Bybit, Kraken, Coinbase, OKX, and 100+ others
- **Paper mode by default** (simulated fills with real market data)
- **Live mode** only when you explicitly set `MODE=live` + provide API keys
- RSI mean-reversion strategy (easily replaceable)
- Basic risk management (fixed fractional position sizing + max position %)
- Clean logging
- Graceful shutdown (Ctrl+C)

---

## Quick Start

### 1. Install

```bash
cd trading_bot
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your preferred settings
```

Important settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `MODE` | `paper` (safe) or `live` | `paper` |
| `EXCHANGE_ID` | ccxt exchange id | `binance` |
| `API_KEY` / `API_SECRET` | Your keys (only needed for live) | empty |
| `SYMBOL` | Trading pair | `BTC/USDT` |
| `TIMEFRAME` | Candle size | `15m` |
| `RSI_PERIOD` / `RSI_OVERSOLD` / `RSI_OVERBOUGHT` | Strategy params | 14 / 30 / 70 |
| `RISK_PER_TRADE_PCT` | % of equity risked per trade | 1.0 |
| `STOP_LOSS_PCT` | Used for position sizing | 2.0 |

### 3. Run (Paper first!)

```bash
python bot.py
```

You should see live prices + RSI values and simulated BUY/SELL when conditions are met.

### 4. Go Live (ONLY after thorough testing)

1. Create **API keys** on your exchange with **trading permissions only** (no withdrawal).
2. Restrict keys by IP if possible.
3. Set in `.env`:
   ```
   MODE=live
   API_KEY=your_key
   API_SECRET=your_secret
   ```
4. Start with very small size (`RISK_PER_TRADE_PCT=0.25` or lower).
5. Run and monitor closely.

---

## Strategy Logic (RSI Mean-Reversion)

- **BUY** when RSI crosses (or is) below the oversold level (default 30)
- **SELL** when RSI crosses (or is) above the overbought level (default 70)
- Only one position at a time by default

This is a classic mean-reversion idea. It works best in ranging markets and can underperform in strong trends. You should backtest and optimize parameters yourself.

---

## Project Structure

```
trading_bot/
├── bot.py              # Main loop
├── config.py           # Loads .env
├── exchange.py         # ccxt wrapper + paper simulator
├── strategy.py         # RSI mean-reversion
├── risk.py             # Position sizing
├── requirements.txt
├── .env.example
└── README.md
```

---

## Extending the Bot

- **Add another strategy**: implement a class with `evaluate(df) → (signal, price, rsi)` and swap it in `bot.py`
- **Futures / leverage**: change `options={"defaultType": "future"}` in `exchange.py` and adjust risk carefully
- **Multiple symbols**: loop over a list of symbols
- **Stop-loss / take-profit orders**: use `create_order` with `stopLoss` / `takeProfit` params (exchange-dependent)
- **Backtesting**: fetch historical OHLCV and run the same signal logic offline (easy to add)

---

## Important Safety Notes

- Always start in **paper mode**.
- Never share your API keys.
- Use keys with the minimum required permissions.
- Monitor the bot; do not leave it unattended with large capital.
- Crypto markets are 24/7 and extremely volatile.
- This code has no warranty. Use at your own risk.

---

## License

MIT — free to use, modify, and learn from.
