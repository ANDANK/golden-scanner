# pages/growth_scanner.py — Accelerating Growth Finder

import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import get_price_history, get_info


def scan_growth(tickers, rev_growth_min, eps_growth_min, rs_min, price_min, price_max):

    diag = ScanDiagnostics()

    with st.spinner(f"Scanning {len(tickers)} tickers for growth acceleration…"):
        spy_df = get_price_history("SPY", period="6mo")
        spy_close = spy_df["Close"].squeeze() if not spy_df.empty else pd.Series()

        results = []
        progress = st.progress(0)

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers))
            diag.seen(ticker)
            try:
                info = get_info(ticker)
                if not info:
                    diag.skipped(ticker, "no fundamental data"); continue

                # Revenue growth (YoY)
                rev_growth = (info.get("revenueGrowth") or 0) * 100
                eps_growth = (info.get("earningsGrowth") or 0) * 100

                if rev_growth < rev_growth_min:
                    diag.skipped(ticker, "rev growth too low"); continue
                if eps_growth < eps_growth_min:
                    diag.skipped(ticker, "EPS growth too low"); continue

                price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
                if not price or not (price_min <= price <= price_max):
                    diag.skipped(ticker, "price out of range"); continue

                df = get_price_history(ticker, period="6mo")
                if df.empty or len(df) < 55:
                    diag.skipped(ticker, "no price history"); continue

                close = df["Close"].squeeze()
                volume = df["Volume"].squeeze()
                sma50 = float(calc_sma(close, 50).iloc[-1])

                if price < sma50:
                    diag.skipped(ticker, "below SMA50"); continue

                rs = calc_relative_strength(close, spy_close) if not spy_close.empty else 1.0
                if rs < rs_min:
                    diag.skipped(ticker, "RS too low"); continue

                rsi = calc_rsi(close)
                macd_line, signal_line, hist = calc_macd(close)

                avg_vol = float(volume.iloc[:-1].rolling(20).mean().dropna().iloc[-1]) if len(volume) > 20 else float(volume.mean())
                curr_vol = float(volume.iloc[-1])
                vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 0

                atr_pct = calc_atr(df)

                # Growth acceleration: rev growth > eps growth = healthy top-line growth
                accel = "✅ Accelerating" if rev_growth > 20 and eps_growth > 15 else "📈 Growing"

                prev = float(close.iloc[-2]) if len(close) > 1 else price
                chg_pct = (price - prev) / prev * 100

                mcap = info.get("marketCap", 0) or 0
                mcap_str = f"${mcap/1e9:.1f}B" if mcap >= 1e9 else f"${mcap/1e6:.0f}M"
                sector = info.get("sector", "N/A")

                # Score
                score = 0
                if rev_growth >= 30: score += 25
                elif rev_growth >= 20: score += 18
                elif rev_growth >= 15: score += 10
                if eps_growth >= 25: score += 25
                elif eps_growth >= 15: score += 15
                if rs >= 1.15: score += 20
                elif rs >= 1.05: score += 12
                if price > sma50: score += 15
                if hist > 0: score += 10
                if vol_ratio >= 1.5: score += 5
                score = min(score, 100)

                results.append({
                    "Ticker":      ticker,
                    "Sector":      sector,
                    "Price":       round(price, 2),
                    "Change %":    round(chg_pct, 2),
                    "Rev Growth %": round(rev_growth, 1),
                    "EPS Growth %": round(eps_growth, 1),
                    "RS vs SPY":   round(rs, 3),
                    "RSI":         round(rsi, 1),
                    "MACD Bull":   "✅" if hist > 0 else "❌",
                    "Vol Ratio":   round(vol_ratio, 2),
                    "ATR %":       round(atr_pct, 2),
                    "Momentum":    accel,
                    "Mkt Cap":     mcap_str,
                    "Score":       score,
                })
                diag.passed(ticker)
            except Exception as e:
                diag.failed(ticker, type(e).__name__)
                continue

        progress.empty()

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out, diag


def render():
    section_header("🚀", "Growth",
                   "Revenue acceleration · EPS expansion · Relative strength leaders")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ Growth Filters</div>', unsafe_allow_html=True)
        rev_growth_min = st.slider("Min Revenue Growth (%)", 0, 100, 15)
        eps_growth_min = st.slider("Min EPS Growth (%)", 0, 100, 12)
        rs_min = st.slider("Min Relative Strength vs SPY", 0.80, 1.50, 1.02, 0.01)
        price_min = st.number_input("Min Price ($)", 1.0, 100.0, 10.0)
        price_max = st.number_input("Max Price ($)", 50.0, 5000.0, 3000.0)
        universe_size = st.slider("Universe Size", 20, len(SP500_SAMPLE), 200, 10)

    tickers = SP500_SAMPLE[:universe_size]

    col1, col2 = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        df, diag = scan_growth(tickers, rev_growth_min, eps_growth_min, rs_min, price_min, price_max)

        if df.empty:
            empty_state("No growth leaders found. Lower Rev/EPS thresholds or RS minimum.")
            diag.render(hide_when_clean=False)
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                metric_card("Results", str(len(df)), color=GOLD)
            with col2:
                metric_card("Avg Rev Growth", f"{df['Rev Growth %'].mean():.1f}%", color=ACCENT_GREEN)
            with col3:
                metric_card("Avg EPS Growth", f"{df['EPS Growth %'].mean():.1f}%", color=ACCENT_BLUE)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df, strategy="Stock", source="Growth Scanner")
            diag.render()

            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;margin:20px 0 6px">&#128200; Charts &amp; Price History</div>',
                unsafe_allow_html=True,
            )
            for idx, (_, row) in enumerate(df.iterrows()):
                ticker = str(row["Ticker"])
                chg    = float(row.get("Change %", 0))
                score  = int(row.get("Score", 0))
                label  = f"📈  {ticker}   ·   ${row['Price']:.2f}   ·   {chg:+.2f}%   ·   Score {score}/100"
                with st.expander(label, expanded=(idx == 0)):
                    df_c = get_price_history(ticker, period="6mo")
                    if not df_c.empty:
                        st.plotly_chart(mini_chart(df_c, ticker), use_container_width=True)
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">🚀</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">Growth Accelerators</div>
            <div style="font-size:13px">Finds companies with compounding revenue and earnings growth.<br>Criteria: Rev Growth &gt; {rev_growth_min}% · EPS Growth &gt; {eps_growth_min}% · RS &gt; {rs_min}</div>
        </div>""", unsafe_allow_html=True)
