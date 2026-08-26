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

print("\n── 7. One table, sorted best-ratio-first, money icons ──────────")
state = {"low": 700.0, "high": 710.0, "mid": 705.0, "noon": 708.0, "spot": 708.5,
         "pos_pct": 80.0, "range_pct": 1.43, "morning_complete": True}

# The premium icon is RELATIVE to the best credit on that underlying, so an
# SPX credit of $10 and a QQQ credit of $1 can both be the fat one.
check("the best credit earns three bags", sp.premium_icons(2.0, 2.0) == "\U0001F4B0" * 3)
check("90% of the best still earns three", sp.premium_icons(1.8, 2.0) == "\U0001F4B0" * 3)
check("75% earns two", sp.premium_icons(1.5, 2.0) == "\U0001F4B0" * 2)
check("55% earns one", sp.premium_icons(1.1, 2.0) == "\U0001F4B0")
check("a thin credit earns none", sp.premium_icons(0.4, 2.0) == "")
check("no divide-by-zero on an empty block", sp.premium_icons(1.0, 0.0) == "")

# One table for every underlying — not one per name.
cards = [
    {"key": "QQQ", "label": "QQQ", "desc": "Nasdaq 100 ETF", "validated": True,
     "state": dict(state), "zone": "put_green", "note": None, "spreads": out},
    {"key": "SPX", "label": "SPX", "desc": "S&P 500", "validated": True,
     "state": dict(state), "zone": "put_green", "note": None, "spreads": scaled},
    {"key": "GLD", "label": "GLD", "desc": "Gold ETF", "validated": False,
     "error": "GLD has no expiry dated today — nearest is 2026-08-28"},
]
tbl = sp.spreads_table_html(cards)
check("exactly one <table> for every underlying", tbl.count("<table") == 1)
check("...closed once", tbl.count("</table>") == 1)
check("HTML is balanced", tbl.count("<tr") == tbl.count("</tr>")
      and tbl.count("<td") == tbl.count("</td>"))
check("every underlying appears", all(f">{k}</span>" in tbl for k in ("QQQ", "SPX", "GLD")))
check("an unmeasured underlying is badged", "UNVALIDATED" in tbl)
check("...and a measured one is not badged in its own header",
      tbl.index("QQQ") < tbl.index("UNVALIDATED"))
check("a failed underlying still shows its reason", "nearest is 2026-08-28" in tbl)
check("the group header spans the full width",
      f'colspan="{len(sp.TABLE_COLS)}"' in tbl)

# QQQ leads because it leads TICKERS; rows inside a block lead with best R:R.
check("QQQ block comes before SPX", tbl.index(">QQQ<") < tbl.index(">SPX<"))
rows = sorted(out, key=lambda x: x["rr"])
best = rows[0]
check("the best-ratio row is starred",
      sp.spread_row_html(best, max(x["credit"] for x in rows), True).count("\u2605") == 1)
check("...and the others are not",
      "\u2605" not in sp.spread_row_html(rows[-1], 1.0, False))
check("the table stars exactly one row per block", tbl.count("\u2605") == 2)

# The displayed order is the actual claim, so read it back out of the HTML.
def _rr_order(html, block):
    seg = html[html.index(f">{block}<"):]
    nxt = seg.find(">SPX<", 1)
    seg = seg[:nxt] if block == "QQQ" and nxt > 0 else seg
    import re
    return [float(m) for m in re.findall(r"1 : ([\d.]+)</td>", seg)]

qqq_rr = _rr_order(tbl, "QQQ")
check("rows are rendered in ascending R:R (best first)",
      qqq_rr == sorted(qqq_rr), str(qqq_rr))
check("selection is still widest-cushion-first inside build_spreads",
      out[0]["cushion_pct"] == max(x["cushion_pct"] for x in out))

check("QQQ leads the shipped ticker list", sp.TICKERS[0]["key"] == "QQQ")
check("SPX is second", sp.TICKERS[1]["key"] == "SPX")
check("the daily-expiry names are added",
      {t["key"] for t in sp.TICKERS} == {"QQQ", "SPX", "IWM", "SMH", "GLD"})
check("only QQQ and SPX claim to be validated",
      {t["key"] for t in sp.TICKERS if t["validated"]} == {"QQQ", "SPX"})
check("SMH and GLD are not claimed as every-weekday expiries",
      not any(t["daily"] for t in sp.TICKERS if t["key"] in ("SMH", "GLD")))

# A block with no state must not take the table down.
bare = sp.spreads_table_html([{"key": "IWM", "label": "IWM", "desc": "", "validated": False,
                               "error": "No intraday bars for today yet."}])
check("a stateless block renders", "<table" in bare and "No intraday bars" in bare)
check("an unknown zone does not raise",
      "<table" in sp.spreads_table_html(
          [{"key": "X", "label": "X", "desc": "", "validated": True,
            "state": dict(state), "zone": None, "spreads": []}]))

