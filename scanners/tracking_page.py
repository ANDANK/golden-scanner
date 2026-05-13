# scanners/tracking_page.py — Tracked Positions + Analytics Dashboard

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header, metric_card, _export_filename
from scanners.gsheet_helper import get_tracking, remove_from_tracking, using_google_sheets


# ── Helpers ────────────────────────────────────────────────────

@st.cache_data(ttl=180, show_spinner=False)
def _fetch_prices(tickers: tuple) -> dict:
    """Batch-fetch current prices for all tracked tickers."""
    if not tickers:
        return {}
    try:
        import yfinance as yf
        prices = {}
        data = yf.download(list(tickers), period="2d", auto_adjust=True,
                           progress=False, group_by="ticker")
        for t in tickers:
            try:
                close = data["Close"] if len(tickers) == 1 else data[t]["Close"]
                prices[t] = round(float(close.dropna().iloc[-1]), 2)
            except Exception:
                prices[t] = None
        return prices
    except Exception:
        return {}


def _pnl_html(pnl: float, pct: float) -> str:
    color = ACCENT_GREEN if pnl >= 0 else ACCENT_RED
    sign  = "▲" if pnl >= 0 else "▼"
    return (
        f'<span style="color:{color};font-weight:600">{sign} ${abs(pnl):,.0f} '
        f'<span style="font-size:11px">({pct:+.1f}%)</span></span>'
    )


def _row_pnl(row):
    ep = row["Entry_Price"]
    cp = row["Current_Price"]
    if pd.isna(ep) or pd.isna(cp) or ep == 0:
        return None, None
    pct = (cp - ep) / ep * 100
    strategy = str(row.get("Strategy", ""))
    is_option = strategy in {"CSP", "CC", "LEAPS", "ETF Options", "3x ETF Options", "Dividend+CC"}
    if is_option:
        multiplier = -1 if strategy in {"CSP", "CC", "Dividend+CC", "ETF Options"} else 1
        dollar = round(multiplier * (cp - ep) * 100, 2)
    else:
        dollar = round((cp - ep) * 100, 2)
    return round(dollar, 2), round(pct, 2)


# ── Analytics charts ───────────────────────────────────────────

def _chart_pnl_over_time(df: pd.DataFrame):
    """Cumulative P&L line chart grouped by Added_Date."""
    tmp = df.copy()
    tmp["Date"] = pd.to_datetime(tmp["Added_Date"].astype(str).str[:10], errors="coerce")
    tmp = tmp.dropna(subset=["Date", "PnL_$"])
    if tmp.empty:
        st.info("Not enough data for P&L chart yet.")
        return
    daily = tmp.groupby("Date")["PnL_$"].sum().sort_index()
    cumulative = daily.cumsum()
    colors = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in cumulative.values]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=cumulative.index, y=cumulative.values,
        mode="lines+markers",
        line=dict(color=GOLD, width=2),
        marker=dict(color=colors, size=7),
        fill="tozeroy",
        fillcolor=f"rgba(212,175,55,0.08)",
        name="Cumulative P&L",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color=BORDER_COLOR, line_width=1)
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        font=dict(color=TEXT_PRIMARY, family="Inter"),
        xaxis=dict(gridcolor=BORDER_COLOR + "33", title=""),
        yaxis=dict(gridcolor=BORDER_COLOR + "33", title="Cumulative P&L ($)", tickprefix="$"),
        margin=dict(l=0, r=0, t=10, b=0),
        height=260,
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def _chart_by_source(df: pd.DataFrame):
    """Pie chart — position count by source category."""
    tmp = df.copy()
    tmp["SourceCat"] = tmp["Source"].astype(str).str.split("-").str[0].str.strip()
    tmp["SourceCat"] = tmp["SourceCat"].replace("", "Other")
    grp = tmp.groupby("SourceCat").size().reset_index(name="Count")
    if grp.empty:
        st.info("No source data.")
        return
    palette = [GOLD, ACCENT_GREEN, ACCENT_BLUE, ACCENT_RED, "#A78BFA", "#34D399", "#F472B6"]
    fig = go.Figure(go.Pie(
        labels=grp["SourceCat"],
        values=grp["Count"],
        hole=0.45,
        marker=dict(colors=palette[:len(grp)], line=dict(color=BG_DARK, width=2)),
        textfont=dict(color=TEXT_PRIMARY, size=12),
    ))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        font=dict(color=TEXT_PRIMARY),
        margin=dict(l=0, r=0, t=10, b=0),
        height=260,
        legend=dict(font=dict(color=TEXT_MUTED, size=11)),
    )
    st.plotly_chart(fig, use_container_width=True)


