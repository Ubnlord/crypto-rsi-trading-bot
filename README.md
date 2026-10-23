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


## Persistent history and dashboard

The bot stores paper portfolio state, confirmed trade records, portfolio snapshots, and bot events in SQLite at `data/trading_bot.sqlite3` by default. Set `DATABASE_PATH` to choose another location. Back up this file and keep it out of public repositories.

Start the read-only dashboard in a separate terminal:

```bash
python dashboard.py
```

Open `http://127.0.0.1:8080`. The dashboard reads recorded snapshots, trades and events; it does not place orders. It binds to localhost by default and has no authentication. **Do not expose it to the public internet** without adding authentication, TLS, and network access controls.

## Backtesting

Prepare a CSV with a numeric `close` column and run:

```bash
python backtest.py historical-candles.csv --fee 0.001 --slippage 0.0005 --output backtest-results.json
```

The report includes net return, estimated fees, win rate, and maximum drawdown. It is a simple spot-strategy research tool, not a tick-accurate exchange simulator. Validate assumptions and avoid tuning parameters on the same period used to report results.

## Risk-control limitation

The configured stop-loss and take-profit thresholds currently support **bot-side monitoring only**. They are not guaranteed exchange-side protective orders: a stopped process, network outage, or exchange API failure can prevent a market exit. Do not rely on these thresholds for live-money protection. Exchange-native conditional orders must be implemented and tested per exchange before live trading can be considered production-ready.


## Container deployment (paper mode)

Requirements: Docker Engine with Compose v2. This deployment intentionally forces `MODE=paper`; live mode is blocked until a verified exchange-native OCO/bracket adapter exists.

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
docker compose logs -f bot
```

Open the dashboard on the same machine at `http://127.0.0.1:8080`. The port is bound to loopback, not a public interface. Do not change that binding on an internet-facing server without adding authentication, TLS, firewall rules, and a proper production web server. Persistent SQLite data lives in the Docker volume `bot-data`.

To stop the services:

```bash
docker compose down
```

To stop and remove persistent data too (destructive):

```bash
docker compose down -v
```

### Live mode status

The application now deliberately refuses live startup because exchange-native OCO protection has not been implemented and verified for the selected exchange. This is intentional fail-closed behavior, not a configuration bug. A generic stop order plus a separate take-profit order can both execute and oversell a spot position; a safe implementation needs exchange-specific atomic OCO/bracket support, correct order-size reconciliation, and tests against the exchange sandbox. Do not bypass this guard for real funds.

### Operations checklist

- Keep API credentials out of images, source control, and logs.
- Back up the SQLite volume and test restoring it.
- Watch `docker compose ps` and `docker compose logs`; the current health check verifies database availability, not profitability or exchange connectivity.
- Run on a host with controlled access. The dashboard has no authentication and is intended for localhost only.
- Run unit tests with `python -m unittest discover -s tests -v` before deployment.