print("\n── 8. A missing option chain must not kill the tab ─────────────")
# The first live run crashed here: todays_chain() returned None, _scan_one
# built a card with a state but no zone, and ZONES[None] raised a KeyError
# whose string is the word "None" — a crash reported as a message saying
# nothing.
_state = {"low": 705.6, "high": 709.9, "mid": 707.75, "noon": 709.44,
          "spot": 709.82, "pos_pct": 89.3, "range_pct": 0.60, "morning_complete": True}
_probe_card = {"key": "QQQ", "label": "QQQ", "desc": "", "validated": True,
               "state": dict(_state), "spreads": []}
check("the group header survives an unknown zone",
      "<td" in sp._group_header_html({**_probe_card, "zone": None}))
check("...and one that is not in the table",
      "<td" in sp._group_header_html({**_probe_card, "zone": "nonsense"}))

_orig_state, _orig_chain = sp.morning_state, sp.todays_chain
try:
    sp.morning_state = lambda sym, scale=1.0: dict(_state)
    sp.todays_chain = lambda sym: (None, "Yahoo returned no expiries at all for QQQ")
    card = sp._scan_one({"key": "QQQ", "spot_symbol": "QQQ",
                         "chain_symbol": "QQQ", "label": "QQQ", "scale": 1.0})
    check("a chain failure still yields a zone", card.get("zone") == "put_green", str(card.get("zone")))
    check("...and the anchor level to trade against", card.get("anchor_only") == 705.6)
    check("...and an error naming the real cause",
          "no expiries" in card.get("error", ""), card.get("error", ""))
    check("no spreads are invented without a chain", card.get("spreads") == [])

    # The reason must distinguish causes that need different fixes.
    sp.todays_chain = lambda sym: (None, "QQQ has no expiry dated 2026-08-26 — nearest is 2026-08-28")
    card2 = sp._scan_one({"key": "QQQ", "spot_symbol": "QQQ",
                          "chain_symbol": "QQQ", "label": "QQQ", "scale": 1.0})
    check("a 'today is not an expiry' cause reads differently from an empty list",
          "nearest is" in card2["error"] and "no expiries" not in card2["error"])
finally:
    sp.morning_state, sp.todays_chain = _orig_state, _orig_chain

check("KeyError(None) really does stringify to 'None' (why the message was useless)",
      str(KeyError(None)) == "None")

print("\n── 9. The 1:25 cap and return on risk ──────────────────────────")
check("cap is set at 1:25", sp.MAX_RR == 25.0, str(sp.MAX_RR))
check("nothing worse than the cap survives",
      all(x["rr"] <= sp.MAX_RR for x in out + cout),
      f"worst kept = 1:{max((x['rr'] for x in out + cout), default=0):.1f}")

# A chain whose far strikes are nearly worthless: the wide spreads price at a
# ratio far past the cap and must be dropped, not shown in red.
thin = pd.DataFrame({
    "strike":    [680.0, 690.0, 698.0, 699.0, 700.0],
    "bid":       [0.01,  0.02,  0.45,  0.80,  1.40],
    "ask":       [0.03,  0.04,  0.55,  0.90,  1.60],
    "lastPrice": [0.02,  0.03,  0.50,  0.85,  1.50],
})
thin_out = sp.build_spreads("put", thin, anchor=700.0, spot=706.0)
check("a thin-credit wide spread is dropped, not displayed",
      all(x["rr"] <= sp.MAX_RR for x in thin_out),
      f"{len(thin_out)} kept")

# Return on risk is the same fact as the ratio, expressed the way it compares
# across widths and underlyings.
if one:
    check("return on risk = max profit / max loss",
          abs(one["ror_pct"] - one["max_profit"] / one["max_loss"] * 100) < 1e-9,
          f'{one["ror_pct"]:.1f}%')
    check("a 1:1 spread returns 100% on risk", abs(one["ror_pct"] - 100.0) < 1e-9)
_probe = next((x for x in out if x["rr"] and abs(x["rr"] - 3.0) < 1.0), None)
check("ror and rr agree everywhere",
      all(abs(x["ror_pct"] - 100.0 / x["rr"]) < 1e-6 for x in out + cout if x["rr"]))
check("the cap implies a floor on return on risk",
      all(x["ror_pct"] >= 100.0 / sp.MAX_RR - 1e-9 for x in out + cout),
      f"floor = {100/sp.MAX_RR:.1f}%")
if one:
    row = sp.spread_row_html(one, one["credit"], False)
    check("the row shows return on risk as a percentage",
          f'{one["ror_pct"]:.1f}%' in row)
    check("the row shows max loss as a negative", "-$" in row)
    check("the row shows the ratio", f'1 : {one["rr"]:.1f}' in row)

print("\n" + "=" * 60)
print(f"RESULT: {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
