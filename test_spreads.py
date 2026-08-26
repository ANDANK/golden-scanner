"""Spreads tab — zone gating and credit-spread arithmetic.

Every expected value below is computed by hand in the test, not read back
from the code under test.
"""
import os
import sys
from unittest.mock import MagicMock

import numpy as np
import pandas as pd


class _FakeSS(dict):
    def __missing__(self, k): return None


class _MockST:
    session_state = _FakeSS()
    @staticmethod
    def cache_data(ttl=None, show_spinner=True):
        def _d(fn): return fn
        return _d
    def __getattr__(self, n): return MagicMock()


sys.modules["streamlit"] = _MockST()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanners import spreads as sp

FAILS = []


def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


print("\n── 1. Zone gating matches the measured breach rates ────────────")
check("noon 100% -> put green", sp.zone_for(100.0) == "put_green")
check("noon 70% -> put green (inclusive)", sp.zone_for(70.0) == "put_green")
check("noon 69.9% -> amber, not green", sp.zone_for(69.9) == "put_amber")
check("noon 60% -> amber (inclusive)", sp.zone_for(60.0) == "put_amber")
check("noon 59.9% -> BLOCKED", sp.zone_for(59.9) == "put_block")
check("noon 50% -> BLOCKED (exactly at midpoint is not a put)", sp.zone_for(50.0) == "put_block")
check("noon 49.9% -> call side", sp.zone_for(49.9) == "call")
check("noon 0% -> call side", sp.zone_for(0.0) == "call")
check("the blocked zone offers no label implying a trade",
      sp.ZONES["put_block"]["label"] == "NO TRADE")
check("each zone states a real breach figure",
      all("/" in z["breach"] and "%" in z["breach"] for z in sp.ZONES.values()))

print("\n── 2. Credit-spread arithmetic (hand-checked) ──────────────────")
# QQQ-style $1 grid. Short 700 at 1.50 mid, long 698 at 0.50 mid.
puts = pd.DataFrame({
    "strike":    [696.0, 697.0, 698.0, 699.0, 700.0, 701.0],
    "bid":       [0.20,  0.30,  0.45,  0.80,  1.40,  2.10],
    "ask":       [0.30,  0.40,  0.55,  0.90,  1.60,  2.30],
    "lastPrice": [0.25,  0.35,  0.50,  0.85,  1.50,  2.20],
})
out = sp.build_spreads("put", puts, anchor=700.0, spot=706.0)
check("candidates produced", len(out) > 0, f"{len(out)}")
one = next((x for x in out if x["short"] == 700.0 and x["long"] == 698.0), None)
check("the 700/698 spread is offered", one is not None)
if one:
    # short mid = (1.40+1.60)/2 = 1.50 ; long mid = (0.45+0.55)/2 = 0.50
    check("credit = short mid - long mid", abs(one["credit"] - 1.00) < 1e-9, f'{one["credit"]}')
    check("max profit = credit x 100", abs(one["max_profit"] - 100.0) < 1e-9)
    check("max loss = (width - credit) x 100", abs(one["max_loss"] - 100.0) < 1e-9)
    check("R:R = max loss / max profit", abs(one["rr"] - 1.0) < 1e-9)
    check("breakeven = short - credit", abs(one["breakeven"] - 699.0) < 1e-9)
    check("cushion measured from spot",
          abs(one["cushion_pct"] - (706.0 - 700.0) / 706.0 * 100) < 1e-9)

print("\n── 3. Strikes are anchored, not chosen to hit a ratio ──────────")
check("no put short strike sits above the morning low",
      all(x["short"] <= 700.0 for x in out))
calls = pd.DataFrame({
    "strike":    [710.0, 711.0, 712.0, 713.0],
    "bid":       [1.40,  0.80,  0.45,  0.20],
    "ask":       [1.60,  0.90,  0.55,  0.30],
    "lastPrice": [1.50,  0.85,  0.50,  0.25],
})
cout = sp.build_spreads("call", calls, anchor=710.0, spot=706.0)
check("no call short strike sits below the morning high",
      cout and all(x["short"] >= 710.0 for x in cout))
