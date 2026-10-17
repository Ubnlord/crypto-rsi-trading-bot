# Bybit demo + MT5 demo: next safe stage

## Current safety state

- LIVE_EXECUTION_ENABLED must remain False.
- MODE=paper simulates fills. MODE=demo selects Bybit's demo API for market data, but strategy orders still go to the local paper simulator. This build does not submit Bybit demo orders.
- mt5_readonly.py only connects after checking MT5 demo trade mode and a server name containing "demo". It has no order-sending API.
- The 0.25% equity risk budget is a sizing limit, not a promise that realized loss cannot exceed it. Gaps, fees, spread, slippage and execution failures can exceed planned risk.
- Never commit API secrets. Use Bybit demo API keys only for demo testing.

## Bybit demo data configuration

Set in a local untracked .env:

    MODE=demo
    EXCHANGE_ID=bybit
    SYMBOL=BTC/USDT
    API_KEY=your_bybit_demo_api_key
    API_SECRET=your_bybit_demo_api_secret
    RISK_PER_TRADE_PCT=0.25

Switch the Bybit account to Demo Trading before creating demo API keys. CCXT enable_demo_trading(True) uses Bybit's api-demo endpoints. Do not combine this with set_sandbox_mode(True); Bybit demo and testnet are different environments.

Run python bot.py only to confirm market data and signals. Any displayed portfolio/order is still simulated paper state in this stage. Never reuse production API keys for this test.

## MT5 demo connection

MT5's official Python integration communicates with a locally installed MT5 terminal. It generally needs a supported Windows host with terminal and broker demo account; a Linux GitHub Codespace is not a normal MT5 terminal host.

Install the vendor package in that Windows environment (python -m pip install MetaTrader5), open/login to a broker's demo account in MT5, then use MT5ReadOnly().connect() and fetch_rates("EURUSD", "M15"). Some brokers use symbol suffixes; use the exact symbol in Market Watch. The connector refuses accounts that do not report demo trade mode and a demo-named server.

## Mandatory gates before any order-enabled demo adapter

1. Add an exchange-specific Bybit demo execution adapter, then verify market/limit order placement, rejected orders, cancellation, partial fills, and query-by-client-order-ID against the actual demo API.
2. Implement Bybit-native conditional stop-loss/take-profit protection appropriate to spot versus derivatives. Place protection immediately after confirmed fills; verify it remotely and halt new entries if protection is missing. Never assume generic OCO support.
3. Reconcile order state, cumulative fills, wallet balances and open positions after timeouts, restarts, duplicate events and partial fills. Persist client order IDs and a durable journal.
4. Use MT5 order_calc_profit for loss-per-lot at the actual stop, round volume downward to broker min/max/step, check margin, and test order_check/demo order_send only after a separate explicit order-enabled demo phase is reviewed. Confirm attached SL/TP and reconcile tickets/deals/positions.
5. Enforce portfolio-wide risk: total open risk, daily loss limit, max positions, stale data, spread limits, cooldown, and kill switch across both adapters.
6. Add integration tests that run on the actual Bybit demo account and MT5 demo account, with sanitized evidence. Unit tests and market-data connectivity alone are insufficient.
7. Independent review of code, logs and test evidence. Live execution remains disabled regardless of test results until an explicit separate release decision.

## Acceptance checks for this commit

- Unit tests for the 0.25% cap and volume rounding.
- Bybit demo endpoint selection occurs before market loading.
- MT5 connector contains read-only market/account access only.
- No new order-sending or live-mode enablement path is introduced.
