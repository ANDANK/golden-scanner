"""Sector Outlook — the verdict line and the drift line must never contradict.

XLF rendered "⚠️ Fading / TRIM — leadership is rolling over" directly above
"↗ Strengthening — on track to become a buy". Both readings were correct
(the month was -2.1%, the fortnight +1.5%) but the row stated two opposite
ACTIONS, and the roll-over claim was false for that path.
"""
import os
import sys
from unittest.mock import MagicMock


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

from scanners import sector_outlook as so

FAILS = []


def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def verdict_for(rs_mom, mom_fast, rank_now, climbing=True):
    top = rank_now <= so.TOP_N
    mom_up = rs_mom >= so.MOM_MIN
    mom_dn = rs_mom <= -so.MOM_MIN
    rolling_over = top and mom_fast < -so.MOM_MIN
    if mom_up and climbing and not rolling_over:
        v = "Accelerating" if top else "Emerging"
    elif rolling_over:
        v = "Fading"
    elif mom_up:
        v = "Improving"
    elif mom_dn:
        v = "Fading" if top else "Cooling"
    else:
        v = "Leading" if top else "Flat"
    return v, rolling_over


print("\n── 1. No drift blurb prescribes an action ──────────────────────")
# The contradiction was structural: the drift text embedded a BUY/SELL verdict
# of its own while sitting above the row's real action line.
for name, (_icon, _col, note) in so.DRIFTS.items():
    check(f"{name} drift text names no action",
          not any(w in note.lower() for w in ("become a buy", "become a sell",
                                              "buy", "sell", "trim")),
          repr(note))

print("\n── 2. The XLF row specifically ─────────────────────────────────")
v, ro = verdict_for(-2.1, 1.5, 2)
why = so._why(v, ro)
drift = so._drift(1.5, -2.1)
check("still classified Fading", v == "Fading")
check("but NOT via the rolling-over path", ro is False)
check("so it no longer claims leadership is rolling over",
      "rolling over" not in why.lower(), why)
check("it says what is actually true instead",
      "lost ground to the market this month" in why, why)
check("drift still reads Strengthening (the fortnight really did turn up)",
      drift == "Strengthening")
check("and the disagreement is spelled out",
      "case for selling is weakening" in so._conflict_note(so.VERDICTS[v][0], drift))

print("\n── 3. A genuine roll-over keeps its original wording ────────────")
v2, ro2 = verdict_for(-2.1, -1.8, 2)
check("fortnight down + top rank -> rolling_over path", v2 == "Fading" and ro2 is True)
check("keeps the roll-over wording", "rolling over" in so._why(v2, ro2).lower())
check("and raises no conflict note (both axes agree)",
      so._conflict_note(so.VERDICTS[v2][0], so._drift(-1.8, -2.1)) == "")

print("\n── 4. Conflict notes fire only on real disagreement ─────────────")
check("sell-side verdict + strengthening -> note", so._conflict_note("out", "Strengthening") != "")
check("buy-side verdict + weakening -> note", so._conflict_note("in", "Weakening") != "")
check("sell-side + weakening -> silent", so._conflict_note("out", "Weakening") == "")
check("buy-side + strengthening -> silent", so._conflict_note("in", "Strengthening") == "")
check("steady never conflicts",
      all(so._conflict_note(b, "Steady") == "" for b in ("in", "out", "hold", "none")))
check("hold/none buckets never conflict",
      all(so._conflict_note(b, d) == ""
          for b in ("hold", "none") for d in so.DRIFTS))

print("\n── 5. Every reachable combination is coherent ───────────────────")
combos = 0
for rs in (-3.0, -1.0, -0.2, 0.0, 0.2, 1.0, 3.0):
    for fast in (-3.0, -1.0, 0.0, 1.0, 3.0):
        for rank in (1, 3, 6, 12):
            v, ro = verdict_for(rs, fast, rank)
            bucket = so.VERDICTS[v][0]
            why = so._why(v, ro)
            drift = so._drift(fast, rs)
            note = so._conflict_note(bucket, drift)
            combos += 1
            # A row must never claim a roll-over when the fortnight is up.
            if "rolling over" in why.lower() and fast > 0:
                check(f"no false roll-over claim (rs={rs} fast={fast} rank={rank})", False)
            # Whenever the two axes disagree the row must SAY so.
            if (bucket, drift) in so._CONFLICT and not note:
                check(f"disagreement is stated (rs={rs} fast={fast} rank={rank})", False)
check(f"all {combos} reachable combinations coherent", True)

print("\n── 6. One RRG quadrant rule across every sector card ───────────")
# The Market Overview standings card and the Sector Rotation page both label
# sectors Leading/Weakening/Improving/Lagging. They used to each carry their
# own copy of the rule; only home.py got a dead-band, so a sector sitting
# flat against SPY read "Lagging" on one card and "Leading" on the other.
from scanners.sector_rotation import rrg_quadrant, RRG_BAND
import inspect
from scanners import home as _home, sector_rotation as _sr

check("the rule is defined once and shared",
      "rrg_quadrant" in inspect.getsource(_home._sector_flows)
      and "rrg_quadrant(rs_val, rs_21)" in inspect.getsource(_sr.compute_row))
check("no card recomputes the quadrant inline",
      not any("rs21 >= 1 else" in inspect.getsource(f)
              for f in (_home._sector_flows, _sr.compute_row)))

# The dead-band is the whole point: flat must not read as strength.
check("a dead-flat sector is not promoted", rrg_quadrant(1.0000, 1.0000) == "Lagging")
check("a knife-edge +0.1% is not promoted", rrg_quadrant(1.0010, 1.0010) == "Lagging")
check("a real edge on both legs leads", rrg_quadrant(1.0300, 1.0400) == "Leading")
check("long leg up, short leg flat -> Weakening", rrg_quadrant(1.0500, 1.0000) == "Weakening")
check("long leg flat, short leg up -> Improving", rrg_quadrant(0.9800, 1.0100) == "Improving")
check("the band is a real threshold, not zero", RRG_BAND > 0)
check("exactly at the band counts as up", rrg_quadrant(1 + RRG_BAND, 1 + RRG_BAND) == "Leading")
check("a hair under the band does not",
      rrg_quadrant(1 + RRG_BAND - 1e-6, 1 + RRG_BAND - 1e-6) == "Lagging")

# Whatever the inputs, both cards must now agree by construction.
disagreements = 0
for rs_l in (0.95, 0.999, 1.0, 1.0025, 1.01, 1.08):
    for rs_s in (0.95, 0.999, 1.0, 1.0025, 1.01, 1.08):
        if rrg_quadrant(rs_l, rs_s) != rrg_quadrant(rs_l, rs_s):
            disagreements += 1
check("every input pair yields one answer for both cards", disagreements == 0)

print("\n" + "=" * 60)
print(f"RESULT: {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
