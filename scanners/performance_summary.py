# scanners/performance_summary.py — Scanner Performance Dashboard
# ─────────────────────────────────────────────────────────────────
# Rendered under "Summary" sub-menu of Tracking.
#
# THIS PAGE IS A DESIGN SKELETON.  All UI / layout / styling / data wiring
# is in place; functional gaps Claude Code can fill in are marked TODO(cc).
#
# What this page does:
#   - Three tabs:  📅 Daily   ·   🗓 Weekly   ·   📊 Analytics
#   - Daily   = positions added during the current trading day
#                (rolls over at 9:30 AM ET next session)
#   - Weekly  = positions added in the current Sun–Sat week.
#                On Sun & Mon we show last week's complete data so users
#                have time to review before the new week's data takes over.
#   - Analytics = win rate by scanner, top & worst tickers, what worked.
#
#   - Within Daily & Weekly each, FOUR category sections:
#         1. Stocks
#         2. CSP + CC (combined — both are short-premium income plays)
#         3. LEAPS
#         4. Options (ETF Options + 3× ETF Options — leveraged option plays)
#       Each section shows: header strip · top-3 winners horizontal bars ·
#                            full positions table.
#
# Data source: Tracking sheet via gsheet_helper.get_tracking(). Every position
#   is OPEN — this dashboard tracks SCANNER PERFORMANCE, not closed-trade P&L.
#   "Win" = current unrealized P&L > 0 for the position type.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import sys, os
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header
from scanners.gsheet_helper import get_tracking, using_google_sheets

import plotly.graph_objects as go


# ══════════════════════════════════════════════════════════════════
# 1) STRATEGY CATEGORIZATION — every tracked position maps to ONE of
#    four buckets that drive the per-tab section layout.
# ══════════════════════════════════════════════════════════════════
CATEGORY_LABELS = {
    "stocks":  "📊  Stocks",
    "csp_cc":  "💰  CSP + CC",
    "leaps":   "🧨  LEAPS",
    "options": "⚡  Options",
}
CATEGORY_ORDER  = ["stocks", "csp_cc", "leaps", "options"]
CATEGORY_COLORS = {
    "stocks":  ACCENT_GREEN,
    "csp_cc":  GOLD,
    "leaps":   ACCENT_BLUE,
    "options": "#A855F7",
}

def _categorize(strategy: str) -> str:
    s = (strategy or "").upper().strip()
    if s in {"CSP", "CC", "DIVIDEND+CC"}:                  return "csp_cc"
    if s in {"LEAPS"}:                                      return "leaps"
    if s in {"ETF OPTIONS", "3X ETF OPTIONS", "OPTIONS"}:  return "options"
    return "stocks"   # default: anything not options is a stock position


# ══════════════════════════════════════════════════════════════════
# 2) DATE LOGIC — trading day rolls at 9:30 AM ET. Weekly is Sun–Sat.
#    Until Mon end-of-day, "current week" still means LAST FULL WEEK.
# ══════════════════════════════════════════════════════════════════
def _trading_today() -> date:
    """Today's trading day. Before 9:30 AM ET, returns the prior trading day."""
    if ZoneInfo:
        now = datetime.now(ZoneInfo("US/Eastern"))
    else:
        now = datetime.now()
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    if now < market_open:
        return (now - timedelta(days=1)).date()
    return now.date()


def _week_bounds(today: date = None) -> tuple[date, date, str]:
    """Return (start_sun, end_sat, label) for the active weekly view.

    On Sunday or Monday the "active" week is still LAST week's Sun–Sat
    (gives the user time to review before the new week dominates the view).
    Tuesday onwards we show this week (Sun–Sat, in progress).
    """
    today = today or date.today()
    # Python: Monday=0 .. Sunday=6
    weekday = today.weekday()
    if weekday == 6:                     # Sunday — show last week
        end   = today - timedelta(days=1)              # Saturday
        start = end   - timedelta(days=6)              # Sunday
        label = f"Last week · {start:%b %d} – {end:%b %d}"
    elif weekday == 0:                   # Monday — show last week
        end   = today - timedelta(days=2)              # Saturday
        start = end   - timedelta(days=6)              # Sunday
        label = f"Last week · {start:%b %d} – {end:%b %d}"
    else:                                # Tue–Sat — show this week so far
        days_since_sun = (weekday + 1) % 7
        start = today - timedelta(days=days_since_sun)
        end   = start + timedelta(days=6)
        label = f"This week · {start:%b %d} – {end:%b %d} (in progress)"
    return start, end, label


