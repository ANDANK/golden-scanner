# scanners/election_playbook.py — Election Playbook 2026 (tab inside WatchList)
#
# Read-only, interactive dashboard built from a user-supplied Oct-2026 midterm
# playbook spreadsheet (data/election_playbook_2026.csv — see
# scripts/build_election_playbook_data.py for the importer). Recomputes a
# plain-English "Today's Instruction" per ticker on every refresh, using LIVE
# price vs. 52-week high / 200-day SMA as the dip trigger (never a stale,
# hand-typed price from the sheet) combined with the calendar phase of the
# election cycle and the sheet's own sequencing rules ("Sequencing & Legend"
# tab: WAIT the extended tape -> SELL CSP into the IV spike -> BUY THE DIP on
# quality -> HEDGE the crowded AI/semi book -> HOLD election-agnostic
# compounders -> AVOID/TRIM the highest-risk names).

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    GOLD, BG_CARD, BG_PANEL, ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE,
    TEXT_PRIMARY, TEXT_MUTED, BORDER_COLOR,
)
from utils import calc_sma, calc_rsi, _export_filename
from data_loader import get_price_history
from scanners.ui_tables import sortable_table_html

HEDGE_COLOR = "#A78BFA"   # violet — kept distinct from the 4-color outlook legend
BUY_SPEC_COLOR = "#FB923C"   # orange — "buy the dip" while the trend itself is still broken

DATA_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data",
    "election_playbook_2026.csv",
)

ELECTION_DATE = date(2026, 11, 3)          # 2026 US midterm election day
WEAK_WINDOW_START = date(2026, 9, 1)
ELECTION_WEEK_END = date(2026, 11, 10)
POST_WINDOW_END = ELECTION_DATE + timedelta(days=182)   # ~6mo post-midterm rally window

OUTLOOK_META = {
    "Down hard":  (ACCENT_RED,   "#F4CCCC", "🔻 Down hard — deepest drawdown risk into Oct"),
    "Down mild":  ("#E08A3A",    "#FCE5CD", "🔸 Down mild — softer / conditional dip"),
    "Resilient":  (ACCENT_GREEN, "#D9EAD3", "🛡️ Resilient / Election-agnostic — hold, little election impact"),
    "Volatile":   (ACCENT_BLUE,  "#CFE2F3", "⚡ Volatile / dip-buy — big swings, buy the flush / sell CSP"),
}

# Column Guide — shown as a reference panel under the main table.
COLUMN_GUIDE = [
    ("Ticker",               "Symbol, sector underneath, and a ⚡ flag if it's a leveraged/inverse ETF."),
    ("Outlook",               "The playbook's read on this name for the Oct window — color-coded, see legend above."),
    ("Price",                 "Latest live price."),
    ("vs 52wk High",          "How far it's pulled back from its 52-week high — this is the dip trigger."),
    ("vs 200-SMA",            "Is the pullback inside a long-term uptrend (Above) or has the trend itself broken (Below)? Now feeds the Buy Dip tier — Confirmed vs. Speculative."),
    ("Today's Instruction",   "The action to consider today, and why — recomputed live on every refresh, never a stale sheet price."),
    ("Election Beta",         "How exposed the price is to the election outcome itself, separate from the sector's own dip risk."),
    ("Horizon / Conviction",  "Suggested holding period and how strongly the original thesis leans."),
    ("Bounce-back Driver",    "The catalyst expected to bring the price back."),
]

ACTION_META = {
    "BUY":       (ACCENT_GREEN,    "🟢 Buy Dip (Confirmed)"),
    "BUY_SPEC":  (BUY_SPEC_COLOR,  "🟠 Buy Dip (Speculative)"),
    "SELL_CSP":  (GOLD,            "💰 Sell CSP"),
    "HOLD":      (ACCENT_BLUE,     "✅ Hold / Core"),
    "WAIT":      (TEXT_MUTED,      "⏳ Wait"),
    "HEDGE":     (HEDGE_COLOR,     "🛡️ Hedge Watch"),
    "AVOID":     (ACCENT_RED,      "🚫 Avoid / Trim"),
}

