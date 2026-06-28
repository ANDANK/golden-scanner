# scanners/edu529_page.py — 529 Equity Planner (Vanguard 529 plan)
#
# Educational tool — NOT investment advice. Performance/risk are computed live
# from publicly-traded proxies (ETF/mutual-fund tickers) for each Vanguard 529
# individual equity portfolio. 529 portfolio NAVs aren't on public feeds, so the
# closest tracking fund is used as a proxy.
#
# Sections:
#   1. Equity fund picker (equity portfolios only — no bond/stable/age funds)
#   2. Performance & risk table (1Y/3Y/5Y CAGR, volatility, max drawdown, return/risk)
#   3. Return-correlation matrix  → overlap detector (high corr = redundant holdings)
#   4. Diversified shortlist (educational)
#   5. Growth projection calculator (monthly contribution · return % · years)

from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from datetime import date
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Palette ────────────────────────────────────────────────────
_GOLD  = "#f59e0b"
_GREEN = "#22c55e"
_RED   = "#ef4444"
_BLUE  = "#3b82f6"
_PUR   = "#a855f7"
_MUTED = "#64748b"
_TEXT  = "#e2e8f0"
_DIM   = "#94a3b8"
_BG    = "#0f1929"
_CARD  = "#111827"
_PANEL = "#1e293b"

# ── Vanguard 529 individual EQUITY portfolios (equity only) ─────
# proxy = closest publicly-traded ticker for live data
# er     = approximate 529 portfolio expense ratio (%) — verify on plan docs
CATALOG = [
    # symbol, name, proxy, er, cat, risk, note, default
    {"sym": "VG500",  "name": "500 Index Portfolio",            "proxy": "VOO",  "er": 0.14, "cat": "US Large Blend",  "risk": "High",     "note": "S&P 500 core", "default": True},
    {"sym": "VGTSM",  "name": "Total Stock Market Index",       "proxy": "VTI",  "er": 0.14, "cat": "US Total Market", "risk": "High",     "note": "Whole US market", "default": True},
    {"sym": "VGGRW",  "name": "Growth Index Portfolio",         "proxy": "VUG",  "er": 0.16, "cat": "US Large Growth", "risk": "High",     "note": "≈ your VIGIX", "default": True},
    {"sym": "VGVAL",  "name": "Value Index Portfolio",          "proxy": "VTV",  "er": 0.16, "cat": "US Large Value",  "risk": "Med-High", "note": "Value tilt", "default": True},
    {"sym": "VGMID",  "name": "Mid-Cap Index Portfolio",        "proxy": "VO",   "er": 0.16, "cat": "US Mid Blend",    "risk": "High",     "note": "Mid caps", "default": True},
    {"sym": "VGSML",  "name": "Small-Cap Index Portfolio",      "proxy": "VB",   "er": 0.16, "cat": "US Small Blend",  "risk": "High",     "note": "Small caps", "default": True},
    {"sym": "VGHDV",  "name": "High Dividend Yield Index",      "proxy": "VYM",  "er": 0.16, "cat": "US Dividend",     "risk": "Medium",   "note": "Income/value", "default": False},
    {"sym": "VGDGR",  "name": "Dividend Growth (active)",       "proxy": "VDIGX","er": 0.40, "cat": "US Quality",      "risk": "Medium",   "note": "Quality dividend growers", "default": False},
    {"sym": "VGUSG",  "name": "US Growth Portfolio (active)",   "proxy": "VWUSX","er": 0.40, "cat": "US Large Growth", "risk": "High",     "note": "Active growth", "default": False},
    {"sym": "VGWND",  "name": "Windsor Portfolio (active)",     "proxy": "VWNDX","er": 0.40, "cat": "US Large Value",  "risk": "Med-High", "note": "Active value", "default": False},
    {"sym": "VGEXP",  "name": "Explorer Portfolio (active)",    "proxy": "VEXPX","er": 0.42, "cat": "US Sm/Mid Growth","risk": "High",     "note": "Active small/mid growth", "default": False},
    {"sym": "VGTIS",  "name": "Total International Stock Index", "proxy": "VXUS", "er": 0.16, "cat": "Intl Dev + EM",   "risk": "Med-High", "note": "All non-US", "default": True},
    {"sym": "VGDEV",  "name": "Developed Markets Index",        "proxy": "VEA",  "er": 0.16, "cat": "Intl Developed",  "risk": "Med-High", "note": "Europe/Japan/Pacific", "default": False},
    {"sym": "VGEMG",  "name": "Emerging Markets Stock Index",   "proxy": "VWO",  "er": 0.20, "cat": "Emerging Markets","risk": "High",     "note": "EM growth", "default": True},
    {"sym": "VGITG",  "name": "International Growth (active)",   "proxy": "VWIGX","er": 0.45, "cat": "Intl Growth",     "risk": "High",     "note": "Active intl growth", "default": False},
    {"sym": "VGREI",  "name": "Real Estate Index Portfolio",    "proxy": "VNQ",  "er": 0.16, "cat": "US REIT",         "risk": "Med-High", "note": "Real-estate diversifier", "default": False},
]
BY_PROXY = {f["proxy"]: f for f in CATALOG}

