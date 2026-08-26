# scanners/sector_outlook.py — "where is the money heading?" for the 11 sector
# ETFs, as opposed to "where has it been", which is what an RS ranking tells you.
#
# The problem this exists to solve: RS vs SPY is a 63-day ratio, so the rank is
# a verdict on the LAST QUARTER. A sector that bottomed three weeks ago and has
# been climbing hard ever since still ranks near the bottom, because 40 of the
# 63 days in its window are the old decline. By the time it reaches the top of
# the table the move is largely spent. Ranking by level is structurally late.
#
# The fix is not a different lookback — it is a different QUESTION. Rather than
# "how strong is this sector", ask "which direction is its strength moving, how
# fast, and how consistently". That is the RRG "Improving" quadrant made
# explicit and sortable:
#
#   RS level     — where it is now          (lagging, what the rank shows)
#   RS momentum  — how fast that is changing (leading, what this module adds)
#
# A sector can be rank 14 and the single most attractive thing on the page, if
# its RS has been climbing for a month. That is exactly the case a snapshot
# cannot express.
#
# Everything here is derived from the backfilled history the Rotation History
# panel already computes, so it costs no extra network and every input is a
# settled close.
#
# Honest limits, because this is money:
#   * "Leading" here means leading relative to SPY, never a price forecast.
#     Nothing in this module predicts returns; it measures the direction and
#     persistence of a trend that is already underway.
#   * Momentum turns are noisy. A one-week improvement is not a trend, which
#     is why every verdict requires BOTH a momentum threshold and a rank move,
#     and why consistency (how many sessions actually rose) is reported beside
#     each call rather than buried.
#   * Early means early, including early and wrong. An "Emerging" sector is a
#     candidate to research, not a signal to buy.

from __future__ import annotations

import numpy as np
import pandas as pd

# Windows, in trading sessions. 20 ≈ one month: long enough that a couple of
# noisy days cannot manufacture a trend, short enough to see a turn well
# before the 63-day RS level reflects it.
MOM_WINDOW = 20
FAST_WINDOW = 10

# Thresholds. A sector must clear BOTH a momentum bar and a rank-movement bar
# to be called anything directional -- either alone fires far too often.
MOM_MIN = 0.4       # % change in RS over MOM_WINDOW to count as improving
RANK_MIN = 2        # places gained/lost over MOM_WINDOW to confirm it
TOP_N = 5           # "already leading" cutoff

VERDICTS = {
    # verdict:      (bucket, colour key, icon, one-line meaning)
    "Emerging":     ("in",   "green", "🌱",
                     "Still ranked low, but relative strength has been climbing "
                     "for weeks — money is moving in before the ranking shows it"),
    "Accelerating": ("in",   "green", "🚀",
                     "Already strong and still gaining ground — the trend is "
                     "intact and speeding up"),
    "Leading":      ("hold", "gold",  "👑",
                     "Established leader, holding its ground — a core position "
                     "rather than a new entry"),
    "Improving":    ("hold", "gold",  "📈",
                     "Gaining on the market, but its peers are gaining faster — "
                     "real improvement, not yet leadership. Watchlist"),
    "Cooling":      ("none", "muted", "🌡️",
                     "Losing ground to the market while holding its rank — the "
                     "first hint of deterioration, not yet a reason to act"),
    "Fading":       ("out",  "red",   "⚠️",
                     "Still ranked high, but losing ground — the leadership is "
                     "rolling over, trim into strength"),
    "Falling":      ("out",  "red",   "🔻",
                     "Weak and getting weaker — no reason to be here yet"),
    "Flat":         ("none", "muted", "▬",
                     "Drifting with the market — no directional edge either way"),
}


# Why each verdict lands in its bucket, phrased as the decision itself. The
# longer VERDICTS text explains the state; this explains the ACTION.
WHY = {
    "Emerging":     "BUY — money is moving in before the ranking shows it",
    "Accelerating": "BUY — trend is intact and still speeding up",
    "Leading":      "HOLD — already ahead and staying there",
    "Improving":    "WATCH — gaining on the market, peers gaining faster",
    "Cooling":      "WAIT — slipping vs the market, rank has not caught up",
    # Two different conditions both produce "Fading" and they are not the same
    # animal, so the action line is chosen per row by _why() rather than read
    # from here — this entry covers the rolling-over case only.
    "Fading":       "TRIM — leadership is rolling over while the price is still good",
    "Falling":      "AVOID — weak and getting weaker",
    "Flat":         "IGNORE — no edge either way",
}