# RSI qualifier appended to buy-dip instruction text — momentum context, not a hard gate.
def _rsi_note(rsi) -> str:
    if pd.isna(rsi):
        return ""
    if rsi <= 35:
        return f" RSI {rsi:.0f} — oversold, selling pressure looks exhausted."
    if rsi >= 60:
        return f" RSI {rsi:.0f} — still elevated, hasn't cooled off much despite the pullback."
    return f" RSI {rsi:.0f} — neutral."


# ── Data loading ────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _load_base_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_CSV)
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].fillna("")
    return df


# ── Seasonal phase ─────────────────────────────────────────────

def _phase_info(today: date) -> dict:
    days_to_election = (ELECTION_DATE - today).days
    if today < WEAK_WINDOW_START:
        return {"key": "PRE", "icon": "⏳", "color": TEXT_MUTED,
                "label": "Extended August Tape — Wait",
                "detail": "Step 1: don't chase an already-extended tape. Volatility historically "
                          "builds into the Sept–Oct window; sit on your hands until it opens.",
                "days_to_election": days_to_election}
    if today < ELECTION_DATE:
        return {"key": "WEAK_WINDOW", "icon": "🌪️", "color": GOLD,
                "label": "Seasonal Weak Window (Sept–Oct) — IV Spike Live",
                "detail": "Volatility historically peaks right before the midterm. Pre-election CSP "
                          "premiums are rich on extended names; watch for the dip-buy flush on quality.",
                "days_to_election": days_to_election}
    if today <= ELECTION_WEEK_END:
        return {"key": "ELECTION_WEEK", "icon": "🗳️", "color": ACCENT_BLUE,
                "label": "Election Week",
                "detail": "Historically both outcomes (House flips or GOP holds the trifecta) were "
                          "positive for the S&P. Don't trade the ballot — party-timed cash exits "
                          "have historically underperformed staying invested.",
                "days_to_election": days_to_election}
    if today <= POST_WINDOW_END:
        return {"key": "POST", "icon": "🚀", "color": ACCENT_GREEN,
                "label": "Post-Midterm Rally Window",
                "detail": "The ~6-month post-midterm stretch is historically the strongest of the "
                          "4-year cycle. CSPs sold in Sept/Oct should be assigning near the start of it.",
                "days_to_election": days_to_election}
    return {"key": "LATE", "icon": "📅", "color": TEXT_MUTED,
            "label": "Outside Playbook Window",
            "detail": "More than ~6 months past the midterm — the seasonal edge this sheet models "
                      "has faded. Treat this as a historical reference, not a live signal.",
            "days_to_election": days_to_election}


# ── Live technicals ─────────────────────────────────────────────

def _fetch_technicals(tickers: list[str], status_fn=None) -> dict:
    out = {}
    total = len(tickers)
    for i, tk in enumerate(tickers):
        if status_fn:
            status_fn(i, total, tk)
        try:
            df = get_price_history(tk, period="1y", interval="1d")
            if df is None or df.empty or "Close" not in df.columns:
                out[tk] = {}
                continue
            close = df["Close"].dropna()
            if close.empty:
                out[tk] = {}
                continue
            price = float(close.iloc[-1])
            high_52w = float(close.max())
            pct_off_high = round((price / high_52w - 1) * 100, 1) if high_52w > 0 else None
            sma200 = None
            if len(close) >= 20:
                sma200 = float(calc_sma(close, 200).iloc[-1])
            above_sma200 = (price > sma200) if sma200 else None
            rsi = float(calc_rsi(close)) if len(close) >= 15 else None
            out[tk] = {
                "Price": round(price, 2),
                "High_52w": round(high_52w, 2),
                "Pct_Off_High": pct_off_high,
                "Above_SMA200": above_sma200,
                "RSI": round(rsi, 1) if rsi is not None else None,
            }
        except Exception:
            out[tk] = {}
    return out


# ── Instruction engine ──────────────────────────────────────────

_DIP_THRESHOLD = {"Down hard": 10, "Down mild": 5, "Volatile": 8, "Resilient": 4}


