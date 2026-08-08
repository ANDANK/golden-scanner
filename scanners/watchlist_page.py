# scanners/watchlist_page.py — WatchList page

import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header, metric_card, _export_filename
from scanners.gsheet_helper import (get_watchlist, remove_from_watchlist,
                                     add_to_tracking, using_google_sheets, show_storage_banner)


@st.cache_data(ttl=180, show_spinner=False)
def _fetch_prices(tickers: tuple) -> dict:
    if not tickers:
        return {}
    try:
        import yfinance as yf
        prices, changes = {}, {}
        data = yf.download(list(tickers), period="2d", auto_adjust=True,
                           progress=False, group_by="ticker")
        for t in tickers:
            try:
                close = data["Close"] if len(tickers) == 1 else data[t]["Close"]
                close = close.dropna()
                if len(close) >= 2:
                    prices[t]  = round(float(close.iloc[-1]), 2)
                    changes[t] = round((close.iloc[-1] / close.iloc[-2] - 1) * 100, 2)
                elif len(close) == 1:
                    prices[t]  = round(float(close.iloc[-1]), 2)
                    changes[t] = 0.0
            except Exception:
                pass
        return {"prices": prices, "changes": changes}
    except Exception:
        return {"prices": {}, "changes": {}}


def render():
    section_header("👁", "WatchList", "Tickers on your radar — not yet in a position")

    tab1, tab2 = st.tabs(["👁 My WatchList", "🗳️ Election Playbook 2026"])
    with tab1:
        _render_my_watchlist()
    with tab2:
        from scanners.election_playbook import render as _render_election_playbook
        _render_election_playbook()