# ══════════════════════════════════════════════════════════════════
# 3) DATA LOAD — pulls Tracking sheet, attaches live prices + unrealized
#    P&L, parses Added_Date for date-window filtering.
# ══════════════════════════════════════════════════════════════════
@st.cache_data(ttl=180, show_spinner=False)
def _fetch_prices(tickers: tuple) -> dict:
    if not tickers:
        return {}
    try:
        import yfinance as yf
        out = {}
        data = yf.download(list(tickers), period="2d", auto_adjust=True,
                           progress=False, group_by="ticker")
        for t in tickers:
            try:
                close = data["Close"] if len(tickers) == 1 else data[t]["Close"]
                out[t] = round(float(close.dropna().iloc[-1]), 2)
            except Exception:
                out[t] = None
        return out
    except Exception:
        return {}


_SELL_STRATS    = {"CSP", "CC", "DIVIDEND+CC", "ETF OPTIONS"}
_OPTION_STRATS  = {"CSP", "CC", "LEAPS", "ETF OPTIONS", "3X ETF OPTIONS"}

def _row_pnl(r) -> pd.Series:
    ep, cp = r["Entry_Price"], r["Current_Price"]
    if pd.isna(ep) or pd.isna(cp) or ep == 0:
        return pd.Series([np.nan, np.nan])
    pct = (cp - ep) / ep * 100
    strat = (r.get("Strategy") or "").upper()
    if strat in _OPTION_STRATS:
        mult = -1 if strat in _SELL_STRATS else 1
        dollar = round(mult * (cp - ep) * 100, 2)
    else:
        dollar = round((cp - ep) * 100, 2)
    return pd.Series([round(dollar, 2), round(pct, 2)])


def _load_positions() -> pd.DataFrame:
    rows = get_tracking()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["Ticker"]       = df["Ticker"].astype(str).str.upper().str.strip()
    df["Entry_Price"]  = pd.to_numeric(df["Entry_Price"], errors="coerce")
    df["Added_Date"]   = pd.to_datetime(df["Added_Date"], errors="coerce")
    df["Added_Day"]    = df["Added_Date"].dt.date
    df["Category"]     = df["Strategy"].apply(_categorize)
    df["Age_Days"]     = (datetime.now() - df["Added_Date"]).dt.days.fillna(0).astype(int)

    prices = _fetch_prices(tuple(df["Ticker"].unique().tolist()))
    df["Current_Price"] = pd.to_numeric(df["Ticker"].map(prices), errors="coerce")
    df[["PnL_$", "PnL_%"]] = df.apply(_row_pnl, axis=1)
    df["Is_Win"] = df["PnL_$"] > 0
    return df


# ══════════════════════════════════════════════════════════════════
# 4) UI PRIMITIVES — KPI card, category header strip, top-3 bars, table.
# ══════════════════════════════════════════════════════════════════
def _kpi(label: str, value: str, sub: str = "", color: str = None):
    color = color or GOLD
    sub_html = (
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:2px">{sub}</div>'
        if sub else ""
    )
    st.markdown(f"""
    <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-top:2px solid {color};
                border-radius:8px;padding:12px 16px;height:100%">
      <div style="color:{TEXT_MUTED};font-size:10px;letter-spacing:1.2px;
                  text-transform:uppercase;margin-bottom:4px">{label}</div>
      <div style="color:{color};font-family:'Cormorant Garamond',serif;
                  font-size:24px;font-weight:700;line-height:1.1">{value}</div>
      {sub_html}
    </div>
    """, unsafe_allow_html=True)


