# pages/momentum_scanner.py — Institutional Momentum

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import get_price_history, get_info, get_batch_quotes


def scan_momentum(tickers, rsi_min, rsi_max, vol_mult, price_min, price_max,
                  mcap_min, exclude_earnings_days):

    diag = ScanDiagnostics()

    with st.spinner(f"Scanning {len(tickers)} tickers for momentum setups…"):
        # Fetch benchmark for RS calculation
        spy_df = get_price_history("SPY", period="6mo")
        spy_close = spy_df["Close"].squeeze() if not spy_df.empty else pd.Series()

        results = []
        progress = st.progress(0)

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers))
            diag.seen(ticker)
            try:
                df = get_price_history(ticker, period="6mo")
                if df.empty or len(df) < 55:
                    diag.skipped(ticker, "no price history"); continue

                close = df["Close"].squeeze()
                volume = df["Volume"].squeeze()

                price = float(close.iloc[-1])
                if not (price_min <= price <= price_max):
                    diag.skipped(ticker, "price out of range"); continue

                # SMA
                sma50  = float(calc_sma(close, 50).iloc[-1])
                # Use sma50 as sma200 placeholder when history is short so
                # price > sma50 > sma200 never fires falsely (sma50 == sma200 → not >)
                sma200 = float(calc_sma(close, 200).iloc[-1]) if len(close) >= 200 else sma50

                # Only bullish trend
                if price < sma50:
                    diag.skipped(ticker, "below SMA50"); continue

                rsi = calc_rsi(close)
                if not (rsi_min <= rsi <= rsi_max):
                    diag.skipped(ticker, f"RSI {rsi:.0f} out of range"); continue

                macd_line, signal_line, hist = calc_macd(close)
                if hist <= 0:
                    diag.skipped(ticker, "MACD bearish"); continue

                # Volume
                avg_vol = float(volume.iloc[:-1].rolling(20).mean().dropna().iloc[-1]) if len(volume) > 20 else float(volume.mean())
                curr_vol = float(volume.iloc[-1])
                vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 0

                if vol_ratio < vol_mult:
                    diag.skipped(ticker, "volume too low"); continue

                # ATR
                atr_pct = calc_atr(df)
                atr_exp = atr_expanding(df)

                # 20-day high / breakout
                is_20dh = is_20d_high(close)

                # Relative Strength
                rs = calc_relative_strength(close, spy_close) if not spy_close.empty else 1.0

                # Fundamentals (market cap + earnings proximity filter)
                info = get_info(ticker)
                mcap = info.get("marketCap", 0) or 0
                if mcap > 0 and mcap < mcap_min:
                    diag.skipped(ticker, "market cap too small"); continue

                if exclude_earnings_days > 0:
                    raw_earn = info.get("earningsTimestamp") or info.get("nextEarningsDate")
                    if raw_earn:
                        try:
                            earn_date = (datetime.utcfromtimestamp(int(raw_earn)).date()
                                         if isinstance(raw_earn, (int, float))
                                         else datetime.strptime(str(raw_earn)[:10], "%Y-%m-%d").date())
                            days_to = (earn_date - datetime.utcnow().date()).days
                            if 0 <= days_to <= exclude_earnings_days:
                                diag.skipped(ticker, "earnings too close"); continue
                        except Exception:
                            pass

                mcap_str = f"${mcap/1e9:.1f}B" if mcap >= 1e9 else (f"${mcap/1e6:.0f}M" if mcap > 0 else "N/A")

                prev_close = float(close.iloc[-2]) if len(close) > 1 else price
                chg_pct = (price - prev_close) / prev_close * 100

                score = compute_momentum_score(
                    price, sma50, sma200, rsi, hist, vol_ratio, is_20dh, rs
                )

                trend = "Bullish" if price > sma50 > sma200 else ("Bullish Partial" if price > sma50 else "Bearish")

                results.append({
                    "Ticker":      ticker,
                    "Price":       round(price, 2),
                    "Change %":    round(chg_pct, 2),
                    "RSI":         round(rsi, 1),
                    "MACD Hist":   round(hist, 3),
                    "Vol Ratio":   round(vol_ratio, 2),
                    "20D High":    "✅" if is_20dh else "—",
                    "ATR %":       round(atr_pct, 2),
                    "ATR Expand":  "✅" if atr_exp else "—",
                    "RS vs SPY":   round(rs, 3),
                    "Trend":       trend,
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
    section_header("⚡", "Momentum",
                   "Institutional breakouts · Price > 50 SMA > 200 SMA · RSI sweet spot · Volume confirmed")

    # ── Sidebar Filters ────────────────────────────────────────
    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ Momentum Filters</div>', unsafe_allow_html=True)
        rsi_min, rsi_max = st.slider("RSI Range", 30, 85, (55, 68))
        vol_mult = st.slider("Min Volume Multiplier", 1.0, 5.0, 1.25, 0.05)
        price_min = st.number_input("Min Price ($)", 1.0, 500.0, 10.0, step=1.0)
        price_max = st.number_input("Max Price ($)", 10.0, 5000.0, 3000.0, step=50.0)
        mcap_min_b = st.slider("Min Market Cap ($B)", 0.0, 50.0, 1.0, 0.5)
        mcap_min = mcap_min_b * 1e9
        exclude_days = st.slider("Exclude Earnings Within (days)", 0, 30, 7)
        universe_size = st.slider("Universe Size (top N tickers)", 20, len(SP500_SAMPLE), 200, 10)

    tickers = SP500_SAMPLE[:universe_size]

    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)
    with col2:
        if st.button("🔄 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    if run:
        df, diag = scan_momentum(tickers, rsi_min, rsi_max, vol_mult, price_min, price_max,
                                 mcap_min, exclude_days)

        if df.empty:
            empty_state("No momentum setups found. Widen filters or expand universe.")
            diag.render(hide_when_clean=False)
        else:
            top = df.iloc[0]
            st.markdown(
                f'<div style="background:linear-gradient(135deg,{BG_CARD},{BG_PANEL});border:1px solid {GOLD}55;'
                f'border-left:4px solid {GOLD};border-radius:8px;padding:12px 20px;margin-bottom:16px">'
                f'<div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:1.5px">&#127942; Top Momentum Pick</div>'
                f'<div style="display:flex;align-items:baseline;gap:12px;margin-top:4px;flex-wrap:wrap">'
                f'<span style="color:{GOLD};font-size:26px;font-family:\'Cormorant Garamond\',serif;font-weight:700">{top["Ticker"]}</span>'
                f'<span style="color:{TEXT_PRIMARY};font-size:17px">${top["Price"]:.2f}</span>'
                f'<span style="color:{ACCENT_GREEN if top["Change %"]>=0 else ACCENT_RED};font-size:14px">{top["Change %"]:+.2f}%</span>'
                f'<span style="color:{TEXT_MUTED};font-size:13px">RSI {top["RSI"]:.1f} &middot; Vol {top["Vol Ratio"]:.1f}&times; &middot; Score {top["Score"]}/100</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

            render_results_table(df, strategy="Stock", source="Momentum Scanner")
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
            <div style="font-size:36px;margin-bottom:12px">⚡</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">Momentum Setup Detector</div>
            <div style="font-size:13px">Finds stocks trending with institutional momentum.<br>Criteria: Price > 50/200 SMA · RSI {rsi_min}–{rsi_max} · Volume ≥ {vol_mult}× average · MACD bullish</div>
        </div>""", unsafe_allow_html=True)
