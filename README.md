# Crypto RSI Trading Bot (Python + CCXT)

Educational, long-only spot trading research project. **Paper mode is the default. Live execution is not approved by this repository change.** Cryptocurrency trading can lose money; backtest results are not predictions of future performance.

## Strategy

The strategy now uses an RSI recovery entry with an EMA trend filter:

- **Entry:** RSI crosses back above the oversold threshold, and the completed candle closes above the EMA trend filter (default EMA 200).
- **Exit signal:** RSI crosses into overbought.
- **Risk exits in backtests:** fixed stop-loss and take-profit levels, with gap-aware fills.
- Paper positions persist atomically to `data/paper-state.json`, including cash, entry price, stop and target levels. Paper fills model configurable adverse slippage and trading fees. Stop/target exits inspect the completed candle OHLC; when both barriers are touched, the simulator assumes the stop occurred first, and gap-through exits fill at the candle open. These are simulated exits, not exchange-side protection.

The strategy requires enough candles to warm up both RSI and EMA. It intentionally returns HOLD until sufficient history is available.

## Paper recovery and execution safety

- Paper state is persisted atomically to `PAPER_STATE_PATH` (default `data/paper-state.json`). If the file is corrupt or has an unsupported schema, startup fails instead of silently resetting balances.
- Paper fills apply `PAPER_SLIPPAGE_PCT` (default `0.05`) against the trader and `PAPER_FEE_PCT` (default `0.1`) to gross execution value on each side. Buy affordability includes fees; sell proceeds are calculated from the quantity actually held. These simple estimates do not reproduce every exchange fee tier, spread, partial fill or market impact.
- Cumulative fill reconciliation helpers calculate only newly filled quantity and reject backwards-moving cumulative fill totals. The bot stops on any reported partial fill rather than pretending the position is reconciled.
- The live execution gate remains hard-disabled. A fail-closed native OCO adapter requires an exchange-specific `create_oco_order` capability and verifies both order IDs/statuses. The current exchange configuration has **not** been sandbox-verified; do not enable live trading.
- Still required before live approval: durable live-order/position journal, polling/canceling partially filled orders and reconciling against exchange balances, restart recovery from exchange truth, native OCO placement/cancel/replace tests on the chosen exchange sandbox, fees/precision/minimum-notional checks, and independent review. Unit tests of mocked adapters are not exchange integration evidence.

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

The `Historical BTCUSDT Backtest` workflow downloads hourly Binance **spot** candles from official public monthly ZIP archives, normalizes the archive's millisecond/microsecond timestamp formats, and attempts to repair missing hours from daily archives. It never fabricates candles: any unresolved gaps are recorded, and the backtester exits an open position at the next available open and suppresses entries on that discontinuous bar. It evaluates the full sample from 2021 onward with 0.10% per-side fees and 0.05% per-side estimated slippage, and uploads the CSV plus JSON report as a 30-day workflow artifact.

Run the same analysis locally after installing pandas and numpy:

```bash
python scripts/fetch_binance_ohlcv.py --start 2021-01-01T00:00:00Z --output data/BTCUSDT_1h.csv
python scripts/evaluate_historical_backtest.py --csv data/BTCUSDT_1h.csv --output backtest-report.json --cash 10000 --fee-pct 0.1 --slippage-pct 0.05
python scripts/walk_forward_backtest.py --csv data/BTCUSDT_1h.csv --output walk-forward-report.json --cash 10000 --fee-pct 0.1 --slippage-pct 0.05
python scripts/run_paper_trial.py --csv data/BTCUSDT_1h.csv --state paper-trial-state.json --report paper-trial-report.json --cash 10000 --fee-pct 0.1 --slippage-pct 0.05
```

The report includes net return after modelled costs, maximum drawdown, total fees, estimated slippage, and closed-trade performance grouped by EMA trend and realised-volatility regimes. Regime attribution is descriptive and retrospective; it is not proof of future profitability. Preserve the CSV and report together so the experiment can be reproduced. The workflow also runs `scripts/run_paper_trial.py` against the same timestamped history. That accelerated replay uses the actual paper fill engine and atomic state file, reloads state at each UTC day boundary, checks balance/position reconciliation, and reports gaps, missed candles, exceptions, rejected fills, journal uniqueness, fees, drawdown and net liquidation P&L. It saves `paper-trial-report.json` and `paper-trial-state.json` as workflow artifacts. This is a reproducible historical replay—not a wall-clock multi-day live market session; a real-time paper trial must still run for multiple days in a persistent environment. The workflow also runs `scripts/walk_forward_backtest.py`: it ranks a small predeclared EMA/RSI grid on the earlier training segment, then compares the training-selected configuration against the existing baseline on a later chronological holdout. The holdout is not used to select parameters. This is a diagnostic, not proof of future profitability; do not retune on the holdout or change defaults based on one historical split.

A workflow run has **not** been verified as successful until the actual run logs and artifact are inspected. Do not treat a configured workflow as completed evidence. Historical backtesting does not verify paper/live position reconciliation or exchange-side protective orders.

## Automated tests

Run locally:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m py_compile config.py strategy.py risk.py backtest.py exchange.py bot.py paper_state.py protective_orders.py scripts/run_paper_trial.py scripts/walk_forward_backtest.py scripts/evaluate_historical_backtest.py scripts/fetch_binance_ohlcv.py
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
- `paper_state.py` — atomic paper portfolio and embedded append-only trade journal
- `scripts/run_paper_trial.py` — historical paper replay with daily restarts and reconciliation\n- `scripts/walk_forward_backtest.py` — train-only parameter ranking and chronological holdout evaluation
- `backtest.py` — deterministic OHLCV backtester
- `tests/test_backtest.py` — regression tests
- `.github/workflows/backtest-tests.yml` — automated test workflow

## License

MIT — free to use, modify and learn from.
