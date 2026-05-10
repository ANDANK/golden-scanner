# pages/etf_3x_options_scanner.py — 3× ETF High-Premium Options

import streamlit as st
import pandas as pd
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import get_price_history, get_options_chain


# Only 3× ETFs with options liquidity
OPTIONABLE_3X = [
    "TQQQ", "SOXL", "UPRO", "TECL", "LABU", "FAS", "TNA",
    "SQQQ", "SOXS", "SPXS", "TECS", "FAZ", "TZA",
]


def scan_3x_options(tickers, iv_rank_min, delta_min, delta_max, premium_pct_min,
                    dte_min, dte_max):

    with st.spinner("Scanning 3× ETF options for high-premium setups…"):
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
                atr_pct = calc_atr(df)

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

                # Use puts (CSP on 3x ETF — higher premium, higher risk)
                chain = puts_ch
                if chain.empty:
                    continue

                otm = chain[chain["strike"] < price].copy()
                if otm.empty:
                    continue

                target_delta = 0.20
                if "delta" in otm.columns and otm["delta"].notna().any():
                    otm["ddist"] = (otm["delta"].abs() - target_delta).abs()
                    otm = otm.sort_values("ddist")
                else:
                    ref = price * 0.88
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

                iv = float(row.get("impliedVolatility", 0.50) or 0.50)
                iv_rank = approx_iv_rank(iv)

                if iv_rank < iv_rank_min:
                    continue

                delta_abs = abs(float(row.get("delta", target_delta) or target_delta))

                ann_ret = annualized_return(mid, strike, dte)
                breakeven = strike - mid

                # Risk flags for leveraged ETFs
                risk_flags = []
                if atr_pct > 8:     risk_flags.append("🔴 Extreme Volatility")
                elif atr_pct > 5:   risk_flags.append("🟡 High Volatility")
                if spread_pct > 10: risk_flags.append("⚠️ Wide Spread")
                if iv > 0.80:       risk_flags.append("🔥 Very High IV")

                risk_str = " · ".join(risk_flags) if risk_flags else "✅ Normal Risk"

                # Premium vs risk ratio
                pvr = round(premium_pct / atr_pct, 2) if atr_pct > 0 else 0

                score = 0
                if iv_rank >= 60: score += 30
                elif iv_rank >= 40: score += 20
                if premium_pct >= 4: score += 30
                elif premium_pct >= 2: score += 20
                elif premium_pct >= 1: score += 10
                if spread_pct <= 5: score += 20
                elif spread_pct <= 10: score += 10
                if pvr >= 0.5: score += 20
                score = min(score, 100)

                prev = float(close.iloc[-2]) if len(close) > 1 else price
                chg_pct = (price - prev) / prev * 100

                results.append({
                    "Ticker":       ticker,
                    "Strategy":     "💰 CSP",
                    "ETF Price":    round(price, 2),
                    "Change %":     round(chg_pct, 2),
                    "Strike":       round(strike, 2),
                    "Premium":      round(mid, 2),
                    "Premium %":    round(premium_pct, 2),
                    "IV":           f"{iv*100:.1f}%",
                    "IV Rank":      round(iv_rank, 1),
                    "Delta":        round(delta_abs, 3),
                    "DTE":          dte,
                    "Ann. Return%": round(ann_ret, 2),
                    "Breakeven":    round(breakeven, 2),
                    "ATR %":        round(atr_pct, 2),
                    "Prem/Risk":    pvr,
                    "Risk Flags":   risk_str,
                    "Expiry":       exp_str,
                    "Score":        score,
                })
            except Exception:
                continue

        progress.empty()

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


def render():
    section_header("⚡📈", "3× ETF Options — Cash-Secured Puts",
                   "Sells OTM puts on leveraged ETFs · Ultra-high IV premium · Premium vs risk ratio")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ 3× ETF Options Filters</div>', unsafe_allow_html=True)
        iv_rank_min = st.slider("Min IV Rank", 0, 100, 25)
        delta_min, delta_max = st.slider("Delta Range (abs)", 0.05, 0.50, (0.15, 0.30), 0.01)
        premium_pct_min = st.slider("Min Premium % of Strike", 0.3, 10.0, 0.70, 0.05)
        dte_min, dte_max = st.slider("DTE Range", 1, 60, (1, 20))

    st.info("⏱ 3× ETF options scan takes 30–90 seconds.")

    col1, col2 = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        df = scan_3x_options(OPTIONABLE_3X, iv_rank_min, delta_min, delta_max,
                             premium_pct_min, dte_min, dte_max)

        if df.empty:
            empty_state("No 3× ETF option setups. Lower premium % or IV rank threshold.")
        else:
            col1, col2, col3, col4 = st.columns(4)
            with col1: metric_card("Setups Found", str(len(df)), color=GOLD)
            with col2: metric_card("Avg Premium %", f"{df['Premium %'].mean():.2f}%", color=ACCENT_GREEN)
            with col3: metric_card("Avg Ann. Return", f"{df['Ann. Return%'].mean():.1f}%", color=ACCENT_BLUE)
            with col4: metric_card("Avg IV Rank", f"{df['IV Rank'].mean():.0f}", color=GOLD)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df, strategy="3x ETF Options", source="3x ETF Options")

            st.markdown(f"""
            <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-left:3px solid {ACCENT_RED};border-radius:6px;padding:12px 16px;margin-top:16px;color:{TEXT_MUTED};font-size:12px">
                ⚠️ <b>Extreme Risk Warning:</b> 3× leveraged ETF options carry outsized risk due to volatility decay compounding.
                These instruments can lose value rapidly even when the underlying moves in your favor.
                <b>Position sizing must be very small.</b> The "Prem/Risk" ratio (Premium % ÷ ATR %) helps gauge if premium compensates for volatility risk.
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">⚡</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">3× ETF Options — High Premium Setups</div>
            <div style="font-size:13px">Elevated IV creates outsized premiums — but risk matches the reward.<br>Criteria: IV Rank &gt; {iv_rank_min} · Premium &gt; {premium_pct_min}% · DTE {dte_min}–{dte_max}</div>
        </div>""", unsafe_allow_html=True)
