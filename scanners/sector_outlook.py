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
         "Relative strength climbing. The top of this list is the earliest signal "
         "on the page — and the least confirmed."),
        ("hold", "👑 LEADING / WATCH — hold what you have", GL,
         "Already ahead and holding (👑), or gaining on the market while peers "
         "gain faster (📈). Fine to hold; a late place to start."),
        ("out",  "🚪 MONEY MOVING OUT — trim / avoid", R,
         "Losing ground to the market. 'Fading' still ranks high, which is exactly "
         "when trimming is easy and feels wrong."),
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
                    f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:3px;'
                    f'line-height:1.6">'
                    f'RS momentum <b style="color:{c}">{r["RS Mom %"]:+.1f}%</b> · '
                    f'rank <b style="color:{TEXT_PRIMARY}">#{r["Rank"]}</b> '
                    f'<b style="color:{a_col}">{arrow}</b> · '
                    f'price <b style="color:{G if r["1M Price %"] >= 0 else R}">'
                    f'{r["1M Price %"]:+.1f}%</b> 1M<br>'
                    f'steady: <b style="color:{cf_col}">{int(r["Up Days"])}/'
                    f'{int(r["Window"])}</b> sessions rising</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ── Full trajectory table ───────────────────────────────────────
    _TH = (f'background:{BG_PANEL};color:{TEXT_MUTED};font-size:9px;font-weight:700;'
           f'text-transform:uppercase;letter-spacing:0.7px;padding:7px 10px;'
           f'border-bottom:2px solid {GL}44;white-space:nowrap;text-align:left')
    cols_t = ["Sector", "Trajectory", "vs SPY 1M", "vs SPY 2W", "Rank", "Δ20", "Δ10",
              "Steady", "RS Range", "1M Price"]
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
