# scanners/performance_summary.py — Wheel Strategy Performance Dashboard
# ─────────────────────────────────────────────────────────────────
# Rendered under the "Summary" sub-menu of Tracking.
# Data source: Google Sheets (or local CSV fallback) via gsheet_helper.
#
# Design reference: Optionswheel community Reddit dashboard — dark + gold
# theme, 4-KPI strip, donut + bar charts, ticker-performance table.
#
# IMPORTANT — schema gap:
#   The current Tracking sheet only stores OPEN positions
#   (Ticker, Strategy, Action, Qty, Entry_Price, Added_Date, Source, Score,
#    HOLD, Est_Upside, Notes).
#   It does NOT capture: Closed_Date, Closed_Price, Realized_PnL, Premium.
#
#   This page works with what's available today (open positions + age + live
#   prices for unrealized P&L). Sections that require closed-trade history
#   (Closed Positions, Premium Realized Today, Monthly Income bars, Strategy
#   Mix, Trade Outcomes) render with placeholder copy explaining what's needed
#   to power them. Once you extend the schema (add Closed_Date + Closed_Price
#   + Realized_Premium columns), this page lights up automatically.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import Counter
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header
from scanners.gsheet_helper import get_tracking, using_google_sheets

# Plotly is already in your stack (deep_analysis uses it).
import plotly.graph_objects as go

# Style constants for chart consistency with the rest of the app
_CHART_FONT  = "Inter, sans-serif"
_GRID_COLOR  = BORDER_COLOR
_AXIS_COLOR  = TEXT_MUTED


# ── Data helpers ────────────────────────────────────────────────

@st.cache_data(ttl=180, show_spinner=False)
def _fetch_prices(tickers: tuple) -> dict:
    """Batch live prices for unrealized P&L."""
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


def _load_open_positions() -> pd.DataFrame:
    rows = get_tracking()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
    df["Entry_Price"] = pd.to_numeric(df["Entry_Price"], errors="coerce")
    # Parse Added_Date — supports "YYYY-MM-DD HH:MM" or "YYYY-MM-DD"
    df["Added_Date"] = pd.to_datetime(df["Added_Date"], errors="coerce")
    df["Age_Days"]   = (datetime.now() - df["Added_Date"]).dt.days.fillna(0).astype(int)

    # Live prices for unrealized P&L
    tickers = tuple(df["Ticker"].unique().tolist())
    prices  = _fetch_prices(tickers)
    df["Current_Price"] = df["Ticker"].map(prices)
    df["Current_Price"] = pd.to_numeric(df["Current_Price"], errors="coerce")

    # Unrealized P&L — stocks=100 shares; options sells (CSP/CC) flip sign
    _SELLS    = {"CSP", "CC", "Dividend+CC", "ETF Options"}
    _OPTIONS  = {"CSP", "CC", "LEAPS", "ETF Options", "3x ETF Options"}
    def _pnl(r):
        ep, cp = r["Entry_Price"], r["Current_Price"]
        if pd.isna(ep) or pd.isna(cp) or ep == 0:
            return pd.Series([np.nan, np.nan])
        pct = (cp - ep) / ep * 100
        strat = str(r.get("Strategy", ""))
        if strat in _OPTIONS:
            mult = -1 if strat in _SELLS else 1
            dollar = round(mult * (cp - ep) * 100, 2)
        else:
            dollar = round((cp - ep) * 100, 2)
        return pd.Series([round(dollar, 2), round(pct, 2)])
    df[["PnL_$", "PnL_%"]] = df.apply(_pnl, axis=1)
    return df


# ── UI primitives ───────────────────────────────────────────────