check("call breakeven is above the short strike",
      cout and all(x["breakeven"] > x["short"] for x in cout))
check("call cushion is positive when spot is below the short",
      cout and all(x["cushion_pct"] > 0 for x in cout))

print("\n── 4. Bad quotes are dropped, not shown as free money ──────────")
junk = pd.DataFrame({
    "strike":    [698.0, 699.0, 700.0],
    "bid":       [0.0,   0.0,   0.0],
    "ask":       [0.0,   0.0,   0.0],
    "lastPrice": [0.0,   0.0,   0.0],
})
check("a 0x0 chain yields nothing", sp.build_spreads("put", junk, 700.0, 706.0) == [])
inverted = pd.DataFrame({
    "strike":    [698.0, 700.0],
    "bid":       [3.00,  0.10],   # long leg worth MORE than the short
    "ask":       [3.20,  0.20],
    "lastPrice": [3.10,  0.15],
})
check("a negative credit is not offered",
      all(x["credit"] > 0 for x in sp.build_spreads("put", inverted, 700.0, 706.0)))
check("credit can never exceed the width",
      all(x["credit"] < x["width"] for x in out + cout))
check("an empty chain is handled", sp.build_spreads("put", pd.DataFrame(), 700.0, 706.0) == [])

print("\n── 5. The SPX x10 scaling ──────────────────────────────────────")
scaled = sp.build_spreads("put", puts, anchor=7000.0, spot=7060.0, scale=10.0)
# Not scaled[0]: candidates are sorted widest-cushion-first, so the furthest
# strike leads. Assert the whole grid scaled, which is the actual claim.
check("every scaled strike is a x10 multiple of the base grid",
      scaled and all(x["short"] in (7000.0, 6990.0, 6980.0) for x in scaled),
      str(sorted({x["short"] for x in scaled})))
check("widest cushion really is first",
      scaled and scaled[0]["cushion_pct"] == max(x["cushion_pct"] for x in scaled))
s10 = next((x for x in scaled if x["short"] == 7000.0 and x["long"] == 6980.0), None)
check("scaled credit is x10", s10 is not None and abs(s10["credit"] - 10.0) < 1e-9)
check("scaled max loss follows the scaled width",
      s10 is not None and abs(s10["max_loss"] - 1000.0) < 1e-9)

print("\n── 6. Time guard ───────────────────────────────────────────────")
check("valid window brackets noon",
      sp.VALID_FROM_MIN < sp.NOON_MIN < sp.VALID_TO_MIN)
check("11:45 ET is inside the window", sp.VALID_FROM_MIN == 11 * 60 + 45)
check("15:00 ET is outside", 15 * 60 > sp.VALID_TO_MIN)

print("\n── 7. Range bar renders without a chart library ────────────────")
state = {"low": 700.0, "high": 710.0, "mid": 705.0, "noon": 708.0, "spot": 708.5,
         "pos_pct": 80.0, "range_pct": 1.43, "morning_complete": True}
bar = sp.range_bar_html(state, "put_green")
check("bar is HTML", "<div" in bar and bar.count("<div") == bar.count("</div>"))
check("marker sits at the noon position", "left:80.0%" in bar)
check("gate ticks are drawn", all(f"left:{x}%" in bar for x in (50, 60, 70)))
check("low and high are labelled", "700.00" in bar and "710.00" in bar)
if one:
    card = sp.spread_card_html(one, True)
    check("spread card is balanced HTML", card.count("<div") == card.count("</div>"))
    check("card shows R:R", "Risk : Reward" in card)
    check("card shows max loss as a negative", "-$" in card)

print("\n" + "=" * 60)
print(f"RESULT: {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