# Educational diversified shortlist (low overlap, cost-aware)
SHORTLIST = [
    ("VTI",  "Total US core — one fund replaces 500 + Growth and removes their internal overlap"),
    ("VXUS", "Total International — the biggest diversifier; minimal overlap with US funds"),
    ("VO",   "US Mid-Cap — exposure beyond the mega-cap names in the 500"),
    ("VB",   "US Small-Cap — adds the smallest, highest-growth tier"),
    ("VTV",  "US Value — style balance against a growth-heavy portfolio"),
    ("VWO",  "Emerging Markets — separate growth engine, low US correlation"),
    ("VNQ",  "Real Estate (REIT) — distinct asset class for diversification"),
    ("VYM",  "High Dividend — lower-volatility income/value sleeve (optional)"),
]

_RISK_COLOR = {"High": _RED, "Med-High": _GOLD, "Medium": _GREEN, "Low": _BLUE}


# ── Data fetch ─────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_closes(proxies: tuple) -> pd.DataFrame:
    try:
        raw = yf.download(list(proxies), period="5y", auto_adjust=True,
                          progress=False, threads=True)
    except Exception:
        return pd.DataFrame()
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else pd.DataFrame()
    else:
        close = raw[["Close"]].rename(columns={"Close": proxies[0]})
    return close.dropna(how="all")


def _metrics(close: pd.Series) -> dict:
    s = close.dropna()
    if len(s) < 30:
        return {}
    px_now = float(s.iloc[-1])

    def cagr(years: int):
        n = years * 252
        if len(s) <= n:
            return None
        start = float(s.iloc[-n])
        return ((px_now / start) ** (1 / years) - 1) * 100 if start > 0 else None

    rets = s.pct_change().dropna()
    vol = float(rets.std() * np.sqrt(252) * 100) if len(rets) > 20 else None
    roll_max = s.cummax()
    mdd = float(((s - roll_max) / roll_max).min() * 100)
    c5 = cagr(5)
    rr = (c5 / vol) if (c5 is not None and vol) else None
    return {
        "price": px_now, "cagr1": cagr(1), "cagr3": cagr(3), "cagr5": c5,
        "vol": vol, "mdd": mdd, "rr": rr,
    }


# ── Formatting ─────────────────────────────────────────────────
def _pct(v, signed=True):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return (f"{v:+.1f}%" if signed else f"{v:.1f}%")

def _pc(v):
    if v is None:
        return _MUTED
    return _GREEN if v >= 0 else _RED

def _money(x):
    try:
        return f"${float(x):,.0f}"
    except Exception:
        return "—"


