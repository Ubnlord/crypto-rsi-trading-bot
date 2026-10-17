# Crypto RSI Trading Bot (Python + CCXT)

Educational, long-only spot trading research project. **Paper mode is the default. Live execution is not approved by this repository change.** Cryptocurrency trading can lose money; backtest results are not predictions of future performance.

## Strategy

The strategy now uses an RSI recovery entry with an EMA trend filter:

- **Entry:** RSI crosses back above the oversold threshold, and the completed candle closes above the EMA trend filter (default EMA 200).
- **Exit signal:** RSI crosses into overbought.
- **Risk exits in backtests:** fixed stop-loss and take-profit levels, with gap-aware fills.
- The live bot's exchange integration does **not** yet place and verify protective stop-loss/take-profit orders. Do not enable live trading based on these changes alone.

The strategy requires enough candles to warm up both RSI and EMA. It intentionally returns HOLD until sufficient history is available.

## Reproducible backtesting

The backtester consumes a historical OHLCV CSV. Required columns: `timestamp` (optional), `open`, `high`, `low`, `close`, `volume`. Timestamps are sorted chronologically when present. Use exchange-sourced historical data and keep the original CSV with your experiment notes.

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run:

```bash
python backtest.py --csv data/BTC_USDT_15m.csv --output backtest-results.json
```

Optional arguments include `--cash`, `--fee-pct`, `--slippage-pct`, `--rsi-period`, and `--ema-period`. Defaults: 10,000 starting quote currency, 0.1% fee per side, 0.05% slippage per side, RSI 14, EMA 200, 1% risk budget per trade, 10% maximum position allocation, 2% stop and 4% target.

The JSON report includes configuration, trades, equity curve, net return, win rate and maximum drawdown. Keep fees, slippage, timeframe, date range and data source consistent when comparing runs. The backtester executes signals at the next candle open, never at the signal candle close. If stop and target are both touched in a candle, it assumes the stop happens first. These conservative assumptions still cannot model every exchange condition.

## Automated tests

Run locally:

```bash
python -m pip install pandas numpy
python -m unittest discover -s tests -v
python -m py_compile strategy.py backtest.py
```

GitHub Actions runs the unit tests and compilation checks on pushes to this upgrade branch and pull requests to `main`.

## Run the bot in paper mode

```bash
cp .env.example .env
# Keep MODE=paper
python bot.py
```

Never commit `.env` or share API keys. Public market data is sufficient for paper testing. If live execution is ever considered, use API keys without withdrawal permissions and IP restrictions where supported.

## Live-trading release gates (not yet satisfied)

Before any live use, separately implement and verify: exchange-side protective orders or a reliable monitored exit mechanism; confirmed fill reconciliation and partial-fill handling; safe handling of existing wallet balances; market precision/minimum-notional checks; persistent state across restarts; exchange-specific error/retry handling; comprehensive integration tests on an exchange sandbox; and an independent review of risk controls. This branch does not change `MODE` defaults and does not enable live trading.

## Project structure

- `bot.py` — polling loop
- `strategy.py` — RSI recovery + EMA trend filter
- `risk.py` — basic position sizing helpers
- `exchange.py` — CCXT wrapper and paper simulator
- `backtest.py` — deterministic OHLCV backtester
- `tests/test_backtest.py` — regression tests
- `.github/workflows/backtest-tests.yml` — automated test workflow

## License

MIT — free to use, modify and learn from.
