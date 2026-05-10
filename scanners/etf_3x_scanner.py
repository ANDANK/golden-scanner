# pages/etf_3x_scanner.py — 3× Leveraged ETF Momentum

import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import get_price_history


LEVERAGE_INFO = {
    "TQQQ": ("QQQ", "NASDAQ 100 Bull 3×", "bullish"),
    "SOXL": ("SOXX", "Semiconductors Bull 3×", "bullish"),
    "UPRO": ("SPY", "S&P 500 Bull 3×", "bullish"),
    "SPXL": ("SPY", "S&P 500 Bull 3×", "bullish"),
    "TECL": ("XLK", "Tech Bull 3×", "bullish"),
    "FNGU": ("FNGS", "Tech Giants Bull 3×", "bullish"),
    "LABU": ("XBI", "Biotech Bull 3×", "bullish"),
    "FAS":  ("XLF", "Financials Bull 3×", "bullish"),
    "TNA":  ("IWM", "Small Cap Bull 3×", "bullish"),
    "NAIL": ("ITB", "Homebuilders Bull 3×", "bullish"),
    "SQQQ": ("QQQ", "NASDAQ 100 Bear 3×", "bearish"),
    "SOXS": ("SOXX", "Semiconductors Bear 3×", "bearish"),
    "SPXS": ("SPY", "S&P 500 Bear 3×", "bearish"),
    "TECS": ("XLK", "Tech Bear 3×", "bearish"),
    "FNGD": ("FNGS", "Tech Giants Bear 3×", "bearish"),
    "FAZ":  ("XLF", "Financials Bear 3×", "bearish"),
    "TZA":  ("IWM", "Small Cap Bear 3×", "bearish"),
}


def scan_3x_etfs(tickers, rsi_min, rsi_max, vol_mult, price_min, direction_filter):

    with st.spinner("Scanning 3× leveraged ETFs for directional momentum…"):
        results = []
        progress = st.progress(0)

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers))
            try:
                info = LEVERAGE_INFO.get(ticker, (ticker, "3× ETF", "bullish"))
                direction = info[2]

                if direction_filter != "Both" and direction != direction_filter.lower():
                    continue

                df = get_price_history(ticker, period="3mo")
                if df.empty or len(df) < 21:
                    continue

                close = df["Close"].squeeze()
                volume = df["Volume"].squeeze()
                price = float(close.iloc[-1])

                if price < price_min:
                    continue

                sma20 = float(calc_sma(close, 20).iloc[-1])
                sma50 = float(calc_sma(close, 50).iloc[-1]) if len(close) >= 50 else sma20

                rsi = calc_rsi(close)
                if not (rsi_min <= rsi <= rsi_max):
                    continue

                if price < sma20:
                    continue

                avg_vol = float(volume.iloc[:-1].rolling(20).mean().dropna().iloc[-1]) if len(volume) > 20 else float(volume.mean())
                curr_vol = float(volume.iloc[-1])
                vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 0

                if vol_ratio < vol_mult:
                    continue

                _, _, hist = calc_macd(close)
                atr_pct = calc_atr(df)
                atr_exp = atr_expanding(df)

                prev = float(close.iloc[-2]) if len(close) > 1 else price
                chg_pct = (price - prev) / prev * 100

                # Trend intensity
                intensity_score = 0
                if price > sma20 > sma50:         intensity_score += 35
                elif price > sma20:               intensity_score += 20
                if rsi_min <= rsi <= rsi_max:     intensity_score += 20
                if hist > 0:                      intensity_score += 20
                if vol_ratio >= 2.0:              intensity_score += 15
                elif vol_ratio >= 1.5:            intensity_score += 10
                if atr_exp:                       intensity_score += 10
                intensity_score = min(intensity_score, 100)

                # Volatility warning
                vol_warn = "⚠️ High Vol" if atr_pct > 5 else ("✅ Normal" if atr_pct < 3 else "🟡 Elevated")

                results.append({
                    "Ticker":      ticker,
                    "Name":        info[1],
                    "Direction":   "🟢 Bull" if direction == "bullish" else "🔴 Bear",
                    "Price":       round(price, 2),
                    "Change %":    round(chg_pct, 2),
                    "RSI":         round(rsi, 1),
                    ">20 SMA":     "✅" if price > sma20 else "❌",
                    ">50 SMA":     "✅" if price > sma50 else "❌",
                    "MACD Bull":   "✅" if hist > 0 else "❌",
                    "Vol Ratio":   round(vol_ratio, 2),
                    "ATR %":       round(atr_pct, 2),
                    "ATR Expand":  "✅" if atr_exp else "—",
                    "Vol Warning": vol_warn,
                    "Score":       intensity_score,
                })
            except Exception:
                continue

        progress.empty()

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