def _build_instruction(strategy: str, outlook_cat: str, ticker: str,
                        pct_off_high, above_sma200, rsi, phase_key: str) -> tuple[str, str]:
    """Return (action_key, headline_text).

    Dip trigger: % off the 52-week high vs. a per-category threshold.
    Dip TIER (new): confirmed vs. speculative, gated on whether price is still
    above its 200-day SMA — a pullback inside an intact uptrend reads very
    differently from one where the long-term trend itself has broken.
    RSI is layered on as momentum context (oversold vs. still hot), not a
    hard gate — it only changes the wording, never the action.
    """
    has_pct = pd.notna(pct_off_high)
    thresh = _DIP_THRESHOLD.get(outlook_cat, 8)
    dip_hit = has_pct and pct_off_high <= -thresh
    # Unconfirmed trend (unknown or below the 200-SMA) is treated as
    # speculative — we can't call it a "healthy" pullback without proof.
    confirmed = dip_hit and above_sma200 is True
    rsi_note = _rsi_note(rsi)

    if has_pct:
        off_txt = f"{abs(pct_off_high):.0f}% off its 52-wk high"
        off_txt_short = f"{abs(pct_off_high):.0f}% off high"
    else:
        off_txt = "no live price yet — refresh to check for a dip"
        off_txt_short = "no live price yet"

    if strategy == "AVOID":
        return "AVOID", f"{ticker} is priced for perfection — avoid or trim unless you'd truly want the shares long-term."

    if strategy == "CORE_HOLD":
        return "HOLD", "Election-agnostic compounder — hold or add anytime, no dip required."

    if strategy == "HEDGE":
        urgency = "consider sizing it up now" if phase_key in ("WEAK_WINDOW", "ELECTION_WEEK") else "keep as dry powder"
        return "HEDGE", f"Tactical short-hold hedge only — {urgency}. Daily-reset decay: exit fast, never buy-and-hold."

    if strategy == "SELL_CSP":
        if phase_key == "PRE":
            return "WAIT", "Hold off selling CSPs until the Sept–Oct IV-spike window opens."
        if phase_key in ("WEAK_WINDOW", "ELECTION_WEEK"):
            return "SELL_CSP", "Sell CSP now, into the pre-election IV spike — reach for Nov–Dec+ expiries."
        return "HOLD", "IV-spike window has passed — manage any open CSPs, don't chase new entries off this playbook."

    if strategy == "DIP_OR_CSP":
        if confirmed:
            return "BUY", f"Buy the dip now (confirmed — still above its 200-SMA) — {off_txt}, or sell a CSP below support for income.{rsi_note}"
        if dip_hit:
            return "BUY_SPEC", f"Buy cautiously — SPECULATIVE, price is below its 200-SMA (trend broken) — {off_txt}. Selling a CSP is the lower-risk way in until the trend confirms.{rsi_note}"
        if phase_key in ("WEAK_WINDOW", "ELECTION_WEEK"):
            return "SELL_CSP", "No flush yet — sell CSP into the IV spike while you wait for the dip."
        return "WAIT", f"Watchlist — {off_txt_short}; wait for a real flush or the Sept–Oct window."

    if strategy == "TACTICAL_LEV":
        base = "3x/2x daily-reset — SHORT HOLD ONLY, never buy-and-hold (decay)."
        if confirmed:
            return "BUY", f"Tactical dip-buy triggered (confirmed — above 200-SMA) — {off_txt_short}. {base}{rsi_note}"
        if dip_hit:
            return "BUY_SPEC", f"Tactical dip-buy — SPECULATIVE, below 200-SMA (fighting the trend on a decaying instrument) — {off_txt_short}. {base}{rsi_note}"
        return "WAIT", f"No flush yet ({off_txt_short}) — {base}"

    # BUY_DIP default
    if confirmed:
        return "BUY", f"Buy the dip now (confirmed — still above its 200-SMA, long-term uptrend intact) — {off_txt}, into the {outlook_cat.lower()} zone.{rsi_note}"
    if dip_hit:
        return "BUY_SPEC", f"Buy cautiously — SPECULATIVE, price is below its 200-SMA (the longer-term trend has broken, this is catching a falling knife) — {off_txt}.{rsi_note}"
    return "WAIT", f"Watchlist — no dip yet ({off_txt_short}); wait for a flush toward the Sept–Oct window."


