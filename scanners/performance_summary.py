# scanners/performance_summary.py — Trading Performance Dashboard
# ─────────────────────────────────────────────────────────────────
# Reddit-style wheel options + stocks performance tracker.
#
# Data source: Google Sheets "Performance" tab (written by Track button)
# Auto-closes positions where Expiry_Date has passed using yfinance history.
# Falls back to local CSV if Sheets is not configured.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import sys, os

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("US/Eastern")
except Exception:
    _ET = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header
from scanners.gsheet_helper import (
    get_performance, update_performance_row,
    using_google_sheets, PERFORMANCE_HEADERS,
)


# ── Constants ──────────────────────────────────────────────────
_SELL_STRATS  = {"CSP", "CC"}          # credit received at open
_DEBIT_STRATS = {"LEAPS"}              # premium paid at open
_STATUS_COLORS = {
    "Open":     "#60A5FA",   # blue
    "Expired":  ACCENT_GREEN,
    "Assigned": "#FBBF24",   # amber
    "Called":   "#A78BFA",   # violet
    "Closed":   ACCENT_GREEN,
    "Loss":     ACCENT_RED,
}
_OUTCOME_COLORS = [ACCENT_GREEN, "#60A5FA", "#FBBF24", "#A78BFA", ACCENT_RED]


# ══════════════════════════════════════════════════════════════════
# 1. DATA LOADING & AUTO-CLOSE
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner=False)
def _hist_close(ticker: str, target_date: str) -> float | None:
    """Return closing price of ticker on or just before target_date."""
    try:
        import yfinance as yf
        td = datetime.strptime(target_date[:10], "%Y-%m-%d").date()
        start = (td - timedelta(days=5)).isoformat()
        end   = (td + timedelta(days=2)).isoformat()
        df = yf.download(ticker, start=start, end=end,
                         auto_adjust=True, progress=False)
        if df.empty:
            return None
        close = df["Close"].squeeze()
        return float(close.iloc[-1])
    except Exception:
        return None


@st.cache_data(ttl=120, show_spinner=False)
def _current_prices(tickers: tuple) -> dict:
    """Batch-fetch latest close prices."""
    if not tickers:
        return {}
    try:
        import yfinance as yf
        data = yf.download(list(tickers), period="2d",
                           auto_adjust=True, progress=False, group_by="ticker")
        out = {}
        for t in tickers:
            try:
                col = data["Close"] if len(tickers) == 1 else data[t]["Close"]
                out[t] = round(float(col.dropna().iloc[-1]), 2)
            except Exception:
                out[t] = None
        return out
    except Exception:
        return {}


def _calc_pl(strategy: str, premium: float, strike: float,
             entry_stock: float, close_price: float, qty: int) -> tuple[float, float]:
    """Return (pl_dollar, pl_pct) for a closed position."""
    multiplier = 100 * qty
    strat = strategy.upper()
    if strat == "CSP":
        if close_price < strike:          # assigned — stock put to you
            pl = (premium - (strike - close_price)) * multiplier
        else:                              # expired worthless — keep premium
            pl = premium * multiplier
        pl_pct = (pl / (strike * multiplier)) * 100 if strike > 0 else 0
    elif strat == "CC":
        if close_price > strike:          # called away — capped upside
            pl = (premium + strike - entry_stock) * multiplier
        else:                              # expired worthless — keep premium
            pl = premium * multiplier
        pl_pct = (pl / (entry_stock * multiplier)) * 100 if entry_stock > 0 else 0
    elif strat == "LEAPS":                # long call
        intrinsic = max(0.0, close_price - strike)
        pl = (intrinsic - premium) * multiplier
        pl_pct = (pl / (premium * multiplier)) * 100 if premium > 0 else 0
    else:                                  # stock
        pl = (close_price - entry_stock) * multiplier
        pl_pct = ((close_price - entry_stock) / entry_stock * 100) if entry_stock > 0 else 0
    return round(pl, 2), round(pl_pct, 2)


def _mark_to_market(strategy: str, premium: float, strike: float,
                    entry_stock: float, current: float, qty: int) -> tuple[float, float]:
    """Simplified intrinsic-value mark-to-market for open positions."""
    multiplier = 100 * qty
    strat = strategy.upper()
    if strat == "CSP":                    # short put
        intrinsic_risk = max(0.0, strike - current)
        pl = (premium - intrinsic_risk) * multiplier
        basis = strike * multiplier
    elif strat == "CC":                   # short call
        intrinsic_risk = max(0.0, current - strike)
        pl = (premium - intrinsic_risk) * multiplier
        basis = entry_stock * multiplier
    elif strat == "LEAPS":               # long call
        intrinsic = max(0.0, current - strike)
        pl = (intrinsic - premium) * multiplier
        basis = premium * multiplier
    else:                                 # stock / golden scan
        pl = (current - entry_stock) * multiplier
        basis = entry_stock * multiplier
    pl_pct = (pl / basis * 100) if basis > 0 else 0
    return round(pl, 2), round(pl_pct, 2)


def _auto_close_row(r: dict, row_i: int) -> dict:
    """Check if an Open position has expired; if so compute P/L and update sheet."""
    expiry_str = str(r.get("Expiry_Date", "")).strip()
    if not expiry_str:
        return r
    try:
        expiry = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
    except Exception:
        return r
    if expiry >= date.today():
        return r  # still active

    # Expired — fetch close price on expiry day
    ticker   = str(r.get("Ticker", "")).upper()
    strategy = str(r.get("Strategy", "")).upper()
    try:
        premium     = float(r.get("Premium", 0) or 0)
        strike      = float(r.get("Strike",  0) or 0)
        entry_stock = float(r.get("Entry_Stock_Price", 0) or 0)
        qty         = int(r.get("Qty", 1) or 1)
    except Exception:
        return r

    close_price = _hist_close(ticker, expiry_str)
    if close_price is None:
        return r

    pl, pl_pct = _calc_pl(strategy, premium, strike, entry_stock, close_price, qty)

    # Determine outcome label
    strat = strategy.upper()
    if strat == "CSP":
        status = "Assigned" if close_price < strike else "Expired"
    elif strat == "CC":
        status = "Called" if close_price > strike else "Expired"
    elif strat == "LEAPS":
        status = "Closed" if close_price > strike else "Expired"
    else:
        status = "Closed"

    fields = {
        "Status":            status,
        "Close_Date":        expiry_str,
        "Close_Stock_Price": str(round(close_price, 2)),
        "PL_Dollar":         str(pl),
        "PL_Pct":            str(pl_pct),
    }
    try:
        update_performance_row(row_i, fields)
    except Exception:
        pass

    r = dict(r)
    r.update(fields)
    return r


