# scanners/tracking_page.py — Tracked Positions + Analytics Dashboard

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header, metric_card, _export_filename
from scanners.gsheet_helper import get_tracking, remove_from_tracking, using_google_sheets, show_storage_banner


# ── Delete callback (fires before rerender — Streamlit reruns naturally) ──

def _cb_delete_tracking(ticker: str, added_date: str):
    """Remove one tracking row then let Streamlit's natural rerun refresh the table."""
    remove_from_tracking(ticker, added_date)
    st.cache_data.clear()


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

def _rgba(hex6: str, alpha: float) -> str:
    """Convert a 6-char hex color + alpha float to rgba() for Plotly compatibility."""
    h = hex6.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


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
    fig.add_hline(y=0, line=dict(dash="dash", color=BORDER_COLOR, width=1))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        font=dict(color=TEXT_PRIMARY, family="Inter"),
        xaxis=dict(gridcolor=_rgba(BORDER_COLOR, 0.2), title=""),
        yaxis=dict(gridcolor=_rgba(BORDER_COLOR, 0.2), title="Cumulative P&L ($)", tickprefix="$"),
        margin=dict(l=0, r=0, t=10, b=0),
        height=260,
        showlegend=False,
    )
    st.plotly_chart(fig, width='stretch')


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
    st.plotly_chart(fig, width='stretch')


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
    fig.add_vline(x=0, line=dict(color=BORDER_COLOR, width=1))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
        font=dict(color=TEXT_PRIMARY, family="Inter"),
        xaxis=dict(gridcolor=_rgba(BORDER_COLOR, 0.2), tickprefix="$"),
        yaxis=dict(gridcolor="rgba(0,0,0,0)"),
        margin=dict(l=0, r=40, t=10, b=0),
        height=max(220, len(combined) * 36),
        showlegend=False,
    )
    st.plotly_chart(fig, width='stretch')


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

    show_storage_banner()

    # Storage indicator + controls row
    storage = "Google Sheets ✅" if using_google_sheets() else "⚠️ Local CSV (ephemeral — lost on restart)"
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

    # ── Positions table with inline delete ────────────────────
    # Suppress default gap between columns for tighter rows
    st.markdown(
        "<style>"
        "div[data-testid='stHorizontalBlock']{gap:0 !important;margin-bottom:0 !important}"
        "div[data-testid='stHorizontalBlock'] > div[data-testid='stColumn']"
        "{padding-top:1px !important;padding-bottom:1px !important}"
        "</style>",
        unsafe_allow_html=True,
    )

    import re as _re, hashlib as _hl

    # Strategy classification
    _OPT_STRATS = {"CSP", "CC", "LEAPS", "ETF OPTIONS", "3X ETF OPTIONS", "DIVIDEND+CC"}
    _STRATEGY_ORDER_OPT  = ["CSP", "CC", "LEAPS", "ETF Options", "3x ETF Options", "Dividend+CC"]
    _STRATEGY_ORDER_STK  = ["Golden Scan", "Momentum", "Stock", "Value", "Growth"]

    df["_strat_up"] = df["Strategy"].astype(str).str.upper().str.strip()
    opt_df = df[df["_strat_up"].isin(_OPT_STRATS)].copy()
    stk_df = df[~df["_strat_up"].isin(_OPT_STRATS)].copy()

    # Sort each section by strategy order then Added_Date desc
    def _sort_by_strat(sub: pd.DataFrame, order: list) -> pd.DataFrame:
        order_map = {s.upper(): i for i, s in enumerate(order)}
        sub = sub.copy()
        sub["_sort_key"] = sub["Strategy"].astype(str).str.upper().map(order_map).fillna(99)
        return sub.sort_values(["_sort_key", "Added_Date"], ascending=[True, False]).drop(columns=["_sort_key"])

    opt_df = _sort_by_strat(opt_df, _STRATEGY_ORDER_OPT)
    stk_df = _sort_by_strat(stk_df, _STRATEGY_ORDER_STK)

    def _render_section(section_df: pd.DataFrame, section_label: str,
                        label_color: str, section_key: str,
                        is_options: bool):
        """Render one section (Options or Stocks) with header rows and delete buttons."""
        if section_df.empty:
            return

        st.markdown(
            f'<div style="color:{label_color};font-size:13px;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:1px;'
            f'border-left:3px solid {label_color};padding:6px 10px;'
            f'background:{BG_PANEL};margin:16px 0 6px;border-radius:0 4px 4px 0">'
            f'{section_label}</div>',
            unsafe_allow_html=True,
        )

        # ── Sort control ─────────────────────────────────────────
        _sort_opts_base = ["Added (Latest)", "Score ↓", "P&L $ ↓", "P&L % ↓", "Ticker A→Z", "Strategy"]
        _sort_key_ss    = f"trk_sort_{section_key}"
        if _sort_key_ss not in st.session_state:
            st.session_state[_sort_key_ss] = "Added (Latest)"

        _ts1, _ts2 = st.columns([0.5, 3])
        with _ts1:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:11px;padding:7px 0;white-space:nowrap">↕ Sort:</div>',
                unsafe_allow_html=True,
            )
        with _ts2:
            _sort_choice = st.selectbox(
                "Sort tracking", _sort_opts_base,
                index=_sort_opts_base.index(st.session_state[_sort_key_ss]),
                key=f"trk_sort_sel_{section_key}",
                label_visibility="collapsed",
            )
        st.session_state[_sort_key_ss] = _sort_choice

        # Apply sort to section_df
        section_df = section_df.copy()
        if _sort_choice == "Score ↓":
            section_df["__sc"] = pd.to_numeric(section_df.get("Score", pd.Series(dtype=float)), errors="coerce").fillna(0)
            section_df = section_df.sort_values("__sc", ascending=False).drop(columns=["__sc"])
        elif _sort_choice == "P&L $ ↓":
            section_df = section_df.sort_values("PnL_$", ascending=False, na_position="last")
        elif _sort_choice == "P&L % ↓":
            section_df = section_df.sort_values("PnL_%", ascending=False, na_position="last")
        elif _sort_choice == "Ticker A→Z":
            section_df = section_df.sort_values("Ticker")
        elif _sort_choice == "Strategy":
            section_df = section_df.sort_values(["Strategy", "Added_Date"], ascending=[True, False])
        # else "Added (Latest)": already sorted by _sort_by_strat above

        if is_options:
            # Options: Ticker | Strategy | Action | Strike | Entry | Current | P&L | Score | Added | Source | 🗑
            _W = [1.0, 0.9, 0.5, 0.65, 0.65, 0.7, 1.05, 0.5, 0.75, 1.3, 0.35]
            _H = ["Ticker", "Strategy", "Action", "Strike", "Premium", "Current $", "P&L (est.)", "Score", "Added", "Source", ""]
        else:
            # Stocks: Ticker | Strategy | Entry | Current | P&L | Score | Added | Source | 🗑
            _W = [1.1, 1.1, 0.75, 0.75, 1.1, 0.55, 0.85, 1.6, 0.38]
            _H = ["Ticker", "Strategy", "Entry $", "Current $", "P&L (est.)", "Score", "Added", "Source", ""]

        # Header row
        hdr = st.columns(_W)
        for col_i, label in enumerate(_H):
            with hdr[col_i]:
                st.markdown(
                    f'<div style="color:{GOLD};font-size:10px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:0.7px;'
                    f'padding:6px 6px 4px;border-bottom:2px solid {GOLD}55;'
                    f'white-space:nowrap">{label}</div>',
                    unsafe_allow_html=True,
                )

        _del_key_base = _hl.md5(f"tracking_{section_key}".encode()).hexdigest()[:6]

        for row_i, (_, row) in enumerate(section_df.iterrows()):
            bg    = BG_CARD if row_i % 2 == 0 else BG_PANEL
            ep    = row["Entry_Price"]
            cp    = row["Current_Price"]
            pnl   = row["PnL_$"]
            ppct  = row["PnL_%"]
            tk    = str(row.get("Ticker", "")).upper().strip()
            added = str(row.get("Added_Date", ""))[:10]
            score = str(row.get("Score", "")).strip() or "—"
            strat = str(row.get("Strategy", ""))
            action = str(row.get("Action", ""))
            src   = str(row.get("Source", ""))[:30]
            a_color = ACCENT_GREEN if action == "Buy" else ACCENT_RED
            td_bg = f"background:{bg};padding:7px 6px;border-bottom:1px solid {BORDER_COLOR}33"

            ep_str = f"${ep:.2f}" if pd.notna(ep) else "—"
            cp_str = f"${cp:.2f}" if pd.notna(cp) else "—"
            pnl_html = _pnl_html(pnl, ppct) if pd.notna(pnl) else '<span style="color:#555">—</span>'

            row_cols = st.columns(_W)

            if is_options:
                # pull Strike / Premium from Qty field or Notes if present
                strike  = str(row.get("Strike", "")).strip() or "—"
                premium = ep_str  # Entry_Price holds the premium for options
                cells_data = [
                    f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700;font-size:13px">{tk}</span>',
                    f'<span style="color:{TEXT_MUTED};font-size:12px">{strat}</span>',
                    f'<span style="color:{a_color};font-size:12px;font-weight:600">{action}</span>',
                    f'<span style="color:{TEXT_MUTED};font-family:\'DM Mono\',monospace;font-size:12px">{strike}</span>',
                    f'<span style="color:{ACCENT_BLUE};font-family:\'DM Mono\',monospace;font-size:12px">{premium}</span>',
                    f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;font-size:12px">{cp_str}</span>',
                    pnl_html,
                    f'<span style="color:{GOLD};font-size:12px">{score}</span>',
                    f'<span style="color:{TEXT_MUTED};font-size:11px">{added}</span>',
                    f'<span style="color:{TEXT_MUTED};font-size:11px" title="{src}">{src}</span>',
                ]
            else:
                cells_data = [
                    f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700;font-size:13px">{tk}</span>',
                    f'<span style="color:{TEXT_MUTED};font-size:12px">{strat}</span>',
                    f'<span style="color:{TEXT_MUTED};font-family:\'DM Mono\',monospace;font-size:12px">{ep_str}</span>',
                    f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;font-size:12px">{cp_str}</span>',
                    pnl_html,
                    f'<span style="color:{GOLD};font-size:12px">{score}</span>',
                    f'<span style="color:{TEXT_MUTED};font-size:11px">{added}</span>',
                    f'<span style="color:{TEXT_MUTED};font-size:11px" title="{src}">{src}</span>',
                ]

            for col_i, html in enumerate(cells_data):
                with row_cols[col_i]:
                    st.markdown(f'<div style="{td_bg}">{html}</div>', unsafe_allow_html=True)

            # Inline delete button (last column)
            _safe_tk = _re.sub(r"[^a-zA-Z0-9]", "_", tk)
            with row_cols[-1]:
                st.button(
                    "🗑",
                    key=f"del_{_del_key_base}_{row_i}_{_safe_tk}",
                    help=f"Remove {tk} ({added}) from tracking",
                    use_container_width=True,
                    on_click=_cb_delete_tracking,
                    args=(tk, added),
                )

    # ── Render Options section then Stocks section ─────────────
    _render_section(opt_df, "⚙️ Options Positions — CSP · CC · LEAPS",
                    "#A78BFA", "options", is_options=True)
    _render_section(stk_df, "📈 Stock Positions — Golden Scan · Momentum · Stock",
                    ACCENT_GREEN, "stocks", is_options=False)

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:6px">'
        f'P&L estimated: stocks = 100 shares · options = 1 contract. Not actual P&L.</div>',
        unsafe_allow_html=True,
    )

    # ── Export ─────────────────────────────────────────────────
    export_cols = ["Ticker","Strategy","Action","Qty","Entry_Price","Current_Price","PnL_$","PnL_%","Score","Added_Date","Source"]
    export_cols = [c for c in export_cols if c in df.columns]
    st.download_button(
        "⬇ Export Tracking CSV",
        df[export_cols].to_csv(index=False),
        _export_filename("tracking"), "text/csv",
    )