def _category_strip(cat_key: str, count: int, wins: int):
    """Header strip above each category section."""
    label = CATEGORY_LABELS[cat_key]
    color = CATEGORY_COLORS[cat_key]
    rate  = (wins / count * 100) if count else 0
    rate_color = ACCENT_GREEN if rate >= 60 else (GOLD if rate >= 40 else ACCENT_RED)
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
                background:linear-gradient(90deg, {color}26, transparent);
                border-left:3px solid {color};
                padding:10px 14px;margin:18px 0 10px;border-radius:4px">
      <div style="color:{color};font-family:'Cormorant Garamond',serif;
                  font-size:18px;font-weight:700;letter-spacing:1px">{label}</div>
      <div style="display:flex;gap:18px;color:{TEXT_MUTED};font-size:11px">
        <span><b style="color:{TEXT_PRIMARY};font-family:'DM Mono',monospace">{count}</b> positions</span>
        <span>Win rate <b style="color:{rate_color};font-family:'DM Mono',monospace">{rate:.0f}%</b></span>
      </div>
    </div>
    """, unsafe_allow_html=True)


def _top3_bars(sub: pd.DataFrame, cat_key: str):
    """Horizontal bar chart — top 3 winning tickers by P&L within the category."""
    color = CATEGORY_COLORS[cat_key]
    if sub.empty or sub["PnL_$"].dropna().empty:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;padding:6px 0;font-style:italic">'
            f'No P&L data yet for this category.</div>',
            unsafe_allow_html=True,
        )
        return
    top = (sub.dropna(subset=["PnL_$"])
             .sort_values("PnL_$", ascending=False)
             .head(3))
    fig = go.Figure(go.Bar(
        x=top["PnL_$"].tolist(),
        y=top["Ticker"].tolist(),
        orientation="h",
        marker_color=color,
        text=[f"${v:+,.0f}  ({p:+.1f}%)" for v, p in zip(top["PnL_$"], top["PnL_%"])],
        textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=11, family="Inter"),
        hovertemplate="<b>%{y}</b><br>P&L: %{x:$,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Top 3 winners",
                   font=dict(color=color, size=12, family="Inter"),
                   x=0, xanchor="left", y=0.96),
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        height=160, margin=dict(l=8, r=80, t=30, b=12),
        xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED,
                   tickfont=dict(size=10), tickprefix="$"),
        yaxis=dict(showgrid=False, color=GOLD, autorange="reversed",
                   tickfont=dict(size=11, family="DM Mono")),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _positions_table(sub: pd.DataFrame, cat_key: str):
    """Compact HTML table of positions in this category."""
    if sub.empty:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;padding:8px 0;font-style:italic;'
            f'border:1px dashed {BORDER_COLOR};border-radius:6px;padding:14px;text-align:center">'
            f'No positions in this category for the selected period.</div>',
            unsafe_allow_html=True,
        )
        return

    head_cells = ["TICKER", "STRATEGY", "SOURCE", "ENTRY", "CURRENT", "P&L", "ROI", "AGE", "SCORE"]
    th = "".join(
        f'<th style="color:{TEXT_MUTED};font-size:10px;font-weight:600;letter-spacing:0.8px;'
        f'text-align:left;padding:8px 10px;border-bottom:1px solid {BORDER_COLOR};white-space:nowrap">{h}</th>'
        for h in head_cells
    )
    rows = []
    for i, (_, r) in enumerate(sub.iterrows()):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        pnl  = r.get("PnL_$")
        pct  = r.get("PnL_%")
        ep   = r.get("Entry_Price")
        cp   = r.get("Current_Price")
        pnl_color = ACCENT_GREEN if (pd.notna(pnl) and pnl >= 0) else ACCENT_RED
        pnl_html  = f'${pnl:+,.0f}' if pd.notna(pnl) else "—"
        pct_html  = f'{pct:+.1f}%' if pd.notna(pct) else "—"
        ep_html   = f'${ep:.2f}'   if pd.notna(ep)  else "—"
        cp_html   = f'${cp:.2f}'   if pd.notna(cp)  else "—"
        rows.append(f"""
        <tr style="background:{bg}">
          <td style="padding:7px 10px;color:{GOLD};font-family:'DM Mono',monospace;font-weight:700;font-size:12px">{r['Ticker']}</td>
          <td style="padding:7px 10px;color:{TEXT_PRIMARY};font-size:11px">{r.get('Strategy','')}</td>
          <td style="padding:7px 10px;color:{TEXT_MUTED};font-size:10px">{r.get('Source','')}</td>
          <td style="padding:7px 10px;color:{TEXT_MUTED};font-family:'DM Mono',monospace;font-size:11px">{ep_html}</td>
          <td style="padding:7px 10px;color:{TEXT_PRIMARY};font-family:'DM Mono',monospace;font-size:11px">{cp_html}</td>
          <td style="padding:7px 10px;color:{pnl_color};font-family:'DM Mono',monospace;font-weight:700;font-size:11px">{pnl_html}</td>
          <td style="padding:7px 10px;color:{pnl_color};font-family:'DM Mono',monospace;font-size:11px">{pct_html}</td>
          <td style="padding:7px 10px;color:{TEXT_MUTED};font-size:11px">{r['Age_Days']}d</td>
          <td style="padding:7px 10px;color:{TEXT_MUTED};font-size:11px">{r.get('Score','—')}</td>
        </tr>
        """)
    table = f"""
    <div style="border:1px solid {BORDER_COLOR};border-radius:6px;overflow:hidden;overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif">
        <thead><tr>{th}</tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """
    st.markdown(table, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# 5) PERIOD KPI STRIP — sits above the four category sections.
# ══════════════════════════════════════════════════════════════════
def _period_kpis(df: pd.DataFrame, period_label: str):
    n = len(df)
    wins = int(df["Is_Win"].sum()) if not df.empty else 0
    rate = (wins / n * 100) if n else 0
    avg_pct = df["PnL_%"].mean() if not df.empty else np.nan
    total_pnl = df["PnL_$"].dropna().sum() if not df.empty else 0
    avg_age = df["Age_Days"].mean() if not df.empty else 0

    rate_color = ACCENT_GREEN if rate >= 60 else (GOLD if rate >= 40 else ACCENT_RED)
    pnl_color  = ACCENT_GREEN if total_pnl >= 0 else ACCENT_RED

    c1, c2, c3, c4 = st.columns(4)
    with c1: _kpi("Positions Tracked", str(n), sub=period_label, color=GOLD)
    with c2: _kpi("Win Rate", f"{rate:.0f}%", sub=f"{wins} of {n}", color=rate_color)
    with c3: _kpi("Total Unrealized P&L", f"${total_pnl:+,.0f}",
                  sub=f"Avg {avg_pct:+.2f}%" if pd.notna(avg_pct) else "—",
                  color=pnl_color)
    with c4: _kpi("Avg Hold", f"{avg_age:.1f}d" if n else "—",
                  sub="Days since added", color=ACCENT_BLUE)


# ══════════════════════════════════════════════════════════════════
# 6) TAB RENDERERS
# ══════════════════════════════════════════════════════════════════
def _render_period_tab(df: pd.DataFrame, period_label: str, empty_msg: str):
    """Daily and Weekly share the same layout — different filtered df."""
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin:8px 0 14px">{period_label}</div>',
        unsafe_allow_html=True,
    )
    if df.empty:
        st.markdown(
            f'<div style="background:{BG_PANEL};border:1px dashed {BORDER_COLOR};border-radius:8px;'
            f'padding:40px 20px;text-align:center;color:{TEXT_MUTED};font-size:13px">'
            f'<div style="font-size:32px;margin-bottom:10px">📭</div>{empty_msg}</div>',
            unsafe_allow_html=True,
        )
        return

    _period_kpis(df, period_label)

    # Four category sections, in fixed order. Each gets Top-3 bars + table.
    for cat in CATEGORY_ORDER:
        sub = df[df["Category"] == cat].copy()
        wins = int(sub["Is_Win"].sum()) if not sub.empty else 0
        _category_strip(cat, len(sub), wins)
        if sub.empty:
            _positions_table(sub, cat)  # renders the empty-state card
            continue
        left, right = st.columns([1, 1])
        with left:
            _top3_bars(sub.sort_values("PnL_$", ascending=False), cat)
        with right:
            # Simple stat strip on the right of Top-3
            best  = sub["PnL_$"].max() if not sub["PnL_$"].dropna().empty else 0
            worst = sub["PnL_$"].min() if not sub["PnL_$"].dropna().empty else 0
            avg   = sub["PnL_%"].mean() if not sub["PnL_%"].dropna().empty else 0
            st.markdown(f"""
            <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:8px;
                        padding:14px;height:100%">
              <div style="color:{TEXT_MUTED};font-size:10px;letter-spacing:1.2px;
                          text-transform:uppercase;margin-bottom:8px">Category stats</div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:11px">
                <div><div style="color:{TEXT_MUTED}">Best</div>
                     <div style="color:{ACCENT_GREEN};font-family:'DM Mono',monospace;font-weight:700;font-size:14px">${best:+,.0f}</div></div>
                <div><div style="color:{TEXT_MUTED}">Worst</div>
                     <div style="color:{ACCENT_RED};font-family:'DM Mono',monospace;font-weight:700;font-size:14px">${worst:+,.0f}</div></div>
                <div style="grid-column:1/-1"><div style="color:{TEXT_MUTED}">Avg ROI</div>
                     <div style="color:{GOLD};font-family:'Cormorant Garamond',serif;font-weight:700;font-size:20px">{avg:+.2f}%</div></div>
              </div>
            </div>
            """, unsafe_allow_html=True)
        _positions_table(sub.sort_values("PnL_$", ascending=False, na_position="last"), cat)


def _render_daily_tab(df: pd.DataFrame):
    trading_day = _trading_today()
    label = f"Trading day · {trading_day:%a %b %d, %Y}"
    today_df = df[df["Added_Day"] == trading_day] if not df.empty else df
    _render_period_tab(
        today_df,
        period_label=label,
        empty_msg="No positions added during today's trading day.<br>"
                  "Use the <b style='color:#F5C842'>📌 Track</b> button on any scanner result to populate.",
    )


def _render_weekly_tab(df: pd.DataFrame):
    start, end, label = _week_bounds()
    week_df = df[
        (df["Added_Day"] >= start) & (df["Added_Day"] <= end)
    ] if not df.empty else df
    _render_period_tab(
        week_df,
        period_label=label,
        empty_msg=f"No positions added between {start:%a %b %d} and {end:%a %b %d}.",
    )


# ── ANALYTICS TAB ──────────────────────────────────────────────────
def _render_analytics_tab(df: pd.DataFrame):
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin:8px 0 14px">All-time · scanner-level rollups</div>',
        unsafe_allow_html=True,
    )
    if df.empty:
        st.markdown(
            f'<div style="background:{BG_PANEL};border:1px dashed {BORDER_COLOR};border-radius:8px;'
            f'padding:40px 20px;text-align:center;color:{TEXT_MUTED};font-size:13px">'
            f'<div style="font-size:32px;margin-bottom:10px">📭</div>'
            f'No tracked positions yet.</div>',
            unsafe_allow_html=True,
        )
        return

    # Overall snapshot
    _period_kpis(df, "All-time across every tracked position")

    # ── WIN RATE BY SCANNER (Source) ───────────────────────────
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="color:{ACCENT_GREEN};font-size:12px;font-weight:700;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin-bottom:8px">🏆 Win rate by scanner</div>',
        unsafe_allow_html=True,
    )
    # Group by the Source prefix (GS-, H&C-, CSP, etc.). Strip the suffix after the dash for grouping.
    src = df.copy()
    src["Source_Group"] = src["Source"].fillna("").astype(str).str.split("-").str[0].replace("", "Other")
    by_src = (src.groupby("Source_Group")
                 .agg(N=("Ticker","count"),
                      Wins=("Is_Win","sum"),
                      AvgPct=("PnL_%","mean"),
                      TotalPnL=("PnL_$","sum"))
                 .reset_index())
    by_src["Rate"] = (by_src["Wins"] / by_src["N"] * 100).round(1)
    by_src = by_src.sort_values("Rate", ascending=False)

    fig = go.Figure(go.Bar(
        x=by_src["Rate"], y=by_src["Source_Group"], orientation="h",
        marker_color=[ACCENT_GREEN if r >= 60 else (GOLD if r >= 40 else ACCENT_RED)
                      for r in by_src["Rate"]],
        text=[f"{r:.0f}%  ({w}/{n})" for r, w, n in zip(by_src["Rate"], by_src["Wins"], by_src["N"])],
        textposition="outside", textfont=dict(color=TEXT_PRIMARY, size=11, family="Inter"),
    ))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        height=max(150, 36 * len(by_src) + 40),
        margin=dict(l=8, r=80, t=10, b=12),
        xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED,
                   range=[0, 110], ticksuffix="%"),
        yaxis=dict(showgrid=False, color=GOLD, autorange="reversed",
                   tickfont=dict(size=11)),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── TOP & WORST TICKERS ────────────────────────────────────
    col_top, col_worst = st.columns(2)
    by_tkr = (df.dropna(subset=["PnL_$"])
                .groupby("Ticker")
                .agg(N=("Ticker","count"), PnL=("PnL_$","sum"), AvgPct=("PnL_%","mean"))
                .reset_index())
    with col_top:
        st.markdown(
            f'<div style="color:{ACCENT_GREEN};font-size:12px;font-weight:700;letter-spacing:1.5px;'
            f'text-transform:uppercase;margin:14px 0 6px">▲ Top 5 tickers</div>',
            unsafe_allow_html=True,
        )
        top5 = by_tkr.sort_values("PnL", ascending=False).head(5)
        fig = go.Figure(go.Bar(
            x=top5["PnL"], y=top5["Ticker"], orientation="h",
            marker_color=ACCENT_GREEN,
            text=[f"${v:+,.0f}" for v in top5["PnL"]],
            textposition="outside", textfont=dict(color=TEXT_PRIMARY, size=11, family="Inter"),
        ))
        fig.update_layout(
            paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
            height=max(140, 28 * len(top5) + 40),
            margin=dict(l=8, r=70, t=10, b=12),
            xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED, tickprefix="$"),
            yaxis=dict(showgrid=False, color=GOLD, autorange="reversed"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with col_worst:
        st.markdown(
            f'<div style="color:{ACCENT_RED};font-size:12px;font-weight:700;letter-spacing:1.5px;'
            f'text-transform:uppercase;margin:14px 0 6px">▼ Bottom 5 tickers</div>',
            unsafe_allow_html=True,
        )
        bot5 = by_tkr.sort_values("PnL", ascending=True).head(5)
        fig = go.Figure(go.Bar(
            x=bot5["PnL"], y=bot5["Ticker"], orientation="h",
            marker_color=ACCENT_RED,
            text=[f"${v:+,.0f}" for v in bot5["PnL"]],
            textposition="outside", textfont=dict(color=TEXT_PRIMARY, size=11, family="Inter"),
        ))
        fig.update_layout(
            paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
            height=max(140, 28 * len(bot5) + 40),
            margin=dict(l=8, r=70, t=10, b=12),
            xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED, tickprefix="$"),
            yaxis=dict(showgrid=False, color=GOLD, autorange="reversed"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── WHAT WORKED / WHAT DIDN'T ──────────────────────────────
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    w1, w2 = st.columns(2)

    # Scanner × Category win rate matrix
    df2 = df.copy()
    df2["Cat_Label"] = df2["Category"].map(CATEGORY_LABELS).fillna("Other")
    df2["Src_Group"] = df2["Source"].fillna("").astype(str).str.split("-").str[0].replace("", "Other")
    grid = (df2.groupby(["Src_Group","Cat_Label"])
                .agg(N=("Ticker","count"), Wins=("Is_Win","sum"), Avg=("PnL_%","mean"))
                .reset_index())
    grid["Rate"] = (grid["Wins"] / grid["N"] * 100).round(0)
    worked  = grid[(grid["N"] >= 3) & (grid["Rate"] >= 60)].sort_values("Rate", ascending=False)
    didnt   = grid[(grid["N"] >= 3) & (grid["Rate"] <  40)].sort_values("Rate", ascending=True)

    def _strategy_list(rows: pd.DataFrame, title: str, color: str, empty_msg: str):
        st.markdown(
            f'<div style="color:{color};font-size:12px;font-weight:700;letter-spacing:1.5px;'
            f'text-transform:uppercase;margin-bottom:8px">{title}</div>',
            unsafe_allow_html=True,
        )
        if rows.empty:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:11px;font-style:italic;'
                f'background:{BG_PANEL};border:1px dashed {BORDER_COLOR};border-radius:6px;'
                f'padding:14px;text-align:center">{empty_msg}</div>',
                unsafe_allow_html=True,
            )
            return
        items = []
        for _, r in rows.head(6).iterrows():
            items.append(f"""
            <div style="display:flex;justify-content:space-between;padding:8px 12px;
                        background:{BG_CARD};border:1px solid {BORDER_COLOR};border-left:3px solid {color};
                        border-radius:4px;margin-bottom:4px">
              <div>
                <div style="color:{TEXT_PRIMARY};font-size:12px;font-weight:600">{r['Src_Group']} → {r['Cat_Label']}</div>
                <div style="color:{TEXT_MUTED};font-size:10px">{int(r['N'])} positions · avg {r['Avg']:+.1f}%</div>
              </div>
              <div style="color:{color};font-family:'DM Mono',monospace;font-weight:700;font-size:14px;align-self:center">{int(r['Rate'])}%</div>
            </div>
            """)
        st.markdown("".join(items), unsafe_allow_html=True)

    with w1:
        _strategy_list(worked, "✅ What worked",  ACCENT_GREEN,
                       "Need at least 3 positions per scanner+category at 60%+ win rate.")
    with w2:
        _strategy_list(didnt, "❌ What didn't work", ACCENT_RED,
                       "Nothing below 40% win rate yet.")

    # TODO(cc): consider adding a small "P&L over time" line chart of cumulative
    # unrealized P&L by Added_Date to see whether scanner picks are improving.


# ══════════════════════════════════════════════════════════════════
# 7) MAIN RENDER
# ══════════════════════════════════════════════════════════════════
def render():
    section_header("📈", "Summary",
                   "Scanner performance · Daily · Weekly · Analytics")

    storage = "Google Sheets" if using_google_sheets() else "Local CSV (data/tracking.csv)"
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:12px">'
        f'Storage: <b style="color:{GOLD}">{storage}</b> · Every tracked position is open · '
        f'<i>Win = unrealized P&L &gt; 0</i></div>',
        unsafe_allow_html=True,
    )

    df = _load_positions()

    tab_d, tab_w, tab_a = st.tabs(["📅  Daily", "🗓  Weekly", "📊  Analytics"])
    with tab_d:
        _render_daily_tab(df)
    with tab_w:
        _render_weekly_tab(df)
    with tab_a:
        _render_analytics_tab(df)

    # Footer disclaimer
    st.markdown(f"""
    <div style="margin-top:24px;color:{TEXT_MUTED};font-size:10px;text-align:center">
      Unrealized P&L derived from live yfinance prices. Not financial advice.
    </div>
    """, unsafe_allow_html=True)