@st.cache_data(ttl=180, show_spinner=False)
def _load_and_process() -> pd.DataFrame:
    """Load Performance tab, auto-close expired, attach live prices for open."""
    raw = get_performance()
    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    # Normalise types
    for col in ["Premium","Strike","Entry_Stock_Price","PL_Dollar","PL_Pct","Ann_Return","Qty","DTE"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Qty"]        = df["Qty"].fillna(1).astype(int)
    df["Entry_Date"] = pd.to_datetime(df["Entry_Date"], errors="coerce")
    df["Close_Date"] = pd.to_datetime(df["Close_Date"], errors="coerce")
    df["Expiry_Date"]= pd.to_datetime(df["Expiry_Date"], errors="coerce")
    df["Month"]      = df["Entry_Date"].dt.to_period("M").astype(str)
    df["Entry_Day"]  = df["Entry_Date"].dt.date

    # ── Auto-close expired Open positions ───────────────────────
    rows_out = []
    for idx, (_, row) in enumerate(df.iterrows()):
        if str(row.get("Status", "")).strip().lower() == "open":
            updated = _auto_close_row(row.to_dict(), idx + 2)  # +2 for header + 1-indexing
            rows_out.append(updated)
        else:
            rows_out.append(row.to_dict())
    df = pd.DataFrame(rows_out)

    # Re-parse after auto-close
    for col in ["Premium","Strike","Entry_Stock_Price","PL_Dollar","PL_Pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Qty"] = pd.to_numeric(df.get("Qty", 1), errors="coerce").fillna(1).astype(int)

    # ── Live prices for remaining Open positions ─────────────────
    open_mask = df["Status"].str.strip().str.lower() == "open"
    open_tickers = tuple(df.loc[open_mask, "Ticker"].dropna().unique().tolist())
    prices = _current_prices(open_tickers) if open_tickers else {}

    def _fill_open_pnl(row):
        if str(row.get("Status","")).strip().lower() != "open":
            return row
        ticker = str(row.get("Ticker","")).upper()
        cp = prices.get(ticker)
        if cp is None:
            return row
        try:
            pl, pl_pct = _mark_to_market(
                str(row.get("Strategy","")),
                float(row.get("Premium", 0) or 0),
                float(row.get("Strike",  0) or 0),
                float(row.get("Entry_Stock_Price", 0) or 0),
                cp,
                int(row.get("Qty", 1) or 1),
            )
            row = dict(row)
            row["PL_Dollar"]        = pl
            row["PL_Pct"]           = pl_pct
            row["Current_Price"]    = cp
        except Exception:
            pass
        return row

    df = pd.DataFrame([_fill_open_pnl(r) for r in df.to_dict("records")])
    for col in ["PL_Dollar","PL_Pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Income = premium × 100 × qty for closed/expired, mark-to-market for open
    def _income(row):
        st_ = str(row.get("Status","")).lower()
        strat = str(row.get("Strategy","")).upper()
        if strat in _SELL_STRATS:
            p = float(row.get("Premium",0) or 0)
            q = int(row.get("Qty",1) or 1)
            if st_ in ("expired","closed","assigned","called"):
                return round(p * 100 * q, 2)
        return float(row.get("PL_Dollar", 0) or 0)

    df["Income"] = df.apply(_income, axis=1)

    df["Ticker"]   = df["Ticker"].astype(str).str.upper().str.strip()
    df["Strategy"] = df["Strategy"].astype(str).str.strip()
    df["Status"]   = df["Status"].astype(str).str.strip()
    if "Entry_Day" not in df.columns:
        df["Entry_Day"] = pd.to_datetime(df["Entry_Date"], errors="coerce").dt.date
    if "Month" not in df.columns:
        df["Month"] = pd.to_datetime(df["Entry_Date"], errors="coerce").dt.to_period("M").astype(str)

    return df


# ══════════════════════════════════════════════════════════════════
# 2. UI HELPERS
# ══════════════════════════════════════════════════════════════════

def _kpi(label: str, value: str, sub: str = "", color: str = None, delta: str = ""):
    color = color or GOLD
    sub_html   = f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:3px">{sub}</div>'   if sub   else ""
    delta_html = (f'<div style="color:{ACCENT_GREEN if not delta.startswith("-") else ACCENT_RED};'
                  f'font-size:11px;margin-top:2px">▲ {delta}</div>') if delta else ""
    st.markdown(f"""
    <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};
                border-top:3px solid {color};border-radius:8px;padding:14px 16px">
      <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;
                  letter-spacing:1.2px;margin-bottom:6px">{label}</div>
      <div style="color:{color};font-family:'Cormorant Garamond',serif;
                  font-size:26px;font-weight:800;line-height:1.1">{value}</div>
      {sub_html}{delta_html}
    </div>""", unsafe_allow_html=True)


def _section_label(text: str, color: str = None):
    color = color or GOLD
    st.markdown(
        f'<div style="color:{color};font-size:12px;font-weight:700;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin:18px 0 8px;border-left:3px solid {color};'
        f'padding-left:10px">{text}</div>',
        unsafe_allow_html=True,
    )


def _status_badge(status: str) -> str:
    color = _STATUS_COLORS.get(status, TEXT_MUTED)
    return (f'<span style="background:{color}22;color:{color};font-size:10px;'
            f'padding:2px 8px;border-radius:10px;font-weight:700;border:1px solid {color}55">'
            f'{status}</span>')


def _pl_html(val) -> str:
    try:
        v = float(val)
        color = ACCENT_GREEN if v >= 0 else ACCENT_RED
        sign  = "+" if v >= 0 else ""
        return f'<span style="color:{color};font-family:\'DM Mono\',monospace;font-weight:700">{sign}${v:,.2f}</span>'
    except Exception:
        return '<span style="color:#555">—</span>'


def _positions_table(df: pd.DataFrame, cols: list, show_pl: bool = True):
    """Render an HTML positions table from a DataFrame."""
    if df.empty:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;'
            f'padding:16px;text-align:center;border:1px dashed {BORDER_COLOR};'
            f'border-radius:6px">No positions in this period.</div>',
            unsafe_allow_html=True,
        )
        return

    th_style = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:0.8px;'
                f'text-transform:uppercase;padding:8px 10px;border-bottom:1px solid {BORDER_COLOR};'
                f'white-space:nowrap;background:{BG_PANEL}')
    header_html = "".join(f'<th style="{th_style}">{c}</th>' for c in cols)

    rows_html = []
    for i, (_, r) in enumerate(df.iterrows()):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        cells = []
        for c in cols:
            val = r.get(c, "—")
            style = f'padding:7px 10px;font-size:11px;background:{bg}'

            if c == "Ticker":
                cells.append(f'<td style="{style};color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700;font-size:12px">{val}</td>')
            elif c in ("P/L $", "PL_Dollar", "Income"):
                cells.append(f'<td style="{style}">{_pl_html(val)}</td>')
            elif c in ("P/L %", "PL_Pct"):
                try:
                    v = float(val)
                    color = ACCENT_GREEN if v >= 0 else ACCENT_RED
                    cells.append(f'<td style="{style};color:{color};font-family:\'DM Mono\',monospace;font-weight:600">{v:+.1f}%</td>')
                except Exception:
                    cells.append(f'<td style="{style};color:{TEXT_MUTED}">—</td>')
            elif c == "Status":
                cells.append(f'<td style="{style}">{_status_badge(str(val))}</td>')
            elif c == "Strategy":
                strat_colors = {"CSP": "#86EFAC","CC": GOLD,"LEAPS": "#60A5FA","Golden Scan": "#A78BFA"}
                sc = strat_colors.get(str(val), TEXT_MUTED)
                cells.append(f'<td style="{style};color:{sc};font-weight:600">{val}</td>')
            elif c == "Premium":
                try:
                    cells.append(f'<td style="{style};color:{ACCENT_GREEN};font-family:\'DM Mono\',monospace">${float(val):.2f}</td>')
                except Exception:
                    cells.append(f'<td style="{style};color:{TEXT_MUTED}">—</td>')
            else:
                cells.append(f'<td style="{style};color:{TEXT_PRIMARY}">{val if val is not None and str(val) != "nan" else "—"}</td>')
        rows_html.append(f'<tr>{"".join(cells)}</tr>')

    st.markdown(f"""
    <div style="border:1px solid {BORDER_COLOR};border-radius:8px;overflow:hidden;overflow-x:auto;margin-bottom:8px">
      <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{"".join(rows_html)}</tbody>
      </table>
    </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# 3. CHART BUILDERS
# ══════════════════════════════════════════════════════════════════

def _chart_monthly_income(df: pd.DataFrame) -> go.Figure:
    closed = df[df["Status"].str.lower().isin(["expired","closed","assigned","called"])]
    if closed.empty:
        return None
    monthly = (closed.groupby("Month")["Income"]
                     .sum()
                     .reset_index()
                     .sort_values("Month"))
    colors = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in monthly["Income"]]
    fig = go.Figure(go.Bar(
        x=monthly["Month"], y=monthly["Income"],
        marker_color=colors,
        text=[f"${v:,.0f}" for v in monthly["Income"]],
        textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=11, family="DM Mono"),
        hovertemplate="<b>%{x}</b><br>Income: $%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Monthly Income (Realized)",
                   font=dict(color=GOLD, size=13, family="Cormorant Garamond"),
                   x=0.01, y=0.95),
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        height=280, margin=dict(l=8, r=8, t=40, b=8),
        xaxis=dict(showgrid=False, color=TEXT_MUTED, tickfont=dict(size=10)),
        yaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED,
                   tickprefix="$", tickfont=dict(size=10, family="DM Mono")),
        showlegend=False,
    )
    return fig


def _chart_strategy_mix(df: pd.DataFrame) -> go.Figure:
    mix = df.groupby("Strategy").size().reset_index(name="Count")
    colors = [{"CSP": GOLD, "CC": ACCENT_GREEN, "LEAPS": "#60A5FA",
               "Golden Scan": "#A78BFA"}.get(s, TEXT_MUTED) for s in mix["Strategy"]]
    fig = go.Figure(go.Pie(
        labels=mix["Strategy"], values=mix["Count"],
        hole=0.55,
        marker=dict(colors=colors, line=dict(color=BG_DARK, width=2)),
        textfont=dict(color=TEXT_PRIMARY, size=11),
        hovertemplate="<b>%{label}</b><br>%{value} trades (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Strategy Mix (YTD)",
                   font=dict(color=GOLD, size=13, family="Cormorant Garamond"),
                   x=0.01, y=0.97),
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        height=280, margin=dict(l=8, r=8, t=40, b=8),
        legend=dict(font=dict(color=TEXT_MUTED, size=10), bgcolor=BG_CARD,
                    orientation="h", y=-0.1),
        showlegend=True,
    )
    return fig


def _chart_top_tickers(df: pd.DataFrame, n: int = 6) -> go.Figure:
    by_tkr = (df.groupby("Ticker")["Income"]
                .sum()
                .reset_index()
                .sort_values("Income", ascending=False)
                .head(n))
    if by_tkr.empty:
        return None
    colors = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in by_tkr["Income"]]
    fig = go.Figure(go.Bar(
        x=by_tkr["Income"], y=by_tkr["Ticker"],
        orientation="h",
        marker_color=colors,
        text=[f"${v:+,.0f}" for v in by_tkr["Income"]],
        textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=11, family="DM Mono"),
        hovertemplate="<b>%{y}</b><br>Income: $%{x:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Top Income Tickers (YTD)",
                   font=dict(color=GOLD, size=13, family="Cormorant Garamond"),
                   x=0.01, y=0.97),
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        height=max(220, 36 * n + 60),
        margin=dict(l=8, r=80, t=40, b=8),
        xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED,
                   tickprefix="$", tickfont=dict(size=10, family="DM Mono")),
        yaxis=dict(showgrid=False, color=GOLD, autorange="reversed",
                   tickfont=dict(size=11, family="DM Mono", color=GOLD)),
        showlegend=False,
    )
    return fig


def _chart_trade_outcomes(df: pd.DataFrame) -> go.Figure:
    outcomes = df["Status"].value_counts().reset_index()
    outcomes.columns = ["Status", "Count"]
    colors = [_STATUS_COLORS.get(s, TEXT_MUTED) for s in outcomes["Status"]]
    fig = go.Figure(go.Pie(
        labels=outcomes["Status"], values=outcomes["Count"],
        hole=0.55,
        marker=dict(colors=colors, line=dict(color=BG_DARK, width=2)),
        textfont=dict(color=TEXT_PRIMARY, size=11),
        hovertemplate="<b>%{label}</b><br>%{value} trades (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Trade Outcomes (YTD)",
                   font=dict(color=GOLD, size=13, family="Cormorant Garamond"),
                   x=0.01, y=0.97),
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        height=280, margin=dict(l=8, r=8, t=40, b=8),
        legend=dict(font=dict(color=TEXT_MUTED, size=10), bgcolor=BG_CARD,
                    orientation="h", y=-0.1),
        showlegend=True,
    )
    return fig


def _chart_win_rate_by_strategy(df: pd.DataFrame) -> go.Figure:
    """Horizontal bar chart: win rate per strategy."""
    df2 = df.copy()
    df2["Win"] = df2["PL_Dollar"].fillna(0) > 0
    grp = (df2.groupby("Strategy")
              .agg(N=("Ticker","count"), Wins=("Win","sum"))
              .reset_index())
    grp["Rate"] = (grp["Wins"] / grp["N"] * 100).round(1)
    grp = grp.sort_values("Rate", ascending=False)
    colors = [ACCENT_GREEN if r >= 60 else (GOLD if r >= 40 else ACCENT_RED)
              for r in grp["Rate"]]
    fig = go.Figure(go.Bar(
        x=grp["Rate"], y=grp["Strategy"],
        orientation="h",
        marker_color=colors,
        text=[f"{r:.0f}%  ({w}/{n})" for r,w,n in zip(grp["Rate"],grp["Wins"],grp["N"])],
        textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=11, family="Inter"),
    ))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        height=max(180, 40 * len(grp) + 40),
        margin=dict(l=8, r=80, t=10, b=12),
        xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED,
                   range=[0, 115], ticksuffix="%"),
        yaxis=dict(showgrid=False, color=GOLD, autorange="reversed",
                   tickfont=dict(size=12, family="DM Mono", color=GOLD)),
        showlegend=False,
    )
    return fig


def _chart_cumulative_pnl(df: pd.DataFrame) -> go.Figure:
    """Cumulative income/P&L over time (line chart)."""
    closed = df[df["Status"].str.lower().isin(["expired","closed","assigned","called"])].copy()
    if closed.empty:
        return None
    closed = closed.sort_values("Entry_Date")
    closed["Cumulative"] = closed["Income"].cumsum()
    fig = go.Figure(go.Scatter(
        x=closed["Entry_Date"], y=closed["Cumulative"],
        mode="lines+markers",
        line=dict(color=GOLD, width=2),
        marker=dict(color=GOLD, size=5),
        fill="tozeroy", fillcolor=f"{GOLD}18",
        hovertemplate="<b>%{x|%b %d}</b><br>Cumulative: $%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        height=240, margin=dict(l=8, r=8, t=16, b=8),
        xaxis=dict(showgrid=False, color=TEXT_MUTED, tickfont=dict(size=10)),
        yaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED,
                   tickprefix="$", tickfont=dict(size=10, family="DM Mono")),
        showlegend=False,
    )
    return fig


# ══════════════════════════════════════════════════════════════════
# 4. SECTION RENDERERS (shared between tabs)
# ══════════════════════════════════════════════════════════════════

def _render_top_cards(df: pd.DataFrame, today: date):
    """Closed today | Open positions | New today — mirror Reddit image."""
    closed_today = df[df["Close_Date"].dt.date == today] if "Close_Date" in df.columns else pd.DataFrame()
    open_pos     = df[df["Status"].str.lower() == "open"]
    new_today    = df[df["Entry_Day"] == today]

    c1, c2, c3 = st.columns(3)

    # ── Closed Today ────────────────────────────────────────────
    with c1:
        total_pl = closed_today["PL_Dollar"].sum() if not closed_today.empty else 0
        color = ACCENT_GREEN if total_pl >= 0 else ACCENT_RED
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};
                    border-top:3px solid {ACCENT_GREEN};border-radius:8px;padding:14px">
          <div style="color:{ACCENT_GREEN};font-size:12px;font-weight:700;
                      text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
            ✅ Closed Positions</div>""", unsafe_allow_html=True)
        if closed_today.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;padding:8px 0">None closed today</div>', unsafe_allow_html=True)
        else:
            for _, r in closed_today.head(4).iterrows():
                pl_ = r.get("PL_Dollar", 0)
                try:
                    pl_str = f'+${float(pl_):,.2f}' if float(pl_) >= 0 else f'-${abs(float(pl_)):,.2f}'
                    pl_col = ACCENT_GREEN if float(pl_) >= 0 else ACCENT_RED
                except Exception:
                    pl_str, pl_col = "—", TEXT_MUTED
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'padding:4px 0;border-bottom:1px solid {BORDER_COLOR}22">'
                    f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-size:11px;font-weight:700">{r["Ticker"]}</span>'
                    f'<span style="color:{TEXT_MUTED};font-size:10px">{r.get("Strategy","")}</span>'
                    f'<span style="color:{pl_col};font-family:\'DM Mono\',monospace;font-size:11px;font-weight:700">{pl_str}</span>'
                    f'</div>', unsafe_allow_html=True,
                )
        st.markdown(
            f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid {BORDER_COLOR}">'
            f'<span style="color:{TEXT_MUTED};font-size:10px">TOTAL P/L  </span>'
            f'<span style="color:{color};font-family:\'DM Mono\',monospace;font-weight:800;font-size:16px">'
            f'{"+" if total_pl >= 0 else ""}${total_pl:,.2f}</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    # ── Open Positions ───────────────────────────────────────────
    with c2:
        open_premium = open_pos["Premium"].fillna(0) * open_pos["Qty"].fillna(1) * 100
        total_credit = open_premium.sum()
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};
                    border-top:3px solid #60A5FA;border-radius:8px;padding:14px">
          <div style="color:#60A5FA;font-size:12px;font-weight:700;
                      text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
            ⏳ Open Positions ({len(open_pos)})</div>""", unsafe_allow_html=True)
        if open_pos.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;padding:8px 0">No open positions</div>', unsafe_allow_html=True)
        else:
            for _, r in open_pos.head(4).iterrows():
                exp = str(r.get("Expiry_Date",""))[:10] if pd.notna(r.get("Expiry_Date")) else "—"
                prem_str = f'${float(r.get("Premium",0) or 0):.2f}'
                pl_open = r.get("PL_Dollar")
                try:
                    pl_col = ACCENT_GREEN if float(pl_open) >= 0 else ACCENT_RED
                    pl_str = f'{float(pl_open):+.2f}'
                except Exception:
                    pl_col, pl_str = TEXT_MUTED, "—"
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;gap:6px;'
                    f'padding:4px 0;border-bottom:1px solid {BORDER_COLOR}22">'
                    f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-size:11px;font-weight:700;min-width:45px">{r["Ticker"]}</span>'
                    f'<span style="color:{TEXT_MUTED};font-size:10px">{r.get("Strategy","")} {exp}</span>'
                    f'<span style="color:{pl_col};font-family:\'DM Mono\',monospace;font-size:10px">${pl_str}</span>'
                    f'</div>', unsafe_allow_html=True,
                )
        st.markdown(
            f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid {BORDER_COLOR}">'
            f'<span style="color:{TEXT_MUTED};font-size:10px">TOTAL OPEN PREMIUM  </span>'
            f'<span style="color:#60A5FA;font-family:\'DM Mono\',monospace;font-weight:800;font-size:16px">${total_credit:,.2f}</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    # ── New Today ────────────────────────────────────────────────
    with c3:
        new_credit = (new_today["Premium"].fillna(0) * new_today["Qty"].fillna(1) * 100).sum()
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};
                    border-top:3px solid {GOLD};border-radius:8px;padding:14px">
          <div style="color:{GOLD};font-size:12px;font-weight:700;
                      text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
            🆕 New Positions ({len(new_today)})</div>""", unsafe_allow_html=True)
        if new_today.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;padding:8px 0">No new positions today</div>', unsafe_allow_html=True)
        else:
            for _, r in new_today.head(4).iterrows():
                exp = str(r.get("Expiry_Date",""))[:10] if pd.notna(r.get("Expiry_Date")) else "—"
                prem_str = f'${float(r.get("Premium",0) or 0):.2f}'
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'padding:4px 0;border-bottom:1px solid {BORDER_COLOR}22">'
                    f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-size:11px;font-weight:700">{r["Ticker"]}</span>'
                    f'<span style="color:{TEXT_MUTED};font-size:10px">{r.get("Strategy","")} {exp}</span>'
                    f'<span style="color:{ACCENT_GREEN};font-family:\'DM Mono\',monospace;font-size:11px">{prem_str}</span>'
                    f'</div>', unsafe_allow_html=True,
                )
        st.markdown(
            f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid {BORDER_COLOR}">'
            f'<span style="color:{TEXT_MUTED};font-size:10px">NEW PREMIUM COLLECTED  </span>'
            f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:800;font-size:16px">${new_credit:,.2f}</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── Summary band ────────────────────────────────────────────
    realized = df.loc[df["Status"].str.lower().isin(["expired","closed","assigned","called"]), "Income"].sum()
    open_pnl = df.loc[df["Status"].str.lower() == "open", "PL_Dollar"].fillna(0).sum()
    r_color  = ACCENT_GREEN if realized >= 0 else ACCENT_RED
    o_color  = ACCENT_GREEN if open_pnl >= 0 else ACCENT_RED
    st.markdown(f"""
    <div style="display:flex;gap:16px;background:{BG_PANEL};border:1px solid {BORDER_COLOR};
                border-radius:8px;padding:12px 20px;margin-bottom:4px">
      <div>
        <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:1px">Premium Realized</div>
        <div style="color:{r_color};font-family:'Cormorant Garamond',serif;font-size:28px;font-weight:800">
          {"+" if realized >= 0 else ""}${realized:,.2f}</div>
        <div style="color:{TEXT_MUTED};font-size:11px">Closed + Expired</div>
      </div>
      <div style="width:1px;background:{BORDER_COLOR};margin:0 8px"></div>
      <div>
        <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:1px">Open Unrealized P&L</div>
        <div style="color:{o_color};font-family:'Cormorant Garamond',serif;font-size:28px;font-weight:800">
          {"+" if open_pnl >= 0 else ""}${open_pnl:,.2f}</div>
        <div style="color:{TEXT_MUTED};font-size:11px">Mark-to-market</div>
      </div>
    </div>""", unsafe_allow_html=True)


def _render_progress_strip(df: pd.DataFrame):
    """Wheel Strategy Progress — big KPI row."""
    closed  = df[df["Status"].str.lower().isin(["expired","closed","assigned","called"])]
    all_pl  = df["PL_Dollar"].fillna(0)
    income_ytd = closed["Income"].sum()
    total_trades = len(df)
    wins    = (all_pl > 0).sum()
    win_rate= wins / total_trades * 100 if total_trades else 0

    # Avg ROI across closed trades
    closed_pl = closed["PL_Pct"].dropna()
    avg_roi = closed_pl.mean() if not closed_pl.empty else 0

    # Avg premium per day (income / days since first trade)
    if not df["Entry_Date"].dropna().empty:
        first = df["Entry_Date"].dropna().min().date()
        days_active = max(1, (date.today() - first).days)
        avg_prem_day = income_ytd / days_active
    else:
        avg_prem_day = 0

    _section_label("🎯 Wheel Strategy Progress", GOLD)
    c1, c2, c3, c4, c5 = st.columns(5)
    income_color = ACCENT_GREEN if income_ytd >= 0 else ACCENT_RED
    with c1: _kpi("Income YTD",       f"${income_ytd:,.2f}", color=income_color)
    with c2: _kpi("Total Trades",     str(total_trades), color=GOLD)
    with c3: _kpi("Win Rate",         f"{win_rate:.1f}%",
                  sub=f"{wins} of {total_trades} wins",
                  color=ACCENT_GREEN if win_rate >= 60 else (GOLD if win_rate >= 40 else ACCENT_RED))
    with c4: _kpi("Avg ROI / Trade",  f"{avg_roi:+.2f}%", color=ACCENT_BLUE)
    with c5: _kpi("Avg Premium / Day",f"${avg_prem_day:,.2f}", color=GOLD)


def _render_ticker_snapshot(df: pd.DataFrame):
    """Reddit-style ticker performance snapshot table."""
    _section_label("📋 Ticker Performance Snapshot", GOLD)
    by_tkr = (df.groupby("Ticker")
                .agg(
                    Total_Income =("Income", "sum"),
                    Trades       =("Ticker", "count"),
                    Avg_ROI      =("PL_Pct",  "mean"),
                    Wins         =("PL_Dollar", lambda x: (pd.to_numeric(x, errors="coerce").fillna(0) > 0).sum()),
                )
                .reset_index()
                .sort_values("Total_Income", ascending=False))
    if by_tkr.empty:
        return

    # Avg Premium per Day = total income / active days
    def _ppd(tkr):
        sub = df[df["Ticker"] == tkr]
        if sub.empty or sub["Entry_Date"].dropna().empty:
            return 0
        days = max(1, (date.today() - sub["Entry_Date"].dropna().min().date()).days)
        return sub["Income"].sum() / days

    by_tkr["Prem_Per_Day"] = by_tkr["Ticker"].apply(_ppd)
    by_tkr["Win_Rate"]     = (by_tkr["Wins"] / by_tkr["Trades"] * 100).round(1)

    th_style = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:0.8px;'
                f'text-transform:uppercase;padding:8px 12px;border-bottom:2px solid {GOLD}55;'
                f'background:{BG_PANEL}')
    headers = ["TICKER","TOTAL INCOME","TRADES","WIN RATE","AVG ROI","PREM/DAY"]
    header_html = "".join(f'<th style="{th_style}">{h}</th>' for h in headers)
    rows_html = []
    for i, (_, r) in enumerate(by_tkr.iterrows()):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        inc = r["Total_Income"]
        roi = r["Avg_ROI"]
        wr  = r["Win_Rate"]
        ppd = r["Prem_Per_Day"]
        inc_color = ACCENT_GREEN if inc >= 0 else ACCENT_RED
        roi_color = ACCENT_GREEN if (roi or 0) >= 0 else ACCENT_RED
        wr_color  = ACCENT_GREEN if wr >= 60 else (GOLD if wr >= 40 else ACCENT_RED)
        rows_html.append(f"""
        <tr>
          <td style="padding:8px 12px;background:{bg};color:{GOLD};font-family:'DM Mono',monospace;font-weight:800;font-size:13px">{r['Ticker']}</td>
          <td style="padding:8px 12px;background:{bg};color:{inc_color};font-family:'DM Mono',monospace;font-weight:700">{"+" if inc>=0 else ""}${inc:,.2f}</td>
          <td style="padding:8px 12px;background:{bg};color:{TEXT_PRIMARY};text-align:center">{int(r['Trades'])}</td>
          <td style="padding:8px 12px;background:{bg};color:{wr_color};font-weight:700">{wr:.0f}%</td>
          <td style="padding:8px 12px;background:{bg};color:{roi_color};font-family:'DM Mono',monospace">{(roi or 0):+.2f}%</td>
          <td style="padding:8px 12px;background:{bg};color:{ACCENT_BLUE};font-family:'DM Mono',monospace">${ppd:,.2f}</td>
        </tr>""")

    total_income = by_tkr["Total_Income"].sum()
    total_trades = by_tkr["Trades"].sum()
    overall_roi  = by_tkr["Avg_ROI"].mean()
    t_color = ACCENT_GREEN if total_income >= 0 else ACCENT_RED
    footer = f"""
    <tr style="border-top:2px solid {GOLD}55">
      <td style="padding:8px 12px;background:{BG_PANEL};color:{GOLD};font-weight:800;font-family:'DM Mono',monospace">TOTAL</td>
      <td style="padding:8px 12px;background:{BG_PANEL};color:{t_color};font-weight:800;font-family:'DM Mono',monospace">${total_income:,.2f}</td>
      <td style="padding:8px 12px;background:{BG_PANEL};color:{TEXT_PRIMARY};text-align:center;font-weight:700">{int(total_trades)}</td>
      <td style="padding:8px 12px;background:{BG_PANEL}">—</td>
      <td style="padding:8px 12px;background:{BG_PANEL};color:{ACCENT_BLUE};font-family:'DM Mono',monospace">{(overall_roi or 0):+.2f}%</td>
      <td style="padding:8px 12px;background:{BG_PANEL}">—</td>
    </tr>"""

    st.markdown(f"""
    <div style="border:1px solid {BORDER_COLOR};border-radius:8px;overflow:hidden;overflow-x:auto;margin:8px 0 20px">
      <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{"".join(rows_html)}{footer}</tbody>
      </table>
    </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# 5. TAB RENDERERS
# ══════════════════════════════════════════════════════════════════

def _render_daily_tab(df: pd.DataFrame):
    today = date.today()
    label = f"Trading Day · {today.strftime('%A %b %d, %Y')}"
    st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;letter-spacing:1.5px;text-transform:uppercase;margin:8px 0 14px">{label}</div>', unsafe_allow_html=True)

    _render_top_cards(df, today)

    # Sections: Stocks | CSP | CC | LEAPS
    for strat, label_text, color in [
        ("Golden Scan", "📊 Stocks / Golden Scan", ACCENT_GREEN),
        ("CSP",         "💰 Cash-Secured Puts",     GOLD),
        ("CC",          "📦 Covered Calls",         "#A78BFA"),
        ("LEAPS",       "🧨 LEAPS",                "#60A5FA"),
    ]:
        sub = df[df["Strategy"] == strat].copy()
        if sub.empty:
            continue
        _section_label(f"{label_text} — {len(sub)} position(s)", color)
        today_sub = sub[sub["Entry_Day"] == today]
        closed_sub = sub[sub["Status"].str.lower().isin(["expired","closed","assigned","called"])]
        cols_show = ["Ticker","Strike","Premium","DTE","Expiry_Date","Entry_Stock_Price","Status","PL_Dollar","PL_Pct"]
        cols_show = [c for c in cols_show if c in sub.columns]
        _positions_table(sub.sort_values("PL_Dollar", ascending=False, na_position="last"), cols_show)


def _render_monthly_tab(df: pd.DataFrame):
    _section_label("📆 Monthly Income & Performance", GOLD)

    # Month selector
    months = sorted(df["Month"].dropna().unique(), reverse=True)
    if not months:
        st.info("No data yet.")
        return
    month_labels = [m for m in months]
    selected = st.selectbox("Select Month", month_labels, index=0, key="perf_month_sel")
    month_df = df[df["Month"] == selected].copy()

    # Metrics for selected month
    closed_m  = month_df[month_df["Status"].str.lower().isin(["expired","closed","assigned","called"])]
    income_m  = closed_m["Income"].sum()
    trades_m  = len(month_df)
    wins_m    = (month_df["PL_Dollar"].fillna(0) > 0).sum()
    wr_m      = wins_m / trades_m * 100 if trades_m else 0
    open_m    = month_df[month_df["Status"].str.lower() == "open"]

    c1, c2, c3, c4 = st.columns(4)
    with c1: _kpi("Income",        f"${income_m:,.2f}",
                  color=ACCENT_GREEN if income_m >= 0 else ACCENT_RED)
    with c2: _kpi("Trades",        str(trades_m), color=GOLD)
    with c3: _kpi("Win Rate",      f"{wr_m:.0f}%",
                  sub=f"{wins_m}/{trades_m}",
                  color=ACCENT_GREEN if wr_m >= 60 else (GOLD if wr_m >= 40 else ACCENT_RED))
    with c4: _kpi("Open Positions",str(len(open_m)), color=ACCENT_BLUE)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # Charts side by side
    fig_m = _chart_monthly_income(df)
    fig_o = _chart_trade_outcomes(month_df)
    col_a, col_b = st.columns([3, 2])
    with col_a:
        if fig_m:
            st.plotly_chart(fig_m, use_container_width=True, config={"displayModeBar": False})
    with col_b:
        if fig_o:
            st.plotly_chart(fig_o, use_container_width=True, config={"displayModeBar": False})

    # Positions table for the month
    _section_label(f"All Positions — {selected}", GOLD)
    cols_show = ["Ticker","Strategy","Universe","Strike","Premium","DTE","Expiry_Date","Entry_Stock_Price","Status","PL_Dollar","PL_Pct","Source"]
    cols_show = [c for c in cols_show if c in month_df.columns]
    df_sorted = month_df.sort_values("Entry_Date", ascending=False)
    df_sorted["Expiry_Date"] = df_sorted["Expiry_Date"].dt.strftime("%Y-%m-%d") if hasattr(df_sorted["Expiry_Date"], "dt") else df_sorted["Expiry_Date"]
    _positions_table(df_sorted, cols_show)

    # Top gainers / losers for month
    col_g, col_l = st.columns(2)
    by_tkr_m = (month_df.groupby("Ticker")["Income"].sum()
                         .reset_index()
                         .sort_values("Income", ascending=False))
    with col_g:
        _section_label("🏆 Top Gainers", ACCENT_GREEN)
        top5 = by_tkr_m.head(5)
        fig = go.Figure(go.Bar(
            x=top5["Income"], y=top5["Ticker"], orientation="h",
            marker_color=ACCENT_GREEN,
            text=[f"${v:+,.0f}" for v in top5["Income"]],
            textposition="outside",
            textfont=dict(color=TEXT_PRIMARY, size=11),
        ))
        fig.update_layout(
            paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
            height=max(150, 32*len(top5)+40),
            margin=dict(l=8, r=70, t=10, b=8),
            xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED, tickprefix="$"),
            yaxis=dict(showgrid=False, color=GOLD, autorange="reversed"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with col_l:
        _section_label("📉 Top Losers", ACCENT_RED)
        bot5 = by_tkr_m.tail(5).sort_values("Income")
        fig = go.Figure(go.Bar(
            x=bot5["Income"], y=bot5["Ticker"], orientation="h",
            marker_color=ACCENT_RED,
            text=[f"${v:+,.0f}" for v in bot5["Income"]],
            textposition="outside",
            textfont=dict(color=TEXT_PRIMARY, size=11),
        ))
        fig.update_layout(
            paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
            height=max(150, 32*len(bot5)+40),
            margin=dict(l=8, r=70, t=10, b=8),
            xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED, tickprefix="$"),
            yaxis=dict(showgrid=False, color=GOLD, autorange="reversed"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_analytics_tab(df: pd.DataFrame):
    _section_label("📊 Analytics — What Worked & What Didn't", GOLD)

    # ── Cumulative P&L curve ─────────────────────────────────────
    fig_cum = _chart_cumulative_pnl(df)
    if fig_cum:
        st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:4px">Cumulative Realized Income Over Time</div>', unsafe_allow_html=True)
        st.plotly_chart(fig_cum, use_container_width=True, config={"displayModeBar": False})

    # ── Win rate by strategy + Strategy mix ─────────────────────
    col_wr, col_mix = st.columns([3, 2])
    with col_wr:
        _section_label("Win Rate by Strategy", ACCENT_GREEN)
        fig_wr = _chart_win_rate_by_strategy(df)
        st.plotly_chart(fig_wr, use_container_width=True, config={"displayModeBar": False})
    with col_mix:
        _section_label("Strategy Mix", GOLD)
        fig_mix = _chart_strategy_mix(df)
        if fig_mix:
            st.plotly_chart(fig_mix, use_container_width=True, config={"displayModeBar": False})

    # ── Top income tickers + Trade outcomes ─────────────────────
    col_top, col_out = st.columns([3, 2])
    with col_top:
        _section_label("Top Income Tickers", GOLD)
        fig_top = _chart_top_tickers(df)
        if fig_top:
            st.plotly_chart(fig_top, use_container_width=True, config={"displayModeBar": False})
    with col_out:
        _section_label("Trade Outcomes", ACCENT_BLUE)
        fig_out = _chart_trade_outcomes(df)
        if fig_out:
            st.plotly_chart(fig_out, use_container_width=True, config={"displayModeBar": False})

    # ── What Worked / What Didn't ────────────────────────────────
    df2 = df.copy()
    df2["Win"] = df2["PL_Dollar"].fillna(0) > 0
    grp = (df2.groupby(["Strategy","Universe"])
              .agg(N=("Ticker","count"), Wins=("Win","sum"),
                   AvgPct=("PL_Pct","mean"), TotalInc=("Income","sum"))
              .reset_index())
    grp["Rate"] = (grp["Wins"] / grp["N"] * 100).round(1)
    worked = grp[(grp["N"] >= 2) & (grp["Rate"] >= 55)].sort_values("Rate", ascending=False)
    didnt  = grp[(grp["N"] >= 2) & (grp["Rate"] <  45)].sort_values("Rate")

    def _insight_list(rows, title, color, empty_msg):
        _section_label(title, color)
        if rows.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;font-style:italic;background:{BG_PANEL};border:1px dashed {BORDER_COLOR};border-radius:6px;padding:14px;text-align:center">{empty_msg}</div>', unsafe_allow_html=True)
            return
        for _, r in rows.head(6).iterrows():
            avg = r["AvgPct"] or 0
            inc = r["TotalInc"]
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;align-items:center;
                        padding:10px 14px;background:{BG_CARD};border:1px solid {BORDER_COLOR};
                        border-left:3px solid {color};border-radius:4px;margin-bottom:4px">
              <div>
                <div style="color:{TEXT_PRIMARY};font-size:13px;font-weight:600">{r['Strategy']} — {r['Universe']}</div>
                <div style="color:{TEXT_MUTED};font-size:10px">{int(r['N'])} trades · avg {avg:+.1f}% · income ${inc:,.0f}</div>
              </div>
              <div style="text-align:right">
                <div style="color:{color};font-family:'Cormorant Garamond',serif;font-weight:800;font-size:20px">{r['Rate']:.0f}%</div>
                <div style="color:{TEXT_MUTED};font-size:10px">win rate</div>
              </div>
            </div>""", unsafe_allow_html=True)

    col_w, col_d = st.columns(2)
    with col_w:
        _insight_list(worked, "✅ What Worked", ACCENT_GREEN,
                      "Need ≥ 2 positions per group at 55%+ win rate.")
    with col_d:
        _insight_list(didnt,  "❌ What Didn't Work", ACCENT_RED,
                      "Nothing below 45% win rate yet — keep trading!")

    # ── Parameter Optimization Suggestions ──────────────────────
    _section_label("💡 Parameter Optimization Suggestions", ACCENT_BLUE)
    suggestions = []

    csp = df[df["Strategy"] == "CSP"].copy()
    if not csp.empty and "PL_Dollar" in csp.columns:
        csp["Win"] = csp["PL_Dollar"].fillna(0) > 0
        csp_wr = csp["Win"].mean() * 100
        if csp_wr < 50:
            suggestions.append(("CSP", f"Win rate {csp_wr:.0f}% — consider lowering delta (0.15–0.20) for higher probability OTM strikes.", ACCENT_RED))
        elif csp_wr > 75:
            suggestions.append(("CSP", f"Win rate {csp_wr:.0f}% — consider slightly higher delta (0.25–0.30) for more premium income.", ACCENT_GREEN))

    cc = df[df["Strategy"] == "CC"].copy()
    if not cc.empty and "PL_Dollar" in cc.columns:
        cc["Win"] = cc["PL_Dollar"].fillna(0) > 0
        cc_wr = cc["Win"].mean() * 100
        if cc_wr < 50:
            suggestions.append(("CC", f"Win rate {cc_wr:.0f}% — stocks trending strongly upward. Lower delta or avoid CC in bull markets.", ACCENT_RED))

    leaps = df[df["Strategy"] == "LEAPS"].copy()
    if not leaps.empty and "PL_Dollar" in leaps.columns:
        leaps["Win"] = leaps["PL_Dollar"].fillna(0) > 0
        leaps_wr = leaps["Win"].mean() * 100
        if leaps_wr < 40:
            suggestions.append(("LEAPS", f"Win rate {leaps_wr:.0f}% — check if IV rank < 30 at entry. High IV at LEAPS entry = expensive premiums.", ACCENT_RED))

    # Sector analysis
    if not df.empty:
        sector_map = {
            "XLK":"Tech","XLF":"Finance","XLE":"Energy","XLV":"Health",
            "XLI":"Industrial","XLU":"Utilities","XLP":"Consumer","XLY":"Discretionary",
            "GLD":"Gold","SLV":"Silver","TLT":"Bonds","QQQ":"Tech","SPY":"Broad Market",
        }
        df_sec = df.copy()
        df_sec["Sector"] = df_sec["Ticker"].map(sector_map).fillna("Individual Stocks")
        sec_grp = (df_sec.groupby("Sector")
                         .agg(N=("Ticker","count"), Inc=("Income","sum"))
                         .reset_index()
                         .sort_values("Inc", ascending=False))
        if not sec_grp.empty:
            best_sec  = sec_grp.iloc[0]
            worst_sec = sec_grp.iloc[-1] if len(sec_grp) > 1 else None
            suggestions.append(("Sector", f"Best performing sector: {best_sec['Sector']} (${best_sec['Inc']:,.0f} income, {int(best_sec['N'])} trades). Consider allocating more here.", ACCENT_GREEN))
            if worst_sec is not None and worst_sec["Inc"] < 0:
                suggestions.append(("Sector", f"Avoid {worst_sec['Sector']} — negative income ${worst_sec['Inc']:,.0f}. Pause until sector trend reverses.", ACCENT_RED))

    if not suggestions:
        suggestions.append(("General", "Keep trading! More data is needed for meaningful optimization (aim for 10+ trades per strategy).", GOLD))

    for strat, msg, color in suggestions:
        st.markdown(f"""
        <div style="display:flex;gap:12px;align-items:flex-start;padding:10px 14px;
                    background:{BG_CARD};border:1px solid {BORDER_COLOR};
                    border-left:3px solid {color};border-radius:4px;margin-bottom:6px">
          <div style="color:{color};font-size:10px;font-weight:800;min-width:80px;
                      text-transform:uppercase;letter-spacing:0.5px;padding-top:1px">{strat}</div>
          <div style="color:{TEXT_PRIMARY};font-size:12px">{msg}</div>
        </div>""", unsafe_allow_html=True)

    # ── Ticker Performance Snapshot ──────────────────────────────
    _render_ticker_snapshot(df)


