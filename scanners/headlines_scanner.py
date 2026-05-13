# pages/headlines_scanner.py — News-Driven Movers & Catalysts

import streamlit as st
import pandas as pd
import yfinance as yf
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import get_price_history, get_batch_quotes, YF_SESSION


@st.cache_data(ttl=180, show_spinner=False)
def get_news(ticker: str):
    try:
        t = yf.Ticker(ticker, session=YF_SESSION)
        news = t.news
        return news[:5] if news else []
    except Exception:
        return []


def scan_headlines(tickers, move_min, vol_spike_min, gap_filter):
    with st.spinner(f"Scanning {len(tickers)} tickers for news catalysts…"):
        results = []
        progress = st.progress(0)

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers))
            try:
                df = get_price_history(ticker, period="5d")
                if df.empty or len(df) < 2:
                    continue

                close = df["Close"].squeeze()
                volume = df["Volume"].squeeze()
                open_p = df["Open"].squeeze()

                price = float(close.iloc[-1])
                prev_close = float(close.iloc[-2])
                chg_pct = (price - prev_close) / prev_close * 100

                if abs(chg_pct) < move_min:
                    continue

                avg_vol = float(volume.iloc[:-1].mean()) if len(volume) > 1 else float(volume.iloc[-1])
                curr_vol = float(volume.iloc[-1])
                vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 0

                if vol_ratio < vol_spike_min:
                    continue

                # Gap detection
                gap_pct = (float(open_p.iloc[-1]) - prev_close) / prev_close * 100 if prev_close else 0
                has_gap = abs(gap_pct) >= 1.5

                if gap_filter and not has_gap:
                    continue

                rsi = calc_rsi(close)
                atr_pct = calc_atr(df)

                # Catalyst tags (heuristic)
                tags = []
                if abs(chg_pct) >= 10: tags.append("🔥 Mega Move")
                elif abs(chg_pct) >= 5: tags.append("⚡ Major Move")
                if has_gap: tags.append("📊 Gap")
                if vol_ratio >= 5: tags.append("🌊 Volume Surge")
                if not tags: tags.append("📰 News")

                direction = "🟢 Bullish" if chg_pct >= 0 else "🔴 Bearish"

                results.append({
                    "Ticker":     ticker,
                    "Price":      round(price, 2),
                    "Change %":   round(chg_pct, 2),
                    "Vol Ratio":  round(vol_ratio, 2),
                    "Gap %":      round(gap_pct, 2),
                    "RSI":        round(rsi, 1),
                    "ATR %":      round(atr_pct, 2),
                    "Direction":  direction,
                    "Catalysts":  " · ".join(tags),
                })
            except Exception:
                continue

        progress.empty()

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out["Abs Move"] = df_out["Change %"].abs()
        df_out = df_out.sort_values("Abs Move", ascending=False).drop("Abs Move", axis=1).reset_index(drop=True)
    return df_out


def render():
    section_header("📰", "Headlines & Catalysts",
                   "News-driven price moves · Volume spikes · Gap detection · Catalyst tagging")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ Headlines Filters</div>', unsafe_allow_html=True)
        move_min    = st.slider("Min Price Move (%)", 1.0, 15.0, 3.0, 0.5)
        vol_spike   = st.slider("Min Volume Spike (×avg)", 1.0, 10.0, 1.25, 0.05)
        gap_filter  = st.checkbox("Gaps only (≥1.5%)", False)
        universe_size = st.slider("Universe Size", 20, len(SP500_SAMPLE), 200, 10)

    tickers = SP500_SAMPLE[:universe_size]

    col1, col2 = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        df = scan_headlines(tickers, move_min, vol_spike, gap_filter)
        st.session_state["_hdl_r"] = df
    from data_loader import show_api_warnings; show_api_warnings()

    _hdl_r = st.session_state.get("_hdl_r")
    if _hdl_r is not None:
        df = _hdl_r
        if df.empty:
            empty_state("No headline movers found. Lower the Move % or Volume Spike threshold.")
        else:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                metric_card("Movers Found", str(len(df)), color=GOLD)
            with col2:
                bulls = (df["Direction"] == "🟢 Bullish").sum()
                metric_card("Bullish", str(bulls), color=ACCENT_GREEN)
            with col3:
                bears = (df["Direction"] == "🔴 Bearish").sum()
                metric_card("Bearish", str(bears), color=ACCENT_RED)
            with col4:
                max_move = df["Change %"].abs().max()
                metric_card("Biggest Move", f"{max_move:.1f}%", color=GOLD)

            st.markdown("<br>", unsafe_allow_html=True)

            top = df.iloc[0]
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">🔥 Biggest Mover — Recent Headlines</div>', unsafe_allow_html=True)

            news = get_news(top["Ticker"])
            chg_color = ACCENT_GREEN if top["Change %"] >= 0 else ACCENT_RED

            st.markdown(f"""
            <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:8px;padding:16px 20px;margin-bottom:16px">
                <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:12px">
                    <span style="color:{GOLD};font-size:24px;font-family:'Cormorant Garamond',serif;font-weight:700">{top['Ticker']}</span>
                    <span style="color:{TEXT_PRIMARY};font-size:18px">${top['Price']:.2f}</span>
                    <span style="color:{chg_color};font-size:16px;font-weight:600">{top['Change %']:+.2f}%</span>
                    <span style="color:{TEXT_MUTED};font-size:12px">{top['Catalysts']}</span>
                </div>
                {''.join([f'<div style="padding:6px 0;border-bottom:1px solid {BORDER_COLOR};color:{TEXT_PRIMARY};font-size:13px">📰 {n.get("title","")}</div>' for n in news[:3]]) if news else f'<div style="color:{TEXT_MUTED};font-size:13px">No headlines available via API.</div>'}
            </div>""", unsafe_allow_html=True)

            render_results_table(df, strategy="Stock", source="Headlines & Catalysts")
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">📰</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">Catalyst & Headline Mover Detector</div>
            <div style="font-size:13px">Finds stocks making major moves on news.<br>Criteria: Move &gt; {move_min}% · Volume Spike ≥ {vol_spike}× · Gap Detection</div>
        </div>""", unsafe_allow_html=True)
