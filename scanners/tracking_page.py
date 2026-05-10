# scanners/tracking_page.py — Tracked Positions page

import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header, metric_card
from scanners.gsheet_helper import get_tracking, remove_from_tracking, using_google_sheets


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
                if len(tickers) == 1:
                    close = data["Close"]
                else:
                    close = data[t]["Close"]
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


def render():
    section_header("📌", "Tracking", "Positions you are actively monitoring")

    # Storage indicator
    storage = "Google Sheets" if using_google_sheets() else "Local CSV (data/tracking.csv)"
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:12px">'
        f'Storage: <b style="color:{GOLD}">{storage}</b></div>',
        unsafe_allow_html=True,
    )

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
    df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
    df["Entry_Price"] = pd.to_numeric(df["Entry_Price"], errors="coerce")

    # Fetch live prices
    tickers_tuple = tuple(df["Ticker"].unique().tolist())
    with st.spinner("Fetching live prices…"):
        prices = _fetch_prices(tickers_tuple)

    df["Current_Price"] = df["Ticker"].map(prices)
    df["Current_Price"] = pd.to_numeric(df["Current_Price"], errors="coerce")

    # P&L — stocks = 100 shares; options = show underlying % only
    def _row_pnl(row):
        ep = row["Entry_Price"]
        cp = row["Current_Price"]
        if pd.isna(ep) or pd.isna(cp) or ep == 0:
            return None, None
        pct = (cp - ep) / ep * 100
        strategy = str(row.get("Strategy",""))
        is_option = strategy in {"CSP","CC","LEAPS","ETF Options","3x ETF Options","Dividend+CC"}
        if is_option:
            # For sell strategies (CSP/CC), positive underlying move hurts
            multiplier = -1 if strategy in {"CSP","CC","Dividend+CC","ETF Options"} else 1
            dollar = round(multiplier * (cp - ep) * 100, 2)  # 1 contract ≈ 100-share delta
        else:
            dollar = round((cp - ep) * 100, 2)
        return round(dollar, 2), round(pct, 2)

    df[["PnL_$","PnL_%"]] = df.apply(lambda r: pd.Series(_row_pnl(r)), axis=1)

    # ── Summary metrics ───────────────────────────────────────
    total_pnl    = df["PnL_$"].dropna().sum()
    winners      = int((df["PnL_$"].dropna() > 0).sum())
    losers       = int((df["PnL_$"].dropna() < 0).sum())
    open_pos     = len(df)

    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("Open Positions", str(open_pos))
    with c2: metric_card("Winners", str(winners), color=ACCENT_GREEN)
    with c3: metric_card("Losers",  str(losers),  color=ACCENT_RED)
    with c4:
        color = ACCENT_GREEN if total_pnl >= 0 else ACCENT_RED
        metric_card("Total P&L (est.)", f"${total_pnl:+,.0f}", color=color)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Table ─────────────────────────────────────────────────
    header_cols = ["Ticker","Strategy","Action","Qty","Entry","Current","P&L (est.)","Added","Source"]
    header_html = "".join(
        f'<th style="background:{BG_PANEL};color:{GOLD};font-size:11px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.8px;padding:10px 14px;'
        f'border-bottom:2px solid {GOLD}44;white-space:nowrap">{c}</th>'
        for c in header_cols
    )

    row_htmls = []
    for i, (_, row) in enumerate(df.iterrows()):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        ep   = row["Entry_Price"]
        cp   = row["Current_Price"]
        pnl  = row["PnL_$"]
        ppct = row["PnL_%"]

        ep_str  = f"${ep:.2f}"   if pd.notna(ep)  else "—"
        cp_str  = f"${cp:.2f}"   if pd.notna(cp)  else "—"
        pnl_str = _pnl_html(pnl, ppct) if pd.notna(pnl) else "—"

        cells = [
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700">{row["Ticker"]}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{TEXT_MUTED};font-size:12px">{row.get("Strategy","")}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{ACCENT_GREEN if str(row.get("Action","")) == "Buy" else ACCENT_RED};font-size:12px;font-weight:600">{row.get("Action","")}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{TEXT_PRIMARY};font-size:12px">{row.get("Qty","")}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{TEXT_MUTED};font-family:\'DM Mono\',monospace;font-size:12px">{ep_str}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;font-size:12px">{cp_str}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">{pnl_str}</td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{TEXT_MUTED};font-size:11px">{str(row.get("Added_Date",""))[:10]}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{TEXT_MUTED};font-size:11px">{row.get("Source","")}</span></td>',
        ]
        row_htmls.append(f'<tr>{"".join(cells)}</tr>')

    table_html = f"""
    <div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:8px;margin-top:8px">
      <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{"".join(row_htmls)}</tbody>
      </table>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:6px">'
        f'P&L is estimated: stocks = 100 shares · options = 1-contract underlying delta. '
        f'Not actual position P&L.</div>',
        unsafe_allow_html=True,
    )

    # ── Remove position ───────────────────────────────────────
    st.markdown("---")
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Remove Position</div>',
        unsafe_allow_html=True,
    )
    r1, r2 = st.columns([4, 1])
    with r1:
        to_remove = st.selectbox(
            "Select ticker to remove",
            options=[""] + df["Ticker"].tolist(),
            label_visibility="collapsed",
            key="tracking_remove_sel",
            placeholder="Choose ticker to remove…",
        )
    with r2:
        if st.button("🗑 Remove", key="tracking_remove_btn", use_container_width=True):
            if to_remove:
                if remove_from_tracking(to_remove):
                    st.success(f"{to_remove} removed from Tracking.")
                    st.cache_data.clear()
                    st.rerun()
            else:
                st.warning("Select a ticker first.")

    # ── Export ────────────────────────────────────────────────
    export_df = df[["Ticker","Strategy","Action","Qty","Entry_Price",
                     "Current_Price","PnL_$","PnL_%","Added_Date","Source"]].copy()
    st.download_button(
        "⬇ Export Tracking CSV",
        export_df.to_csv(index=False),
        "tracking.csv", "text/csv",
    )