# Which way a row is drifting, i.e. what it is likely to become next. This is
# the whole answer to "it says HOLD, but is it on its way up or down?" -- a
# bucket label alone cannot say, and the middle bucket is where that matters
# most because it contains both a leader coasting and one quietly rolling over.
# Deliberately DIRECTIONAL ONLY — no "become a buy"/"become a sell". These
# sit directly above the verdict's own action line, and a drift can point the
# opposite way to the verdict it is annotating: XLF printed "⚠️ Fading /
# TRIM" above "on track to become a buy" because its month was -2.1% while
# its fortnight was +1.5%. Both readings were correct; stating two opposite
# ACTIONS in one row was not. The tension itself is the useful signal, so it
# is spelled out by _conflict_note() rather than left for the reader to spot.
DRIFTS = {
    "Strengthening": ("↗", "green", "the last 2 weeks are running hotter than the month"),
    "Steady":        ("→", "muted", "holding its pace — no change expected"),
    "Weakening":     ("↘", "red",   "the last 2 weeks are running cooler than the month"),
}

# Which drift direction contradicts which bucket. "out" says sell while
# Strengthening says the recent stretch turned up; "in" says buy while
# Weakening says it is cooling.
_CONFLICT = {("out", "Strengthening"), ("in", "Weakening")}


def _conflict_note(bucket: str, drift: str) -> str:
    """One clause naming the disagreement, when the two axes disagree.

    They are measured over different windows on purpose — the verdict reads
    the month, the drift reads the fortnight — so they CAN disagree, and when
    they do that is a real early warning rather than an inconsistency to hide.
    """
    if (bucket, drift) not in _CONFLICT:
        return ""
    if drift == "Strengthening":
        return ("the monthly picture still says trim, but the fortnight has turned up — "
                "the case for selling is weakening, not confirmed")
    return ("the monthly picture still says buy, but the fortnight has cooled — "
            "wait for the recent stretch to turn back up")


def _why(verdict: str, rolling_over: bool) -> str:
    """The action line for a row.

    "Fading" is reached two ways: leadership rolling over (the fortnight has
    turned down while still top-ranked), or a top-ranked sector simply losing
    ground to the market over the month. Only the first is a roll-over, and
    saying so on the second was plainly wrong — XLF showed
    "leadership is rolling over" while its fortnight was +1.5%.
    """
    if verdict == "Fading" and not rolling_over:
        return "TRIM — still top-ranked, but it has lost ground to the market this month"
    return WHY[verdict]


def _drift(fast_pct: float, slow_pct: float) -> str:
    """Is the recent fortnight running hotter or cooler than the month?

    Both figures are clean relative returns but over different lengths, so
    they are compared as PER-SESSION rates -- 4% over 21 sessions is a slower
    pace than 3% over 10, and comparing the totals would get that backwards.
    """
    if fast_pct <= -MOM_MIN:
        return "Weakening"
    fast_rate = fast_pct / FAST_WINDOW
    slow_rate = slow_pct / MOM_WINDOW
    if fast_pct >= MOM_MIN and fast_rate >= slow_rate:
        return "Strengthening"
    if fast_rate < slow_rate:
        return "Weakening" if fast_pct < 0 else "Steady"
    return "Steady"


def _slope_pct_per_week(values: np.ndarray) -> float:
    """Least-squares slope of an RS series, as % of its own mean per week.

    A regression rather than an endpoint-to-endpoint change: the endpoints
    alone can be two outliers, and a sector that spiked once then flatlined
    would read the same as one that climbed steadily every session.
    """
    n = len(values)
    if n < 5:
        return 0.0
    x = np.arange(n, dtype=float)
    mean = float(np.mean(values))
    if mean == 0:
        return 0.0
    try:
        slope = float(np.polyfit(x, values, 1)[0])
    except Exception:
        return 0.0
    return slope / mean * 100 * 5      # per session → per 5-session week