# ── Performance & risk table ───────────────────────────────────
def _perf_table(funds: list, close_df: pd.DataFrame):
    th = (f'color:{_MUTED};font-size:10px;font-weight:700;text-transform:uppercase;'
          f'letter-spacing:.5px;padding:8px 10px;border-bottom:2px solid {_GOLD}55;'
          f'background:{_PANEL};white-space:nowrap;text-align:right')
    th_l = th.replace("text-align:right", "text-align:left")
    hdr = (f'<th style="{th_l}">Fund</th><th style="{th_l}">Category</th>'
           f'<th style="{th}">Exp %</th><th style="{th}">Risk</th>'
           f'<th style="{th}">1Y</th><th style="{th}">3Y</th><th style="{th}">5Y</th>'
           f'<th style="{th}">Vol</th><th style="{th}">Max DD</th><th style="{th}">Ret/Risk</th>')
    body = ""
    rows_for_sort = []
    for f in funds:
        m = _metrics(close_df[f["proxy"]]) if f["proxy"] in close_df.columns else {}
        rows_for_sort.append((f, m))
    # sort by 5Y CAGR desc (None last)
    rows_for_sort.sort(key=lambda x: (x[1].get("cagr5") is None, -(x[1].get("cagr5") or 0)))
    for i, (f, m) in enumerate(rows_for_sort):
        bg = _CARD if i % 2 == 0 else _PANEL
        td = f'padding:7px 10px;border-bottom:1px solid {_PANEL};background:{bg};font-size:12px;text-align:right'
        td_l = td.replace("text-align:right", "text-align:left")
        rk = f["risk"]; rkc = _RISK_COLOR.get(rk, _MUTED)
        rr = m.get("rr")
        rr_c = _GREEN if (rr and rr >= 0.5) else (_GOLD if (rr and rr >= 0.3) else _MUTED)
        body += (
            f'<tr>'
            f'<td style="{td_l}"><span style="color:{_GOLD};font-weight:700">{f["name"]}</span>'
            f'<br><span style="color:{_MUTED};font-size:10px;font-family:DM Mono,monospace">'
            f'{f["sym"]} · proxy {f["proxy"]}</span></td>'
            f'<td style="{td_l};color:{_DIM};font-size:11px">{f["cat"]}<br>'
            f'<span style="color:{_MUTED};font-size:10px">{f["note"]}</span></td>'
            f'<td style="{td};color:{_DIM}">{f["er"]:.2f}</td>'
            f'<td style="{td}"><span style="color:{rkc};font-weight:600;font-size:11px">{rk}</span></td>'
            f'<td style="{td};color:{_pc(m.get("cagr1"))};font-weight:600">{_pct(m.get("cagr1"))}</td>'
            f'<td style="{td};color:{_pc(m.get("cagr3"))};font-weight:600">{_pct(m.get("cagr3"))}</td>'
            f'<td style="{td};color:{_pc(m.get("cagr5"))};font-weight:700">{_pct(m.get("cagr5"))}</td>'
            f'<td style="{td};color:{_DIM}">{_pct(m.get("vol"), signed=False)}</td>'
            f'<td style="{td};color:{_RED}">{_pct(m.get("mdd"))}</td>'
            f'<td style="{td};color:{rr_c};font-weight:600">{("%.2f"%rr) if rr else "—"}</td>'
            f'</tr>'
        )
    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {_PANEL}">'
        f'<table style="width:100%;border-collapse:collapse;background:{_BG}">'
        f'<thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table></div>'
        f'<div style="color:{_MUTED};font-size:10px;margin-top:4px">'
        f'CAGR = annualized return · Vol = annualized volatility · Max DD = worst peak-to-trough · '
        f'Ret/Risk = 5Y CAGR ÷ Vol (higher = more efficient). Live data via proxy tickers.</div>',
        unsafe_allow_html=True,
    )