# ── Small UI helpers ─────────────────────────────────────────────

def _badge(text: str, color: str, title: str = "") -> str:
    t = f' title="{_esc(title)}"' if title else ""
    return (f'<span{t} style="background:{color}22;color:{color};border:1px solid {color}55;'
            f'padding:2px 8px;border-radius:10px;font-size:10.5px;font-weight:700;'
            f'white-space:nowrap">{text}</span>')


def _esc(s: str) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _timeline_html(today: date, phase_key: str) -> str:
    span_start = date(2026, 8, 1)
    span_end = POST_WINDOW_END
    total_days = (span_end - span_start).days
    segments = [
        ("PRE", span_start, WEAK_WINDOW_START, TEXT_MUTED, "Aug — Wait"),
        ("WEAK_WINDOW", WEAK_WINDOW_START, ELECTION_DATE, GOLD, "Sept–Oct — IV Spike"),
        ("ELECTION_WEEK", ELECTION_DATE, ELECTION_WEEK_END, ACCENT_BLUE, "Election Wk"),
        ("POST", ELECTION_WEEK_END, span_end, ACCENT_GREEN, "Post-Midterm Rally"),
    ]
    seg_html = ""
    for key, start, end, color, label in segments:
        width = max((end - start).days, 1) / total_days * 100
        active = key == phase_key
        opacity = "1" if active else "0.45"
        border = f"2px solid {color}" if active else "1px solid transparent"
        seg_html += (
            f'<div style="flex:0 0 {width:.2f}%;background:{color}33;opacity:{opacity};'
            f'border:{border};border-radius:4px;margin:0 1px;padding:4px 2px;text-align:center;'
            f'font-size:9px;font-weight:700;color:{color};white-space:nowrap;overflow:hidden">'
            f'{label}</div>'
        )
    today_clamped = max(span_start, min(today, span_end))
    marker_pct = (today_clamped - span_start).days / total_days * 100
    return (
        f'<div style="position:relative;margin:10px 0 4px">'
        f'<div style="display:flex;height:26px">{seg_html}</div>'
        f'<div style="position:absolute;top:-6px;left:{marker_pct:.2f}%;transform:translateX(-50%)">'
        f'<div style="width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;'
        f'border-top:7px solid {GOLD}"></div></div>'
        f'</div>'
        f'<div style="color:{TEXT_MUTED};font-size:9px;text-align:right">▲ today</div>'
    )


# ── Main render ───────────────────────────────────────────────────

