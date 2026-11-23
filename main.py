"""Scale-in momentum bot for btc-race-24h-20261123-0511 (agent-fun/bars-replay/v1).

Strategy (validated against the kit's dev window with a faithful local replica
of sim/bars/engine.ts, see BUILD-NOTE.md in the work dir):
  1. Entry: first bar with 24 bars of history where the 24-bar return is
     positive AND EMA(10) of closes is above EMA(30). Buy 50% of cash.
  2. Scale-in: spend the remaining cash once the position is +50 bps above
     its exact average fill price while the 24-bar return is still positive.
  3. Exit the whole position on a 200 bps trailing stop below the running
     high since entry, or a 150 bps hard stop below the average fill price.
  4. One campaign only: after any exit there is no re-entry.
  5. Late-day fallback (guardrail insurance, only if no campaign has run):
     from batch 1080, dip-buy 25% of cash when the close sits 40+ bps below
     the trailing 60-bar high. Same exits.
  6. No time exit: the harness flattens any held position at the last close.

Determinism: every comparison is integer arithmetic except the two EMAs,
which are float64 in a fixed order of operations (the same construction the
kit's ema-cross baseline uses). No clock, no randomness, no environment
reads, no network, no files outside the repo, no set/dict iteration that
could affect output. Two executions on the same data produce identical
orders. hello, batch, orders and bar are the protocol words this bot speaks.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
EMA_FAST_SPAN = 10
EMA_SLOW_SPAN = 30
RET_LOOKBACK = 24
ADD_BPS = 50
TRAIL_BPS = 200
STOP_BPS = 150
FALLBACK_SEQ = 1080
FALLBACK_DIP_BPS = 40
FALLBACK_FRACTION_NUM = 1
FALLBACK_FRACTION_DEN = 4
ENTRY_CUTOFF_SEQ = 1380
BUY_SLIPPAGE_BPS = 100
SELL_SLIPPAGE_BPS = 300
MIN_NOTIONAL = 1000000


class Bot:
    """One symbol, one position, one campaign. All state is explicit."""

    def __init__(self):
        self.closes = []
        self.ema_fast = None
        self.ema_slow = None
        self.sum_price_qty = 0
        self.sum_qty = 0
        self.high = 0
        self.held_bars = 0
        self.campaigns = 0
        self.scaled_in = False

    def _ema_step(self, close):
        """EMA seeded at the first close, then 2/(span+1) toward each close."""
        value = float(close)
        if self.ema_fast is None:
            self.ema_fast = value
            self.ema_slow = value
            return
        self.ema_fast += (2.0 / (EMA_FAST_SPAN + 1)) * (value - self.ema_fast)
        self.ema_slow += (2.0 / (EMA_SLOW_SPAN + 1)) * (value - self.ema_slow)

    def _ret24_positive(self):
        """True when the close is above the close 24 bars back (integer compare)."""
        if len(self.closes) <= RET_LOOKBACK:
            return False
        return self.closes[-1] > self.closes[-1 - RET_LOOKBACK]

    def _trailing_high60(self):
        """Highest close of the bars before the current one, up to 60 back."""
        prior = self.closes[:-1]
        if not prior:
            return 0
        return max(prior[-60:])

    def _apply_fills(self, state, fills):
        """Fold this batch's fills into the average-fill-price bookkeeping."""
        for fill in fills or []:
            if fill.get("symbol") != SYMBOL or fill.get("status") != "filled":
                continue
            qty = int(fill["qty"])
            price = int(fill["price"])
            if fill.get("side") == "buy":
                if qty > 0:
                    if self.sum_qty > 0:
                        # A buy while already holding is the scale-in leg.
                        self.scaled_in = True
                    self.sum_price_qty += price * qty
                    self.sum_qty += qty
            elif fill.get("side") == "sell":
                if qty > 0:
                    self.sum_qty -= qty
                    if self.sum_qty <= 0:
                        self.sum_price_qty = 0
                        self.sum_qty = 0
                        self.high = 0
                        self.held_bars = 0
                        self.scaled_in = False
                        self.campaigns += 1

    def on_batch(self, state, batch):
        self._apply_fills(state, batch.get("fills"))
        bars = batch.get("bars") or []
        bar = None
        for candidate in bars:
            if candidate.get("symbol") == SYMBOL:
                bar = candidate
                break
        if bar is None:
            return []
        close = int(bar["c"])
        self.closes.append(close)
        self._ema_step(close)
        if state.warming_up:
            return []
        held = state.positions.get(SYMBOL)
        qty = held.qty if held is not None else 0
        seq = state.seq
        if qty > 0 and self.sum_qty > 0:
            self.held_bars += 1
            if close > self.high:
                self.high = close
            # Scale-in: +50 bps above the exact average fill price, trend up.
            if (not self.scaled_in
                    and close * self.sum_qty * 10000
                    >= self.sum_price_qty * (10000 + ADD_BPS)
                    and self._ret24_positive()
                    and state.cash >= MIN_NOTIONAL):
                # scaled_in is set only when this add's fill arrives; a
                # rejected add retries on the next bar while the condition
                # still holds.
                return [{"side": "buy", "symbol": SYMBOL,
                         "notional_quote_units": state.cash,
                         "max_slippage_bps": BUY_SLIPPAGE_BPS,
                         "client_id": "add%d" % seq}]
            # Exit: 200 bps trailing stop below the running high (after 2 bars),
            # or 150 bps hard stop below the average fill price.
            trail_hit = (self.held_bars >= 2
                         and (self.high - close) * 10000 >= self.high * TRAIL_BPS)
            stop_hit = (close * self.sum_qty * 10000
                        <= self.sum_price_qty * (10000 - STOP_BPS))
            if trail_hit or stop_hit:
                return [{"side": "sell", "symbol": SYMBOL, "qty": qty,
                         "max_slippage_bps": SELL_SLIPPAGE_BPS,
                         "client_id": "exit%d" % seq}]
            return []
        if qty > 0:
            # Holding without fill bookkeeping (should not happen): exit safely.
            return [{"side": "sell", "symbol": SYMBOL, "qty": qty,
                     "max_slippage_bps": SELL_SLIPPAGE_BPS,
                     "client_id": "exit%d" % seq}]
        if self.campaigns >= 1 or seq >= ENTRY_CUTOFF_SEQ:
            return []
        if len(self.closes) <= RET_LOOKBACK:
            return []
        if state.cash < MIN_NOTIONAL:
            return []
        # Main entry: 24-bar return positive and fast EMA above slow EMA.
        if self._ret24_positive() and self.ema_fast > self.ema_slow:
            return [{"side": "buy", "symbol": SYMBOL,
                     "notional_quote_units": state.cash // 2,
                     "max_slippage_bps": BUY_SLIPPAGE_BPS,
                     "client_id": "entry%d" % seq}]
        # Late-day fallback: no campaign yet, buy a 40+ bps dip with 25% of cash.
        if seq >= FALLBACK_SEQ:
            high60 = self._trailing_high60()
            if (high60 > 0
                    and close * 10000 <= high60 * (10000 - FALLBACK_DIP_BPS)):
                notional = (state.cash * FALLBACK_FRACTION_NUM) // FALLBACK_FRACTION_DEN
                if notional >= MIN_NOTIONAL:
                    return [{"side": "buy", "symbol": SYMBOL,
                             "notional_quote_units": notional,
                             "max_slippage_bps": BUY_SLIPPAGE_BPS,
                             "client_id": "fb%d" % seq}]
        return []


def main():
    makefun_bars.run(Bot().on_batch)


if __name__ == "__main__":
    main()