def _kpi_card(icon: str, icon_bg: str, label: str, value: str,
              delta_str: str = "", value_color: str = None):
    """One of the four big circular-icon KPI cards in the WHEEL STRATEGY row."""
    value_color = value_color or GOLD
    delta_html = (
        f'<div style="color:{ACCENT_GREEN if delta_str.startswith("+") else (ACCENT_RED if delta_str.startswith("-") else TEXT_MUTED)};'
        f'font-size:11px;font-weight:600;margin-top:2px;">▲ {delta_str}</div>'
        if delta_str else ""
    )
    st.markdown(f"""
    <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:10px;
                padding:14px 16px;display:flex;align-items:center;gap:14px;height:100%">
      <div style="width:42px;height:42px;border-radius:50%;background:{icon_bg};
                  display:flex;align-items:center;justify-content:center;
                  font-size:20px;flex-shrink:0">{icon}</div>
      <div style="min-width:0;flex:1">
        <div style="color:{TEXT_MUTED};font-size:10px;letter-spacing:1.2px;
                    text-transform:uppercase;font-weight:600;margin-bottom:2px">{label}</div>
        <div style="color:{value_color};font-family:'Cormorant Garamond',serif;
                    font-size:24px;font-weight:700;line-height:1.1">{value}</div>
        {delta_html}
      </div>
    </div>
    """, unsafe_allow_html=True)


def _card_open(title: str, icon: str = "", accent: str = None):
    """Open the outer card div for one of the top-row position panels."""
    accent = accent or GOLD
    st.markdown(f"""
    <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:10px;
                padding:14px 16px;border-top:2px solid {accent};height:100%">
      <div style="color:{accent};font-size:12px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;margin-bottom:10px">{icon} {title}</div>
    """, unsafe_allow_html=True)


def _card_close():
    st.markdown("</div>", unsafe_allow_html=True)


def _placeholder(text: str, height: int = 240):
    """Empty-state block for sections waiting on closed-trade data."""
    st.markdown(f"""
    <div style="background:{BG_PANEL};border:1px dashed {BORDER_COLOR};border-radius:8px;
                padding:24px;text-align:center;color:{TEXT_MUTED};font-size:12px;
                min-height:{height}px;display:flex;align-items:center;justify-content:center">
      <div style="max-width:340px;line-height:1.7">{text}</div>
    </div>
    """, unsafe_allow_html=True)


def _open_positions_table(df: pd.DataFrame) -> str:
    """Compact HTML table — Ticker · Strategy · Strike-ish · Exp · Qty · Status."""
    if df.empty:
        return f'<div style="color:{TEXT_MUTED};font-size:12px;padding:8px 0">No open positions.</div>'
    head = ["TICKER", "STRATEGY", "ENTRY", "AGE", "QTY", "PNL"]
    th = "".join(
        f'<th style="color:{TEXT_MUTED};font-size:10px;font-weight:600;letter-spacing:0.8px;'
        f'text-align:left;padding:6px 10px;border-bottom:1px solid {BORDER_COLOR}">{h}</th>'
        for h in head
    )
    rows = []
    for _, r in df.head(8).iterrows():
        pnl = r.get("PnL_$")
        pnl_html = (
            f'<span style="color:{ACCENT_GREEN if pnl>=0 else ACCENT_RED};font-weight:600">'
            f'${pnl:+,.0f}</span>'
            if pd.notna(pnl) else f'<span style="color:{TEXT_MUTED}">—</span>'
        )
        ep = r.get("Entry_Price")
        ep_str = f"${ep:.2f}" if pd.notna(ep) else "—"
        rows.append(f"""
        <tr>
          <td style="padding:6px 10px;color:{GOLD};font-family:'DM Mono',monospace;font-weight:700;font-size:12px">{r['Ticker']}</td>
          <td style="padding:6px 10px;color:{TEXT_MUTED};font-size:11px">{r.get('Strategy','')}</td>
          <td style="padding:6px 10px;color:{TEXT_PRIMARY};font-family:'DM Mono',monospace;font-size:11px">{ep_str}</td>
          <td style="padding:6px 10px;color:{TEXT_MUTED};font-size:11px">{r['Age_Days']}d</td>
          <td style="padding:6px 10px;color:{TEXT_PRIMARY};font-size:11px">{r.get('Qty','')}</td>
          <td style="padding:6px 10px;font-family:'DM Mono',monospace;font-size:11px">{pnl_html}</td>
        </tr>
        """)
    return f"""
    <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif">
      <thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody>
    </table>
    """