def render():
    base = _load_base_data()

    today = datetime.now().date()
    phase = _phase_info(today)

    # ── Header / phase banner ───────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{phase["color"]}18,{GOLD}08);'
        f'border:1px solid {phase["color"]}55;border-radius:12px;padding:16px 20px;margin-bottom:10px">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px">'
        f'<div>'
        f'<div style="color:{GOLD};font-size:15px;font-weight:700;margin-bottom:4px">'
        f'🗳️ Election Playbook 2026 — Oct Midterm Sequencing</div>'
        f'<div style="color:{phase["color"]};font-size:13px;font-weight:700">'
        f'{phase["icon"]} PHASE: {phase["label"]}</div>'
        f'</div>'
        f'<div style="text-align:right">'
        f'<div style="color:{TEXT_PRIMARY};font-size:20px;font-weight:700;font-family:\'DM Mono\',monospace">'
        f'{phase["days_to_election"]:+d}d</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px">days to Nov 3, 2026 election</div>'
        f'</div>'
        f'</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11.5px;line-height:1.6;margin-top:8px">{phase["detail"]}</div>'
        f'{_timeline_html(today, phase["key"])}'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.expander("📖 How to use this sheet — sequencing, color key & leveraged-ETF warning"):
        st.markdown(
            f"""
**How to sequence it (from the "Sequencing & Legend" tab):**

1. **WAIT** for the seasonal weak window (Sept–Oct). Volatility historically peaks right before the
   midterm and fades after the vote. Don't chase an already-extended August tape.
2. **SELL CASH-SECURED PUTS** into the pre-election IV spike on extended names you'd happily own
   lower (financials/defense, Tier-1/2 semis). Reach for Nov–Dec+ expiries so any assignment lands
   at the start of the strong post-midterm window.
3. **BUY THE DIP** on quality that gets marked down but isn't broken. Target an October low as the entry.
   *(Below, this is split into 🟢 Confirmed — still above its 200-day SMA, the uptrend is intact — vs.
   🟠 Speculative — below its 200-SMA, the trend itself has broken.)*
4. **HEDGE** the crowded AI/semi book — tactical, short-hold downside insurance, not the defensives.
5. **HOLD** election-agnostic compounders through the noise — no dip required.
6. **AVOID / TRIM** the highest-risk dip names unless you truly want the shares.

**House Flip vs Hold — quick logic:** both outcomes were historically positive for the S&P (flip = a
softer ~10% 6-month rally as gridlock protects the status quo; hold = deregulation/energy/defense/tariff
runway stays open). Discipline: don't trade the ballot — party-timed cash exits have historically
underperformed staying invested. Defense budgets don't contract on a power shift either way.

**Leveraged / inverse ETF warning:** every 2x/3x/inverse ETF here resets leverage **daily**. Over
multi-day holds, volatility decay erodes returns — in a choppy tape they can lose money even if the
underlying nets flat. Use them as short-hold **tactical** tools only, never buy-and-hold. NRGU is an
ETN (adds issuer credit risk).

*(Full outlook color key and a column-by-column guide are under the table below.)*

*(Source workbook snapshot: Aug 8, 2026. "Today's Instruction" is recomputed live every refresh from
three signals — % off the 52-week high (the dip trigger), position vs. the 200-day SMA (confirms
whether the pullback sits inside an intact uptrend or a broken one), and RSI (momentum context) —
never a hand-typed price from the sheet.)*

⚠️ **This is a framework built on historical base rates and the source workbook's own notes — not
financial advice or a forecast. Not a licensed advisor. Verify live prices, forward P/Es, IV rank and
support levels before acting.**
            """,
            unsafe_allow_html=True,
        )

    # ── Load / refresh live technicals ──────────────────────────
    r1, r2, r3 = st.columns([1.3, 1, 3])
    with r1:
        run = st.button("🔄 Refresh Live Prices & Instructions", type="primary",
                        use_container_width=True, key="ep_run")
    with r2:
        if st.button("🧹 Clear", use_container_width=True, key="ep_clear"):
            st.session_state.pop("ep_tech", None)
            st.session_state.pop("ep_ts", None)
            st.rerun()
    with r3:
        if st.session_state.get("ep_ts"):
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:11px;padding-top:8px">'
                f'Last refreshed: {st.session_state["ep_ts"]}</div>',
                unsafe_allow_html=True,
            )

    if run:
        tickers = base["Ticker"].tolist()
        prog = st.progress(0, text="Fetching live prices…")
        stat = st.empty()

        def _status(i, n, tk):
            prog.progress((i + 1) / n, text=f"Fetching {tk} ({i + 1}/{n})")
            stat.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px">📡 {tk}</div>',
                         unsafe_allow_html=True)

        tech = _fetch_technicals(tickers, status_fn=_status)
        prog.empty(); stat.empty()
        st.session_state["ep_tech"] = tech
        st.session_state["ep_ts"] = datetime.now().strftime("%b %d %Y  %I:%M %p")
        st.rerun()

    tech = st.session_state.get("ep_tech", {})
    if not tech:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;'
            f'padding:36px;text-align:center;color:{TEXT_MUTED}">'
            f'Press <b style="color:{GOLD}">🔄 Refresh Live Prices & Instructions</b> to pull current '
            f'prices for all {len(base)} tickers and generate today\'s per-ticker instructions.'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Build the working DataFrame ─────────────────────────────
    df = base.copy()
    df["Price"] = df["Ticker"].map(lambda t: tech.get(t, {}).get("Price"))
    df["Pct_Off_High"] = df["Ticker"].map(lambda t: tech.get(t, {}).get("Pct_Off_High"))
    df["Above_SMA200"] = df["Ticker"].map(lambda t: tech.get(t, {}).get("Above_SMA200"))
    df["RSI"] = df["Ticker"].map(lambda t: tech.get(t, {}).get("RSI"))

    actions, headlines = [], []
    for _, row in df.iterrows():
        a, h = _build_instruction(row["Strategy"], row["Outlook_Category"], row["Ticker"],
                                  row["Pct_Off_High"], row["Above_SMA200"], row["RSI"], phase["key"])
        actions.append(a); headlines.append(h)
    df["Action"] = actions
    df["Instruction"] = headlines

    # ── Filters ──────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        sectors = st.multiselect("Sector", sorted(df["Sector"].unique()), key="ep_f_sector")
    with f2:
        outlooks = st.multiselect("Outlook", list(OUTLOOK_META.keys()), key="ep_f_outlook")
    with f3:
        action_opts = [a for a in ACTION_META if a in df["Action"].unique()]
        actions_f = st.multiselect(
            "Today's Action", action_opts,
            format_func=lambda a: ACTION_META[a][1], key="ep_f_action",
        )
    with f4:
        search = st.text_input("Search ticker", key="ep_f_search", placeholder="e.g. NVDA")

    f5, f6 = st.columns([1, 3])
    with f5:
        lev_only = st.checkbox("Leveraged/inverse only", key="ep_f_lev")

    fdf = df.copy()
    if sectors:
        fdf = fdf[fdf["Sector"].isin(sectors)]
    if outlooks:
        fdf = fdf[fdf["Outlook_Category"].isin(outlooks)]
    if actions_f:
        fdf = fdf[fdf["Action"].isin(actions_f)]
    if search:
        fdf = fdf[fdf["Ticker"].str.contains(search.strip().upper(), na=False)]
    if lev_only:
        fdf = fdf[fdf["Leveraged"] == "Y"]

    # ── Summary action pills ────────────────────────────────────
    counts = df["Action"].value_counts().to_dict()
    pill_html = "".join(
        f'<span style="background:{color}18;color:{color};border:1px solid {color}55;'
        f'padding:5px 12px;border-radius:20px;font-size:11.5px;font-weight:700;margin-right:8px">'
        f'{label.split(" ", 1)[1] if " " in label else label}: {counts.get(k, 0)}</span>'
        for k, (color, label) in ACTION_META.items()
    )
    st.markdown(
        f'<div style="margin:10px 0 14px;display:flex;flex-wrap:wrap;gap:4px">{pill_html}</div>',
        unsafe_allow_html=True,
    )

    if fdf.empty:
        st.markdown(
            f'<div style="text-align:center;padding:40px;color:{TEXT_MUTED}">'
            f'No tickers match these filters.</div>', unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:6px">'
        f'Showing {len(fdf)} of {len(df)} tickers — click any column header to sort</div>',
        unsafe_allow_html=True,
    )

    # ── Build sortable table ────────────────────────────────────
    columns = [
        {"label": "Ticker", "type": "str"},
        {"label": "Outlook", "type": "str"},
        {"label": "Price", "type": "num"},
        {"label": "vs 52wk High", "type": "num"},
        {"label": "vs 200-SMA", "type": "str"},
        {"label": "Today's Instruction", "type": "str"},
        {"label": "Election Beta", "type": "str"},
        {"label": "Horizon / Conviction", "type": "str"},
        {"label": "Bounce-back Driver", "type": "str"},
    ]

    rows = []
    for _, row in fdf.iterrows():
        oc = row["Outlook_Category"]
        o_color, _, o_title = OUTLOOK_META.get(oc, (TEXT_MUTED, "", ""))
        why = row.get("Why_Drop", "")
        outlook_cell = _badge(oc, o_color, title=why)

        price = row["Price"]
        price_html = (f'<span style="font-family:\'DM Mono\',monospace;color:{TEXT_PRIMARY}">'
                     f'${price:,.2f}</span>') if pd.notna(price) else '<span style="color:#6B7280">—</span>'

        pct = row["Pct_Off_High"]
        if pd.notna(pct):
            pcol = ACCENT_RED if pct <= -8 else (GOLD if pct <= -3 else ACCENT_GREEN)
            pct_html = f'<span style="color:{pcol};font-weight:700">{pct:+.1f}%</span>'
            pct_sort = pct
        else:
            pct_html = '<span style="color:#6B7280">—</span>'
            pct_sort = 0

        above = row["Above_SMA200"]
        if above is True:
            sma_html = f'<span style="color:{ACCENT_GREEN}">▲ Above</span>'
        elif above is False:
            sma_html = f'<span style="color:{ACCENT_RED}">▼ Below</span>'
        else:
            sma_html = '<span style="color:#6B7280">—</span>'

        a_color, a_label = ACTION_META.get(row["Action"], (TEXT_MUTED, row["Action"]))
        instr_title = f'{row.get("Play_Type","")} | {row.get("Notes","")}'
        instr_html = (
            f'<div>{_badge(a_label, a_color)}</div>'
            f'<div title="{_esc(instr_title)}" style="color:{TEXT_MUTED};font-size:11px;'
            f'margin-top:3px;max-width:320px;white-space:normal">{_esc(row["Instruction"])}</div>'
        )

        beta = row.get("Election_Beta", "")
        beta_color = ACCENT_RED if "HIGH" in beta else (GOLD if "MED" in beta else ACCENT_GREEN)
        beta_html = _badge(beta or "—", beta_color, title=row.get("Election_Sensitivity", ""))

        lev_tag = " ⚡3x/2x" if row["Leveraged"] == "Y" else ""
        ticker_html = (
            f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700">'
            f'{row["Ticker"]}</span>{lev_tag}<br>'
            f'<span style="color:{TEXT_MUTED};font-size:10px">{_esc(row["Sector"])}</span>'
        )

        rows.append([
            (ticker_html, row["Ticker"]),
            (outlook_cell, oc),
            (price_html, price if pd.notna(price) else -999999),
            (pct_html, pct_sort),
            (sma_html, "Above" if above else "Below" if above is False else "—"),
            (instr_html, row["Action"]),
            (beta_html, beta),
            (_esc(row.get("Horizon_Conviction", "")), row.get("Horizon_Conviction", "")),
            (f'<span title="{_esc(row.get("Notes",""))}">{_esc(row.get("Bounce_Driver",""))}</span>',
             row.get("Bounce_Driver", "")),
        ])

    html = sortable_table_html(columns, rows, max_height=560)
    st.components.v1.html(html, height=580, scrolling=True)

    # ── Reference panel: outlook legend + column guide ──────────
    legend_html = "".join(
        f'<div style="margin-bottom:5px">{_badge(cat, color)} '
        f'<span style="color:{TEXT_MUTED};font-size:11.5px">{title.split(" — ", 1)[1] if " — " in title else ""}</span></div>'
        for cat, (color, _, title) in OUTLOOK_META.items()
    )
    guide_rows = "".join(
        f'<tr><td style="padding:6px 12px;border-bottom:1px solid {BORDER_COLOR}22;color:{GOLD};'
        f'font-size:11.5px;font-weight:700;white-space:nowrap;vertical-align:top">{col}</td>'
        f'<td style="padding:6px 12px;border-bottom:1px solid {BORDER_COLOR}22;color:{TEXT_MUTED};'
        f'font-size:11.5px">{meaning}</td></tr>'
        for col, meaning in COLUMN_GUIDE
    )
    st.markdown(
        f'<div style="margin-top:14px;padding:14px 16px;background:{BG_PANEL};'
        f'border:1px solid {BORDER_COLOR};border-radius:10px">'
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;margin-bottom:8px">Outlook Color Key</div>'
        f'{legend_html}'
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;margin:14px 0 8px">Column Guide</div>'
        f'<table style="width:100%;border-collapse:collapse">{guide_rows}</table>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Export ────────────────────────────────────────────────
    export_cols = ["Ticker", "Sector", "Outlook_Category", "Price", "Pct_Off_High",
                   "Above_SMA200", "RSI", "Action", "Instruction", "Election_Beta",
                   "Play_Type", "Horizon_Conviction", "Bounce_Driver", "Notes"]
    st.download_button(
        "⬇ Export Filtered View (CSV)",
        fdf[export_cols].to_csv(index=False),
        _export_filename("election_playbook_2026"), "text/csv",
        key="ep_export",
    )