def render():
    section_header("⚡📊", "3× Leveraged ETFs",
                   "High-conviction directional momentum · Price > 20 & 50 SMA · Rising ATR")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ 3× ETF Filters</div>', unsafe_allow_html=True)
        direction_filter = st.selectbox("Direction", ["Both", "Bullish", "Bearish"])
        rsi_min, rsi_max = st.slider("RSI Range", 30, 85, (55, 70))
        vol_mult  = st.slider("Min Volume Multiplier", 1.0, 5.0, 1.25, 0.05)
        price_min = st.number_input("Min Price ($)", 1.0, 50.0, 5.0)

    col1, col2 = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        df = scan_3x_etfs(ETF_3X_UNIVERSE, rsi_min, rsi_max, vol_mult, price_min, direction_filter)
        st.session_state["_3x_r"] = df

    _3x_r = st.session_state.get("_3x_r")
    if _3x_r is not None:
        df = _3x_r
        if df.empty:
            empty_state("No 3× ETF setups found. Adjust RSI or volume filter.")
        else:
            col1, col2, col3, col4 = st.columns(4)
            with col1: metric_card("Setups Found", str(len(df)), color=GOLD)
            with col2:
                bulls = (df["Direction"] == "🟢 Bull").sum()
                metric_card("Bullish", str(bulls), color=ACCENT_GREEN)
            with col3:
                bears = (df["Direction"] == "🔴 Bear").sum()
                metric_card("Bearish", str(bears), color=ACCENT_RED)
            with col4: metric_card("Avg Score", f"{df['Score'].mean():.0f}/100", color=GOLD)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df, strategy="3x ETF", source="3x Leveraged ETFs")

            st.markdown(
                f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-left:3px solid {ACCENT_RED};'
                f'border-radius:6px;padding:12px 16px;margin-top:16px;color:{TEXT_MUTED};font-size:12px">'
                f'&#9888;&#65039; <b>Risk Warning:</b> 3&times; leveraged ETFs experience volatility decay over time &mdash; '
                f'they are designed for <b>short-term directional trades only</b>. '
                f'Never hold through high-volatility periods or overnight without conviction. '
                f'ATR Warning column indicates current volatility level.</div>',
                unsafe_allow_html=True,
            )

            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;margin:20px 0 6px">&#128200; Charts &amp; Price History</div>',
                unsafe_allow_html=True,
            )
            for idx, (_, row) in enumerate(df.iterrows()):
                ticker    = str(row["Ticker"])
                name      = str(row.get("Name", ""))
                direction = str(row.get("Direction", ""))
                chg       = float(row.get("Change %", 0))
                score     = int(row.get("Score", 0))
                label     = f"📈  {ticker}   ·   {name}   ·   {direction}   ·   {chg:+.2f}%   ·   Score {score}/100"
                with st.expander(label, expanded=(idx == 0)):
                    df_c = get_price_history(ticker, period="3mo")
                    if not df_c.empty:
                        st.plotly_chart(mini_chart(df_c, ticker), use_container_width=True)
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">⚡</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">3× Leveraged ETF Momentum Finder</div>
            <div style="font-size:13px">Short-term high-velocity directional plays.<br>Criteria: Price > 20/50 SMA · RSI {rsi_min}–{rsi_max} · Volume ≥ {vol_mult}×</div>
        </div>""", unsafe_allow_html=True)