# ── Correlation / overlap matrix ───────────────────────────────
def _corr_matrix(funds: list, close_df: pd.DataFrame):
    proxies = [f["proxy"] for f in funds if f["proxy"] in close_df.columns]
    if len(proxies) < 2:
        st.info("Pick at least two funds to see overlap.")
        return
    rets = close_df[proxies].pct_change().dropna()
    if len(rets) > 756:
        rets = rets.iloc[-756:]   # ~3y
    corr = rets.corr()

    def _cell_color(v):
        if v >= 0.95: return _RED
        if v >= 0.85: return _GOLD
        if v >= 0.70: return _DIM
        return _GREEN

    th = (f'color:{_MUTED};font-size:10px;font-weight:700;padding:6px 8px;'
          f'background:{_PANEL};border-bottom:2px solid {_GOLD}55;white-space:nowrap')
    hdr = f'<th style="{th};text-align:left">Corr</th>' + "".join(
        f'<th style="{th};text-align:center">{p}</th>' for p in proxies)
    body = ""
    for r in proxies:
        cells = (f'<td style="padding:6px 8px;background:{_PANEL};color:{_GOLD};'
                 f'font-weight:700;font-size:11px;font-family:DM Mono,monospace">{r}</td>')
        for c in proxies:
            v = float(corr.loc[r, c])
            col = _cell_color(v) if r != c else _MUTED
            cells += (f'<td style="padding:6px 8px;text-align:center;font-size:11px;'
                      f'color:{col};font-weight:{"700" if v>=0.85 and r!=c else "500"}">{v:.2f}</td>')
        body += f"<tr>{cells}</tr>"
    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {_PANEL}">'
        f'<table style="width:100%;border-collapse:collapse;background:{_BG}">'
        f'<thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table></div>',
        unsafe_allow_html=True,
    )
    # Flag the most-redundant pair
    pairs = []
    for i in range(len(proxies)):
        for j in range(i + 1, len(proxies)):
            pairs.append((proxies[i], proxies[j], float(corr.iloc[i, j])))
    pairs.sort(key=lambda x: -x[2])
    redundant = [p for p in pairs if p[2] >= 0.90]
    legend = (f'<span style="color:{_RED}">≥0.95 near-duplicate</span> · '
              f'<span style="color:{_GOLD}">0.85–0.95 heavy overlap</span> · '
              f'<span style="color:{_DIM}">0.70–0.85 moderate</span> · '
              f'<span style="color:{_GREEN}">&lt;0.70 diversifying</span>')
    st.markdown(f'<div style="color:{_MUTED};font-size:11px;margin-top:6px">{legend}</div>',
                unsafe_allow_html=True)
    if redundant:
        items = " · ".join(f"<b style='color:{_RED}'>{a}↔{b}</b> ({v:.2f})" for a, b, v in redundant[:5])
        st.markdown(
            f'<div style="background:{_RED}14;border:1px solid {_RED}44;border-radius:8px;'
            f'padding:10px 14px;margin-top:8px;color:{_TEXT};font-size:12px">'
            f'⚠️ <b>High overlap detected</b> — these pairs move almost identically, so holding '
            f'both adds little diversification: {items}. Consider keeping one and using the freed '
            f'allocation for a low-correlation fund (international, small-cap, EM, or REIT).</div>',
            unsafe_allow_html=True,
        )


# ── Shortlist ──────────────────────────────────────────────────
def _render_shortlist(close_df: pd.DataFrame):
    st.markdown(
        f'<div style="color:{_GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1px;margin:6px 0 8px">🎯 Diversified Equity Shortlist (educational)</div>'
        f'<div style="color:{_MUTED};font-size:12px;margin-bottom:10px">'
        f'A low-overlap, cost-aware set of building blocks. You hold <b>VIGIX (Growth)</b> + '
        f'<b>VFFSX (500)</b> ~50/50 — Growth is a <i>subset</i> of the 500, so the two overlap '
        f'heavily. The picks below spread risk across size, style, geography, and asset class.</div>',
        unsafe_allow_html=True,
    )
    for proxy, why in SHORTLIST:
        f = BY_PROXY.get(proxy, {})
        m = _metrics(close_df[proxy]) if proxy in close_df.columns else {}
        c5 = m.get("cagr5")
        st.markdown(
            f'<div style="background:{_PANEL};border-left:3px solid {_GOLD};border-radius:0 6px 6px 0;'
            f'padding:8px 12px;margin-bottom:6px">'
            f'<span style="color:{_GOLD};font-weight:700;font-family:DM Mono,monospace">{proxy}</span> '
            f'<span style="color:{_TEXT};font-size:12px">{f.get("name","")}</span> '
            f'<span style="color:{_pc(c5)};font-size:11px">· 5Y {_pct(c5)}</span><br>'
            f'<span style="color:{_DIM};font-size:11px">{why}</span></div>',
            unsafe_allow_html=True,
        )


