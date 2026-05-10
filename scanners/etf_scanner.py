# pages/etf_scanner.py — ETF Sector Rotation & Trend Finder

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import get_price_history, get_info


SECTOR_MAP = {
    "SPY": "Broad Market", "QQQ": "Technology", "IWM": "Small Cap",
    "DIA": "Dow Jones", "VTI": "Total Market", "VOO": "S&P 500",
    "GLD": "Gold", "SLV": "Silver", "TLT": "Long-Term Bonds", "HYG": "High Yield Bonds",
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Healthcare",
    "XLI": "Industrials", "XLU": "Utilities", "XLP": "Staples", "XLY": "Discretionary",
    "XLB": "Materials", "XLRE": "Real Estate",
    "EEM": "Emerging Mkts", "EFA": "International Dev.", "VEA": "Int'l Dev.",
    "VWO": "Emerging Mkts", "AGG": "Bonds Aggregate", "BND": "Total Bond",
    "LQD": "Corp Bonds", "MUB": "Muni Bonds", "VCIT": "Int Corp Bonds", "VCSH": "Short Corp",
    "ARKK": "Disruptive Innovation", "ARKW": "Next Gen Internet", "ARKG": "Genomic Rev.",
    "IYR": "Real Estate", "VNQ": "Real Estate", "JETS": "Airlines", "XRT": "Retail",
    "KRE": "Regional Banks", "IAT": "Banks", "SOXX": "Semiconductors",
}


def scan_etfs(tickers, rs_min, rsi_min, rsi_max, price_min):

    with st.spinner("Scanning ETFs for trend strength and sector rotation signals…"):
        spy_df = get_price_history("SPY", period="6mo")
        spy_close = spy_df["Close"].squeeze() if not spy_df.empty else pd.Series()

        results = []
        progress = st.progress(0)

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers))
            try:
                df = get_price_history(ticker, period="6mo")
                if df.empty or len(df) < 55:
                    continue

                close = df["Close"].squeeze()
                volume = df["Volume"].squeeze()
                price = float(close.iloc[-1])

                if price < price_min:
                    continue

                sma50  = float(calc_sma(close, 50).iloc[-1])
                sma200 = float(calc_sma(close, 200).iloc[-1]) if len(close) >= 200 else sma50 * 0.95

                if price < sma50:
                    continue

                rsi = calc_rsi(close)
                if not (rsi_min <= rsi <= rsi_max):
                    continue

                rs = calc_relative_strength(close, spy_close) if not spy_close.empty else 1.0
                if rs < rs_min:
                    continue

                _, _, hist = calc_macd(close)
                avg_vol = float(volume.iloc[:-1].rolling(20).mean().dropna().iloc[-1]) if len(volume) > 20 else float(volume.mean())
                curr_vol = float(volume.iloc[-1])
                vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 0
                atr_pct = calc_atr(df)

                prev = float(close.iloc[-2]) if len(close) > 1 else price
                chg_pct = (price - prev) / prev * 100

                trend = "Strong Bull" if price > sma50 > sma200 else "Bull"

                # Flow signal heuristic
                flow = "🟢 Inflows" if vol_ratio >= 1.3 and chg_pct >= 0 else ("🔴 Outflows" if vol_ratio >= 1.3 and chg_pct < 0 else "⚪ Neutral")

                score = 0
                if price > sma50 > sma200: score += 30
                elif price > sma50: score += 15
                if rsi_min <= rsi <= rsi_max: score += 20
                if rs >= 1.15: score += 25
                elif rs >= 1.05: score += 15
                if hist > 0: score += 15
                if vol_ratio >= 1.5: score += 10
                score = min(score, 100)

                results.append({
                    "Ticker":   ticker,
                    "Sector":   SECTOR_MAP.get(ticker, "Other"),
                    "Price":    round(price, 2),
                    "Change %": round(chg_pct, 2),
                    "RSI":      round(rsi, 1),
                    "RS vs SPY":round(rs, 3),
                    "MACD Bull":"✅" if hist > 0 else "❌",
                    "Vol Ratio":round(vol_ratio, 2),
                    "ATR %":    round(atr_pct, 2),
                    "Trend":    trend,
                    "Flow":     flow,
                    "Score":    score,
                })
            except Exception:
                continue

        progress.empty()

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


def render():
    section_header("📊", "ETF Trends",
                   "Sector rotation · Relative strength leaders · Volume-confirmed flows")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ ETF Filters</div>', unsafe_allow_html=True)
        rs_min   = st.slider("Min Relative Strength vs SPY", 0.80, 1.50, 1.02, 0.01)
        rsi_min, rsi_max = st.slider("RSI Range", 30, 85, (50, 70))
        price_min = st.number_input("Min ETF Price ($)", 1.0, 100.0, 5.0)

    col1, col2 = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        df = scan_etfs(ETF_UNIVERSE, rs_min, rsi_min, rsi_max, price_min)

        if df.empty:
            empty_state("No ETFs matched filters. Lower RS minimum or widen RSI range.")
        else:
            # Sector summary chart
            if "Sector" in df.columns and len(df) > 1:
                sector_scores = df.groupby("Sector")["Score"].mean().sort_values(ascending=False)
                fig = go.Figure(go.Bar(
                    x=sector_scores.values,
                    y=sector_scores.index,
                    orientation="h",
                    marker_color=[GOLD if s >= 70 else (ACCENT_BLUE if s >= 50 else TEXT_MUTED)
                                  for s in sector_scores.values],
                ))
                fig.update_layout(
                    title="Sector Strength (avg score)",
                    paper_bgcolor=BG_CARD, plot_bgcolor=BG_PANEL,
                    font_color=TEXT_PRIMARY, height=max(200, len(sector_scores) * 35),
                    margin=dict(l=10, r=10, t=40, b=10),
                    xaxis=dict(gridcolor=BORDER_COLOR, range=[0, 100]),
                    yaxis=dict(gridcolor=BORDER_COLOR),
                )
                st.plotly_chart(fig, use_container_width=True)

            col1, col2, col3 = st.columns(3)
            with col1: metric_card("ETFs Found", str(len(df)), color=GOLD)
            with col2: metric_card("Avg RS", f"{df['RS vs SPY'].mean():.3f}", color=ACCENT_GREEN)
            with col3:
                top_sector = df.groupby("Sector")["Score"].mean().idxmax() if "Sector" in df.columns else "—"
                metric_card("Top Sector", top_sector, color=ACCENT_BLUE)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df, strategy="ETF", source="ETF Scanner")

            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;margin:20px 0 6px">&#128200; Charts &amp; Price History</div>',
                unsafe_allow_html=True,
            )
            for idx, (_, row) in enumerate(df.iterrows()):
                ticker = str(row["Ticker"])
                chg    = float(row.get("Change %", 0))
                score  = int(row.get("Score", 0))
                sector = str(row.get("Sector", ""))
                label  = f"📈  {ticker}   ·   {sector}   ·   {chg:+.2f}%   ·   Score {score}/100"
                with st.expander(label, expanded=(idx == 0)):
                    df_c = get_price_history(ticker, period="6mo")
                    if not df_c.empty:
                        st.plotly_chart(mini_chart(df_c, ticker), use_container_width=True)
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">📊</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">ETF Trend & Rotation Finder</div>
            <div style="font-size:13px">Identify leading sectors and macro trends.<br>Criteria: Price > 50/200 SMA · RS ≥ {rs_min} · RSI {rsi_min}–{rsi_max}</div>
        </div>""", unsafe_allow_html=True)