def _chart_best_worst(df: pd.DataFrame):
    """Horizontal bar chart — top 5 winners and bottom 5 losers by P&L $."""
    tmp = df.dropna(subset=["PnL_$"]).copy()
    if tmp.empty:
        st.info("No P&L data yet.")
        return
    tmp = tmp.sort_values("PnL_$")
    bottom5 = tmp.head(5)
    top5    = tmp.tail(5).iloc[::-1]
    combined = pd.concat([top5, bottom5]).drop_duplicates()
    colors = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in combined["PnL_$"]]
    labels = combined["Ticker"] + " (" + combined["Added_Date"].astype(str).str[:10] + ")"
    fig = go.Figure(go.Bar(
        x=combined["PnL_$"].tolist(),
        y=labels.tolist(),
        orientation="h",
        marker_color=colors,
        text=[f"${v:+,.0f}" for v in combined["PnL_$"]],
        textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=11),
    ))
    fig.add_vline(x=0, line_color=BORDER_COLOR, line_width=1)
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        font=dict(color=TEXT_PRIMARY, family="Inter"),
        xaxis=dict(gridcolor=BORDER_COLOR + "33", tickprefix="$"),
        yaxis=dict(gridcolor="rgba(0,0,0,0)"),
        margin=dict(l=0, r=40, t=10, b=0),
        height=max(220, len(combined) * 36),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_trade_analysis(df: pd.DataFrame):
    """Auto-generated bullet analysis for losing trades."""
    losers = df[df["PnL_$"].notna() & (df["PnL_$"] < 0)].copy()
    if losers.empty:
        st.markdown(
            f'<div style="color:{ACCENT_GREEN};padding:12px">'
            f'✅ No losing trades in the selected period — great work!</div>',
            unsafe_allow_html=True,
        )
        return

    bullets = []
    for _, row in losers.iterrows():
        tk   = row["Ticker"]
        strat = str(row.get("Strategy", "Stock"))
        src  = str(row.get("Source", ""))
        pnl  = row["PnL_$"]
        pct  = row.get("PnL_%", 0) or 0
        ep   = row.get("Entry_Price", 0) or 0
        cp   = row.get("Current_Price", 0) or 0

        reasons = []
        if "CSP" in strat or "CC" in strat:
            reasons.append("Sell strategy: underlying moved against short position")
            if cp and ep and cp > ep * 1.05:
                reasons.append("Stock rose >5% — consider wider OTM strikes or shorter DTE next time")
        elif "LEAPS" in strat:
            reasons.append("Long option: time decay or IV crush may have reduced value")
        else:
            reasons.append("Long stock position moved lower")

        if "GS-" in src:
            scanner = src.replace("GS-", "").split("·")[0].strip()
            reasons.append(f"Sourced from Golden Scan ({scanner}) — review signal strength threshold")
        elif "H&C" in src:
            reasons.append("News-driven entry: gap fades are common, consider waiting for confirmation")

        if pct < -10:
            reasons.append(f"Large drawdown ({pct:.1f}%) — consider tighter stop-loss rules")
        elif pct < -5:
            reasons.append(f"Moderate loss ({pct:.1f}%) — within expected volatility range")

        bullet_html = "".join(f'<li style="margin:3px 0;color:{TEXT_MUTED};font-size:12px">{r}</li>' for r in reasons)
        bullets.append(
            f'<div style="background:{BG_PANEL};border-left:3px solid {ACCENT_RED};'
            f'border-radius:4px;padding:10px 14px;margin-bottom:8px">'
            f'<div style="color:{ACCENT_RED};font-weight:700;font-size:13px;margin-bottom:4px">'
            f'{tk} &nbsp; <span style="font-size:11px;color:{TEXT_MUTED}">${pnl:+,.0f}</span></div>'
            f'<ul style="margin:0;padding-left:18px">{bullet_html}</ul></div>'
        )

    st.markdown("".join(bullets), unsafe_allow_html=True)
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:8px">'
        f'⚠️ Analysis is heuristic-based. Not financial advice.</div>',
        unsafe_allow_html=True,
    )