# ══════════════════════════════════════════════════════════════════
# 6. MAIN RENDER
# ══════════════════════════════════════════════════════════════════

def render():
    section_header("📈", "Performance Dashboard",
                   "Wheel options + stocks · Auto-closes on expiry · Score ≥ 60 auto-tracked")

    storage = "Google Sheets ✓" if using_google_sheets() else "Local CSV (data/performance.csv)"
    col_info, col_ref = st.columns([4, 1])
    with col_info:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:12px">'
            f'Storage: <b style="color:{GOLD}">{storage}</b> · '
            f'Track any scanner result to populate · Auto-closes when DTE expires</div>',
            unsafe_allow_html=True,
        )
    with col_ref:
        if st.button("🔄 Refresh", use_container_width=True, key="perf_refresh"):
            st.cache_data.clear()
            st.rerun()

    df = _load_and_process()

    if df.empty:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px dashed {BORDER_COLOR};border-radius:10px;
                    padding:50px 20px;text-align:center;color:{TEXT_MUTED}">
          <div style="font-size:48px;margin-bottom:16px">📈</div>
          <div style="font-size:18px;color:{TEXT_PRIMARY};margin-bottom:8px">No Performance Data Yet</div>
          <div style="font-size:13px">Click the <b style="color:{GOLD}">📌 Track</b> button on any CSP, CC, or LEAPS
          scanner result to start tracking.<br>Data is stored in Google Sheets "Performance" tab.</div>
        </div>""", unsafe_allow_html=True)
        return

    # ── Strategy filter ──────────────────────────────────────────
    all_strats = ["All"] + sorted(df["Strategy"].dropna().unique().tolist())
    sel_strat  = st.selectbox("Filter by Strategy", all_strats, index=0, key="perf_strat_filter")
    if sel_strat != "All":
        df = df[df["Strategy"] == sel_strat]

    if df.empty:
        st.info(f"No positions for strategy: {sel_strat}")
        return

    # ── Top summary (always visible above tabs) ──────────────────
    _render_progress_strip(df)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Tab styling (same gold pill style as other pages) ────────
    st.markdown(f"""
    <style>
    .stTabs [data-baseweb="tab-list"] {{
        background:linear-gradient(180deg,{BG_PANEL},{BG_DARK}) !important;
        border:1px solid {BORDER_COLOR} !important; border-radius:10px !important;
        padding:6px !important; gap:4px !important;
        box-shadow:0 4px 12px rgba(0,0,0,.5) !important; margin-bottom:18px !important;
    }}
    .stTabs [data-baseweb="tab"] {{
        height:44px !important; padding:0 22px !important; font-size:14px !important;
        font-weight:700 !important; letter-spacing:.5px !important;
        color:{TEXT_MUTED} !important;
        background:linear-gradient(180deg,{BG_CARD},#0c0c12) !important;
        border:1px solid {BORDER_COLOR} !important; border-radius:8px !important;
    }}
    .stTabs [aria-selected="true"] {{
        color:{BG_DARK} !important;
        background:linear-gradient(180deg,#FFE07A,{GOLD} 45%,{GOLD_DARK}) !important;
        border-color:{GOLD_DARK} !important; font-weight:800 !important;
        box-shadow:0 6px 18px rgba(245,200,66,.45) !important;
    }}
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] {{ display:none !important; }}
    </style>""", unsafe_allow_html=True)

    tab_d, tab_m, tab_a = st.tabs(["📅  DAILY", "📆  MONTHLY", "📊  ANALYTICS"])

    with tab_d:
        _render_daily_tab(df)
    with tab_m:
        _render_monthly_tab(df)
    with tab_a:
        _render_analytics_tab(df)

    st.markdown(
        f'<div style="margin-top:24px;color:{TEXT_MUTED};font-size:10px;text-align:center">'
        f'Open P&L is mark-to-market (intrinsic value only). '
        f'Closed P&L uses actual or historical close prices. Not financial advice.</div>',
        unsafe_allow_html=True,
    )
