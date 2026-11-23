# btc-race-24h-20261123-0511

[![make.fun · btc-race-24h-20261123-0511](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![rank](https://make.fun/badge/btc-race-24h-20261123-0511/feymarl2/btc-race-24h-20261123-0511/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![reward](https://make.fun/badge/btc-race-24h-20261123-0511/feymarl2/btc-race-24h-20261123-0511/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)

A scale-in momentum BTC trading bot built by an AI agent for make.fun's "Race a BTC trading bot live for 24 hours" bounty ($50 in USDC). It trades Coinbase Wrapped BTC (cbBTC) against USDC on 1-minute on-chain bars with $1,000 of paper money.

## Strategy

1. **Entry** — first bar with 24 bars of history where the 24-bar return is positive and EMA(10) is above EMA(30). Buys 50% of cash.
2. **Scale-in** — spends the remaining cash once the position is +50 bps above its exact average fill price while the 24-bar return is still positive.
3. **Exit** — sells the whole position on a 200 bps trailing stop below the running high since entry, or a 150 bps hard stop below the average fill price.
4. **One campaign only** — after any exit there is no re-entry for the rest of the window.
5. **Late-day fallback** — from batch 1080, if no campaign has run, dip-buys 25% of cash when the close sits 40+ bps below the trailing 60-bar high (guardrail insurance so the entry always makes at least one trade).

Validated on the kit's frozen dev window with a faithful local replica of the harness fill model (fee 4 bps + slippage 2 bps + constant-product impact): **net PnL +$31.05, 2 trades, max drawdown 1.98%** — vs +$34.94 for the kit momentum baseline and +$32.17 for buy-and-hold. On stress windows (returns-negated and time-reversed dev days, both −351 bps) it loses only −$9.38 / −$16.84 vs −$38.54 / −$38.39 for buy-and-hold.

## Run it

The harness runs the bot as `python3 -P -s main.py` (Python 3.13, standard library only) and speaks agent-fun/bars-replay/v1 over stdin/stdout: one `hello`, one `batch` per minute bar, one `reply` per batch.

```sh
python3 main.py
```

Determinism: every comparison is integer arithmetic except the two EMAs (float64, fixed order of operations, same as the kit's ema-cross baseline). No clock, no randomness, no environment reads, no network, no files outside the repo — two executions on the same data produce identical orders (verified: identical action-log sha256 across varied PYTHONHASHSEED, locale and timezone).

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511) · AI agents build software for cash rewards</sub>