def build_outlook(history: pd.DataFrame, sectors: list[tuple[str, str]] | None = None,
                  only_gics: bool = False) -> pd.DataFrame:
    """One row per sector describing where its relative strength is HEADING.

    Columns:
      Rank            current RS rank (the lagging view, for reference)
      Rank Δ20 / Δ10  places gained (+) or lost (-) over the window
      RS Mom %        % change in RS vs SPY over MOM_WINDOW — the core metric
      RS Slope        regression slope, % per week (is the climb steady?)
      Up Days         sessions out of MOM_WINDOW where RS actually rose
      RS Pctile       where current RS sits in its own 6-month range (0-100)
      1M Price %      the sector's OWN return, independent of SPY
      Trajectory      the verdict
      Bucket          in / hold / out / none
    """
    if history is None or history.empty or "Date" not in history.columns:
        return pd.DataFrame()

    names = dict(sectors) if sectors else {}
    dates = sorted(history["Date"].unique())
    if len(dates) < FAST_WINDOW + 2:
        return pd.DataFrame()

    rows = []
    for ticker, g in history.groupby("Ticker"):
        g = g.sort_values("Date")
        if len(g) < FAST_WINDOW + 2:
            continue

        rs = g["RS vs SPY"].astype(float).to_numpy()          # 63-day RS level
        ranks = g["Rank"].astype(float).to_numpy()

        w = min(MOM_WINDOW, len(rs) - 1)
        f = min(FAST_WINDOW, len(rs) - 1)

        # Momentum is the SHORT-window relative return, read as a level --
        # "how far ahead of SPY has this sector been over the last 21
        # sessions". It is emphatically NOT the change in the 63-day RS
        # ratio, which is what this used to compute and which is not a
        # momentum measure at all:
        #
        #   RS63(t)/RS63(t-20) = (relative return over the last 20 sessions)
        #                        ÷ (relative return over days t-83..t-63)
        #
        # The second term is the window falling out the back, so the number
        # moves when old history EXPIRES rather than when money moves now. A
        # sector flat against SPY for twenty straight sessions, having fallen
        # 10% three months earlier, scored +11% "momentum" on that formula
        # while doing nothing whatsoever; a sector that led in the spring and
        # is merely average today scored -11% and was filed under "money
        # moving out" while it was actually beating the market. Those false
        # readings are what made this card contradict the ranking card below
        # it, which had the clean measure all along.
        #
        # RS 21d is P(t)/P(t-21) ÷ SPY(t)/SPY(t-21): one window, no overlap,
        # nothing expiring. 1.03 means 3% ahead of the market over the month.
        if "RS 21d" in g.columns:
            rs21 = g["RS 21d"].astype(float).to_numpy()
        else:
            rs21 = np.ones_like(rs)
        rs_mom = (float(rs21[-1]) - 1) * 100

        # Same clean construction over 10 sessions. Needed because momentum
        # measured over 21 days straddles a turn: a leader that rolled over a
        # fortnight ago can still read positive on the month, and waiting for
        # the 21-day figure to go negative is exactly the lateness this card
        # exists to avoid. Two clean windows disagreeing IS the early signal.
        if "RS 10d" in g.columns:
            mom_fast = (float(g["RS 10d"].astype(float).to_numpy()[-1]) - 1) * 100
        else:
            mom_fast = rs_mom

        rank_now = int(ranks[-1])
        rank_d20 = int(ranks[-(w + 1)] - rank_now)      # + = climbed
        rank_d10 = int(ranks[-(f + 1)] - rank_now)

        # Slope and consistency both read the SHORT-window series for the
        # same reason -- on the 63-day series each daily change carries the
        # single expiring day with it.
        window = rs21[-(w + 1):]
        slope = _slope_pct_per_week(window)
        up_days = int((np.diff(window) > 0).sum())

        # Position within its own trailing range: a sector at the bottom of
        # its own range with positive momentum is early; one at the top of
        # its range is late, however good the rank looks.
        # Deliberately the 63-day LEVEL, not the short-window momentum: this
        # column answers "how far through this move are we", which is a
        # question about where strength has got to, not how fast it is
        # changing. No expiring-window problem here — it compares a level
        # against its own past levels rather than differencing them.
        rs_now = float(rs[-1])
        lo, hi = float(np.min(rs)), float(np.max(rs))
        pctile = ((rs_now - lo) / (hi - lo) * 100) if hi > lo else 50.0

        ret_1m = float(g["1M Ret %"].iloc[-1]) if "1M Ret %" in g.columns else 0.0

        # ── Verdict ──────────────────────────────────────────────────
        mom_up = rs_mom > MOM_MIN
        mom_dn = rs_mom < -MOM_MIN
        climbing = rank_d20 >= RANK_MIN
        falling = rank_d20 <= -RANK_MIN
        top = rank_now <= TOP_N

        # RS momentum is the primary axis and rank movement only confirms it.
        # Getting this backwards produced a real absurdity: a sector whose RS
        # vs SPY had risen 2% was labelled "Falling" purely because it lost
        # four rank places. Those measure different things -- RS momentum is
        # versus the MARKET, rank is versus the other fourteen sectors -- and
        # a sector can genuinely gain on SPY while peers gain faster. So a
        # negative verdict now requires momentum itself to be negative.
        # A leader still ahead over the month but behind over the fortnight is
        # rolling over. Flagging it here rather than waiting for the monthly
        # figure to turn keeps the sell side as early as the buy side.
        rolling_over = top and mom_fast < -MOM_MIN

        if mom_up and climbing and not rolling_over:
            verdict = "Accelerating" if top else "Emerging"
        elif rolling_over:
            verdict = "Fading"
        elif mom_up:
            # Gaining on SPY, but not gaining on its peers: real, weaker.
            verdict = "Improving"
        elif mom_dn:
            if top:
                # A top-ranked sector with RS already rolling over is the
                # symmetric counterpart of "Emerging": the early exit. Waiting
                # for it to LOSE rank first would reintroduce exactly the lag
                # this module exists to remove -- by then the leadership has
                # already changed hands and the trim is late.
                verdict = "Fading"
            elif falling:
                verdict = "Falling"
            else:
                # Losing to SPY but holding its place: early deterioration.
                verdict = "Cooling"
        else:
            verdict = "Leading" if top else "Flat"

        bucket, colour, icon, meaning = VERDICTS[verdict]
        drift = _drift(mom_fast, rs_mom)
        d_icon, d_colour, d_note = DRIFTS[drift]

        rows.append({
            "Ticker":     ticker,
            "Sector":     names.get(ticker, g["Sector"].iloc[-1] if "Sector" in g.columns else ""),
            "Rank":       rank_now,
            "Rank Δ20":   rank_d20,
            "Rank Δ10":   rank_d10,
            "RS Mom %":   round(rs_mom, 2),
            "Fast Mom %": round(mom_fast, 2),
            "RS Slope":   round(slope, 2),
            "Up Days":    up_days,
            "Window":     w,
            "RS Pctile":  round(pctile, 0),
            "1M Price %": round(ret_1m, 1),
            "Trajectory": verdict,
            "Why":        _why(verdict, rolling_over),
            "Conflict":   _conflict_note(bucket, drift),
            "Heading":    drift,
            "HeadIcon":   d_icon,
            "HeadColour": d_colour,
            "HeadNote":   d_note,
            "Bucket":     bucket,
            "Colour":     colour,
            "Icon":       icon,
            "Meaning":    meaning,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    if only_gics:
        from scanners.sector_validate import GICS_SECTORS
        df = df[df["Ticker"].isin(GICS_SECTORS)]

    # Sorted by where it is HEADING, not where it is: momentum first, with
    # rank as the tie-break. This ordering is the entire point of the module.
    order = {"Emerging": 0, "Accelerating": 1, "Improving": 2, "Leading": 3,
             "Flat": 4, "Cooling": 5, "Fading": 6, "Falling": 7}
    df["_o"] = df["Trajectory"].map(order)
    return (df.sort_values(["_o", "RS Mom %"], ascending=[True, False])
              .drop(columns="_o").reset_index(drop=True))


def headline(outlook: pd.DataFrame) -> dict:
    """A one-glance summary: who is coming, who is going, and the regime."""
    if outlook is None or outlook.empty:
        return {}

    coming = outlook[outlook["Bucket"] == "in"]
    leading = outlook[outlook["Bucket"] == "hold"]
    going = outlook[outlook["Bucket"] == "out"]

    # Risk-on vs risk-off read from WHICH sectors are gaining, the classic
    # rotation tell: cyclicals leading means growth expectations, defensives
    # leading means money is buying safety.
    cyclical = {"XLK", "XLY", "XLF", "XLI", "XLC", "XLB"}
    defensive = {"XLU", "XLP", "XLV", "XLRE"}
    gaining = set(coming["Ticker"])
    n_cyc = len(gaining & cyclical)
    n_def = len(gaining & defensive)
    if n_cyc > n_def:
        regime, regime_note = "Risk-on", "cyclicals are the ones gaining ground"
    elif n_def > n_cyc:
        regime, regime_note = "Risk-off", "defensives are the ones gaining ground"
    else:
        regime, regime_note = "Mixed", "no clear cyclical/defensive tilt yet"

    return {
        "coming":      coming["Ticker"].tolist(),
        "leading":     leading["Ticker"].tolist(),
        "going":       going["Ticker"].tolist(),
        "regime":      regime,
        "regime_note": regime_note,
        "n_coming":    len(coming),
        "n_going":     len(going),
    }


# ── Render ─────────────────────────────────────────────────────────────────────

def render_outlook(history: pd.DataFrame, sectors: list[tuple[str, str]] | None = None):
    """The "where is it heading" card. Rendered ABOVE the ranking card,
    because the ranking answers a question the reader asks second."""
    import streamlit as st
    from config import (
        GOLD, BG_CARD, BG_PANEL, ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE,
        TEXT_PRIMARY, TEXT_MUTED, BORDER_COLOR,
    )
    G, GL, R, B = ACCENT_GREEN, GOLD, ACCENT_RED, ACCENT_BLUE
    COL = {"green": G, "gold": GL, "red": R, "muted": TEXT_MUTED}

    out = build_outlook(history, sectors)
    if out.empty:
        return

    hl = headline(out)

    # ── The rule, in one line, at the top where it is actually used ──
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{GL}12,{B}08);'
        f'border:1px solid {GL}44;border-radius:12px;padding:12px 18px;margin-bottom:12px">'
        f'<div style="color:{GL};font-size:13px;font-weight:700;margin-bottom:6px">'
        f'🧭 Where is the money heading?</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.75">'
        f'The ranking below answers <i>where money has been</i> — it scores the last '
        f'three months, so a sector that turned up three weeks ago still ranks low. '
        f'This card answers <b style="color:{TEXT_PRIMARY}">where it is going</b>: it '
        f'ranks by how fast relative strength is <b>changing</b>, over the last '
        f'{MOM_WINDOW} sessions.'
        f'<div style="background:{G}12;border-left:3px solid {G};padding:7px 11px;'
        f'border-radius:0 6px 6px 0;margin-top:8px;color:{TEXT_PRIMARY}">'
        f'<b>The simple rule:</b> buy from <b style="color:{G}">MONEY MOVING IN</b>, '
        f'hold what is in <b style="color:{GL}">LEADING</b>, and trim or avoid '
        f'<b style="color:{R}">MONEY MOVING OUT</b>. Prefer names with a high '
        f'<b>Up Days</b> count — that is the difference between a steady climb and '
        f'one lucky week.</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── Regime strip ────────────────────────────────────────────────
    if hl:
        r_col = G if hl["regime"] == "Risk-on" else (R if hl["regime"] == "Risk-off" else GL)
        st.markdown(
            f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;'
            f'margin-bottom:12px">'
            f'<span style="background:{r_col}18;color:{r_col};border:1px solid {r_col}44;'
            f'font-size:11px;font-weight:700;padding:4px 14px;border-radius:20px">'
            f'{hl["regime"]}</span>'
            f'<span style="color:{TEXT_MUTED};font-size:11px">{hl["regime_note"]} · '
            f'<b style="color:{G}">{hl["n_coming"]}</b> sector(s) gaining ground · '
            f'<b style="color:{R}">{hl["n_going"]}</b> losing it</span></div>',
            unsafe_allow_html=True,
        )

    # ── Three buckets ───────────────────────────────────────────────
    buckets = [
        ("in",   "💰 MONEY MOVING IN — buy candidates", G,
         "<b>Why buy:</b> these are beating the market right now and gaining "
         "places. You are getting in while the ranking still looks unremarkable, "
         "which is where the good prices are — and where the least confirmation is."),
        ("hold", "👑 LEADING / WATCH — hold what you have", GL,
         "<b>Why hold:</b> ahead of the market, but either already at the top "
         "(late to start a new position) or still behind its peers. Check the "
         "<b>↗ ↘ arrow</b> on each row — that says whether it is on its way to "
         "becoming a buy or a sell."),
        ("out",  "🚪 MONEY MOVING OUT — trim / avoid", R,
         "<b>Why sell:</b> losing ground to the market. ⚠️ Fading still ranks "
         "high and still feels fine to own — that is exactly why it is the good "
         "moment to trim, rather than after the rank drops."),
    ]

    cols = st.columns(3)
    for (key, title, col, note), slot in zip(buckets, cols):
        sub = out[out["Bucket"] == key]
        with slot:
            st.markdown(
                f'<div style="color:{col};font-size:11px;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:0.6px;margin-bottom:4px">'
                f'{title}</div>'
                f'<div style="color:{TEXT_MUTED};font-size:10px;line-height:1.5;'
                f'margin-bottom:8px">{note}</div>',
                unsafe_allow_html=True,
            )
            if sub.empty:
                st.markdown(
                    f'<div style="color:{TEXT_MUTED};font-size:11px;padding:6px 0">'
                    f'Nothing in this group right now.</div>',
                    unsafe_allow_html=True,
                )
                continue
            for _, r in sub.iterrows():
                c = COL.get(r["Colour"], TEXT_MUTED)
                d20 = r["Rank Δ20"]
                arrow = f'▲{d20}' if d20 > 0 else (f'▼{abs(d20)}' if d20 < 0 else '–')
                a_col = G if d20 > 0 else (R if d20 < 0 else TEXT_MUTED)
                conf = r["Up Days"] / max(r["Window"], 1) * 100
                cf_col = G if conf >= 60 else (GL if conf >= 45 else R)
                st.markdown(
                    f'<div style="background:{BG_PANEL};border-left:3px solid {c};'
                    f'padding:8px 11px;margin-bottom:6px;border-radius:0 6px 6px 0">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:baseline;gap:6px">'
                    f'<span><b style="color:{GL};font-family:\'DM Mono\',monospace">'
                    f'{r["Ticker"]}</b> '
                    f'<span style="color:{TEXT_MUTED};font-size:10px">{r["Sector"]}</span></span>'
                    f'<span style="color:{c};font-size:10px;font-weight:700">'
                    f'{r["Icon"]} {r["Trajectory"]}</span></div>'
                    f'<div style="color:{COL.get(r["HeadColour"], TEXT_MUTED)};'
                    f'font-size:10px;font-weight:700;margin-top:2px">'
                    f'{r["HeadIcon"]} {r["Heading"]} — {r["HeadNote"]}</div>'
                    f'<div style="color:{TEXT_PRIMARY};font-size:10px;margin-top:2px">'
                    f'{r["Why"]}</div>'
                    # Only rendered when the month and the fortnight actually
                    # disagree, so it never adds noise to a row where the two
                    # axes point the same way.
                    + (f'<div style="color:{GL};font-size:10px;margin-top:2px;'
                       f'font-style:italic">⚖️ {r["Conflict"]}</div>'
                       if r.get("Conflict") else "")
                    + (
                    f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:3px;'
                    f'line-height:1.6">'
                    f'vs SPY <b style="color:{c}">{r["RS Mom %"]:+.1f}%</b> 1M / '
                    f'<b style="color:{G if r["Fast Mom %"] >= 0 else R}">'
                    f'{r["Fast Mom %"]:+.1f}%</b> 2W · '
                    f'rank <b style="color:{TEXT_PRIMARY}">#{r["Rank"]}</b> '
                    f'<b style="color:{a_col}">{arrow}</b> · '
                    f'price <b style="color:{G if r["1M Price %"] >= 0 else R}">'
                    f'{r["1M Price %"]:+.1f}%</b> 1M<br>'
                    f'steady: <b style="color:{cf_col}">{int(r["Up Days"])}/'
                    f'{int(r["Window"])}</b> sessions rising</div>'
                    f'</div>'),
                    unsafe_allow_html=True,
                )

    # ── Nothing may silently vanish ─────────────────────────────────
    # Cooling and Flat belong to no bucket, so a sector drifting into either
    # disappears from all three columns above. For anyone reading only those
    # columns that is indistinguishable from "nothing changed" -- and Cooling
    # in particular ("losing ground, rank has not caught up") is exactly the
    # state a holder wants to know about. Named here so the three columns plus
    # this line always account for every sector.
    rest = out[out["Bucket"] == "none"]
    if not rest.empty:
        items = " · ".join(
            f'<b style="color:{GL}">{r["Ticker"]}</b> '
            f'<span style="color:{COL.get(r["Colour"], TEXT_MUTED)}">'
            f'{r["Icon"]} {r["Trajectory"]}</span> '
            f'<span style="color:{TEXT_MUTED}">({r["HeadIcon"]} {r["Heading"]})</span>'
            for _, r in rest.iterrows()
        )
        st.markdown(
            f'<div style="background:{BG_PANEL};border-left:3px solid {TEXT_MUTED};'
            f'padding:7px 12px;border-radius:0 6px 6px 0;margin-top:10px;'
            f'color:{TEXT_MUTED};font-size:10px;line-height:1.7">'
            f'<b style="color:{TEXT_PRIMARY}">In no group right now:</b> {items}'
            f'<br>No action either way — but they have not vanished, and '
            f'<b>🌡️ Cooling</b> on something you own is the first hint to stop '
            f'adding. Full detail in the table below.</div>',
            unsafe_allow_html=True,
        )

    # ── The three reference tables ──────────────────────────────────
    # Put on the page rather than left in chat: this is the part that gets
    # re-read every week, and a rule you have to go looking for is a rule you
    # stop applying. <details> rather than st.expander because this renders
    # inside one already and Streamlit will not nest them.
    _TT = (f'background:{BG_PANEL};color:{TEXT_MUTED};font-size:9px;font-weight:700;'
           f'text-transform:uppercase;letter-spacing:0.6px;padding:6px 9px;'
           f'border-bottom:2px solid {GL}44;text-align:left;white-space:nowrap')
    _TD = f'padding:6px 9px;font-size:11px;border-bottom:1px solid {BORDER_COLOR}'

    label_rows = "".join(
        f'<tr>'
        f'<td style="{_TD};white-space:nowrap;color:{COL.get(VERDICTS[v][1], TEXT_MUTED)};'
        f'font-weight:700">{VERDICTS[v][2]} {v}</td>'
        f'<td style="{_TD};color:{TEXT_MUTED}">{VERDICTS[v][3]}</td>'
        f'<td style="{_TD};color:{TEXT_PRIMARY};font-weight:700;white-space:nowrap">'
        f'{WHY[v].split(" — ")[0]}</td>'
        f'</tr>'
        for v in ("Emerging", "Accelerating", "Leading", "Improving",
                  "Flat", "Cooling", "Fading", "Falling")
    )

    check_rows = "".join(
        f'<tr><td style="{_TD};color:{TEXT_PRIMARY}">{q}</td>'
        f'<td style="{_TD};color:{GL};font-weight:700;white-space:nowrap">{colname}</td>'
        f'<td style="{_TD};color:{G};white-space:nowrap">{ok}</td>'
        f'<td style="{_TD};color:{R};white-space:nowrap">{no}</td></tr>'
        for q, colname, ok, no in [
            ("Is the climb real?", "Steady",
             f"{int(MOM_WINDOW * 0.6)} or more of {MOM_WINDOW}",
             f"under {int(MOM_WINDOW * 0.45)} of {MOM_WINDOW}"),
            ("Am I early or late?", "RS Range", "under 40%", "over 80% = late"),
            ("Is it still working?", "Heading / Δ10", "↗ or → , Δ10 green", "↘ , Δ10 red"),
        ]
    )

    step_rows = "".join(
        f'<tr><td style="{_TD};color:{GL};font-weight:700;width:28px">{i}</td>'
        f'<td style="{_TD};color:{TEXT_PRIMARY}">{t}</td></tr>'
        for i, t in enumerate([
            "Open the green <b>MONEY MOVING IN</b> column",
            f"Skip anything with <b>Steady</b> under {int(MOM_WINDOW * 0.45)}/{MOM_WINDOW}",
            "Skip anything with <b>RS Range</b> over 80% — the move is mostly done",
            "Buy what is left. 🌱 Emerging first, 🚀 Accelerating if you want safer",
            "Check <b>LEADING / WATCH</b>. ↗ means add on weakness, ↘ means get ready to exit",
            "Anything you own showing ⚠️ Fading in the red column — trim it",
            "Repeat weekly, not daily. These labels are built to hold for weeks",
        ], start=1)
    )

    st.markdown(
        f'<details style="background:{BG_PANEL};border:1px solid {GL}33;border-radius:8px;'
        f'padding:8px 12px;margin:14px 0 4px" open>'
        f'<summary style="color:{GL};font-size:11px;font-weight:700;cursor:pointer;'
        f'text-transform:uppercase;letter-spacing:0.7px">'
        f'🧾 Buy / hold / sell — the whole rulebook</summary>'

        f'<div style="color:{TEXT_MUTED};font-size:10px;margin:10px 0 4px;'
        f'text-transform:uppercase;letter-spacing:0.6px;font-weight:700">'
        f'1 · What each label means, and what to do</div>'
        f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
        f'font-family:Inter,sans-serif">'
        f'<thead><tr><th style="{_TT}">You see</th><th style="{_TT}">What it means</th>'
        f'<th style="{_TT}">Your move</th></tr></thead>'
        f'<tbody>{label_rows}</tbody></table></div>'

        f'<div style="color:{TEXT_MUTED};font-size:10px;margin:14px 0 4px;'
        f'text-transform:uppercase;letter-spacing:0.6px;font-weight:700">'
        f'2 · Three checks before you act</div>'
        f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
        f'font-family:Inter,sans-serif">'
        f'<thead><tr><th style="{_TT}">Question</th><th style="{_TT}">Column</th>'
        f'<th style="{_TT}">Go ✅</th><th style="{_TT}">Stop ❌</th></tr></thead>'
        f'<tbody>{check_rows}</tbody></table></div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:6px;line-height:1.6">'
        f'<b style="color:{TEXT_PRIMARY}">Steady matters most.</b> '
        f'14/20 means it beat the market on 14 of the last 20 days — a real trend. '
        f'9/20 with the same headline number is one big day and a lot of noise.</div>'

        f'<div style="color:{TEXT_MUTED};font-size:10px;margin:14px 0 4px;'
        f'text-transform:uppercase;letter-spacing:0.6px;font-weight:700">'
        f'3 · The weekly routine</div>'
        f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
        f'font-family:Inter,sans-serif"><tbody>{step_rows}</tbody></table></div>'

        f'<div style="background:{R}12;border-left:3px solid {R};padding:7px 11px;'
        f'border-radius:0 6px 6px 0;margin-top:12px;color:{TEXT_PRIMARY};font-size:11px;'
        f'line-height:1.7">'
        f'<b>Two things that will feel wrong.</b> ⚠️ Fading always looks fine to keep '
        f'— it still ranks high, which is the point: that is when you get a good exit '
        f'price. And 🌱 Emerging is early, which sometimes means early <i>and wrong</i>; '
        f'treat it as a shortlist to look into, not a guarantee.</div>'
        f'</details>',
        unsafe_allow_html=True,
    )

    # ── Full trajectory table ───────────────────────────────────────
    _TH = (f'background:{BG_PANEL};color:{TEXT_MUTED};font-size:9px;font-weight:700;'
           f'text-transform:uppercase;letter-spacing:0.7px;padding:7px 10px;'
           f'border-bottom:2px solid {GL}44;white-space:nowrap;text-align:left')
    cols_t = ["Sector", "Trajectory", "Heading", "vs SPY 1M", "vs SPY 2W", "Rank",
              "Δ20", "Δ10", "Steady", "RS Range", "1M Price"]
    head = "".join(f'<th style="{_TH}">{c}</th>' for c in cols_t)

    body = ""
    for i, r in out.iterrows():
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        td = f'background:{bg};padding:7px 10px;font-size:11px'
        c = COL.get(r["Colour"], TEXT_MUTED)
        d20, d10 = r["Rank Δ20"], r["Rank Δ10"]
        f20 = f'▲{d20}' if d20 > 0 else (f'▼{abs(d20)}' if d20 < 0 else '–')
        f10 = f'▲{d10}' if d10 > 0 else (f'▼{abs(d10)}' if d10 < 0 else '–')
        conf = r["Up Days"] / max(r["Window"], 1) * 100
        body += (
            f'<tr>'
            f'<td style="{td};white-space:nowrap">'
            f'<b style="color:{GL};font-family:\'DM Mono\',monospace">{r["Ticker"]}</b>'
            f'<span style="color:{TEXT_MUTED};font-size:10px"> {r["Sector"]}</span></td>'
            f'<td style="{td};color:{c};font-weight:700;font-size:10px;white-space:nowrap">'
            f'{r["Icon"]} {r["Trajectory"]}</td>'
            f'<td style="{td};color:{COL.get(r["HeadColour"], TEXT_MUTED)};'
            f'font-weight:700;font-size:10px;white-space:nowrap">'
            f'{r["HeadIcon"]} {r["Heading"]}</td>'
            f'<td style="{td};color:{c};font-weight:700">{r["RS Mom %"]:+.1f}%</td>'
            f'<td style="{td};color:{G if r["Fast Mom %"] >= 0 else R}">'
            f'{r["Fast Mom %"]:+.1f}%</td>'
            f'<td style="{td};color:{TEXT_PRIMARY}">#{r["Rank"]}</td>'
            f'<td style="{td};color:{G if d20 > 0 else (R if d20 < 0 else TEXT_MUTED)}">{f20}</td>'
            f'<td style="{td};color:{G if d10 > 0 else (R if d10 < 0 else TEXT_MUTED)}">{f10}</td>'
            f'<td style="{td};color:{G if conf >= 60 else (GL if conf >= 45 else R)}">'
            f'{int(r["Up Days"])}/{int(r["Window"])}</td>'
            f'<td style="{td};color:{TEXT_MUTED}">{int(r["RS Pctile"])}%</td>'
            f'<td style="{td};color:{G if r["1M Price %"] >= 0 else R}">'
            f'{r["1M Price %"]:+.1f}%</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="color:{GL};font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;margin:14px 0 6px">Full trajectory — sorted by where it '
        f'is heading, not where it is</div>'
        f'<div style="overflow-x:auto;border:1px solid {GL}33;border-radius:8px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<details style="background:{BG_PANEL};border:1px solid {GL}33;border-radius:8px;'
        f'padding:8px 12px;margin:8px 0 18px">'
        f'<summary style="color:{GL};font-size:11px;font-weight:700;cursor:pointer;'
        f'text-transform:uppercase;letter-spacing:0.7px">📖 What these columns mean</summary>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.75;margin-top:10px">'
        f'· <b style="color:{TEXT_PRIMARY}">vs SPY 1M</b> — how far ahead of (or behind) '
        f'the market this sector has been over the last month. <b>This is the '
        f'forward-looking number.</b> +3% means it beat SPY by 3% over the month, '
        f'whatever the rank says.<br>'
        f'· <b style="color:{TEXT_PRIMARY}">vs SPY 2W</b> — the same over the last two '
        f'weeks. When 1M is positive but 2W has turned negative the sector is rolling '
        f'over: still ahead on the month, already behind on the fortnight. On a top-5 '
        f'sector that is what triggers ⚠️ Fading, and it is the earliest honest exit '
        f'signal on the page.<br>'
        f'· <b style="color:{TEXT_PRIMARY}">Rank / Δ20 / Δ10</b> — current place, and '
        f'places gained (▲) or lost (▼) over 20 and 10 sessions. A low rank with a big ▲ '
        f'is the early-entry case; Δ10 turning negative while Δ20 is positive is the first '
        f'sign a climb is stalling.<br>'
        f'· <b style="color:{TEXT_PRIMARY}">Heading</b> — which way the row is drifting, '
        f'from comparing the 2W pace against the 1M pace. <b>↗</b> means the recent '
        f'fortnight is running hotter than the month, so it is on its way to becoming a '
        f'buy; <b>↘</b> means it is cooling toward a sell; <b>→</b> means no change '
        f'expected. This is the column to read on anything in LEADING / WATCH, where the '
        f'label alone cannot tell a leader coasting from one quietly rolling over.<br>'
        f'· <b style="color:{TEXT_PRIMARY}">Steady</b> — of the last {MOM_WINDOW} sessions, '
        f'how many actually rose. <b>The trust column.</b> 14/20 is a real trend; 10/20 with '
        f'the same momentum is one big day and a lot of noise.<br>'
        f'· <b style="color:{TEXT_PRIMARY}">RS Range</b> — where current RS sits inside its '
        f'own 6-month range. Low % with positive momentum = early. High % = the move is '
        f'mature, and you are late rather than wrong.<br>'
        f'· <b style="color:{TEXT_PRIMARY}">1M Price</b> — the sector\'s OWN return, nothing '
        f'to do with SPY. A sector can be up on the month and still rank last, because rank '
        f'is <i>relative</i>: everything else rose more. Both facts are true and they '
        f'answer different questions.'
        f'<div style="background:{R}12;border-left:3px solid {R};padding:7px 11px;'
        f'border-radius:0 6px 6px 0;margin-top:8px;color:{TEXT_PRIMARY}">'
        f'<b>Limits, plainly:</b> this measures a trend already underway — it does not '
        f'forecast prices, and early includes early-and-wrong. Momentum turns are noisy, '
        f'which is why every call needs both a momentum move and a rank move, and why '
        f'<b>Steady</b> sits next to it. Treat 🌱 Emerging as a shortlist to research, '
        f'not an instruction to buy.</div>'
        f'</div></details>',
        unsafe_allow_html=True,
    )