# ── Charts ──────────────────────────────────────────────────────

def _bar_chart_monthly(monthly: dict) -> go.Figure:
    months = list(monthly.keys())
    vals   = list(monthly.values())
    fig = go.Figure(go.Bar(
        x=months, y=vals,
        marker_color=[ACCENT_GREEN if v > 0 else ACCENT_RED for v in vals],
        text=[f"${v:,.0f}" for v in vals],
        textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=11, family=_CHART_FONT),
    ))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        height=240, margin=dict(l=4, r=4, t=10, b=24),
        xaxis=dict(showgrid=False, color=_AXIS_COLOR, tickfont=dict(size=10)),
        yaxis=dict(showgrid=True, gridcolor=_GRID_COLOR, color=_AXIS_COLOR,
                   tickfont=dict(size=10), tickprefix="$"),
        showlegend=False, font=dict(family=_CHART_FONT),
    )
    return fig


def _donut(values: list, labels: list, colors: list, center_label: str) -> go.Figure:
    fig = go.Figure(go.Pie(
        values=values, labels=labels, hole=0.62,
        marker=dict(colors=colors, line=dict(color=BG_CARD, width=2)),
        textinfo="none",
        hovertemplate="<b>%{label}</b><br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        height=240, margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False, font=dict(family=_CHART_FONT),
        annotations=[dict(text=center_label, showarrow=False,
                          font=dict(color=GOLD, size=18, family="Cormorant Garamond"))],
    )
    return fig


def _h_bars(rows: list) -> str:
    """Inline HTML bar list — Ticker · $income · bar."""
    if not rows:
        return f'<div style="color:{TEXT_MUTED};font-size:12px">No data yet.</div>'
    maxv = max(r["value"] for r in rows) or 1
    out = []
    for r in rows:
        w = max(2, int(r["value"] / maxv * 100))
        out.append(f"""
        <div style="display:grid;grid-template-columns:60px 110px 1fr;gap:10px;
                    align-items:center;padding:5px 0">
          <div style="color:{GOLD};font-family:'DM Mono',monospace;font-weight:700;font-size:12px">{r['ticker']}</div>
          <div style="color:{TEXT_PRIMARY};font-family:'DM Mono',monospace;font-size:11px">${r['value']:,.2f}</div>
          <div style="background:{BG_PANEL};border-radius:3px;height:6px;overflow:hidden">
            <div style="background:{ACCENT_GREEN};height:6px;width:{w}%"></div>
          </div>
        </div>
        """)
    return "".join(out)


# ── Main render ─────────────────────────────────────────────────

def render():
    section_header("📈", "Summary",
                   "Performance dashboard · sourced from Tracking sheet")

    storage = "Google Sheets" if using_google_sheets() else "Local CSV (data/tracking.csv)"
    today_str = datetime.now().strftime("%b %d, %Y").upper()

    # Hero title strip — TRADES – DATE (gold)
    st.markdown(f"""
    <div style="text-align:center;font-family:'Cormorant Garamond',serif;
                font-size:32px;font-weight:700;letter-spacing:2px;margin:8px 0 14px">
      <span style="color:{TEXT_PRIMARY}">TRADES</span>
      <span style="color:{TEXT_MUTED};margin:0 8px">—</span>
      <span style="color:{ACCENT_GREEN}">{today_str}</span>
    </div>
    <div style="color:{TEXT_MUTED};font-size:11px;text-align:center;margin-bottom:14px">
      Storage: <b style="color:{GOLD}">{storage}</b>
    </div>
    """, unsafe_allow_html=True)

    df = _load_open_positions()

    # ── TOP ROW · 3 cards ────────────────────────────────────
    c1, c2, c3 = st.columns([1, 1, 1])

    with c1:
        _card_open("Closed Positions", icon="✓", accent=ACCENT_GREEN)
        _placeholder(
            "Closed-trade history requires adding "
            "<b style='color:#F1F1F1'>Closed_Date</b> and "
            "<b style='color:#F1F1F1'>Closed_Price</b> columns "
            "to the Tracking sheet. Once a position has a closed date, it'll appear here.",
            height=180,
        )
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;padding-top:10px;'
            f'border-top:1px solid {BORDER_COLOR};margin-top:8px">'
            f'<div><div style="color:{TEXT_MUTED};font-size:10px;letter-spacing:1px;text-transform:uppercase">Total Profit</div>'
            f'<div style="color:{ACCENT_GREEN};font-family:\'Cormorant Garamond\',serif;font-size:22px;font-weight:700">—</div></div>'
            f'<div style="text-align:right"><div style="color:{TEXT_MUTED};font-size:10px;letter-spacing:1px;text-transform:uppercase">Avg ROI</div>'
            f'<div style="color:{ACCENT_GREEN};font-family:\'DM Mono\',monospace;font-size:14px">—</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        _card_close()

    with c2:
        _card_open("Open Positions", icon="◷", accent=GOLD)
        st.markdown(_open_positions_table(df), unsafe_allow_html=True)
        total_open = len(df) if not df.empty else 0
        total_pnl  = df["PnL_$"].dropna().sum() if not df.empty else 0
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;padding-top:10px;'
            f'border-top:1px solid {BORDER_COLOR};margin-top:8px">'
            f'<div><div style="color:{TEXT_MUTED};font-size:10px;letter-spacing:1px;text-transform:uppercase">Total Open</div>'
            f'<div style="color:{GOLD};font-family:\'Cormorant Garamond\',serif;font-size:22px;font-weight:700">{total_open}</div></div>'
            f'<div style="text-align:right"><div style="color:{TEXT_MUTED};font-size:10px;letter-spacing:1px;text-transform:uppercase">Unrealized P&L</div>'
            f'<div style="color:{ACCENT_GREEN if total_pnl>=0 else ACCENT_RED};font-family:\'DM Mono\',monospace;font-size:14px;font-weight:700">${total_pnl:+,.0f}</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        _card_close()

    with c3:
        _card_open("New Positions", icon="＋", accent=ACCENT_BLUE)
        today = datetime.now().date()
        new_today = df[df["Added_Date"].dt.date == today] if not df.empty and "Added_Date" in df else pd.DataFrame()
        if new_today.empty:
            st.markdown(
                f'<div style="text-align:center;color:{TEXT_MUTED};font-size:12px;'
                f'padding:30px 8px">No new positions today</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(_open_positions_table(new_today), unsafe_allow_html=True)
        st.markdown(
            f'<div style="padding-top:10px;border-top:1px solid {BORDER_COLOR};margin-top:8px;text-align:center">'
            f'<div style="color:{TEXT_MUTED};font-size:10px;letter-spacing:1px;text-transform:uppercase">Added Today</div>'
            f'<div style="color:{ACCENT_BLUE};font-family:\'Cormorant Garamond\',serif;font-size:22px;font-weight:700">{len(new_today)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        _card_close()

    # ── PREMIUM REALIZED STRIP ───────────────────────────────
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    p1, p2 = st.columns(2)
    with p1:
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:10px;
                    padding:14px 18px;display:flex;align-items:center;gap:14px">
          <div style="width:36px;height:36px;border-radius:50%;background:rgba(34,197,94,0.15);
                      display:flex;align-items:center;justify-content:center;font-size:18px">🏷️</div>
          <div style="flex:1">
            <div style="color:{TEXT_MUTED};font-size:10px;letter-spacing:1.2px;text-transform:uppercase">Premium Realized Today</div>
            <div style="color:{ACCENT_GREEN};font-family:'Cormorant Garamond',serif;font-size:26px;font-weight:700;line-height:1.1">—</div>
            <div style="color:{TEXT_MUTED};font-size:10px">(Schema gap — needs Closed_Date column)</div>
          </div>
        </div>
        """, unsafe_allow_html=True)
    with p2:
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:10px;
                    padding:14px 18px;display:flex;align-items:center;gap:14px">
          <div style="width:36px;height:36px;border-radius:50%;background:rgba(59,130,246,0.15);
                      display:flex;align-items:center;justify-content:center;font-size:18px">💵</div>
          <div style="flex:1">
            <div style="color:{TEXT_MUTED};font-size:10px;letter-spacing:1.2px;text-transform:uppercase">New Premium Collected Today</div>
            <div style="color:{ACCENT_BLUE};font-family:'Cormorant Garamond',serif;font-size:26px;font-weight:700;line-height:1.1">—</div>
            <div style="color:{TEXT_MUTED};font-size:10px">(From new options sells)</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── WHEEL STRATEGY PROGRESS — section header ─────────────
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown(f"""
    <div style="text-align:center;font-family:'Cormorant Garamond',serif;
                font-size:24px;font-weight:700;letter-spacing:2px;color:{TEXT_PRIMARY};margin:6px 0 16px">
      WHEEL STRATEGY PROGRESS
    </div>
    """, unsafe_allow_html=True)

    # ── 4 KPI cards ──────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    n_trades = len(df) if not df.empty else 0
    today    = datetime.now().date()
    n_today  = (df["Added_Date"].dt.date == today).sum() if not df.empty else 0
    total_entry_capital = (df["Entry_Price"] * 100).sum() if not df.empty else 0
    avg_premium_per_day = (total_entry_capital / max(1, df["Age_Days"].sum())) if not df.empty else 0

    with k1:
        _kpi_card("$", "rgba(34,197,94,0.18)",
                  "Income YTD", "$ —",
                  delta_str="+— today",
                  value_color=ACCENT_GREEN)
    with k2:
        _kpi_card("📊", "rgba(59,130,246,0.18)",
                  "Total Trades", str(n_trades),
                  delta_str=f"+{n_today} today" if n_today else "",
                  value_color=ACCENT_BLUE)
    with k3:
        _kpi_card("🎯", "rgba(168,85,247,0.18)",
                  "Avg ROI Per Trade", "—",
                  value_color="#A855F7")
    with k4:
        _kpi_card("📅", "rgba(245,200,66,0.18)",
                  "Avg Premium / Day", f"${avg_premium_per_day:,.2f}",
                  value_color=GOLD)

    # ── 3-COLUMN CHART ROW ───────────────────────────────────
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    ch1, ch2, ch3 = st.columns(3)

    with ch1:
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:10px;padding:14px 14px 8px">
          <div style="color:{ACCENT_GREEN};font-size:11px;font-weight:700;letter-spacing:1.5px;
                      text-transform:uppercase;margin-bottom:6px">📊 Monthly Income</div>
        """, unsafe_allow_html=True)
        _placeholder(
            "Monthly income chart unlocks once closed-trade premiums "
            "are recorded. Add a <b style='color:#F1F1F1'>Realized_Premium</b> "
            "column to start populating this.",
            height=200,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with ch2:
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:10px;padding:14px">
          <div style="color:{ACCENT_GREEN};font-size:11px;font-weight:700;letter-spacing:1.5px;
                      text-transform:uppercase;margin-bottom:6px">🥧 Strategy Mix</div>
        """, unsafe_allow_html=True)
        # We CAN compute this from open positions — count by Strategy
        if not df.empty:
            mix = df["Strategy"].astype(str).str.upper().value_counts()
            colors = [GOLD, ACCENT_BLUE, ACCENT_GREEN, "#A855F7", ACCENT_RED, "#FBBF24"]
            fig = _donut(mix.values.tolist(), mix.index.tolist(),
                         colors[:len(mix)],
                         center_label=f"{len(df)}<br><span style='font-size:10px;color:#6B7280;font-family:Inter'>open</span>")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            legend = "".join(
                f'<div style="display:flex;align-items:center;gap:6px;font-size:11px;color:{TEXT_MUTED}">'
                f'<span style="width:8px;height:8px;border-radius:50%;background:{colors[i % len(colors)]}"></span>'
                f'{strat} {count}</div>'
                for i, (strat, count) in enumerate(mix.items())
            )
            st.markdown(f'<div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center">{legend}</div>',
                        unsafe_allow_html=True)
        else:
            _placeholder("No positions yet.", height=200)
        st.markdown("</div>", unsafe_allow_html=True)

    with ch3:
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:10px;padding:14px">
          <div style="color:{ACCENT_GREEN};font-size:11px;font-weight:700;letter-spacing:1.5px;
                      text-transform:uppercase;margin-bottom:6px">⭐ Top Tickers (Open)</div>
        """, unsafe_allow_html=True)
        if not df.empty:
            # Use entry capital as a proxy until realized premiums exist
            grp = (df.assign(Capital=df["Entry_Price"].fillna(0) * 100)
                     .groupby("Ticker")["Capital"].sum()
                     .sort_values(ascending=False).head(5))
            rows = [{"ticker": t, "value": float(v)} for t, v in grp.items()]
            st.markdown(_h_bars(rows), unsafe_allow_html=True)
            total = sum(r["value"] for r in rows)
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;padding-top:10px;'
                f'border-top:1px solid {BORDER_COLOR};margin-top:8px;font-size:11px">'
                f'<span style="color:{TEXT_MUTED}">Total Capital Deployed</span>'
                f'<span style="color:{ACCENT_GREEN};font-family:\'DM Mono\',monospace;font-weight:700">${total:,.0f}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            _placeholder("No positions yet.", height=200)
        st.markdown("</div>", unsafe_allow_html=True)

    # ── TRADE OUTCOMES + TICKER PERFORMANCE TABLE ──────────
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    o1, o2 = st.columns([1, 2])

    with o1:
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:10px;padding:14px">
          <div style="color:{ACCENT_GREEN};font-size:11px;font-weight:700;letter-spacing:1.5px;
                      text-transform:uppercase;margin-bottom:6px">🥧 Trade Outcomes</div>
        """, unsafe_allow_html=True)
        _placeholder(
            "Outcome breakdown (Closed · Expired · Assigned · Exercised) "
            "needs an <b style='color:#F1F1F1'>Outcome</b> column on closed rows.",
            height=240,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with o2:
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:10px;padding:14px">
          <div style="color:{ACCENT_GREEN};font-size:11px;font-weight:700;letter-spacing:1.5px;
                      text-transform:uppercase;margin-bottom:10px">📊 Ticker Performance Snapshot</div>
        """, unsafe_allow_html=True)
        if not df.empty:
            agg = (df.assign(Capital=df["Entry_Price"].fillna(0) * 100,
                              PnL=df["PnL_$"].fillna(0))
                     .groupby("Ticker")
                     .agg(Trades=("Ticker","count"),
                          Capital=("Capital","sum"),
                          PnL=("PnL","sum"))
                     .sort_values("Capital", ascending=False))
            head = ["TICKER", "TRADES", "CAPITAL", "UNREALIZED P&L", "ROI"]
            th = "".join(
                f'<th style="color:{TEXT_MUTED};font-size:10px;font-weight:600;letter-spacing:0.8px;'
                f'text-align:left;padding:6px 10px;border-bottom:1px solid {BORDER_COLOR}">{h}</th>'
                for h in head
            )
            rows = []
            for t, r in agg.iterrows():
                roi = (r["PnL"] / r["Capital"] * 100) if r["Capital"] else 0
                rows.append(f"""
                <tr>
                  <td style="padding:6px 10px;color:{GOLD};font-family:'DM Mono',monospace;font-weight:700;font-size:12px">{t}</td>
                  <td style="padding:6px 10px;color:{TEXT_PRIMARY};font-size:11px">{int(r['Trades'])}</td>
                  <td style="padding:6px 10px;color:{TEXT_PRIMARY};font-family:'DM Mono',monospace;font-size:11px">${r['Capital']:,.0f}</td>
                  <td style="padding:6px 10px;font-family:'DM Mono',monospace;font-size:11px;color:{ACCENT_GREEN if r['PnL']>=0 else ACCENT_RED};font-weight:600">${r['PnL']:+,.0f}</td>
                  <td style="padding:6px 10px;font-family:'DM Mono',monospace;font-size:11px;color:{ACCENT_GREEN if roi>=0 else ACCENT_RED}">{roi:+.2f}%</td>
                </tr>
                """)
            total_cap = agg["Capital"].sum()
            total_pnl = agg["PnL"].sum()
            total_roi = (total_pnl / total_cap * 100) if total_cap else 0
            rows.append(f"""
            <tr>
              <td style="padding:8px 10px;color:{ACCENT_BLUE};font-weight:700;font-size:12px;border-top:1px solid {BORDER_COLOR}">TOTAL</td>
              <td style="padding:8px 10px;color:{ACCENT_BLUE};font-weight:700;font-size:11px;border-top:1px solid {BORDER_COLOR}">{int(agg['Trades'].sum())}</td>
              <td style="padding:8px 10px;color:{ACCENT_BLUE};font-family:'DM Mono',monospace;font-weight:700;font-size:11px;border-top:1px solid {BORDER_COLOR}">${total_cap:,.0f}</td>
              <td style="padding:8px 10px;font-family:'DM Mono',monospace;font-weight:700;font-size:11px;border-top:1px solid {BORDER_COLOR};color:{ACCENT_GREEN if total_pnl>=0 else ACCENT_RED}">${total_pnl:+,.0f}</td>
              <td style="padding:8px 10px;font-family:'DM Mono',monospace;font-weight:700;font-size:11px;border-top:1px solid {BORDER_COLOR};color:{ACCENT_GREEN if total_roi>=0 else ACCENT_RED}">{total_roi:+.2f}%</td>
            </tr>
            """)
            st.markdown(
                f"<table style='width:100%;border-collapse:collapse;font-family:\"Inter\",sans-serif'>"
                f"<thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table>",
                unsafe_allow_html=True,
            )
        else:
            _placeholder("No positions yet — add some from any scanner via the 📌 Track button.",
                         height=240)
        st.markdown("</div>", unsafe_allow_html=True)

    # ── FOOTER STRIP ─────────────────────────────────────────
    st.markdown(f"""
    <div style="margin-top:18px;background:{BG_PANEL};border:1px solid {BORDER_COLOR};
                border-radius:8px;padding:16px;text-align:center;
                color:{TEXT_PRIMARY};font-size:13px;letter-spacing:1.5px">
      🎯 <span style="color:{TEXT_PRIMARY};font-weight:600">SYSTEMATIC.</span>
         <span style="color:{TEXT_PRIMARY};font-weight:600">DISCIPLINED.</span>
         <span style="color:{TEXT_PRIMARY};font-weight:600">CONSISTENT.</span>
         <span style="color:{ACCENT_GREEN};font-weight:600">THAT'S THE PLAN.</span>
    </div>
    <div style="text-align:center;color:{TEXT_MUTED};font-size:10px;margin-top:8px">
      Not financial advice. Just documenting my trading journey.
    </div>
    """, unsafe_allow_html=True)
