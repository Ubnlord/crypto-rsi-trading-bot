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

## Automated historical market-data evaluation

The `Historical BTCUSDT Backtest` workflow downloads hourly Binance **spot** candles from the public market-data endpoint, excluding the unfinished candle and rejecting duplicate or missing hourly timestamps. It evaluates the full sample from 2021 onward with 0.10% per-side fees and 0.05% per-side estimated slippage, and uploads the original CSV plus a JSON report as a 30-day workflow artifact.

Run the same analysis locally after installing pandas and numpy:

```bash
python scripts/fetch_binance_ohlcv.py --start 2021-01-01T00:00:00Z --output data/BTCUSDT_1h.csv
python scripts/evaluate_historical_backtest.py --csv data/BTCUSDT_1h.csv --output backtest-report.json --cash 10000 --fee-pct 0.1 --slippage-pct 0.05
```

The report includes net return after modelled costs, maximum drawdown, total fees, estimated slippage, and closed-trade performance grouped by EMA trend and realised-volatility regimes. Regime attribution is descriptive and retrospective; it is not proof of future profitability. Preserve the CSV and report together so the experiment can be reproduced.

A workflow run has **not** been verified as successful until the actual run logs and artifact are inspected. Do not treat a configured workflow as completed evidence. Historical backtesting does not verify paper/live position reconciliation or exchange-side protective orders.

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

This branch has a hard code-level gate (`LIVE_EXECUTION_ENABLED = False`): setting `MODE=live` fails validation. Keep it that way until all release gates pass. Before any live use, separately implement and verify: exchange-native protective stop-loss and take-profit orders; confirmed fill reconciliation including partial fills; safe handling of existing wallet balances; market precision/minimum-notional checks; persistent state and reconciliation across restarts; exchange-specific error/retry handling; comprehensive integration tests on the selected exchange sandbox; and independent risk review. These capabilities have not yet been verified, and no live orders should be sent.

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