# ── Projection calculator ──────────────────────────────────────
def _project(start: float, monthly: float, annual_pct: float, years: int):
    r = annual_pct / 100.0 / 12.0
    n = years * 12
    bal = start
    series = [start]
    contrib = start
    contrib_series = [start]
    for _ in range(n):
        bal = bal * (1 + r) + monthly
        contrib += monthly
        series.append(bal)
        contrib_series.append(contrib)
    return series, contrib_series


def _render_calculator(funds: list, close_df: pd.DataFrame):
    st.markdown(
        f'<div style="color:{_GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1px;margin:6px 0 8px">📈 Growth Projection — where will I be?</div>',
        unsafe_allow_html=True,
    )

    # Reference CAGRs to help pick a realistic return
    ref = []
    for f in funds:
        m = _metrics(close_df[f["proxy"]]) if f["proxy"] in close_df.columns else {}
        if m.get("cagr5") is not None:
            ref.append(f'{f["proxy"]} {m["cagr5"]:.0f}%')
    if ref:
        st.markdown(
            f'<div style="color:{_MUTED};font-size:11px;margin-bottom:8px">'
            f'5Y historical returns for reference: {" · ".join(ref[:10])} '
            f'<i>(past performance ≠ future)</i></div>',
            unsafe_allow_html=True,
        )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        start = st.number_input("Current balance ($)", min_value=0.0, value=20000.0, step=1000.0, key="e529_start")
    with c2:
        monthly = st.number_input("Monthly contribution ($)", min_value=0.0, value=500.0, step=50.0, key="e529_monthly")
    with c3:
        annual = st.slider("Expected annual return (%)", 0.0, 15.0, 8.0, 0.5, key="e529_ret")
    with c4:
        years = st.slider("Years to maturity", 1, 25, 10, key="e529_years")

    series, contrib = _project(start, monthly, annual, years)
    fv = series[-1]
    total_contrib = contrib[-1]
    growth = fv - total_contrib
    mult = (fv / total_contrib) if total_contrib > 0 else 0

    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("Projected value", _money(fv))
    with m2: st.metric("Total contributed", _money(total_contrib))
    with m3: st.metric("Investment growth", _money(growth), f"{(growth/total_contrib*100 if total_contrib else 0):+.0f}%")
    with m4: st.metric("Value ÷ contributed", f"{mult:.2f}×")

    # Scenario band: return ±2%
    months = list(range(len(series)))
    base_y = series
    lo_y, _ = _project(start, monthly, max(0.0, annual - 2), years)
    hi_y, _ = _project(start, monthly, annual + 2, years)
    x_years = [mn / 12 for mn in months]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x_years, y=hi_y, line=dict(width=0), showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x_years, y=lo_y, fill="tonexty", line=dict(width=0),
                             fillcolor=f"rgba(59,130,246,0.12)",
                             name=f"±2% band", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x_years, y=base_y, line=dict(color=_GOLD, width=2.5),
                             name=f"{annual:.1f}% return"))
    fig.add_trace(go.Scatter(x=x_years, y=contrib, line=dict(color=_GREEN, width=1.5, dash="dot"),
                             name="Contributions only"))
    fig.update_layout(
        paper_bgcolor=_CARD, plot_bgcolor=_BG, font_color=_TEXT, height=340,
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(title="Years", gridcolor=_PANEL),
        yaxis=dict(title="Balance ($)", gridcolor=_PANEL, tickprefix="$"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Year-by-year table (every year)
    rows = ""
    for yr in range(0, years + 1):
        idx = yr * 12
        bal = series[idx]; con = contrib[idx]; g = bal - con
        bg = _CARD if yr % 2 == 0 else _PANEL
        td = f'padding:5px 12px;background:{bg};font-size:12px;border-bottom:1px solid {_PANEL}'
        rows += (
            f'<tr><td style="{td};color:{_DIM}">Year {yr}</td>'
            f'<td style="{td};text-align:right;color:{_DIM}">{_money(con)}</td>'
            f'<td style="{td};text-align:right;color:{_GREEN}">{_money(g)}</td>'
            f'<td style="{td};text-align:right;color:{_GOLD};font-weight:700">{_money(bal)}</td></tr>'
        )
    th = (f'color:{_MUTED};font-size:10px;font-weight:700;text-transform:uppercase;padding:7px 12px;'
          f'background:{_PANEL};border-bottom:2px solid {_GOLD}55')
    with st.expander("📅 Year-by-year breakdown", expanded=False):
        st.markdown(
            f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {_PANEL}">'
            f'<table style="width:100%;border-collapse:collapse;background:{_BG}">'
            f'<thead><tr><th style="{th};text-align:left">Year</th>'
            f'<th style="{th};text-align:right">Contributed</th>'
            f'<th style="{th};text-align:right">Growth</th>'
            f'<th style="{th};text-align:right">Balance</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>',
            unsafe_allow_html=True,
        )


# ── Entry point ────────────────────────────────────────────────
def render():
    st.markdown(
        f'<div style="font-size:20px;font-weight:800;color:{_GOLD};margin-bottom:2px">'
        f'🎓 529 Equity Planner — Vanguard 529 Plan</div>'
        f'<div style="font-size:12px;color:{_MUTED};margin-bottom:8px">'
        f'Equity portfolios only (no bond / stable-value / age-based) · live performance &amp; risk '
        f'via proxy tickers · overlap detector · growth projection</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="background:{_PANEL};border:1px solid {_GOLD}44;border-left:4px solid {_GOLD};'
        f'border-radius:0 8px 8px 0;padding:8px 14px;margin-bottom:12px;color:{_DIM};font-size:11px">'
        f'⚠️ <b>Educational tool, not financial advice.</b> Proxy tickers approximate each 529 '
        f'portfolio; expense ratios are estimates — confirm on official Vanguard 529 documents. '
        f'Consult a licensed advisor before making changes.</div>',
        unsafe_allow_html=True,
    )

    names = [f"{f['name']}  ({f['proxy']})" for f in CATALOG]
    default_names = [f"{f['name']}  ({f['proxy']})" for f in CATALOG if f["default"]]
    picked = st.multiselect(
        "Pick equity funds to analyze", names, default=default_names, key="e529_pick",
    )
    picked_funds = [f for f in CATALOG if f"{f['name']}  ({f['proxy']})" in picked]
    if not picked_funds:
        st.info("Select one or more equity funds above to begin.")
        return

    with st.spinner("Fetching 5-year price history (cached 1 hour)…"):
        close_df = _fetch_closes(tuple(sorted({f["proxy"] for f in picked_funds}
                                              | {p for p, _ in SHORTLIST})))

    if close_df.empty:
        st.error("Could not fetch price data right now. Try again shortly.")
        return

    tab_perf, tab_overlap, tab_short, tab_calc = st.tabs([
        "📊 Performance & Risk",
        "🔗 Overlap Detector",
        "🎯 Shortlist",
        "📈 Projection",
    ])
    with tab_perf:
        _perf_table(picked_funds, close_df)
    with tab_overlap:
        st.markdown(
            f'<div style="color:{_MUTED};font-size:12px;margin-bottom:8px">'
            f'Return correlation among your selected funds (last ~3 years). High correlation = the '
            f'funds rise and fall together = little diversification benefit from holding both.</div>',
            unsafe_allow_html=True,
        )
        _corr_matrix(picked_funds, close_df)
    with tab_short:
        _render_shortlist(close_df)
    with tab_calc:
        _render_calculator(picked_funds, close_df)
