# Crypto RSI Trading Bot

A Python cryptocurrency trading bot built on [ccxt](https://github.com/ccxt/ccxt), using an RSI mean-reversion strategy with paper trading as the default.

> **Risk warning:** This is educational software, not financial advice. Crypto trading can cause substantial or total loss. Paper results do not predict live performance. Live trading is disabled unless explicitly configured, and you remain responsible for every trade.

## Product capabilities

- Unified market data through supported ccxt exchanges.
- Paper trading by default, using live market prices and simulated fills.
- Explicit live mode with a fail-closed credential check.
- Configurable RSI thresholds, position sizing, and exposure limits.
- Graceful shutdown and structured application logs.
- Regression tests for RSI edge cases and invalid market data.

## Quick start

```bash
git clone https://github.com/Ubnlord/crypto-rsi-trading-bot.git
cd crypto-rsi-trading-bot
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

On Windows, create the environment file with `Copy-Item .env.example .env` if `cp` is unavailable.

## Configuration

Edit `.env`. Never commit credentials or paste them into issues.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MODE` | `paper` | `paper` or explicitly enabled `live` |
| `EXCHANGE_ID` | `kraken` | Exchange identifier supported by ccxt |
| `SYMBOL` | `BTC/USD` | Market symbol in ccxt format |
| `TIMEFRAME` | `15m` | Candle interval |
| `CANDLE_LIMIT` | `100` | Number of candles fetched |
| `RSI_PERIOD` | `14` | RSI lookback |
| `RSI_OVERSOLD` / `RSI_OVERBOUGHT` | `30` / `70` | Signal thresholds |
| `RISK_PER_TRADE_PCT` | `1.0` | Intended equity risk per trade |
| `MAX_POSITION_PCT` | `10.0` | Maximum position notional as a percentage of equity |
| `STOP_LOSS_PCT` | `2.0` | Distance used for position sizing; does not place an exchange stop order |
| `TAKE_PROFIT_PCT` | `4.0` | Reserved configuration; automatic take-profit execution is not implemented |
| `POLL_INTERVAL_SECONDS` | `60` | Main loop interval |

Paper mode starts with a simulated balance of 10,000 units. The current paper ledger is in-memory and resets when the process restarts.

## Test

Install dependencies, then run:

```bash
python -m unittest discover -s tests -v
```

## Live trading checklist

Live trading is **not recommended until you have reviewed the implementation and tested it thoroughly**. The application now refuses to start with `MODE=live` unless both `API_KEY` and `API_SECRET` are set.

Before considering live use:

1. Use an exchange API key with trading-only permissions; disable withdrawals and restrict allowed IPs.
2. Start with tiny amounts and confirm symbol, market type, balance currency, minimum order size, and fee behavior.
3. Verify exchange-specific order status handling and reconciliation after partial fills, timeouts, and network failures.
4. Add and independently verify exchange-side stop-loss/take-profit orders before relying on them. The configured percentages do not currently create protective orders.
5. Run the bot under supervision. Do not assume it is safe for unattended trading.

## Current limitations

This is an evolving trading application, not a managed or audited trading service. Paper balances and positions are not persisted; trade history, user accounts, web dashboard, alerting, and automated backtesting are not included. Spot position detection relies on the exchange's available base balance, which may include assets unrelated to this bot. The strategy is a simple RSI heuristic and has no profitability guarantee.

## License

MIT. See [LICENSE](LICENSE).