# ── Main render ────────────────────────────────────────────────

def render():
    section_header("📌", "Tracking", "Positions you are actively monitoring · Live P&L · Analytics")

    # Storage indicator + controls row
    storage = "Google Sheets" if using_google_sheets() else "Local CSV (data/tracking.csv)"
    s1, s2, s3 = st.columns([5, 1, 1])
    with s1:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;padding-top:6px">'
            f'Storage: <b style="color:{GOLD}">{storage}</b></div>',
            unsafe_allow_html=True,
        )
    with s2:
        show_all = st.checkbox("All-time", value=False, key="tracking_show_all",
                               help="Show all tracked positions (default: last 30 days)")
    with s3:
        if st.button("🔄 Refresh", key="tracking_refresh", use_container_width=True,
                     help="Fetch latest prices"):
            st.cache_data.clear()
            st.rerun()

    rows = get_tracking()
    if not rows:
        st.markdown(
            f'<div style="text-align:center;padding:60px 20px;color:{TEXT_MUTED}">'
            f'<div style="font-size:48px;margin-bottom:16px">📌</div>'
            f'<div style="font-size:16px">No positions tracked yet.</div>'
            f'<div style="font-size:13px;margin-top:8px">Click <b>📌 Track</b> on any scanner results to add.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    df = pd.DataFrame(rows)
    df["Ticker"]      = df["Ticker"].astype(str).str.upper().str.strip()
    df["Entry_Price"] = pd.to_numeric(df["Entry_Price"], errors="coerce")

    # ── Date filter (last 30 days default) ────────────────────
    if not show_all:
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        df = df[df["Added_Date"].astype(str) >= cutoff]
        if df.empty:
            st.info("No positions in the last 30 days. Check 'All-time' to see older entries.")
            return

    # ── Fetch live prices ──────────────────────────────────────
    tickers_tuple = tuple(df["Ticker"].unique().tolist())
    with st.spinner("Fetching live prices…"):
        prices = _fetch_prices(tickers_tuple)

    df["Current_Price"] = pd.to_numeric(df["Ticker"].map(prices), errors="coerce")
    df[["PnL_$", "PnL_%"]] = df.apply(lambda r: pd.Series(_row_pnl(r)), axis=1)

    # ── Summary metrics row ────────────────────────────────────
    total_pnl = df["PnL_$"].dropna().sum()
    winners   = int((df["PnL_$"].dropna() > 0).sum())
    losers    = int((df["PnL_$"].dropna() < 0).sum())
    open_pos  = len(df)
    win_rate  = round(winners / (winners + losers) * 100, 1) if (winners + losers) > 0 else 0
    avg_ret   = round(df["PnL_%"].dropna().mean(), 2) if not df["PnL_%"].dropna().empty else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: metric_card("Positions", str(open_pos))
    with c2: metric_card("Winners", str(winners), color=ACCENT_GREEN)
    with c3: metric_card("Losers",  str(losers),  color=ACCENT_RED)
    with c4: metric_card("Win Rate", f"{win_rate}%", color=GOLD)
    with c5:
        pnl_color = ACCENT_GREEN if total_pnl >= 0 else ACCENT_RED
        metric_card("Total P&L", f"${total_pnl:+,.0f}", color=pnl_color)
    with c6:
        ret_color = ACCENT_GREEN if avg_ret >= 0 else ACCENT_RED
        metric_card("Avg Return", f"{avg_ret:+.1f}%", color=ret_color)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Analytics Dashboard ────────────────────────────────────
    with st.expander("📊 Analytics Dashboard", expanded=True):
        tab1, tab2, tab3, tab4 = st.tabs([
            "📈 P&L Over Time", "🥧 By Source", "🏆 Best & Worst", "🔍 Trade Analysis"
        ])
        with tab1:
            _chart_pnl_over_time(df)
        with tab2:
            _chart_by_source(df)
        with tab3:
            _chart_best_worst(df)
        with tab4:
            _render_trade_analysis(df)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Positions table ────────────────────────────────────────
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;'
        f'letter-spacing:1px;margin-bottom:6px">📋 Positions</div>',
        unsafe_allow_html=True,
    )
    header_cols = ["Ticker", "Strategy", "Action", "Qty", "Entry", "Current", "P&L (est.)", "Score", "Added", "Source"]
    header_html = "".join(
        f'<th style="background:{BG_PANEL};color:{GOLD};font-size:11px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.8px;padding:10px 14px;'
        f'border-bottom:2px solid {GOLD}44;white-space:nowrap">{c}</th>'
        for c in header_cols
    )

    row_htmls = []
    for i, (_, row) in enumerate(df.iterrows()):
        bg   = BG_CARD if i % 2 == 0 else BG_PANEL
        ep   = row["Entry_Price"]
        cp   = row["Current_Price"]
        pnl  = row["PnL_$"]
        ppct = row["PnL_%"]
        ep_str  = f"${ep:.2f}"   if pd.notna(ep)  else "—"
        cp_str  = f"${cp:.2f}"   if pd.notna(cp)  else "—"
        pnl_str = _pnl_html(pnl, ppct) if pd.notna(pnl) else "—"
        score   = str(row.get("Score", "")).strip() or "—"
        td = f'border-bottom:1px solid {BORDER_COLOR}22;background:{bg}'
        cells = [
            f'<td style="padding:8px 14px;{td}"><span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700">{row["Ticker"]}</span></td>',
            f'<td style="padding:8px 14px;{td}"><span style="color:{TEXT_MUTED};font-size:12px">{row.get("Strategy","")}</span></td>',
            f'<td style="padding:8px 14px;{td}"><span style="color:{ACCENT_GREEN if str(row.get("Action",""))=="Buy" else ACCENT_RED};font-size:12px;font-weight:600">{row.get("Action","")}</span></td>',
            f'<td style="padding:8px 14px;{td}"><span style="color:{TEXT_PRIMARY};font-size:12px">{row.get("Qty","")}</span></td>',
            f'<td style="padding:8px 14px;{td}"><span style="color:{TEXT_MUTED};font-family:\'DM Mono\',monospace;font-size:12px">{ep_str}</span></td>',
            f'<td style="padding:8px 14px;{td}"><span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;font-size:12px">{cp_str}</span></td>',
            f'<td style="padding:8px 14px;{td}">{pnl_str}</td>',
            f'<td style="padding:8px 14px;{td}"><span style="color:{GOLD};font-size:12px">{score}</span></td>',
            f'<td style="padding:8px 14px;{td}"><span style="color:{TEXT_MUTED};font-size:11px">{str(row.get("Added_Date",""))[:10]}</span></td>',
            f'<td style="padding:8px 14px;{td}"><span style="color:{TEXT_MUTED};font-size:11px">{row.get("Source","")}</span></td>',
        ]
        row_htmls.append(f'<tr>{"".join(cells)}</tr>')

    st.markdown(f"""
    <div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:8px;margin-top:4px">
      <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{"".join(row_htmls)}</tbody>
      </table>
    </div>""", unsafe_allow_html=True)

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:6px">'
        f'P&L estimated: stocks = 100 shares · options = 1-contract underlying delta. Not actual P&L.</div>',
        unsafe_allow_html=True,
    )

    # ── Remove position ────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Remove Position</div>',
        unsafe_allow_html=True,
    )
    remove_options = [""] + [
        f"{str(r.get('Ticker','')).upper()} — {str(r.get('Added_Date',''))[:10]}"
        for _, r in df.iterrows()
    ]
    r1, r2 = st.columns([4, 1])
    with r1:
        to_remove_label = st.selectbox(
            "Select position to remove",
            options=remove_options,
            label_visibility="collapsed",
            key="tracking_remove_sel",
            placeholder="Choose position to remove…",
        )
    with r2:
        if st.button("🗑 Remove", key="tracking_remove_btn", use_container_width=True):
            if to_remove_label:
                parts = to_remove_label.split(" — ", 1)
                tk = parts[0].strip()
                dt = parts[1].strip() if len(parts) > 1 else ""
                if remove_from_tracking(tk, dt):
                    st.success(f"{tk} ({dt}) removed.")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Could not remove — row not found.")
            else:
                st.warning("Select a position first.")

    # ── Export ─────────────────────────────────────────────────
    export_cols = ["Ticker","Strategy","Action","Qty","Entry_Price","Current_Price","PnL_$","PnL_%","Score","Added_Date","Source"]
    export_cols = [c for c in export_cols if c in df.columns]
    st.download_button(
        "⬇ Export Tracking CSV",
        df[export_cols].to_csv(index=False),
        _export_filename("tracking"), "text/csv",
    )
