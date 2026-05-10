# pages/etf_options_scanner.py — Liquid ETF Options

import streamlit as st
import pandas as pd
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import get_price_history, get_options_chain


def scan_etf_options(tickers, iv_rank_min, delta_min, delta_max, premium_pct_min,
                     dte_min, dte_max, trade_type):

    with st.spinner("Scanning ETF options for liquid premium setups…"):
        results = []
        progress = st.progress(0)
        today = datetime.now()

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers))
            try:
                df = get_price_history(ticker, period="3mo")
                if df.empty or len(df) < 20:
                    continue

                close = df["Close"].squeeze()
                volume = df["Volume"].squeeze()
                price = float(close.iloc[-1])

                rsi = calc_rsi(close)
                _, _, hist = calc_macd(close)
                avg_vol = float(volume.rolling(20).mean().dropna().iloc[-1])
                vol_ratio = float(volume.iloc[-1]) / avg_vol if avg_vol > 0 else 1

                calls, puts, expiries = get_options_chain(ticker)
                if (calls.empty and puts.empty) or not expiries:
                    continue

                best_exp = None
                for exp in expiries:
                    try:
                        exp_dt = datetime.strptime(exp, "%Y-%m-%d")
                        dte = (exp_dt - today).days
                        if dte_min <= dte <= dte_max:
                            best_exp = (exp, dte)
                            break
                    except Exception:
                        continue

                if best_exp is None:
                    continue

                exp_str, dte = best_exp
                calls_ch, puts_ch, _ = get_options_chain(ticker, exp_str)

                chain = puts_ch if trade_type == "CSP (Puts)" else calls_ch
                if chain.empty:
                    continue

                if trade_type == "CSP (Puts)":
                    otm = chain[chain["strike"] < price]
                else:
                    otm = chain[chain["strike"] > price]

                if otm.empty:
                    continue

                target_delta = 0.22
                if "delta" in otm.columns and otm["delta"].notna().any():
                    otm = otm.copy()
                    otm["ddist"] = (otm["delta"].abs() - target_delta).abs()
                    otm = otm.sort_values("ddist")
                else:
                    otm = otm.copy()
                    ref = price * 0.93 if trade_type == "CSP (Puts)" else price * 1.05
                    otm["sdist"] = (otm["strike"] - ref).abs()
                    otm = otm.sort_values("sdist")

                row = otm.iloc[0]
                strike = float(row["strike"])
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                mid = (bid + ask) / 2 if bid + ask > 0 else float(row.get("lastPrice", 0) or 0)

                if mid <= 0:
                    continue

                spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 999
                premium_pct = (mid / strike) * 100
                if premium_pct < premium_pct_min:
                    continue

                iv = float(row.get("impliedVolatility", 0.20) or 0.20)
                iv_rank = approx_iv_rank(iv)

                if iv_rank < iv_rank_min:
                    continue

                delta_abs = abs(float(row.get("delta", target_delta) or target_delta))

                # Liquidity score: tight spread + high volume
                opt_vol = int(row.get("volume", 0) or 0)
                liq_score = 0
                if spread_pct <= 1: liq_score += 40
                elif spread_pct <= 3: liq_score += 25
                if opt_vol >= 1000: liq_score += 40
                elif opt_vol >= 100: liq_score += 20
                if iv_rank >= 40: liq_score += 20

                ann_ret = annualized_return(mid, strike, dte)
                prev = float(close.iloc[-2]) if len(close) > 1 else price
                chg_pct = (price - prev) / prev * 100

                results.append({
                    "Ticker":        ticker,
                    "Trade Type":    trade_type,
                    "ETF Price":     round(price, 2),
                    "Change %":      round(chg_pct, 2),
                    "Strike":        round(strike, 2),
                    "Premium":       round(mid, 2),
                    "Premium %":     round(premium_pct, 2),
                    "Delta":         round(delta_abs, 3),
                    "IV Rank":       round(iv_rank, 1),
                    "DTE":           dte,
                    "Ann. Return %": round(ann_ret, 2),
                    "Spread %":      round(spread_pct, 2),
                    "Opt Volume":    opt_vol,
                    "Liq. Score":    liq_score,
                    "RSI":           round(rsi, 1),
                    "Expiry":        exp_str,
                    "Score":         liq_score,
                })
            except Exception:
                continue

        progress.empty()

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


def render():
    section_header("📈", "ETF Options",
                   "Liquid premium trades on high-AUM ETFs · Tight spreads · High options volume")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ ETF Options Filters</div>', unsafe_allow_html=True)
        trade_type = st.selectbox("Trade Type", ["CSP (Puts)", "Covered Call (Calls)"])
        iv_rank_min = st.slider("Min IV Rank", 0, 100, 25)
        delta_min, delta_max = st.slider("Delta Range (abs)", 0.05, 0.50, (0.15, 0.30), 0.01)
        premium_pct_min = st.slider("Min Premium %", 0.3, 3.0, 0.70, 0.05)
        dte_min, dte_max = st.slider("DTE Range", 1, 90, (1, 20))

    st.info("⏱ ETF options scan takes 30–90 seconds.")

    col1, col2 = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        # Core liquid ETFs first
        liquid_etfs = ["SPY", "QQQ", "IWM", "GLD", "TLT", "HYG", "XLK", "XLF",
                       "XLE", "XLV", "EEM", "ARKK", "SOXX", "VNQ", "XLY"]
        df = scan_etf_options(liquid_etfs, iv_rank_min, delta_min, delta_max,
                              premium_pct_min, dte_min, dte_max, trade_type)

        if df.empty:
            empty_state("No ETF option setups found. Lower IV rank or premium threshold.")
        else:
            col1, col2, col3 = st.columns(3)
            with col1: metric_card("Setups Found", str(len(df)), color=GOLD)
            with col2: metric_card("Avg Premium %", f"{df['Premium %'].mean():.2f}%", color=ACCENT_GREEN)
            with col3: metric_card("Avg IV Rank", f"{df['IV Rank'].mean():.0f}", color=ACCENT_BLUE)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df, strategy="ETF Options", source="ETF Options")

            st.markdown(f"""
            <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px 16px;margin-top:16px;color:{TEXT_MUTED};font-size:12px">
                💡 <b>Liquidity Score</b> combines spread tightness and option volume.
                ETF options typically have higher liquidity than individual stocks — ideal for premium selling strategies.
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">📈</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">ETF Options Premium Finder</div>
            <div style="font-size:13px">Liquid ETF options with tight spreads and strong premiums.<br>Trade: {trade_type} · Delta {delta_min}–{delta_max} · DTE {dte_min}–{dte_max}</div>
        </div>""", unsafe_allow_html=True)