def _render_my_watchlist():
    show_storage_banner()

    storage = "Google Sheets ✅" if using_google_sheets() else "⚠️ Local CSV (ephemeral — lost on restart)"
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:12px">'
        f'Storage: <b style="color:{GOLD}">{storage}</b></div>',
        unsafe_allow_html=True,
    )

    rows = get_watchlist()
    if not rows:
        st.markdown(
            f'<div style="text-align:center;padding:60px 20px;color:{TEXT_MUTED}">'
            f'<div style="font-size:48px;margin-bottom:16px">👁</div>'
            f'<div style="font-size:16px">Your WatchList is empty.</div>'
            f'<div style="font-size:13px;margin-top:8px">Click <b>👁 Watch</b> on any scanner results to add.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    df = pd.DataFrame(rows)
    df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
    df["Price_At_Add"] = pd.to_numeric(df["Price_At_Add"], errors="coerce")

    # Fetch live prices + daily change
    tickers_tuple = tuple(df["Ticker"].unique().tolist())
    with st.spinner("Fetching live prices…"):
        result  = _fetch_prices(tickers_tuple)
    price_map  = result.get("prices", {})
    change_map = result.get("changes", {})

    df["Current_Price"] = df["Ticker"].map(price_map)
    df["Change_Today%"] = df["Ticker"].map(change_map)
    df["Current_Price"] = pd.to_numeric(df["Current_Price"], errors="coerce")
    df["Change_Today%"] = pd.to_numeric(df["Change_Today%"], errors="coerce")
    df["Since_Add%"] = ((df["Current_Price"] - df["Price_At_Add"]) / df["Price_At_Add"] * 100).round(2)

    # ── Summary metrics ───────────────────────────────────────
    total   = len(df)
    gainers = int((df["Change_Today%"] > 0).sum())
    losers  = int((df["Change_Today%"] < 0).sum())
    movers  = df["Change_Today%"].abs().nlargest(1)
    top_mover = df.loc[movers.index[0], "Ticker"] if not movers.empty else "—"

    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("Watching", str(total))
    with c2: metric_card("Up Today",   str(gainers), color=ACCENT_GREEN)
    with c3: metric_card("Down Today", str(losers),  color=ACCENT_RED)
    with c4: metric_card("Top Mover",  top_mover,    color=GOLD)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Table ─────────────────────────────────────────────────
    header_cols = ["Ticker","Added","Price When Added","Current","Today %","Since Add %","Source"]
    header_html = "".join(
        f'<th style="background:{BG_PANEL};color:{GOLD};font-size:11px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.8px;padding:10px 14px;'
        f'border-bottom:2px solid {GOLD}44;white-space:nowrap">{c}</th>'
        for c in header_cols
    )

    def _pct_html(val):
        if pd.isna(val):
            return '<span style="color:#6B7280">—</span>'
        color = ACCENT_GREEN if val >= 0 else ACCENT_RED
        arrow = "▲" if val >= 0 else "▼"
        return f'<span style="color:{color};font-weight:600">{arrow} {abs(val):.2f}%</span>'

    row_htmls = []
    for i, (_, row) in enumerate(df.iterrows()):
        bg  = BG_CARD if i % 2 == 0 else BG_PANEL
        cp  = row["Current_Price"]
        pad = row["Price_At_Add"]
        cells = [
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700">{row["Ticker"]}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{TEXT_MUTED};font-size:11px">{str(row.get("Added_Date",""))[:10]}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{TEXT_MUTED};font-family:\'DM Mono\',monospace;font-size:12px">'
            f'{"${:.2f}".format(pad) if pd.notna(pad) else "—"}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;font-size:12px">'
            f'{"${:.2f}".format(cp) if pd.notna(cp) else "—"}</span></td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'{_pct_html(row["Change_Today%"])}</td>',
            f'<td style="padding:8px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">'
            f'{_pct_html(row["Since_Add%"])}</td>',
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

    # ── Move to Tracking ──────────────────────────────────────
    st.markdown("---")
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Move to Tracking</div>',
        unsafe_allow_html=True,
    )
    m1, m2, m3 = st.columns([3, 2, 1])
    with m1:
        to_move = st.selectbox(
            "ticker", [""] + df["Ticker"].tolist(),
            label_visibility="collapsed",
            key="wl_move_sel",
            placeholder="Choose ticker to move…",
        )
    with m2:
        strategy_opt = st.selectbox(
            "strategy", ["Stock","CSP","CC","LEAPS","ETF Options","3x ETF","3x ETF Options","Dividend"],
            label_visibility="collapsed",
            key="wl_move_strategy",
        )
    with m3:
        if st.button("📌 Track", key="wl_move_btn", use_container_width=True):
            if to_move:
                ok, msg = add_to_tracking(to_move, strategy_opt, source="WatchList")
                if ok:
                    remove_from_watchlist(to_move)
                    st.success(f"{to_move} moved to Tracking as {strategy_opt}.")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.warning(msg)
            else:
                st.warning("Select a ticker first.")

    # ── Remove from WatchList ─────────────────────────────────
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:1px;margin:12px 0 8px">Remove from WatchList</div>',
        unsafe_allow_html=True,
    )
    r1, r2 = st.columns([4, 1])
    with r1:
        to_remove = st.selectbox(
            "remove ticker", [""] + df["Ticker"].tolist(),
            label_visibility="collapsed",
            key="wl_remove_sel",
            placeholder="Choose ticker to remove…",
        )
    with r2:
        if st.button("🗑 Remove", key="wl_remove_btn", use_container_width=True):
            if to_remove:
                if remove_from_watchlist(to_remove):
                    st.success(f"{to_remove} removed from WatchList.")
                    st.cache_data.clear()
                    st.rerun()
            else:
                st.warning("Select a ticker first.")

    # ── Export ────────────────────────────────────────────────
    export_df = df[["Ticker","Added_Date","Price_At_Add","Current_Price",
                     "Change_Today%","Since_Add%","Source"]].copy()
    st.download_button(
        "⬇ Export WatchList CSV",
        export_df.to_csv(index=False),
        _export_filename("watchlist"), "text/csv",
    )
